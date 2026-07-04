#!/usr/bin/env python3
"""
Primus entry point.

Starts the FastAPI HTTP server. The server lifespan handler runs the full
backend startup sequence (config → db → memory → tools → jobs → router →
messaging → desktop) before accepting traffic.

Port and host are resolved from environment variables so that Render (and any
other PaaS) can inject them at runtime.
"""

import os
import sys

import uvicorn

from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("PRIMUS_RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    logger.info(f"Starting Primus on {host}:{port}")

    uvicorn.run(
        "backend.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        access_log=True,
    )


if __name__ == "__main__":
    main()
