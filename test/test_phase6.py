"""
Test script for Phase 6: Desktop Agent
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import desktop tools to register them!
import backend.desktop.tools

from backend.desktop import DesktopConnector
from backend.tools import ToolManager


async def test_desktop_capabilities():
    print("\n" + "="*50)
    print("Testing desktop capabilities")
    print("="*50)
    connector = DesktopConnector({})
    await connector._detect_capabilities()
    print(f"OS: {connector.capabilities.os}")
    print(f"Python: {connector.capabilities.python_version}")
    print(f"Git available: {connector.capabilities.has_git}")
    print(f"Ollama available: {connector.capabilities.has_ollama}")
    print(f"Docker available: {connector.capabilities.has_docker}")
    print("OK: Desktop capabilities detected")


async def test_terminal_tool():
    print("\n" + "="*50)
    print("Testing terminal tool")
    print("="*50)
    manager = ToolManager({"terminal": True, "filesystem": True, "python": True, "git": True})
    result = await manager.execute_tool("terminal", command="echo 'Hello, Primus!'")
    print(f"Success: {result.success}")
    print(f"Content: {result.content}")
    if not result.success:
        print(f"Error: {result.error}")
    print("OK: Terminal tool tested")


async def test_filesystem_tool():
    print("\n" + "="*50)
    print("Testing filesystem tool")
    print("="*50)
    manager = ToolManager({"terminal": True, "filesystem": True, "python": True, "git": True})

    # Test list
    result = await manager.execute_tool("filesystem", operation="list", path=".")
    print(f"List success: {result.success}")

    # Test write
    test_content = "This is a test file from Phase 6"
    result = await manager.execute_tool("filesystem",
        operation="write",
        path="test_phase6_temp.txt",
        content=test_content
    )
    print(f"Write success: {result.success}")

    # Test read
    result = await manager.execute_tool("filesystem",
        operation="read",
        path="test_phase6_temp.txt"
    )
    print(f"Read success: {result.success}")
    print(f"Read content matches: {result.content == test_content}")

    # Clean up
    if os.path.exists("test_phase6_temp.txt"):
        os.unlink("test_phase6_temp.txt")

    print("OK: Filesystem tool tested")


async def test_python_tool():
    print("\n" + "="*50)
    print("Testing python tool")
    print("="*50)
    manager = ToolManager({"terminal": True, "filesystem": True, "python": True, "git": True})
    code = "print('Hello from Python!')"
    result = await manager.execute_tool("python", code=code)
    print(f"Success: {result.success}")
    print(f"Output: {result.content}")
    print("OK: Python tool tested")


async def test_git_tool():
    print("\n" + "="*50)
    print("Testing git tool")
    print("="*50)
    manager = ToolManager({"terminal": True, "filesystem": True, "python": True, "git": True})
    result = await manager.execute_tool("git", command="status")
    print(f"Success: {result.success}")
    if result.success:
        print(f"Git status: {result.content[:100]}...")
    else:
        print(f"Error (git may not be available): {result.error}")
    print("OK: Git tool tested")


async def main():
    print("\n" + "="*50)
    print("Phase 6 Test Suite")
    print("="*50)

    await test_desktop_capabilities()
    await test_terminal_tool()
    await test_filesystem_tool()
    await test_python_tool()
    await test_git_tool()

    print("\n" + "="*50)
    print("Phase 6 tests complete!")
    print("="*50)


if __name__ == "__main__":
    asyncio.run(main())
