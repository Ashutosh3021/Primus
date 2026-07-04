"""
Module lifecycle management for Primus backend.

Every optional module lives in exactly one of three states:

  DISABLED              – not enabled in config; nothing to do.
  WAITING_FOR_CONFIG    – enabled, but a required secret is missing;
                          initialization deferred until Wizard supplies it.
  RUNNING               – enabled, secret present, fully initialized.

The ModuleRegistry is a process-level singleton.  startup.py and api/__init__.py
read/write it; server.py exposes its state through the health and status endpoints.
"""

from enum import Enum
from typing import Dict, Optional


class ModuleState(str, Enum):
    DISABLED = "disabled"
    WAITING_FOR_CONFIG = "waiting_for_configuration"
    RUNNING = "running"


class ModuleRegistry:
    """
    Process-level registry that tracks the lifecycle state of every optional
    module (router, telegram, discord, …).
    """

    def __init__(self) -> None:
        self._states: Dict[str, ModuleState] = {}
        self._missing_secrets: Dict[str, str] = {}   # module → secret_ref

    # ------------------------------------------------------------------ mutate

    def set_disabled(self, module: str) -> None:
        self._states[module] = ModuleState.DISABLED
        self._missing_secrets.pop(module, None)

    def set_waiting(self, module: str, missing_secret: str) -> None:
        self._states[module] = ModuleState.WAITING_FOR_CONFIG
        self._missing_secrets[module] = missing_secret

    def set_running(self, module: str) -> None:
        self._states[module] = ModuleState.RUNNING
        self._missing_secrets.pop(module, None)

    # ------------------------------------------------------------------ query

    def get_state(self, module: str) -> Optional[ModuleState]:
        return self._states.get(module)

    def get_missing_secret(self, module: str) -> Optional[str]:
        return self._missing_secrets.get(module)

    def is_running(self, module: str) -> bool:
        return self._states.get(module) == ModuleState.RUNNING

    def snapshot(self) -> Dict[str, str]:
        """Return a plain-dict snapshot suitable for JSON serialisation."""
        return {module: state.value for module, state in self._states.items()}


# ── Singleton ────────────────────────────────────────────────────────────────

_registry = ModuleRegistry()


def get_module_registry() -> ModuleRegistry:
    """Return the process-level module registry."""
    return _registry
