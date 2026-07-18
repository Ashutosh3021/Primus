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
    Validate a single legacy provider block.

    Args:
        provider_config: Provider config dictionary

    Raises:
        ValidationError: If validation fails
    """
    validate_required_fields(provider_config, ["name", "model"])
    # secret_ref is required for all cloud providers; Ollama runs locally
    # and uses the env-var placeholder "not-required" set in render.yaml.
    if provider_config.get("name") != "ollama":
        validate_required_fields(provider_config, ["secret_ref"])


def validate_providers_map(providers_map: Dict[str, Any]) -> None:
    """
    Validate the multi-provider map (v1.3.0 schema).

    Each entry must declare a `default_model`.  Cloud providers must declare a
    `secret_ref` (Ollama is exempt).  The legacy `provider` block is optional
    once a `providers` map is present.
    """
    if not isinstance(providers_map, dict) or not providers_map:
        raise ValidationError("'providers' must be a non-empty object.")
    for name, cfg in providers_map.items():
        if not isinstance(cfg, dict):
            raise ValidationError(f"Provider '{name}' config must be an object.")
        if "default_model" not in cfg:
            raise ValidationError(
                f"Provider '{name}' is missing required field 'default_model'."
            )
        if name != "ollama" and not cfg.get("secret_ref"):
            raise ValidationError(
                f"Provider '{name}' is missing required field 'secret_ref'."
            )


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

    Supports both the legacy schema (a single `provider` block) and the new
    multi-provider schema (a `providers` map).  At least one of the two must
    be present.

    Args:
        data: Config dictionary

    Raises:
        ValidationError: If validation fails
    """
    validate_required_fields(data, ["version", "messaging", "memory", "tools"])

    has_map = "providers" in data and isinstance(data.get("providers"), dict) and data["providers"]
    has_legacy = "provider" in data and isinstance(data.get("provider"), dict)

    if not has_map and not has_legacy:
        raise ValidationError("Config must declare either 'providers' or 'provider'.")

    if has_map:
        validate_providers_map(data["providers"])
    elif has_legacy:
        validate_provider_config(data["provider"])

    validate_messaging_config(data["messaging"])
    validate_memory_config(data["memory"])
    validate_tools_config(data["tools"])
