"""
Configuration loading and validation for Primus backend.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from backend.constants import CONFIG_PATH, VERSION
from backend.exceptions import (
    ConfigNotFoundError,
    ConfigInvalidError,
    ConfigVersionError,
)
from backend.validators import validate_config


@dataclass
class ProviderConfig:
    """Provider configuration."""

    name: str
    secret_ref: str
    model: str


@dataclass
class MessagingConfig:
    """Messaging configuration."""

    telegram: Dict[str, Any]
    discord: Dict[str, Any]


@dataclass
class MemoryConfig:
    """Memory configuration."""

    enabled: bool
    backend: str


@dataclass
class ToolsConfig:
    """Tools configuration."""

    web_search: bool
    browser: bool
    terminal: bool


@dataclass
class Config:
    """Full Primus configuration."""

    version: int
    provider: ProviderConfig
    messaging: MessagingConfig
    memory: MemoryConfig
    tools: ToolsConfig


def load_config(config_path: Path = CONFIG_PATH) -> Config:
    """
    Load and validate config from file.

    Args:
        config_path: Path to config.json

    Returns:
        Validated Config object

    Raises:
        ConfigNotFoundError: If config file doesn't exist
        ConfigInvalidError: If config is invalid
        ConfigVersionError: If config version is incompatible
    """
    if not config_path.exists():
        raise ConfigNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    # Validate config structure
    validate_config(data)

    # Check version
    config_version = data.get("version")
    if config_version > VERSION:
        raise ConfigVersionError(
            f"Config version {config_version} is newer than supported version {VERSION}. "
            "Please update Primus."
        )

    # Build config object
    provider = ProviderConfig(
        name=data["provider"]["name"],
        secret_ref=data["provider"]["secret_ref"],
        model=data["provider"]["model"],
    )

    messaging = MessagingConfig(
        telegram=data["messaging"].get("telegram", {"enabled": False}),
        discord=data["messaging"].get("discord", {"enabled": False}),
    )

    memory = MemoryConfig(
        enabled=data["memory"].get("enabled", True),
        backend=data["memory"].get("backend", "sqlite"),
    )

    tools = ToolsConfig(
        web_search=data["tools"].get("web_search", False),
        browser=data["tools"].get("browser", False),
        terminal=data["tools"].get("terminal", False),
    )

    return Config(
        version=config_version,
        provider=provider,
        messaging=messaging,
        memory=memory,
        tools=tools,
    )
