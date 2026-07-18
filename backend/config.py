"""
Configuration loading and validation for Primus backend.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from backend.constants import CONFIG_PATH, VERSION
from backend.exceptions import (
    ConfigNotFoundError,
    ConfigInvalidError,
    ConfigVersionError,
)
from backend.validators import validate_config


@dataclass
class ProviderConfig:
    """Provider configuration."""

    name: str
    secret_ref: str
    model: str


@dataclass
class MessagingConfig:
    """Messaging configuration."""

    telegram: Dict[str, Any]
    discord: Dict[str, Any]


@dataclass
class MemoryConfig:
    """Memory configuration."""

    enabled: bool
    backend: str


@dataclass
class ToolsConfig:
    """Tools configuration."""

    web_search: bool
    browser: bool
    terminal: bool


@dataclass
class DesktopConfig:
    """Desktop agent configuration."""

    enabled: bool
    allowed_paths: list


@dataclass
class ContextConfig:
    """Context Engine configuration (budget + pruning)."""

    max_tokens: int = 128_000
    prune_threshold: float = 0.85


@dataclass
class PersonaConfig:
    """Global persona configuration (one active persona for all interfaces)."""

    active: str = "default"
    custom_text: str = ""


@dataclass
class Config:
    """Full Primus configuration."""

    version: int
    provider: ProviderConfig
    messaging: MessagingConfig
    memory: MemoryConfig
    tools: ToolsConfig
    desktop: DesktopConfig
    # ── Context Engine (v1.3.0) ──
    context: ContextConfig
    # ── Global Persona (v1.3.1) ──
    persona: PersonaConfig
    # ── Multi-Provider + Multi-Model (v1.3.0) ──
    # providers: name -> {enabled, secret_ref, default_model}
    # Each provider maintains its OWN persistent configuration.
    providers: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # The currently-selected provider (the one /api/chat and messaging use).
    current_provider: str = ""
    # Auto-routing flag.
    auto_enabled: bool = False


def load_config(config_path: Path = CONFIG_PATH) -> Config:
    """
    Load and validate config from file.

    Args:
        config_path: Path to config.json

    Returns:
        Validated Config object

    Raises:
        ConfigNotFoundError: If config file doesn't exist
        ConfigInvalidError: If config is invalid
        ConfigVersionError: If config version is incompatible
    """
    if not config_path.exists():
        raise ConfigNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    # Validate config structure
    validate_config(data)

    # Check version
    config_version = data.get("version")
    if config_version > VERSION:
        raise ConfigVersionError(
            f"Config version {config_version} is newer than supported version {VERSION}. "
            "Please update Primus."
        )

    # ── Multi-provider map (v1.3.0) ──
    # A config may declare either:
    #   * a `providers` map (new schema) — preferred, or
    #   * a single legacy `provider` block — migrated on the fly.
    providers_raw = data.get("providers")
    if providers_raw and isinstance(providers_raw, dict):
        providers = {k: dict(v) for k, v in providers_raw.items()}
        current_provider = data.get("current_provider") or (
            providers and next(iter(providers))
        ) or data.get("provider", {}).get("name", "")
        auto_enabled = bool((data.get("auto") or {}).get("enabled", False))
    else:
        # Legacy single-provider config → wrap into the multi-provider map.
        legacy = data.get("provider", {}) or {}
        legacy_name = legacy.get("name", "openrouter")
        providers = {
            legacy_name: {
                "enabled": True,
                "secret_ref": legacy.get("secret_ref"),
                "default_model": legacy.get("model"),
            }
        }
        current_provider = legacy_name
        auto_enabled = False

    # Ensure current_provider always points at an existing entry.
    if current_provider not in providers and providers:
        current_provider = next(iter(providers))

    # Build the legacy `provider` mirror so backward-compatible readers
    # (server status, etc.) keep working unchanged.
    cur_cfg = providers.get(current_provider, {})
    provider = ProviderConfig(
        name=current_provider,
        secret_ref=cur_cfg.get("secret_ref"),
        model=cur_cfg.get("default_model"),
    )

    messaging = MessagingConfig(
        telegram=data["messaging"].get("telegram", {"enabled": False}),
        discord=data["messaging"].get("discord", {"enabled": False}),
    )

    memory = MemoryConfig(
        enabled=data["memory"].get("enabled", True),
        backend=data["memory"].get("backend", "sqlite"),
    )

    tools = ToolsConfig(
        web_search=data["tools"].get("web_search", False),
        browser=data["tools"].get("browser", False),
        terminal=data["tools"].get("terminal", False),
    )

    desktop = DesktopConfig(
        enabled=data.get("desktop", {}).get("enabled", True),
        allowed_paths=data.get("desktop", {}).get("allowed_paths", ["."])
    )

    ctx_raw = data.get("context", {}) or {}
    context = ContextConfig(
        max_tokens=int(ctx_raw.get("max_tokens", 128_000)),
        prune_threshold=float(ctx_raw.get("prune_threshold", 0.85)),
    )

    persona_raw = data.get("persona", {}) or {}
    persona = PersonaConfig(
        active=str(persona_raw.get("active", "default")) or "default",
        custom_text=str(persona_raw.get("custom_text", "") or ""),
    )

    return Config(
        version=config_version,
        provider=provider,
        messaging=messaging,
        memory=memory,
        tools=tools,
        desktop=desktop,
        context=context,
        persona=persona,
        providers=providers,
        current_provider=current_provider,
        auto_enabled=auto_enabled,
    )


def save_provider_runtime_state(
    providers_map: Dict[str, Dict[str, Any]],
    current_provider: str,
    auto_enabled: bool,
    config_path: Path = CONFIG_PATH,
) -> None:
    """
    Persist multi-provider runtime state to config.json.

    Only the multi-provider keys (`providers`, `current_provider`, `auto`) and
    a legacy `provider` mirror are (re)written.  Every other section
    (messaging, memory, tools, desktop, assistant, …) is preserved so this
    call can be made repeatedly without clobbering the rest of the config.

    Writing is atomic: a `.tmp` file is created and renamed into place so a
    crash mid-write cannot corrupt config.json (which must survive restarts).
    """
    data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    # Normalise the providers map to plain dicts.
    normalised = {
        name: {
            "enabled": bool(cfg.get("enabled", False)),
            "secret_ref": cfg.get("secret_ref"),
            "default_model": cfg.get("default_model"),
        }
        for name, cfg in (providers_map or {}).items()
    }

    # Ensure the current provider exists in the map.
    if current_provider not in normalised and normalised:
        current_provider = next(iter(normalised))

    data["providers"] = normalised
    data["current_provider"] = current_provider
    data["auto"] = {"enabled": bool(auto_enabled)}
    data["version"] = max(int(data.get("version", VERSION) or VERSION), 2)

    # Legacy mirror — kept for backward-compatible readers.
    cur = normalised.get(current_provider, {})
    data["provider"] = {
        "name": current_provider,
        "secret_ref": cur.get("secret_ref"),
        "model": cur.get("default_model"),
    }

    tmp_path = config_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(config_path)


def save_persona_config(
    active: str,
    custom_text: str,
    config_path: Path = CONFIG_PATH,
) -> None:
    """
    Persist the global persona selection to config.json (atomic).

    Only the `persona` section is (re)written; every other section is
    preserved so this call can be repeated without clobbering the rest of
    the config (which must survive restarts).
    """
    data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["persona"] = {
        "active": str(active or "default"),
        "custom_text": str(custom_text or ""),
    }
    data["version"] = max(int(data.get("version", VERSION) or VERSION), 2)

    tmp_path = config_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(config_path)

def save_context_config(
    max_tokens: int,
    prune_threshold: float,
    config_path: Path = CONFIG_PATH,
) -> None:
    """
    Persist Context Engine budget settings to config.json (atomic).

    Only the `context` section is (re)written; every other section is
    preserved so this call can be repeated without clobbering the rest of the
    config (which must survive restarts).
    """
    data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["context"] = {
        "max_tokens": int(max_tokens),
        "prune_threshold": float(prune_threshold),
    }
    data["version"] = max(int(data.get("version", VERSION) or VERSION), 2)

    tmp_path = config_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(config_path)

