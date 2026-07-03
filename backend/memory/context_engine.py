"""
Context Engine for retrieving and ranking relevant memories.
"""

from typing import List, Optional
from datetime import datetime, timedelta

from backend.db import (
    MemoryStore,
    ConversationStore,
    MemoryEntry,
    ConversationMessage,
    MemoryLayer
)
from backend.memory.prompt_builder import PromptBuilder, PromptContext
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


class ContextEngine:
    """
    Retrieves, ranks, and compresses context for prompts.
    """

    def __init__(self, max_history_messages: int = 50):
        self.memory_store = MemoryStore()
        self.conversation_store = ConversationStore()
        self.prompt_builder = PromptBuilder()
        self.max_history_messages = max_history_messages

    async def get_relevant_memories(
        self, 
        user_id: str, 
        query: str
    ) -> List[MemoryEntry]:
        """
        Get relevant memories for a query (simple keyword-based for now).
        """
        relevant = []
        query_lower = query.lower()
        
        # Get all long-term memories
        all_memories = await self.memory_store.get_all(user_id, MemoryLayer.LONG_TERM)
        
        for mem in all_memories:
            # Simple keyword matching
            mem_text = f"{mem.key} {mem.value}".lower()
            if any(keyword in mem_text for keyword in query_lower.split()):
                relevant.append(mem)
        
        # Limit to 20 most recent relevant
        return sorted(relevant, key=lambda m: m.updated_at or datetime.min, reverse=True)[:20]

    async def build_context(
        self, 
        user_id: str, 
        conversation_id: str, 
        query: str
    ) -> PromptContext:
        """
        Build a complete prompt context.
        """
        # Get preferences
        preferences = await self.memory_store.get_all(user_id, MemoryLayer.PREFERENCE)
        
        # Get project info
        project_info = await self.memory_store.get_all(user_id, MemoryLayer.PROJECT)
        
        # Get relevant long-term memories
        long_term_memories = await self.get_relevant_memories(user_id, query)
        
        # Get recent conversation (short-term)
        short_term_memories = await self.conversation_store.get_conversation(
            user_id, 
            conversation_id, 
            self.max_history_messages
        )
        
        ctx = PromptContext(
            long_term_memories=long_term_memories,
            short_term_memories=short_term_memories,
            preferences=preferences,
            project_info=project_info,
            current_query=query
        )
        
        return ctx

    async def build_prompt(
        self, 
        user_id: str, 
        conversation_id: str, 
        query: str
    ) -> str:
        """Build prompt from context."""
        ctx = await self.build_context(user_id, conversation_id, query)
        return self.prompt_builder.build_prompt(ctx)

    async def add_interaction(
        self, 
        user_id: str, 
        conversation_id: str, 
        user_message: str, 
        assistant_response: str
    ):
        """Add interaction to conversation history."""
        # Add user message
        await self.conversation_store.add(ConversationMessage(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=user_message
        ))
        
        # Add assistant response
        await self.conversation_store.add(ConversationMessage(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_response
        ))
