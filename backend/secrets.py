"""
Secrets management for Primus backend.
"""

from backend.exceptions import SecretNotFoundError


def get_secret(secret_ref: str) -> str:
    """
    Get a secret from the secret store.

    Args:
        secret_ref: Reference to the secret

    Returns:
        The secret value

    Raises:
        SecretNotFoundError: If secret is not found
    """
    # TODO: Implement OS keyring and .env fallback
    raise SecretNotFoundError(f"Secrets module not yet implemented. Secret ref: {secret_ref}")
