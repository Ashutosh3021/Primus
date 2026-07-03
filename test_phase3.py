"""
Test script for Phase 3 - Memory and Context Engine.
"""

import asyncio

from backend.db import MemoryEntry, ConversationMessage, MemoryLayer, init_db
from backend.api import (
    add_memory,
    get_memory,
    get_all_memories,
    build_prompt,
    add_interaction,
    initialize_memory
)


async def test_memory_crud():
    """Test CRUD operations for memory."""
    print("Testing memory CRUD...")
    
    # Test adding a preference
    pref = MemoryEntry(
        user_id="test_user",
        layer=MemoryLayer.PREFERENCE,
        key="response_style",
        value="Use a friendly, sarcastic tone with Ben 10 references."
    )
    added_pref = await add_memory(pref)
    print(f"Added preference: {added_pref.id} {added_pref.key}")
    
    # Test retrieving
    retrieved = await get_memory("test_user", MemoryLayer.PREFERENCE, "response_style")
    assert retrieved is not None, "Should retrieve preference"
    print(f"Retrieved preference: {retrieved.value}")
    
    # Test adding long-term memory
    long_term = MemoryEntry(
        user_id="test_user",
        layer=MemoryLayer.LONG_TERM,
        key="user_name",
        value="Ashutosh"
    )
    await add_memory(long_term)
    print("Added long-term memory")
    
    # Test getting all memories
    all_prefs = await get_all_memories("test_user", MemoryLayer.PREFERENCE)
    print(f"Retrieved {len(all_prefs)} preference(s)")
    assert len(all_prefs) == 1, "Should have one preference"
    
    print("OK: Memory CRUD tests passed")


async def test_context_engine():
    """Test context engine and prompt building."""
    print("\nTesting context engine...")
    
    # Add some interactions
    await add_interaction(
        "test_user", 
        "test_convo", 
        "Hi, what's my name?", 
        "I don't remember, but I can help you if you tell me!"
    )
    await add_interaction(
        "test_user", 
        "test_convo", 
        "My name is Ashutosh!", 
        "Nice to meet you, Ashutosh!"
    )
    
    # Build prompt
    prompt = await build_prompt("test_user", "test_convo", "What's my name?")
    print("Built prompt:")
    print("-" * 50)
    print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
    print("-" * 50)
    
    assert "Ashutosh" in prompt, "Prompt should include user name memory"
    print("OK: Context engine test passed")


async def main():
    print("=" * 50)
    print("Phase 3 Test Suite")
    print("=" * 50)
    
    await init_db()
    initialize_memory()
    
    await test_memory_crud()
    await test_context_engine()
    
    print("\n" + "=" * 50)
    print("All Phase 3 tests completed successfully!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
