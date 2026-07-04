"""
Tools module for Primus.
"""

# Import tools here to register them
import backend.tools.web_search

from backend.tools.base import (
    BaseTool, ToolParam, ToolResult, ToolRegistry, ToolManager
)

__all__ = [
    "BaseTool",
    "ToolParam",
    "ToolResult",
    "ToolRegistry",
    "ToolManager"
]
