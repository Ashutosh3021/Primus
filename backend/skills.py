"""
Global Skills system for Primus.

Skills are reusable instruction sets stored in the shared, persistent memory
(the ``skills`` context layer).  Any interface can create one with
``/skill-maker`` and run it by sending ``/<name>`` — the behaviour is identical
everywhere because the runtime resolves and executes skills through this single
manager.

A skill is a small record::

    {"name": "<name>", "description": "<text>", "instructions": "<prompt>"}

The ``instructions`` are injected into the prompt as an ACTIVE SKILL directive
when the skill is invoked, then the request flows through the normal
Context Engine → Provider path like any other message.
"""

import json
import re
from typing import Dict, List, Optional

from backend.context.layers import ContextLayer
from backend.context.store import LayeredMemoryStore, DEFAULT_USER
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)

# Skill names must be URL/path-safe (no spaces) so they can be invoked as /name.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")


class SkillManager:
    """Persistent store + resolver for skills (shared across all interfaces)."""

    def __init__(self) -> None:
        self.store = LayeredMemoryStore()

    async def create_skill(
        self, name: str, instructions: str, description: Optional[str] = None
    ) -> Dict[str, str]:
        name = self._normalise_name(name)
        instructions = (instructions or "").strip()
        if not instructions:
            raise ValueError("Skill instructions cannot be empty.")
        description = (description or name).strip() or name
        payload = json.dumps(
            {"name": name, "description": description, "instructions": instructions},
            ensure_ascii=False,
        )
        await self.store.set(ContextLayer.SKILLS, name, payload, DEFAULT_USER)
        logger.info(f"Skill created: /{name}")
        return {"name": name, "description": description, "instructions": instructions}

    async def get_skill(self, name: str) -> Optional[Dict[str, str]]:
        name = self._normalise_name(name)
        entry = await self.store.get(ContextLayer.SKILLS, name, DEFAULT_USER)
        if not entry:
            return None
        try:
            return json.loads(entry["value"])
        except Exception:
            return None

    async def list_skills(self) -> List[Dict[str, str]]:
        entries = await self.store.get_all(ContextLayer.SKILLS, DEFAULT_USER)
        out: List[Dict[str, str]] = []
        for e in entries:
            try:
                out.append(json.loads(e["value"]))
            except Exception:
                continue
        return out

    async def delete_skill(self, name: str) -> bool:
        name = self._normalise_name(name)
        removed = await self.store.delete(ContextLayer.SKILLS, name, DEFAULT_USER)
        if removed:
            logger.info(f"Skill deleted: /{name}")
        return removed

    async def match(self, text: str) -> Optional[Dict[str, str]]:
        """
        If `text` begins with ``/<name>`` and a skill named `name` exists,
        return that skill; otherwise return None.
        """
        t = (text or "").strip()
        if not t.startswith("/"):
            return None
        head = t[1:].split(None, 1)[0].strip().lower()
        if not head:
            return None
        return await self.get_skill(head)

    @staticmethod
    def _normalise_name(name: str) -> str:
        name = (name or "").strip().lower().lstrip("/")
        if not _SKILL_NAME_RE.match(name):
            raise ValueError(
                f"Invalid skill name {name!r}. Use lowercase letters, digits, "
                "underscores or hyphens (no spaces)."
            )
        return name


# ── Module-level singleton ─────────────────────────────────────────────────────

_mgr: Optional[SkillManager] = None


def initialize_skills() -> SkillManager:
    """Initialise the global skills singleton."""
    global _mgr
    _mgr = SkillManager()
    return _mgr


def get_skill_manager() -> SkillManager:
    """Return the live skills singleton, initialising if needed."""
    global _mgr
    if _mgr is None:
        _mgr = SkillManager()
    return _mgr


__all__ = ["SkillManager", "initialize_skills", "get_skill_manager"]
