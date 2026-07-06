"""
Secrets management for Primus backend.

Storage strategy
----------------
On Render (headless Linux) the OS keyring has no backend.  We skip it
entirely and use a dedicated secrets file on the persistent disk.

Write path (set_secret):
  1. Write atomically to SECRETS_PATH (.secrets.env) via a .tmp file so
     a crash between write and rename cannot corrupt the store.
  2. Immediately inject into os.environ so the running process sees the
     value without a restart.

Read path (get_secret):
  Priority:
    1. os.environ  — covers Render dashboard env vars (PROVIDER_GEMINI_API_KEY,
                     MESSAGING_TELEGRAM_BOT_TOKEN, etc.) set before process start.
    2. SECRETS_PATH (.secrets.env) — values written by set_secret() / Wizard.
    3. ENV_PATH (.env) — legacy / developer override.
  get_secret() reloads both files with override=False before each lookup so
  values added by set_secret() in the same process are always visible.

Restart survival
----------------
Both SECRETS_PATH and CONFIG_PATH live under BASE_DIR which is mounted on
Render's persistent 1 GB disk (/opt/render/project/src).  Restarts do not
touch the disk, so all written secrets survive indefinitely.
"""

import os
from pathlib import Path

from dotenv import load_dotenv, dotenv_values

from backend.constants import ENV_PATH, SECRETS_PATH
from backend.exceptions import SecretNotFoundError
from backend.logger import get_errors_logger, register_secret

logger = get_errors_logger(__name__)

# ── Load both secret stores at import time ────────────────────────────────────
# override=False so Render dashboard env vars (already in os.environ) win.
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)
    logger.info(f"Loaded .env from {ENV_PATH}")

if SECRETS_PATH.exists():
    load_dotenv(dotenv_path=SECRETS_PATH, override=True)
    logger.info(f"Loaded secrets store from {SECRETS_PATH}")


def _reload_secrets() -> None:
    """
    Re-read both secret files into os.environ.

    Called by get_secret() so values written by set_secret() during this
    process lifetime are always visible without a restart.
    override=True for SECRETS_PATH ensures a value written by set_secret()
    takes precedence over a stale os.environ entry from the same process.
    """
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False)
    if SECRETS_PATH.exists():
        load_dotenv(dotenv_path=SECRETS_PATH, override=True)


def _write_secrets_file(env_key: str, secret_value: str) -> None:
    """
    Atomically write (or overwrite) a key=value pair in SECRETS_PATH.

    Uses a .tmp file + rename so that a crash mid-write never leaves the
    secrets store in a partially-written, corrupt state.
    """
    # Read existing entries (skip the key we are about to write)
    existing: dict[str, str] = {}
    if SECRETS_PATH.exists():
        existing = dict(dotenv_values(SECRETS_PATH))
    existing[env_key] = secret_value

    # Build file content
    lines = [f"{k}={v}\n" for k, v in existing.items()]

    # Atomic write: write to .tmp then rename
    tmp_path = SECRETS_PATH.with_suffix(".env.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    tmp_path.replace(SECRETS_PATH)

    # Inject into the running process immediately
    os.environ[env_key] = secret_value
    logger.info(f"Secret stored and injected into os.environ: {env_key}")


def get_secret(secret_ref: str) -> str:
    """
    Retrieve a secret.

    Lookup order:
      1. os.environ (covers Render dashboard env vars set before startup)
      2. SECRETS_PATH (.secrets.env) re-loaded fresh
      3. ENV_PATH (.env) re-loaded fresh

    Args:
        secret_ref: Dotted reference, e.g. "provider.gemini.api_key"

    Returns:
        The secret value string.

    Raises:
        SecretNotFoundError: If not found in any store.
    """
    env_key = secret_ref.replace(".", "_").upper()

    # Re-load files so mid-process writes by set_secret() are visible.
    _reload_secrets()

    value = os.getenv(env_key)
    if value:
        register_secret(value)
        logger.info(f"Secret resolved: {secret_ref} (key={env_key})")
        return value

    raise SecretNotFoundError(
        f"Secret not found: {secret_ref} "
        f"(looked for env var {env_key} in os.environ, "
        f"{SECRETS_PATH.name}, and {ENV_PATH.name})"
    )


def set_secret(secret_ref: str, secret_value: str) -> None:
    """
    Persist a secret to the secrets store and inject it into os.environ.

    Args:
        secret_ref:   Dotted reference, e.g. "provider.gemini.api_key"
        secret_value: The plaintext value to store.
    """
    if not secret_value:
        logger.warning(f"set_secret called with empty value for {secret_ref} — ignored")
        return

    env_key = secret_ref.replace(".", "_").upper()
    _write_secrets_file(env_key, secret_value)


def list_stored_secrets() -> list[str]:
    """
    Return the list of secret keys (not values) currently in SECRETS_PATH.
    Used by diagnostics and the health endpoint.
    """
    if not SECRETS_PATH.exists():
        return []
    return list(dotenv_values(SECRETS_PATH).keys())
