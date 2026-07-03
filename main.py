#!/usr/bin/env python3
"""
Primus backend entry point.
"""

import sys
from typing import Any

from backend.helpers import setup_signal_handlers
from backend.logger import get_errors_logger
from backend.startup import shutdown, startup

logger = get_errors_logger(__name__)


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown()
    sys.exit(0)


def main() -> None:
    """Main entry point."""
    try:
        # Set up signal handlers
        setup_signal_handlers(signal_handler)

        # Run startup
        config = startup()

        # For foundation phase, just exit cleanly after startup
        logger.info("Foundation phase complete. Exiting...")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
