"""
Context Engine — the core asset of Primus.

One shared, provider-agnostic memory organised into eight layers.  Responsible
for:

  * storing / retrieving layered memory (facts, project, skills, summaries …)
  * maintaining the live ACTIVE SESSION (recent conversation messages)
  * building prompts from the layers in priority order
  * tracking the CONTEXT BUDGET (max / current / remaining / percentage)
  * automatic pruning when the budget exceeds its threshold
  * HARD COMPACTION (/compact): summarise the conversation, archive the
    summary into Compact Memory, and clear the active session.

All state lives in SQLite (the `memories` and `conversations` tables) so it
survives restart.  Memory is shared — there is no provider dimension.
"""

import aiosqlite
from typing import Any, Dict, List, Optional

from backend.db import DB_PATH, ConversationStore, ConversationMessage
from backend.context.layers import (
    ContextLayer,
    LAYER_PRIORITY,
    LAYER_META,
    PERSISTED_LAYERS,
)
from backend.context.store import LayeredMemoryStore, DEFAULT_USER
from backend.context.budget import ContextBudget, estimate_tokens
from backend.context.prompt_builder import PromptBuilder
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)

# Rolling key for the current conversation summary layer.
SUMMARY_KEY = "current"


class ContextEngine:
    """Layered, shared, persistent context for every provider."""

    def __init__(
        self,
        max_tokens: int = 128_000,
        prune_threshold: float = 0.85,
        user_id: str = DEFAULT_USER,
    ):
        self.store = LayeredMemoryStore()
        self.conv_store = ConversationStore()
        self.budget = ContextBudget(max_tokens=max_tokens, prune_threshold=prune_threshold)
        self.builder = PromptBuilder(max_tokens=max_tokens)
        # One shared memory — ignore any per-user id passed in.
        self.user_id = DEFAULT_USER
        # Last computed budget + prune flag, keyed by conversation_id.
        self._last_budget: Dict[str, ContextBudget] = {}
        self._last_pruned: Dict[str, bool] = {}

    # ── Configuration ──────────────────────────────────────────────────────────

    def set_max_tokens(self, max_tokens: int) -> None:
        self.budget.max_tokens = max_tokens
        self.builder.max_tokens = max_tokens

    def set_prune_threshold(self, prune_threshold: float) -> None:
        self.budget.prune_threshold = prune_threshold

    # ── Layered memory (persisted) ──────────────────────────────────────────────

    async def set_fact(
        self,
        layer: ContextLayer,
        key: str,
        value: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self.store.set(layer, key, value, self.user_id, metadata)

    async def get_layer(self, layer: ContextLayer) -> List[Dict[str, Any]]:
        return await self.store.get_all(layer, self.user_id)

    async def delete_fact(self, layer: ContextLayer, key: str) -> bool:
        return await self.store.delete(layer, key, self.user_id)

    async def count_by_layer(self) -> Dict[str, int]:
        return await self.store.count_by_layer(self.user_id)

    # ── Active session (live conversation) ───────────────────────────────────────

    async def add_session_message(
        self, conversation_id: str, role: str, content: str
    ) -> None:
        await self.conv_store.add(
            ConversationMessage(
                user_id=self.user_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
            )
        )

    async def add_interaction(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """Record a full turn and auto-prune if the budget is exceeded."""
        await self.add_session_message(conversation_id, "user", user_message)
        await self.add_session_message(conversation_id, "assistant", assistant_response)
        await self._maybe_prune(conversation_id)

    async def get_active_session(
        self, conversation_id: str, limit: int = 10_000
    ) -> List[Dict[str, Any]]:
        msgs = await self.conv_store.get_conversation(self.user_id, conversation_id, limit)
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in msgs
        ]

    async def active_session_count(self, conversation_id: str) -> int:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, "
                "conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
                "timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, metadata TEXT)"
            )
            cur = await conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE user_id=? AND conversation_id=?",
                (self.user_id, conversation_id),
            )
            row = await cur.fetchone()
        return row[0] if row else 0

    async def clear_active_session(self, conversation_id: str) -> int:
        async with aiosqlite.connect(DB_PATH) as conn:
            cur = await conn.execute(
                "DELETE FROM conversations WHERE user_id=? AND conversation_id=?",
                (self.user_id, conversation_id),
            )
            await conn.commit()
            return cur.rowcount

    # ── Budget / context ─────────────────────────────────────────────────────────

    async def estimate_context(self, conversation_id: str) -> ContextBudget:
        """Compute a budget snapshot for the given conversation."""
        total = 0
        for layer in PERSISTED_LAYERS:
            entries = await self.store.get_all(layer, self.user_id)
            for e in entries:
                total += estimate_tokens(f"{e['key']}: {e['value']}")
        msgs = await self.get_active_session(conversation_id, limit=10_000)
        for m in msgs:
            total += estimate_tokens(f"{m['role']}: {m['content']}")
        return ContextBudget(
            max_tokens=self.budget.max_tokens,
            prune_threshold=self.budget.prune_threshold,
            current_tokens=total,
        )

    async def get_budget(self, conversation_id: str) -> ContextBudget:
        if conversation_id in self._last_budget:
            return self._last_budget[conversation_id]
        return await self.estimate_context(conversation_id)

    def last_pruned(self, conversation_id: str) -> bool:
        return self._last_pruned.get(conversation_id, False)

    # ── Prompt building ───────────────────────────────────────────────────────────

    async def build_prompt(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
        skill_instructions: str | None = None,
    ) -> str:
        """
        Assemble the prompt from the layers in priority order.

        Persisted layers are injected as structured sections; the ACTIVE
        SESSION is appended (oldest-first) and trimmed by the builder if it
        would overflow the budget.  The resulting budget snapshot (including
        the current query) is cached for /api/context.

        The SYSTEM persona comes from the GLOBAL active persona
        (backend.persona) so every interface shares one persona.  An optional
        ``skill_instructions`` block is injected as an ACTIVE SKILL directive
        when a skill is being invoked.
        """
        # Global active persona — single source of truth for all interfaces.
        try:
            from backend.persona import get_active_persona_text
            persona = get_active_persona_text() or self.builder.persona_default
        except Exception:
            persona = self.builder.persona_default

        layer_sections: List[tuple] = []
        for layer in LAYER_PRIORITY:
            if layer in (ContextLayer.PERSONA, ContextLayer.ACTIVE_SESSION):
                continue
            entries = await self.store.get_all(layer, self.user_id)
            if entries:
                body = "\n".join(f"- {e['key']}: {e['value']}" for e in entries)
                title = f"--- {LAYER_META[layer]['title'].upper()} ---"
                layer_sections.append((title, body))

        active = await self.get_active_session(conversation_id, limit=10_000)
        prompt = self.builder.build(
            persona, layer_sections, active, query,
            skill_instructions=skill_instructions,
        )

        # Cache the budget (including the current message) for later reads.
        b = await self.estimate_context(conversation_id)
        b.current_tokens += estimate_tokens(f"user: {query}")
        self._last_budget[conversation_id] = b
        return prompt

    # ── Automatic pruning ─────────────────────────────────────────────────────────

    async def _maybe_prune(self, conversation_id: str, current_msg_tokens: int = 0) -> bool:
        budget = await self.estimate_context(conversation_id)
        budget.current_tokens += current_msg_tokens
        pruned = False
        if budget.exceeds():
            msgs = await self.get_active_session(conversation_id, limit=100_000)
            per = [estimate_tokens(f"{m['role']}: {m['content']}") for m in msgs]
            total = budget.current_tokens
            drop_ids: List[int] = []
            i = 0
            while total > budget.soft_limit() and i < len(msgs):
                total -= per[i]
                drop_ids.append(msgs[i]["id"])
                i += 1
            if drop_ids:
                await self._delete_messages(drop_ids)
                pruned = True
        nb = await self.estimate_context(conversation_id)
        self._last_budget[conversation_id] = nb
        self._last_pruned[conversation_id] = pruned
        return pruned

    async def _delete_messages(self, ids: List[int]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                f"DELETE FROM conversations WHERE id IN ({placeholders})", ids
            )
            await conn.commit()

    # ── Hard compaction (/compact) ────────────────────────────────────────────────

    async def apply_compaction(self, conversation_id: str, summary: str) -> None:
        """
        Archive `summary` into Compact Memory, update the rolling Conversation
        Summary, and clear the active session so the next message continues
        with Persona + Persistent Memory + Compact Summary + Current Message.
        """
        from datetime import datetime

        stamp = datetime.utcnow().isoformat(timespec="seconds")
        await self.store.set(
            ContextLayer.COMPACT_MEMORY, f"compact_{stamp}", summary, self.user_id,
            metadata={"conversation_id": conversation_id},
        )
        await self.store.set(
            ContextLayer.CONVERSATION_SUMMARY, SUMMARY_KEY, summary, self.user_id,
            metadata={"conversation_id": conversation_id, "updated_at": stamp},
        )
        await self.clear_active_session(conversation_id)
        # After clearing, the active session is empty → budget drops.
        nb = await self.estimate_context(conversation_id)
        self._last_budget[conversation_id] = nb
        self._last_pruned[conversation_id] = False


__all__ = ["ContextEngine", "SUMMARY_KEY"]
