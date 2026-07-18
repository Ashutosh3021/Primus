"""
ProviderManager — the in-memory authority for Primus' multi-provider state.

Holds the resolved provider configuration map (one entry per supported
provider, each with its own enabled flag, secret_ref and default_model) and
knows how to:

  * report which providers are enabled / configured (secret present)
  * list available models for any provider
  * validate a chosen model (no fuzzy matching)
  * build a live BaseProvider instance for a (provider, model) pair

It never touches disk — persistence is the job of backend.config
(save_provider_runtime_state).  The api layer owns the singleton instance
and keeps it in sync with config.json.
"""

from typing import Any, Callable, Dict, List, Optional

from backend.providers import PROVIDER_REGISTRY, BaseProvider
from backend.providers.models_catalog import (
    DEFAULT_MODEL_BY_PROVIDER,
    get_model_catalog,
    is_model_available,
)
from backend.exceptions import (
    ConfigInvalidError,
    SecretNotFoundError,
)
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


# Secret-ref template for providers that need one.  Ollama runs locally and
# needs no key.
def _default_secret_ref(name: str) -> Optional[str]:
    return None if name == "ollama" else f"provider.{name}.api_key"


def build_default_providers_map() -> Dict[str, Dict[str, Any]]:
    """
    Build a full provider map covering every registered provider.

    Each entry starts disabled with a catalog default model so the UI can
    show every provider and so commands can reference any of them.  The
    active config is overlaid on top of this in initialize_router.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for name in PROVIDER_REGISTRY:
        out[name] = {
            "enabled": False,
            "secret_ref": _default_secret_ref(name),
            "default_model": DEFAULT_MODEL_BY_PROVIDER.get(name, ""),
        }
    return out


class ProviderManager:
    """Owns the live multi-provider configuration."""

    def __init__(
        self,
        providers_map: Dict[str, Dict[str, Any]],
        get_secret_fn: Optional[Callable[[str], str]] = None,
    ):
        # Always start from the full registered set, then overlay the
        # persisted config so missing providers still appear (disabled).
        self._providers: Dict[str, Dict[str, Any]] = build_default_providers_map()
        if providers_map:
            for name, cfg in providers_map.items():
                if name in self._providers:
                    merged = dict(self._providers[name])
                    merged.update(cfg or {})
                    self._providers[name] = merged
                else:
                    self._providers[name] = dict(cfg or {})

        if get_secret_fn is None:
            from backend.secrets import get_secret
            get_secret_fn = get_secret
        self._get_secret: Callable[[str], str] = get_secret_fn

    # ── Accessors ──────────────────────────────────────────────────────────

    def get_providers(self) -> Dict[str, Dict[str, Any]]:
        return self._providers

    def get_provider_config(self, name: str) -> Optional[Dict[str, Any]]:
        return self._providers.get(name)

    def is_registered(self, name: str) -> bool:
        return name in PROVIDER_REGISTRY

    def is_enabled(self, name: str) -> bool:
        cfg = self._providers.get(name)
        return bool(cfg and cfg.get("enabled", False))

    def has_secret(self, name: str) -> bool:
        """True if the provider needs no key or its key is stored."""
        cfg = self._providers.get(name)
        if not cfg:
            return False
        ref = cfg.get("secret_ref")
        if not ref:
            return True  # Ollama / keyless providers
        try:
            self._get_secret(ref)
            return True
        except SecretNotFoundError:
            return False
        except Exception:
            # Keyring / I/O failure — treat as missing so we don't route to it.
            return False

    def is_configured(self, name: str) -> bool:
        """Enabled AND secret present — safe to route traffic to it."""
        return self.is_enabled(name) and self.has_secret(name)

    def configured_providers(self) -> List[str]:
        return [n for n in PROVIDER_REGISTRY if self.is_configured(n)]

    def available_models(self, name: str) -> List[str]:
        return get_model_catalog(name)

    def is_model_available(self, name: str, model: str) -> bool:
        return is_model_available(name, model)

    # ── Mutations (persisted by the caller via save_provider_runtime_state) ──

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name in self._providers:
            self._providers[name]["enabled"] = bool(enabled)

    def set_default_model(self, name: str, model: str) -> None:
        if name in self._providers:
            self._providers[name]["default_model"] = model

    def get_default_model(self, name: str) -> str:
        cfg = self._providers.get(name, {})
        return cfg.get("default_model") or DEFAULT_MODEL_BY_PROVIDER.get(name, "")

    # ── Instance construction ────────────────────────────────────────────────

    def build_provider(self, name: str, model: Optional[str] = None) -> BaseProvider:
        """
        Build a live provider instance for (name, model).

        Raises ConfigInvalidError if the provider is unknown or has no model.
        Raises SecretNotFoundError if a required secret is missing.
        """
        if name not in PROVIDER_REGISTRY:
            raise ConfigInvalidError(
                f"Unknown provider: {name}. "
                f"Available providers: {list(PROVIDER_REGISTRY.keys())}"
            )
        cfg = self._providers.get(name, {})
        resolved_model = model or cfg.get("default_model")
        if not resolved_model:
            raise ConfigInvalidError(
                f"Provider {name} has no model configured."
            )
        ref = cfg.get("secret_ref")
        api_key = "not-required"
        if ref:
            api_key = self._get_secret(ref)  # may raise SecretNotFoundError
        provider_cls = PROVIDER_REGISTRY[name]
        return provider_cls(api_key, resolved_model)
