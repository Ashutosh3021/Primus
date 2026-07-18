"""
Prompt Builder for the Context Engine.

Consumes the memory layers in the fixed priority order (see
backend.context.layers.LAYER_PRIORITY) and assembles a single, well-structured
prompt string.  If the assembled prompt would exceed the context budget it
trims the OLDEST active-session messages first (lowest priority), falling back
to a hard character truncation only as a last resort.
"""

from typing import Any, Dict, List, Tuple

from backend.context.budget import estimate_tokens
from backend.context.layers import LAYER_PRIORITY, LAYER_META, ContextLayer

DEFAULT_PERSONA = (
    "You are Primus, a persistent open-source AI operating system. "
    "You have access to layered memory about the user and previous work. "
    "Use the provided context to stay consistent and helpful."
)


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
        skill_instructions: str | None = None,
    ) -> str:
        """
        Assemble the final prompt.

        layer_sections: ordered (title, body) pairs for the non-persona,
                        non-session layers, already in priority order.
        active_session: chronological list of {role, content} dicts.
        skill_instructions: when a skill is invoked, its instructions are
                        injected as an ACTIVE SKILL directive after the persona.
        """
        max_chars = self.max_tokens * 4

        head = f"SYSTEM / PERSONA\n{persona or self.persona_default}\n"
        if skill_instructions:
            head += (
                f"\n--- ACTIVE SKILL ---\n{skill_instructions.strip()}\n"
            )
        mem_blocks = "\n\n".join(title + "\n" + body for title, body in layer_sections)
        if mem_blocks:
            head += "\n" + mem_blocks + "\n"

        query_block = f"\n\nCURRENT MESSAGE\n{current_query or ''}\n"

        msgs = list(active_session)
        full = self._assemble(head, msgs, query_block)
        # Trim oldest active-session messages until within budget.
        while len(full) > max_chars and msgs:
            msgs.pop(0)
            full = self._assemble(head, msgs, query_block)
        if len(full) > max_chars:
            full = full[:max_chars] + "\n[truncated]"
        return full

    @staticmethod
    def _assemble(head: str, msgs: List[Dict[str, Any]], query_block: str) -> str:
        if msgs:
            session_text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in msgs)
            return head + "\nACTIVE SESSION (recent)\n" + session_text + query_block
        return head + query_block


__all__ = ["PromptBuilder", "DEFAULT_PERSONA"]
