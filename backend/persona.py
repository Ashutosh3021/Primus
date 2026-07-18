"""
Global Persona system for Primus.

There is exactly ONE active persona for the entire runtime.  Changing it
immediately affects every interface — Telegram, the Web Dashboard, the REST
API, and any future client — because they all build their prompts through the
same Context Engine, which reads the active persona from here.

Personas are persisted in config.json (`persona` section) so the choice
survives restart.  A singleton ``PersonaManager`` holds the live state; the
rest of the runtime reads it through ``get_active_persona_text()``.
"""

from typing import Dict, List, Optional

from backend.config import Config, save_persona_config
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


# Built-in persona presets.  ``custom`` is handled specially (its text lives in
# the persisted ``custom_text`` field rather than here).
PERSONA_PRESETS: Dict[str, str] = {
    "default": (
        "You are Primus, a persistent open-source AI operating system. "
        "You have access to layered memory about the user and previous work. "
        "Use the provided context to stay consistent and helpful."
    ),
    "critic": (
        "You are Primus operating in CRITIC mode. Scrutinise claims, surface "
        "risks, assumptions, and failure modes, and challenge weak reasoning "
        "before endorsing any plan. Be direct and evidence-oriented."
    ),
    "architect": (
        "You are Primus operating in ARCHITECT mode. Favour clean, scalable, "
        "and maintainable designs. Think in systems and trade-offs, propose "
        "structure before implementation, and highlight integration points."
    ),
    "analyst": (
        "You are Primus operating in ANALYST mode. Break problems into "
        "components, reason from data and evidence, quantify where possible, "
        "and present conclusions with their supporting rationale."
    ),
}

# Names that are reserved for the built-in presets (plus "custom").
VALID_PERSONAS: List[str] = sorted(list(PERSONA_PRESETS.keys()) + ["custom"])


class PersonaManager:
    """Owns the single active persona for the whole runtime."""

    def __init__(self, active: str = "default", custom_text: str = ""):
        self._active = active if active in PERSONA_PRESETS or active == "custom" else "default"
        self._custom_text = custom_text or ""

    # ── Mutations (persisted via save_persona_config) ─────────────────────────

    def set_active(self, name: str) -> None:
        name = (name or "").strip().lower()
        if name == "custom":
            if not self._custom_text.strip():
                raise ValueError(
                    "No custom persona text set. "
                    "Use '/persona custom <your persona text>' first."
                )
            self._active = "custom"
        elif name in PERSONA_PRESETS:
            self._active = name
        else:
            raise ValueError(
                f"Unknown persona: {name!r}. "
                f"Available: {', '.join(VALID_PERSONAS)}"
            )
        self._persist()

    def set_custom(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            raise ValueError("Custom persona text cannot be empty.")
        self._custom_text = text
        self._active = "custom"
        self._persist()

    # ── Reads ──────────────────────────────────────────────────────────────────

    def get_active_name(self) -> str:
        return self._active

    def get_active_text(self) -> str:
        if self._active == "custom":
            return self._custom_text or PERSONA_PRESETS["default"]
        return PERSONA_PRESETS.get(self._active, PERSONA_PRESETS["default"])

    def list_personas(self) -> Dict[str, object]:
        return {
            "active": self._active,
            "presets": list(PERSONA_PRESETS.keys()),
            "custom_set": bool(self._custom_text.strip()),
        }

    # ── Persistence ─────────────────────────────────────────────────────────────

    def _persist(self) -> None:
        try:
            save_persona_config(self._active, self._custom_text)
        except Exception as exc:  # config write must never break a request
            logger.warning(f"Failed to persist persona config: {exc}")


# ── Module-level singleton ─────────────────────────────────────────────────────

_mgr: Optional[PersonaManager] = None


def initialize_persona(config: Optional[Config] = None) -> PersonaManager:
    """Initialise the global persona singleton from config (if present)."""
    global _mgr
    active, custom = "default", ""
    if config is not None:
        pc = getattr(config, "persona", None)
        if pc is not None:
            active = pc.active or "default"
            custom = pc.custom_text or ""
    _mgr = PersonaManager(active, custom)
    return _mgr


def get_persona_manager() -> PersonaManager:
    """Return the live persona singleton, initialising with defaults if needed."""
    global _mgr
    if _mgr is None:
        _mgr = PersonaManager()
    return _mgr


def get_active_persona_text() -> str:
    """The active persona text used as the SYSTEM persona in prompts."""
    return get_persona_manager().get_active_text()


__all__ = [
    "PERSONA_PRESETS",
    "VALID_PERSONAS",
    "PersonaManager",
    "initialize_persona",
    "get_persona_manager",
    "get_active_persona_text",
]
