"""
Layered memory store for the Context Engine.

Stores the eight context layers in the existing `memories` SQLite table,
reusing the same schema as the legacy memory system but writing the layer as
the `ContextLayer` string value (so the two systems coexist in one table).

Memory is SHARED — there is no provider dimension.  Every entry is written
under a single fixed user id ("default") so all providers read the same
memory.
"""

import aiosqlite
import json
from typing import Any, Dict, List, Optional

from backend.db import DB_PATH
from backend.context.layers import ContextLayer, PERSISTED_LAYERS
from backend.logger import get_errors_logger

logger = get_errors_logger(__name__)

# One shared memory — never provider-specific.
DEFAULT_USER = "default"

# Guard so the store works even if called before init_db() has run.
_ENSURE_TABLE = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, layer, key)
);
"""


class LayeredMemoryStore:
    """Persistent key/value store keyed by (user, layer, key)."""

    async def set(
        self,
        layer: ContextLayer,
        key: str,
        value: str,
        user_id: str = DEFAULT_USER,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = _now()
        md = json.dumps(metadata or {})
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(_ENSURE_TABLE)
            await conn.execute(
                """
                INSERT INTO memories (user_id, layer, key, value, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, layer, key) DO UPDATE SET
                    value=excluded.value,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (user_id, layer.value, key, value, md, now, now),
            )
            await conn.commit()

    async def get(
        self,
        layer: ContextLayer,
        key: str,
        user_id: str = DEFAULT_USER,
    ) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(_ENSURE_TABLE)
            cur = await conn.execute(
                "SELECT key, value, metadata, created_at, updated_at "
                "FROM memories WHERE user_id=? AND layer=? AND key=?",
                (user_id, layer.value, key),
            )
            row = await cur.fetchone()
        if not row:
            return None
        return _row_to_dict(row)

    async def get_all(
        self,
        layer: Optional[ContextLayer] = None,
        user_id: str = DEFAULT_USER,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(_ENSURE_TABLE)
            if layer is not None:
                cur = await conn.execute(
                    "SELECT key, value, metadata, created_at, updated_at "
                    "FROM memories WHERE user_id=? AND layer=? ORDER BY updated_at DESC",
                    (user_id, layer.value),
                )
            else:
                cur = await conn.execute(
                    "SELECT key, value, metadata, created_at, updated_at "
                    "FROM memories WHERE user_id=? ORDER BY updated_at DESC",
                    (user_id,),
                )
            async for row in cur:
                out.append(_row_to_dict(row))
        return out

    async def delete(
        self,
        layer: ContextLayer,
        key: str,
        user_id: str = DEFAULT_USER,
    ) -> bool:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(_ENSURE_TABLE)
            cur = await conn.execute(
                "DELETE FROM memories WHERE user_id=? AND layer=? AND key=?",
                (user_id, layer.value, key),
            )
            await conn.commit()
            return cur.rowcount > 0

    async def count_by_layer(
        self, user_id: str = DEFAULT_USER
    ) -> Dict[str, int]:
        """Return a count per persisted layer (0 for empty layers)."""
        counts = {layer.value: 0 for layer in PERSISTED_LAYERS}
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(_ENSURE_TABLE)
            cur = await conn.execute(
                "SELECT layer, COUNT(*) FROM memories WHERE user_id=? GROUP BY layer",
                (user_id,),
            )
            async for row in cur:
                counts[row[0]] = row[1]
        return counts


def _now() -> str:
    from datetime import datetime

    return datetime.utcnow().isoformat()


def _row_to_dict(row) -> Dict[str, Any]:
    key, value, metadata, created_at, updated_at = row
    try:
        md = json.loads(metadata) if metadata else {}
    except Exception:
        md = {}
    return {
        "key": key,
        "value": value,
        "metadata": md,
        "created_at": created_at,
        "updated_at": updated_at,
    }


__all__ = ["LayeredMemoryStore", "DEFAULT_USER"]
