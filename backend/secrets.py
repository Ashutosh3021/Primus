"""
Secrets management for Primus backend (OS keyring + .env fallback).

Persistence strategy
--------------------
1. set_secret() tries the OS keyring first.  On headless Linux servers
   (Render, Docker) there is no D-Bus / SecretService backend, so keyring
   raises an exception.  We catch that exception and fall through to the
   .env file writer — no 500 is ever returned to the caller.

2. After writing to .env we ALSO inject the value directly into os.environ
   so that get_secret() can retrieve it in the *same process* without
   waiting for a restart.  load_dotenv() runs once at module import time;
   values written to .env after that are invisible to os.getenv() unless
   we update os.environ ourselves.

3. get_secret() tries the OS keyring first, then os.environ.  It calls
   load_dotenv(override=True) right before the os.getenv() call so that
   newly written .env values (from a previous set_secret) are always
   visible, even when the module-level load_dotenv ran before the secret
   was stored.
"""

import os

from dotenv import load_dotenv
import keyring

from backend.constants import ENV_PATH
from backend.exceptions import SecretNotFoundError
from backend.logger import get_errors_logger, register_secret

logger = get_errors_logger(__name__)

# Load environment variables from .env file if present at import time.
# set_secret() and get_secret() each call load_dotenv(override=True) as
# needed so that values written to .env mid-process are always visible.
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
    logger.info(f"Loaded environment variables from {ENV_PATH}")


def _write_env_file(env_key: str, secret_value: str) -> None:
    """
    Write (or overwrite) a key=value pair in the .env file and immediately
    inject it into os.environ so the running process can read it without a
    restart.
    """
    lines: list = []

    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Remove any existing entry for this key
    new_lines = [
        line for line in lines
        if not line.strip().startswith(env_key + "=")
    ]

    # Append the new entry
    new_lines.append(f"{env_key}={secret_value}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Inject immediately into the running process so get_secret() works
    # without a restart — os.getenv() reads os.environ, not the file.
    os.environ[env_key] = secret_value
    logger.info(f"Stored secret in .env and injected into os.environ: {env_key}")


def get_secret(secret_ref: str) -> str:
    """
    Get a secret from the secret store. First tries OS keychain, then .env file.

    Calls load_dotenv(override=True) before reading os.environ so that secrets
    written by set_secret() in the same process lifetime are always visible,
    even if they were written after the module-level load_dotenv() ran at
    import time.

    Args:
        secret_ref: Reference to the secret (e.g., "provider.openrouter.api_key")

    Returns:
        The secret value

    Raises:
        SecretNotFoundError: If secret is not found in either store
    """
    # 1. Try OS keyring
    try:
        secret = keyring.get_password("primus", secret_ref)
        if secret:
            register_secret(secret)
            logger.info(f"Retrieved secret from keychain: {secret_ref}")
            return secret
    except Exception as e:
        logger.warning(f"Failed to retrieve from keychain: {e}")

    # 2. Re-load .env so values written by set_secret() mid-process are visible
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=True)

    # 3. Try os.environ (covers both pre-existing env vars and .env values)
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

    Tries the OS keyring when use_keyring=True.  If the keyring is
    unavailable (e.g. headless Linux on Render), falls back to the .env
    file automatically — no exception is propagated to the caller.

    Args:
        secret_ref: Reference to the secret (e.g., "provider.openrouter.api_key")
        secret_value: The secret value to store
        use_keyring: Whether to attempt the OS keyring first (default True)
    """
    env_key = secret_ref.replace(".", "_").upper()

    if use_keyring:
        try:
            keyring.set_password("primus", secret_ref, secret_value)
            logger.info(f"Stored secret in keychain: {secret_ref}")
            # Also inject into os.environ so get_secret() works in-process
            # without having to re-read the keyring on every call.
            os.environ[env_key] = secret_value
            return
        except Exception as e:
            logger.warning(
                f"Keyring unavailable ({type(e).__name__}: {e}) — "
                f"falling back to .env file for secret: {secret_ref}"
            )

    # .env fallback — always reaches here when keyring is absent or fails
    _write_env_file(env_key, secret_value)
