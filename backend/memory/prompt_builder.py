"""
Prompt Builder for constructing AI prompts with context.
"""

from typing import List, Optional
from dataclasses import dataclass, field

from backend.db import MemoryEntry, ConversationMessage, MemoryLayer


@dataclass
class PromptContext:
    system_prompt: str = "You are Primus, a helpful AI assistant."
    long_term_memories: List[MemoryEntry] = field(default_factory=list)
    short_term_memories: List[ConversationMessage] = field(default_factory=list)
    preferences: List[MemoryEntry] = field(default_factory=list)
    project_info: List[MemoryEntry] = field(default_factory=list)
    current_query: str = ""


class PromptBuilder:
    """Builds structured prompts with context."""

    def __init__(self, max_context_tokens: int = 128000):
        self.max_context_tokens = max_context_tokens
        # Rough estimate: 1 token ≈ 4 chars
        self.max_context_chars = max_context_tokens * 4

    def _format_memory_entry(self, entry: MemoryEntry) -> str:
        return f"[{entry.layer.value}] {entry.key}: {entry.value}"

    def _format_conversation_message(self, msg: ConversationMessage) -> str:
        return f"{msg.role}: {msg.content}"

    def _truncate_to_limit(self, content: str, limit: int) -> str:
        if len(content) <= limit:
            return content
        return content[:limit] + " [truncated]"

    def build_prompt(self, ctx: PromptContext) -> str:
        """
        Build a prompt from context components, respecting limits.
        """
        sections = []
        
        # 1. System prompt (highest priority)
        sections.append(ctx.system_prompt)
        
        # 2. Preferences (high priority)
        if ctx.preferences:
            sections.append("\n--- USER PREFERENCES ---")
            for pref in ctx.preferences:
                sections.append(self._format_memory_entry(pref))
        
        # 3. Project info
        if ctx.project_info:
            sections.append("\n--- PROJECT INFO ---")
            for info in ctx.project_info:
                sections.append(self._format_memory_entry(info))
        
        # 4. Long-term memories
        if ctx.long_term_memories:
            sections.append("\n--- RELEVANT MEMORIES ---")
            for mem in ctx.long_term_memories:
                sections.append(self._format_memory_entry(mem))
        
        # 5. Conversation history (short-term)
        if ctx.short_term_memories:
            sections.append("\n--- CONVERSATION HISTORY ---")
            for msg in ctx.short_term_memories:
                sections.append(self._format_conversation_message(msg))
        
        # 6. Current query
        sections.append("\n--- USER QUERY ---")
        sections.append(ctx.current_query)
        
        full_prompt = "\n".join(sections)
        
        # Truncate if necessary (simple approach)
        if len(full_prompt) > self.max_context_chars:
            full_prompt = self._truncate_to_limit(full_prompt, self.max_context_chars)
        
        return full_prompt
