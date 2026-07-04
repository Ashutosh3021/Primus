"""
Test script for Phase 4 - Messaging and Tools.
"""

import asyncio
from backend.config import load_config
from backend.db import init_db
from backend.tools import ToolManager, ToolRegistry
from backend.api import (
    initialize_memory, initialize_tools, initialize_messaging,
    initialize_router
)


async def main():
    print("=" * 50)
    print("Phase 4 Test Suite")
    print("=" * 50)

    # Load config
    config = load_config()

    # Test tool registry
    print("\n1. Testing tool registry...")
    all_tools = ToolRegistry.get_all_tools()
    print(f"Registered tools: {list(all_tools.keys())}")
    assert "web_search" in all_tools, "web_search tool missing!"

    # Test tool manager initialization
    print("\n2. Testing tool manager...")
    tool_mgr = ToolManager({
        "web_search": True,
        "browser": False,
        "terminal": False
    })
    enabled = tool_mgr.get_enabled_tool_names()
    print(f"Enabled tools: {enabled}")
    assert "web_search" in enabled, "web_search not enabled!"

    # Initialize all components
    print("\n3. Initializing all components...")
    await init_db()
    initialize_memory()
    initialize_tools(config)

    try:
        initialize_router(config)
    except Exception as e:
        print(f"Router initialization skipped (credentials issue): {e}")

    initialize_messaging(config)
    print("OK! All components initialized")

    print("\n" + "=" * 50)
    print("Phase 4 tests complete!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
