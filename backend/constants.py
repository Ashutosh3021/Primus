"""
Constants for Primus backend.
"""

from pathlib import Path

# Version
VERSION: int = 1

# Paths
BASE_DIR: Path = Path(__file__).parent.parent
BACKEND_DIR: Path = BASE_DIR / "backend"
CONFIG_PATH: Path = BASE_DIR / "config.json"
ENV_PATH: Path = BASE_DIR / ".env"
SECRETS_PATH: Path = BASE_DIR / ".secrets.env"   # persistent secrets store (never commit)
LOG_DIR: Path = BASE_DIR / "logs"

# Log streams
LOG_STREAMS = [
    "ai_requests",
    "tool_calls",
    "errors",
    "jobs",
    "notifications",
    "metrics",
    "health",
    "diagnostics",
    "recovery",
]

# Default log file size (10MB)
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024

# Default log backup count (5)
DEFAULT_LOG_BACKUP_COUNT = 5
