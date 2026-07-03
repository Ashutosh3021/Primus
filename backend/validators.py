"""
Validation functions for Primus config.
"""

from typing import Any, Dict, List

from backend.exceptions import ValidationError


def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> None:
    """
    Validate that required fields are present.

    Args:
        data: Dictionary to validate
        required_fields: List of required field names

    Raises:
        ValidationError: If any required field is missing
    """
    missing = [field for field in required_fields if field not in data]
    if missing:
        raise ValidationError(f"Missing required fields: {', '.join(missing)}")


def validate_provider_config(provider_config: Dict[str, Any]) -> None:
    """
    Validate provider configuration.

    Args:
        provider_config: Provider config dictionary

    Raises:
        ValidationError: If validation fails
    """
    validate_required_fields(provider_config, ["name", "secret_ref", "model"])


def validate_messaging_config(messaging_config: Dict[str, Any]) -> None:
    """
    Validate messaging configuration.

    Args:
        messaging_config: Messaging config dictionary
    """
    pass


def validate_memory_config(memory_config: Dict[str, Any]) -> None:
    """
    Validate memory configuration.

    Args:
        memory_config: Memory config dictionary
    """
    pass


def validate_tools_config(tools_config: Dict[str, Any]) -> None:
    """
    Validate tools configuration.

    Args:
        tools_config: Tools config dictionary
    """
    pass


def validate_config(data: Dict[str, Any]) -> None:
    """
    Validate full config dictionary.

    Args:
        data: Config dictionary

    Raises:
        ValidationError: If validation fails
    """
    validate_required_fields(data, ["version", "provider", "messaging", "memory", "tools"])
    validate_provider_config(data["provider"])
    validate_messaging_config(data["messaging"])
    validate_memory_config(data["memory"])
    validate_tools_config(data["tools"])
