"""
Application startup sequence for Primus backend.
"""

import asyncio
from backend.config import Config, load_config
from backend.api import initialize_router, initialize_memory
from backend.db import init_db
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


async def startup_async() -> Config:
    """Async startup sequence."""
    logger.info("Starting Primus backend...")

    # Load and validate config
    logger.info("Loading configuration...")
    config = load_config()
    logger.info(f"Configuration loaded successfully. Version: {config.version}")

    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Initialize memory system
    logger.info("Initializing memory system...")
    initialize_memory()

    # Initialize AI router
    logger.info("Initializing AI router...")
    initialize_router(config)
    logger.info("AI router initialized.")

    logger.info("Primus backend startup complete.")
    return config


def startup() -> Config:
    """
    Run the application startup sequence (synchronous wrapper).
    """
    return asyncio.run(startup_async())


def shutdown() -> None:
    """
    Run the application shutdown sequence.
    """
    logger.info("Shutting down Primus backend...")
    # TODO: Clean up resources in future phases (close provider clients, etc.)
    logger.info("Primus backend shutdown complete.")
