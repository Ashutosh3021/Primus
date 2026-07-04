"""
Desktop agent module for Primus.
"""
import os
import platform
import asyncio
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


@dataclass
class DesktopCapabilities:
    """Desktop capabilities detected at runtime."""
    os: str = field(default_factory=platform.system)
    python_version: str = field(default_factory=platform.python_version)
    has_terminal: bool = True
    has_filesystem: bool = True
    has_git: bool = False
    has_ollama: bool = False
    has_docker: bool = False
    online: bool = True


class DesktopConnector:
    """Base class for desktop agent connector."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.capabilities = DesktopCapabilities()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._last_heartbeat: Optional[datetime] = None

    async def start(self):
        """Start the desktop connector and heartbeat."""
        logger.info("Starting desktop connector...")
        await self._detect_capabilities()
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Desktop connector started")

    async def stop(self):
        """Stop the desktop connector."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        logger.info("Desktop connector stopped")

    async def _detect_capabilities(self):
        """Detect what's available on the desktop."""
        # Check for git
        try:
            git_path = os.popen("git --version").read()
            self.capabilities.has_git = "git version" in git_path
        except Exception:
            pass

        # Check for ollama
        try:
            ollama_path = os.popen("ollama --version").read()
            self.capabilities.has_ollama = "ollama version" in ollama_path
        except Exception:
            pass

        # Check for docker
        try:
            docker_path = os.popen("docker --version").read()
            self.capabilities.has_docker = "Docker version" in docker_path
        except Exception:
            pass

        logger.info(f"Detected capabilities: {self.capabilities}")

    async def _heartbeat_loop(self):
        """Send heartbeats periodically."""
        while self._running:
            try:
                self._last_heartbeat = datetime.utcnow()
                await asyncio.sleep(30)  # Every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)


class PermissionValidator:
    """Validates permissions for desktop operations."""

    def __init__(self, allowed_paths: list[str]):
        self.allowed_paths = allowed_paths

    def can_read(self, path: str) -> bool:
        """Check if we can read from the path."""
        normalized = os.path.normpath(path)
        for allowed in self.allowed_paths:
            if normalized.startswith(os.path.normpath(allowed)):
                return True
        return False

    def can_write(self, path: str) -> bool:
        """Check if we can write to the path."""
        return self.can_read(path)

    def can_execute(self, command: str) -> bool:
        """Check if we can execute a command."""
        # For now, allow all (should be more restrictive in production)
        return True


__all__ = [
    "DesktopCapabilities",
    "DesktopConnector",
    "PermissionValidator"
]
