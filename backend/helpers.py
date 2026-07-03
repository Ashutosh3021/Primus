"""
Utility functions for Primus backend.
"""

import signal
from typing import Any, Callable


def setup_signal_handlers(handler: Callable[[int, Any], None]) -> None:
    """
    Set up signal handlers for graceful shutdown.

    Args:
        handler: Signal handler function
    """
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
