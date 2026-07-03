"""
Application startup sequence for Primus backend.
"""

from backend.config import Config, load_config
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

    # TODO: Initialize dependencies in future phases
    # - Provider
    # - Memory
    # - Messaging
    # - Tools

    logger.info("Primus backend startup complete.")
    return config


def shutdown() -> None:
    """
    Run the application shutdown sequence.
    """
    logger.info("Shutting down Primus backend...")
    # TODO: Clean up resources in future phases
    logger.info("Primus backend shutdown complete.")
