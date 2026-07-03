"""
Secrets management for Primus backend (OS keyring + .env fallback).
"""

import os
from typing import Optional

from dotenv import load_dotenv
import keyring

from backend.constants import ENV_PATH
from backend.exceptions import SecretNotFoundError
from backend.logger import get_errors_logger, register_secret

logger = get_errors_logger(__name__)

# Load environment variables from .env file if present
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
    logger.info(f"Loaded environment variables from {ENV_PATH}")


def get_secret(secret_ref: str) -> str:
    """
    Get a secret from the secret store. First tries OS keychain, then .env file.
    
    Args:
        secret_ref: Reference to the secret (e.g., "provider.openrouter.api_key")
        
    Returns:
        The secret value
        
    Raises:
        SecretNotFoundError: If secret is not found in either store
    """
    # First try OS keyring
    try:
        secret = keyring.get_password("primus", secret_ref)
        if secret:
            register_secret(secret)
            logger.info(f"Retrieved secret from keychain: {secret_ref}")
            return secret
    except Exception as e:
        logger.warning(f"Failed to retrieve from keychain: {e}")
    
    # If not found, try .env file
    env_key = secret_ref.replace(".", "_").upper()
    secret = os.getenv(env_key)
    if secret:
        register_secret(secret)
        logger.info(f"Retrieved secret from .env: {env_key}")
        return secret
        
    raise SecretNotFoundError(
        f"Secret not found: {secret_ref} (tried keychain and .env variable {env_key})"
    )


def set_secret(secret_ref: str, secret_value: str, use_keyring: bool = True) -> None:
    """
    Set a secret in the secret store.
    
    Args:
        secret_ref: Reference to the secret (e.g., "provider.openrouter.api_key")
        secret_value: The secret value to store
        use_keyring: Whether to use OS keyring (True) or .env file (False)
    """
    if use_keyring:
        keyring.set_password("primus", secret_ref, secret_value)
        logger.info(f"Stored secret in keychain: {secret_ref}")
    else:
        # Write to .env file
        env_key = secret_ref.replace(".", "_").upper()
        lines = []
        
        if ENV_PATH.exists():
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
        # Remove existing entry
        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith(env_key + "="):
                found = True
            else:
                new_lines.append(line)
                
        # Add new entry
        new_lines.append(f"{env_key}={secret_value}\n")
        
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
            
        logger.info(f"Stored secret in .env: {env_key}")
