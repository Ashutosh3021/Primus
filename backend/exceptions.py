"""
Custom exceptions for Primus backend.
"""


class PrimusException(Exception):
    """Base exception for all Primus errors."""

    pass


class ConfigError(PrimusException):
    """Raised when there's an error with configuration."""

    pass


class ConfigNotFoundError(ConfigError):
    """Raised when config.json is not found."""

    pass


class ConfigInvalidError(ConfigError):
    """Raised when config.json is invalid."""

    pass


class ConfigVersionError(ConfigError):
    """Raised when config version is incompatible."""

    pass


class SecretError(PrimusException):
    """Raised when there's an error with secrets."""

    pass


class SecretNotFoundError(SecretError):
    """Raised when a secret is not found."""

    pass


class ValidationError(PrimusException):
    """Raised when validation fails."""

    pass


class ProviderError(PrimusException):
    """Raised when there's an error with a provider."""

    pass


class MessagingError(PrimusException):
    """Raised when there's an error with messaging."""

    pass
