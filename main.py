#!/usr/bin/env python3
"""
Primus backend entry point.
"""

import asyncio
import sys
from typing import Any

from backend.helpers import setup_signal_handlers
from backend.logger import get_errors_logger
from backend.startup import startup_async, run_forever, shutdown_async

logger = get_errors_logger(__name__)


async def main():
    """Main entry point."""
    try:
        # Run startup
        config = await startup_async()

        # Set up shutdown signals
        def signal_handler(signum: int, frame: Any) -> None:
            logger.info(f"Received signal {signum}, shutting down...")
            asyncio.create_task(shutdown_async())

        setup_signal_handlers(signal_handler)

        # Run forever
        await run_forever(config)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        await shutdown_async()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
