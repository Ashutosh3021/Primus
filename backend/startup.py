
"""
Application startup sequence for Primus backend.
"""

import asyncio
import signal
from backend.config import Config, load_config
from backend.api import (
    initialize_router, initialize_memory, initialize_tools,
    initialize_messaging, initialize_jobs, initialize_desktop,
    start_messaging, stop_messaging, start_jobs, stop_jobs,
    start_desktop, stop_desktop
)
from backend.db import init_db
from backend.logger import get_errors_logger
from backend.diagnostics import get_diagnostics_manager
from backend.metrics import get_metrics_registry
from backend.health import get_health_checker
from backend.recovery import get_recovery_manager

logger = get_errors_logger(__name__)
_running = False


async def startup_async() -> Config:
    """Async startup sequence."""
    global _running
    logger.info("Starting Primus backend...")

    # Start diagnostics
    diag = get_diagnostics_manager()
    diag.start_diagnostics()

    try:
        # Load and validate config
        logger.info("Loading configuration...")
        config = load_config()
        diag.mark_config_loaded()
        logger.info(f"Configuration loaded successfully. Version: {config.version}")

        # Initialize database
        logger.info("Initializing database...")
        await init_db()
        diag.mark_db_initialized()

        # Initialize memory system
        logger.info("Initializing memory system...")
        initialize_memory()
        diag.mark_memory_initialized()

        # Initialize tools
        logger.info("Initializing tool system...")
        initialize_tools(config)
        diag.mark_tools_initialized()

        # Initialize jobs
        logger.info("Initializing job system...")
        initialize_jobs(config)
        diag.mark_jobs_initialized()

        # Initialize AI router
        logger.info("Initializing AI router...")
        initialize_router(config)
        diag.mark_router_initialized()

        # Initialize messaging
        logger.info("Initializing messaging...")
        initialize_messaging(config)
        diag.mark_messaging_initialized()

        # Initialize desktop
        logger.info("Initializing desktop agent...")
        initialize_desktop(config)
        diag.mark_desktop_initialized()

        _running = True
        logger.info("Primus backend startup complete.")
        return config
    except Exception as e:
        diag.add_error(str(e))
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise


async def run_forever(config: Config):
    """Run forever, handling signals."""
    global _running

    # Start messaging, jobs, and desktop
    await start_messaging()
    await start_jobs()
    await start_desktop()

    # Wait until shutdown
    while _running:
        await asyncio.sleep(1)


def startup() -> Config:
    """
    Run the application startup sequence (synchronous wrapper).
    """
    return asyncio.run(startup_async())


async def shutdown_async():
    """Async shutdown sequence."""
    global _running
    logger.info("Shutting down Primus backend...")
    _running = False
    await stop_desktop()
    await stop_messaging()
    await stop_jobs()
    logger.info("Primus backend shutdown complete.")


def shutdown() -> None:
    """
    Run the application shutdown sequence.
    """
    asyncio.run(shutdown_async())

