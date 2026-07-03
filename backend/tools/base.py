"""
Base tool class and registry for Primus.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Type
from dataclasses import dataclass

from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


@dataclass
class ToolParam:
    """Tool parameter definition."""
    name: str
    type: str
    description: str
    required: bool = True


@dataclass
class ToolResult:
    """Tool execution result."""
    success: bool
    content: str
    error: Optional[str] = None


class BaseTool(ABC):
    """Base class for all tools."""

    name: str
    description: str
    params: List[ToolParam]

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        pass


class ToolRegistry:
    """Registry for all available tools."""

    _tools: Dict[str, Type[BaseTool]] = {}

    @classmethod
    def register(cls, tool_cls: Type[BaseTool]) -> Type[BaseTool]:
        """Decorator to register a tool class."""
        tool_name = tool_cls.name
        if tool_name in cls._tools:
            logger.warning(f"Tool {tool_name} already registered, overwriting")
        cls._tools[tool_name] = tool_cls
        logger.info(f"Registered tool: {tool_name}")
        return tool_cls

    @classmethod
    def get_tool(cls, name: str) -> Optional[Type[BaseTool]]:
        """Get a tool class by name."""
        return cls._tools.get(name)

    @classmethod
    def get_all_tools(cls) -> Dict[str, Type[BaseTool]]:
        """Get all registered tools."""
        return dict(cls._tools)


class ToolManager:
    """Manager for executing tools."""

    def __init__(self, config_tools: Dict[str, bool]):
        self.enabled_tools = {
            name: cls for name, cls in ToolRegistry.get_all_tools().items()
            if config_tools.get(name, False)
        }
        self.instances: Dict[str, BaseTool] = {}
        logger.info(f"Tool manager initialized with tools: {list(self.enabled_tools.keys())}")

    def get_enabled_tool_names(self) -> List[str]:
        """Get list of enabled tool names."""
        return list(self.enabled_tools.keys())

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute an enabled tool."""
        if tool_name not in self.enabled_tools:
            return ToolResult(
                success=False,
                content="",
                error=f"Tool {tool_name} is not enabled"
            )

        try:
            if tool_name not in self.instances:
                self.instances[tool_name] = self.enabled_tools[tool_name]()

            tool = self.instances[tool_name]
            return await tool.execute(**kwargs)

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Error executing tool: {str(e)}"
            )
