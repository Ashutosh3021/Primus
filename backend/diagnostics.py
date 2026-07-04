
"""
Startup diagnostics and system information for Primus backend.
"""
import sys
import platform
import psutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List
from datetime import datetime

from backend.constants import VERSION, BASE_DIR
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


@dataclass
class SystemInfo:
    """System information."""
    python_version: str
    platform: str
    architecture: str
    processor: str
    memory_total: int
    memory_available: int
    cpu_count: int
    cpu_percent: float
    disk_total: int
    disk_available: int


@dataclass
class StartupDiagnostic:
    """Startup diagnostic result."""
    timestamp: str
    version: int
    system: SystemInfo
    config_loaded: bool = False
    db_initialized: bool = False
    memory_initialized: bool = False
    tools_initialized: bool = False
    jobs_initialized: bool = False
    router_initialized: bool = False
    messaging_initialized: bool = False
    desktop_initialized: bool = False
    errors: List[str] = field(default_factory=list)


class DiagnosticsManager:
    """Manager for diagnostics and system info."""

    def __init__(self):
        self._startup_diagnostic = None
        self._start_time = None

    def start_diagnostics(self):
        """Start the startup diagnostics."""
        self._start_time = datetime.now().timestamp()
        self._startup_diagnostic = StartupDiagnostic(
            timestamp=datetime.now().isoformat(),
            version=VERSION,
            system=self._collect_system_info()
        )
        logger.info("Startup diagnostics initialized")

    def mark_config_loaded(self):
        """Mark configuration as loaded."""
        if self._startup_diagnostic:
            self._startup_diagnostic.config_loaded = True

    def mark_db_initialized(self):
        """Mark database as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.db_initialized = True

    def mark_memory_initialized(self):
        """Mark memory system as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.memory_initialized = True

    def mark_tools_initialized(self):
        """Mark tools as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.tools_initialized = True

    def mark_jobs_initialized(self):
        """Mark jobs as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.jobs_initialized = True

    def mark_router_initialized(self):
        """Mark AI router as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.router_initialized = True

    def mark_messaging_initialized(self):
        """Mark messaging as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.messaging_initialized = True

    def mark_desktop_initialized(self):
        """Mark desktop agent as initialized."""
        if self._startup_diagnostic:
            self._startup_diagnostic.desktop_initialized = True

    def add_error(self, error):
        """
        Add an error to diagnostics.

        Args:
            error: Error message
        """
        if self._startup_diagnostic:
            self._startup_diagnostic.errors.append(error)

    def get_startup_diagnostic(self):
        """Get the startup diagnostic result."""
        return self._startup_diagnostic

    def get_system_info(self):
        """
        Get current system information.

        Returns:
            Dictionary of system info
        """
        info = self._collect_system_info()
        return {
            "python_version": info.python_version,
            "platform": info.platform,
            "architecture": info.architecture,
            "processor": info.processor,
            "memory": {
                "total": info.memory_total,
                "available": info.memory_available
            },
            "cpu": {
                "count": info.cpu_count,
                "percent": info.cpu_percent
            },
            "disk": {
                "total": info.disk_total,
                "available": info.disk_available
            }
        }

    def get_uptime(self):
        """
        Get application uptime in seconds.

        Returns:
            Uptime in seconds
        """
        if self._start_time:
            return datetime.now().timestamp() - self._start_time
        return 0.0

    def _collect_system_info(self):
        """Collect system information."""
        mem = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage(".")
        except Exception:
            # Fallback if disk usage fails
            disk = type('obj', (object,), {'total': 0, 'free': 0})()
        return SystemInfo(
            python_version=sys.version,
            platform=platform.platform(),
            architecture=platform.machine(),
            processor=platform.processor(),
            memory_total=mem.total,
            memory_available=mem.available,
            cpu_count=psutil.cpu_count(),
            cpu_percent=psutil.cpu_percent(),
            disk_total=disk.total,
            disk_available=disk.free
        )


# Global diagnostics manager
_diagnostics_manager = DiagnosticsManager()


def get_diagnostics_manager():
    """Get the global diagnostics manager."""
    return _diagnostics_manager

