"""
Global Skills system for Primus.

Skills are reusable instruction sets stored in the shared, persistent memory
(the ``skills`` context layer).  Any interface can create one with
``/skill-maker`` and run it by sending ``/<name>`` — the behaviour is identical
everywhere because the runtime resolves and executes skills through this single
manager.

A skill is a structured record::

    {
      "name": "<name>",
      "prompt": "<instructions injected into the prompt>",
      "description": "<short human description>",
      "commands": ["/<name>", "/<name> delete"],
      "metadata": {
        "version": "1.0.0",
        "dependencies": [],
        "created_date": "<iso8601>",
        "examples": ["/<name> do something"]
      },
      "active": false
    }

The ``prompt`` is injected into the prompt as an ACTIVE SKILL directive when the
skill is invoked, and every *active* skill is loaded automatically by the
Prompt Builder so it is always in context.

Editing is not supported — a skill is deleted and recreated.  Everything is
persisted in SQLite, so skills survive restart.
"""

import copy
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from backend.context.layers import ContextLayer
from backend.context.store import LayeredMemoryStore, DEFAULT_USER
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)

# Skill names must be URL/path-safe (no spaces) so they can be invoked as /name.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")

DEFAULT_VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_name(name: str) -> str:
    name = (name or "").strip().lower().lstrip("/")
    if not _SKILL_NAME_RE.match(name):
        raise ValueError(
            f"Invalid skill name {name!r}. Use lowercase letters, digits, "
            "underscores or hyphens (no spaces)."
        )
    return name


def _commands_for(name: str) -> List[str]:
    return [f"/{name}", f"/{name} delete"]


def _to_record(raw: Dict[str, object]) -> Dict[str, object]:
    """Normalise a stored JSON blob into a full skill record (back-compat)."""
    name = str(raw.get("name", "")).strip().lower()
    prompt = (raw.get("prompt") or raw.get("instructions") or "").strip()
    description = (raw.get("description") or name).strip() or name
    meta = raw.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    record = {
        "name": name,
        "prompt": prompt,
        "description": description,
        "commands": list(raw.get("commands") or _commands_for(name)),
        "metadata": {
            "version": str(meta.get("version") or DEFAULT_VERSION),
            "dependencies": list(meta.get("dependencies") or []),
            "created_date": str(meta.get("created_date") or ""),
            "examples": list(meta.get("examples") or []),
        },
        "active": bool(raw.get("active", False)),
    }
    return record


