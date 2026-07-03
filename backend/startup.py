"""
Application startup sequence for Primus backend.
"""

from backend.config import Config, load_config
from backend.api import initialize_router
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


def startup() -> Config:
    """
    Run the application startup sequence.

    Returns:
        Loaded and validated Config object
    """
    logger.info("Starting Primus backend...")

    # Load and validate config
    logger.info("Loading configuration...")
    config = load_config()
    logger.info(f"Configuration loaded successfully. Version: {config.version}")

    # Initialize AI router
    logger.info("Initializing AI router...")
    initialize_router(config)
    logger.info("AI router initialized.")

    logger.info("Primus backend startup complete.")
    return config


def shutdown() -> None:
    """
    Run the application shutdown sequence.
    """
    logger.info("Shutting down Primus backend...")
    # TODO: Clean up resources in future phases (close provider clients, etc.)
    logger.info("Primus backend shutdown complete.")
