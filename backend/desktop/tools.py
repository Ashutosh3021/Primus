"""
Desktop tools for Primus.
"""
import os
import subprocess
import asyncio
from typing import Dict, Any, Optional, List
from backend.tools.base import BaseTool, ToolParam, ToolResult, ToolRegistry
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


@ToolRegistry.register
class TerminalTool(BaseTool):
    """Tool for executing terminal commands."""
    name = "terminal"
    description = "Execute commands in a local terminal"
    params = [
        ToolParam("command", "string", "The command to execute", required=True),
        ToolParam("timeout", "integer", "Timeout in seconds (default 60)", required=False)
    ]

    async def execute(self, command: str, timeout: int = 60, **kwargs) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode() + stderr.decode()

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Command failed with code {proc.returncode}: {output}"
                )

            return ToolResult(success=True, content=output)

        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(
                success=False,
                content="",
                error=f"Command timed out after {timeout} seconds"
            )
        except Exception as e:
            logger.error(f"Terminal tool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to execute command: {str(e)}"
            )


@ToolRegistry.register
class FilesystemTool(BaseTool):
    """Tool for filesystem operations."""
    name = "filesystem"
    description = "Read or write local files"
    params = [
        ToolParam("operation", "string", "Operation to perform: read, write, list", required=True),
        ToolParam("path", "string", "Path to file or directory", required=True),
        ToolParam("content", "string", "Content for write operation", required=False)
    ]

    async def execute(self, operation: str, path: str, content: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            if operation == "read":
                with open(path, "r", encoding="utf-8") as f:
                    return ToolResult(success=True, content=f.read())

            elif operation == "write":
                if content is None:
                    return ToolResult(
                        success=False,
                        content="",
                        error="Content is required for write operation"
                    )
                dirname = os.path.dirname(path)
                if dirname:  # Only create directories if there is one!
                    os.makedirs(dirname, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return ToolResult(success=True, content=f"Successfully wrote to {path}")

            elif operation == "list":
                items = os.listdir(path)
                return ToolResult(
                    success=True,
                    content="\n".join(items)
                )

            else:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Unknown operation: {operation}"
                )

        except Exception as e:
            logger.error(f"Filesystem tool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to perform operation: {str(e)}"
            )


@ToolRegistry.register
class PythonTool(BaseTool):
    """Tool for executing Python code."""
    name = "python"
    description = "Execute Python code locally"
    params = [
        ToolParam("code", "string", "Python code to execute", required=True),
        ToolParam("timeout", "integer", "Timeout in seconds (default 30)", required=False)
    ]

    async def execute(self, code: str, timeout: int = 30, **kwargs) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "-c", code,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode() + stderr.decode()

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Code execution failed with code {proc.returncode}: {output}"
                )

            return ToolResult(success=True, content=output)

        except Exception as e:
            logger.error(f"Python tool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to execute code: {str(e)}"
            )


@ToolRegistry.register
class GitTool(BaseTool):
    """Tool for git operations."""
    name = "git"
    description = "Perform git operations in local repositories"
    params = [
        ToolParam("command", "string", "Git command to run", required=True),
        ToolParam("path", "string", "Path to git repository", required=False)
    ]

    async def execute(self, command: str, path: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            cmd = f"git {command}"
            if path:
                cmd = f"cd {path} && {cmd}"

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()
            output = stdout.decode() + stderr.decode()

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Git command failed with code {proc.returncode}: {output}"
                )

            return ToolResult(success=True, content=output)

        except Exception as e:
            logger.error(f"Git tool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to execute git command: {str(e)}"
            )


@ToolRegistry.register
class OllamaTool(BaseTool):
    """Tool for interacting with Ollama."""
    name = "ollama"
    description = "Run local models with Ollama"
    params = [
        ToolParam("model", "string", "Ollama model to use", required=True),
        ToolParam("prompt", "string", "Prompt to send to the model", required=True)
    ]

    async def execute(self, model: str, prompt: str, **kwargs) -> ToolResult:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    "http://localhost:11434/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False}
                )
                response.raise_for_status()
                data = response.json()

                return ToolResult(
                    success=True,
                    content=data.get("response", "")
                )

        except Exception as e:
            logger.error(f"Ollama tool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to use Ollama: {str(e)}"
            )


@ToolRegistry.register
class DockerTool(BaseTool):
    """Tool for Docker operations."""
    name = "docker"
    description = "Manage Docker containers and images"
    params = [
        ToolParam("command", "string", "Docker command to run", required=True)
    ]

    async def execute(self, command: str, **kwargs) -> ToolResult:
        try:
            cmd = f"docker {command}"
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = await proc.communicate()
            output = stdout.decode() + stderr.decode()

            if proc.returncode != 0:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Docker command failed with code {proc.returncode}: {output}"
                )

            return ToolResult(success=True, content=output)

        except Exception as e:
            logger.error(f"Docker tool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                content="",
                error=f"Failed to execute docker command: {str(e)}"
            )


__all__ = [
    "TerminalTool",
    "FilesystemTool",
    "PythonTool",
    "GitTool",
    "OllamaTool",
    "DockerTool"
]