class SkillManager:
    """Persistent store + resolver for skills (shared across all interfaces)."""

    def __init__(self) -> None:
        self.store = LayeredMemoryStore()

    # ── Create / Import ──────────────────────────────────────────────────────────

    async def create_skill(
        self,
        name: str,
        instructions: str,
        description: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        examples: Optional[List[str]] = None,
        active: bool = False,
        version: Optional[str] = None,
        created_date: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        """Create (or overwrite) a skill. No editing — overwrite == recreate."""
        name = _normalise_name(name)
        prompt = (instructions or "").strip()
        if not prompt:
            raise ValueError("Skill prompt (instructions) cannot be empty.")
        description = (description or name).strip() or name
        meta = dict(metadata or {})
        record = {
            "name": name,
            "prompt": prompt,
            "description": description,
            "commands": _commands_for(name),
            "metadata": {
                "version": str(version or meta.get("version") or DEFAULT_VERSION),
                "dependencies": list(dependencies if dependencies is not None
                                     else meta.get("dependencies") or []),
                "created_date": str(created_date or meta.get("created_date") or _now_iso()),
                "examples": list(examples if examples is not None
                                 else meta.get("examples") or []),
            },
            "active": bool(active),
        }
        payload = json.dumps(record, ensure_ascii=False)
        await self.store.set(ContextLayer.SKILLS, name, payload, DEFAULT_USER)
        logger.info(f"Skill created: /{name} (active={record['active']})")
        return record

    async def import_skill(self, data: Dict[str, object]) -> Dict[str, object]:
        """Create a skill from a full exported record (must include name+prompt)."""
        if not isinstance(data, dict):
            raise ValueError("Imported skill must be a JSON object.")
        name = data.get("name")
        prompt = data.get("prompt") or data.get("instructions")
        if not name or not prompt:
            raise ValueError("Imported skill needs both 'name' and 'prompt'.")
        meta = data.get("metadata") or {}
        return await self.create_skill(
            name,
            prompt,
            description=data.get("description"),
            dependencies=meta.get("dependencies") if isinstance(meta, dict) else None,
            examples=meta.get("examples") if isinstance(meta, dict) else None,
            active=bool(data.get("active", False)),
            version=meta.get("version") if isinstance(meta, dict) else None,
            created_date=meta.get("created_date") if isinstance(meta, dict) else None,
        )

    # ── Read ────────────────────────────────────────────────────────────────────

    async def get_skill(self, name: str) -> Optional[Dict[str, object]]:
        name = _normalise_name(name)
        entry = await self.store.get(ContextLayer.SKILLS, name, DEFAULT_USER)
        if not entry:
            return None
        try:
            return _to_record(json.loads(entry["value"]))
        except Exception:
            return None

    async def list_skills(self) -> List[Dict[str, object]]:
        entries = await self.store.get_all(ContextLayer.SKILLS, DEFAULT_USER)
        out: List[Dict[str, object]] = []
        for e in entries:
            try:
                out.append(_to_record(json.loads(e["value"])))
            except Exception:
                continue
        return out

    async def list_active(self) -> List[Dict[str, object]]:
        return [s for s in await self.list_skills() if s.get("active")]

    async def get_active_prompt(self) -> Optional[str]:
        """Combined prompt of all active skills (for the Prompt Builder)."""
        active = await self.list_active()
        parts = [(s.get("prompt") or "").strip() for s in active]
        parts = [p for p in parts if p]
        return "\n\n".join(parts) if parts else None

    async def export_skill(self, name: str) -> Dict[str, object]:
        skill = await self.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name!r}")
        return copy.deepcopy(skill)

    # ── Update (active flag only) ─────────────────────────────────────────────────

    async def set_active(self, name: str, active: bool) -> Dict[str, object]:
        skill = await self.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name!r}")
        skill["active"] = bool(active)
        await self.store.set(
            ContextLayer.SKILLS, skill["name"],
            json.dumps(skill, ensure_ascii=False), DEFAULT_USER,
        )
        logger.info(f"Skill /{skill['name']} active={skill['active']}")
        return skill

    # ── Merge ────────────────────────────────────────────────────────────────────

    async def merge_skills(
        self,
        names: List[str],
        new_name: str,
        prompt: str,
        description: Optional[str] = None,
        active: bool = True,
    ) -> Dict[str, object]:
        """
        Combine ``prompt`` with the prompts of every skill in ``names`` into a
        single new skill, then save it (optionally as the default/active skill).
        """
        new_name = _normalise_name(new_name)
        blocks = [(prompt or "").strip()]
        merged_deps: List[str] = []
        merged_examples: List[str] = []
        for n in names:
            sk = await self.get_skill(n)
            if sk:
                p = (sk.get("prompt") or "").strip()
                if p:
                    blocks.append(p)
                merged_deps.extend(sk["metadata"].get("dependencies") or [])
                merged_examples.extend(sk["metadata"].get("examples") or [])
        combined = "\n\n".join(b for b in blocks if b)
        # De-duplicate dependencies / examples while preserving order.
        merged_deps = list(dict.fromkeys(merged_deps))
        merged_examples = list(dict.fromkeys(merged_examples))
        return await self.create_skill(
            new_name, combined,
            description=description or f"Merged skill: {new_name}",
            dependencies=merged_deps,
            examples=merged_examples,
            active=active,
        )

    # ── Delete (permanent; no editing) ───────────────────────────────────────────

    async def delete_skill(self, name: str) -> bool:
        name = _normalise_name(name)
        removed = await self.store.delete(ContextLayer.SKILLS, name, DEFAULT_USER)
        if removed:
            logger.info(f"Skill deleted: /{name}")
        return removed

    async def match(self, text: str) -> Optional[Dict[str, object]]:
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
