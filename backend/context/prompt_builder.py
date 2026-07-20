"""
Prompt Builder for the Context Engine.

Consumes the memory layers in the fixed priority order (see
backend.context.layers.LAYER_PRIORITY) and assembles a single, well-structured
prompt string.  If the assembled prompt would exceed the context budget it
trims the OLDEST active-session messages first (lowest priority), falling back
to a hard character truncation only as a last resort.

Priority order (highest → lowest):
  1. System Persona          — identity and behavior rules
  2. Active Skill            — injected only when a skill is invoked / active
  3. Relevant Context        — USER_FACTS, PROJECT_MEMORY, LONG_TERM,
                               CONVERSATION_SUMMARY, COMPACT_MEMORY
  4. Active Session          — recent conversation turns (pruned first)
  5. Current Message         — the user's message

The SKILLS layer is intentionally EXCLUDED from the context section — skill
prompts are only injected via `skill_instructions` so they never appear twice.

Memory relevance filtering:
  * Entries whose key contains a deployment/config noise word and whose value
    does not contain any word from the user's query are suppressed.
  * The remaining entries are sorted by recency (most-recently updated first).
  * At most MAX_CONTEXT_ENTRIES entries per layer are included so one very
    large layer cannot drown out everything else.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.context.budget import estimate_tokens
from backend.context.layers import LAYER_PRIORITY, LAYER_META, ContextLayer

DEFAULT_PERSONA = (
    "You are Primus, a persistent open-source AI operating system. "
    "You have access to layered memory about the user and previous work. "
    "Use the provided context to stay consistent and helpful."
)

# Layers that should NEVER be rendered as a context section because they are
# handled via dedicated channels (skills via skill_instructions; persona via
# the SYSTEM block).
_EXCLUDED_LAYERS = frozenset({ContextLayer.SKILLS, ContextLayer.PERSONA})

# Words that mark a memory entry as "operational noise" (deploy config, command
# outputs, etc.) that should be suppressed unless directly relevant to the query.
_NOISE_KEYWORDS = frozenset({
    "render.yaml", "dockerfile", "deploy", "deployment", "vercel", "railway",
    "heroku", "procfile", "requirements.txt", "pip install", "git push",
    "git clone", "/provider", "/model", "/auto", "/compact", "/skill",
    "secret_ref", "api_key", "bot_token",
})

# Maximum number of entries per layer rendered into the prompt.
MAX_CONTEXT_ENTRIES = 12


def _query_words(query: str) -> frozenset:
    """Extract meaningful lower-case words from the user query."""
    return frozenset(w.lower() for w in re.findall(r"\w+", query) if len(w) > 2)


def _is_relevant(key: str, value: str, query_words: frozenset) -> bool:
    """
    Return True if this memory entry is relevant enough to include.

    An entry is suppressed when ALL of the following hold:
      * its key or value contains at least one noise keyword, AND
      * none of the query words appear in its key or value.
    """
    text = (key + " " + value).lower()
    has_noise = any(nk in text for nk in _NOISE_KEYWORDS)
    if not has_noise:
        return True
    if not query_words:
        return True
    has_match = any(qw in text for qw in query_words)
    return has_match


class PromptBuilder:
    """
    Builds a prompt from layered context in priority order.

    Args:
        max_tokens: context-window ceiling used for safety trimming.
        persona_default: fallback persona text when no PERSONA layer is set.
    """

    def __init__(self, max_tokens: int = 128_000, persona_default: str = DEFAULT_PERSONA):
        self.max_tokens = max_tokens
        self.persona_default = persona_default

    def build(
        self,
        persona: str,
        layer_sections: List[Tuple[str, str]],
        active_session: List[Dict[str, Any]],
        current_query: str,
        skill_instructions: Optional[str] = None,
    ) -> str:
        """
        Assemble the final prompt.

        layer_sections: ordered (title, body) pairs for the non-persona,
                        non-session layers, already in priority order.
        active_session: chronological list of {role, content} dicts.
        skill_instructions: when a skill is invoked or active, its instructions
                        are injected as an ACTIVE SKILL directive after the persona.
        """
        max_chars = self.max_tokens * 4

        # 1. Persona block — ALWAYS first
        head = f"SYSTEM / PERSONA\n{persona or self.persona_default}\n"

        # 2. Active Skill — only present when a skill is active/invoked
        if skill_instructions:
            head += (
                f"\n--- ACTIVE SKILL ---\n{skill_instructions.strip()}\n"
            )

        # 3. Relevant context layers
        mem_blocks = "\n\n".join(title + "\n" + body for title, body in layer_sections)
        if mem_blocks:
            head += "\n" + mem_blocks + "\n"

        # 5. Current message block
        query_block = f"\n\nCURRENT MESSAGE\n{current_query or ''}\n"

        # 4. Active Session inserted between context and current message
        msgs = list(active_session)
        full = self._assemble(head, msgs, query_block)

        # Trim oldest active-session messages until within budget.
        while len(full) > max_chars and msgs:
            msgs.pop(0)
            full = self._assemble(head, msgs, query_block)
        if len(full) > max_chars:
            full = full[:max_chars] + "\n[truncated]"
        return full

    def filter_entries(
        self,
        entries: List[Dict[str, Any]],
        query: str,
        max_entries: int = MAX_CONTEXT_ENTRIES,
    ) -> List[Dict[str, Any]]:
        """
        Filter and rank a layer's entries for relevance to `query`.

        1. Suppress noise entries that are irrelevant to the query.
        2. Sort by updated_at descending (most recent first).
        3. Cap at max_entries.
        """
        qw = _query_words(query)
        relevant = [
            e for e in entries
            if _is_relevant(e.get("key", ""), e.get("value", ""), qw)
        ]
        # Sort by recency (newest first).  Entries may lack updated_at.
        relevant.sort(key=lambda e: (e.get("updated_at") or ""), reverse=True)
        return relevant[:max_entries]

    @staticmethod
    def _assemble(head: str, msgs: List[Dict[str, Any]], query_block: str) -> str:
        if msgs:
            session_text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in msgs)
            return head + "\nACTIVE SESSION (recent)\n" + session_text + query_block
        return head + query_block


__all__ = ["PromptBuilder", "DEFAULT_PERSONA", "MAX_CONTEXT_ENTRIES", "_EXCLUDED_LAYERS"]
