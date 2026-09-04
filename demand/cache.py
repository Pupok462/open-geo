from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB = "data/demand_cache.db"
DEFAULT_TTL_DAYS = 7


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS demand_cache ("
        " provider TEXT NOT NULL,"
        " key TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " fetched_at TEXT NOT NULL,"
        " fetched_epoch REAL NOT NULL,"
        " PRIMARY KEY (provider, key))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS demand_quota ("
        " provider TEXT NOT NULL,"
        " day TEXT NOT NULL,"
        " used INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (provider, day))"
    )
    conn.commit()


def get(
    conn: sqlite3.Connection,
    provider: str,
    key: str,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> Optional[Any]:
    """Return the cached payload, or None when absent or stale.

    Volume figures move slowly; re-asking for the same phrase inside the TTL only
    burns a scarce daily quota (Wordstat allows 1000 calls/day).
    """
    if ttl_days <= 0:
        return None
    row = conn.execute(
        "SELECT payload, fetched_epoch FROM demand_cache WHERE provider=? AND key=?",
        (provider, key),
    ).fetchone()
    if row is None:
        return None
    if time.time() - float(row["fetched_epoch"]) > ttl_days * 86400:
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def put(conn: sqlite3.Connection, provider: str, key: str, payload: Any) -> None:
    conn.execute(
        "INSERT INTO demand_cache(provider, key, payload, fetched_at, fetched_epoch) "
        "VALUES(?,?,?,?,?) ON CONFLICT(provider, key) DO UPDATE SET "
        "payload=excluded.payload, fetched_at=excluded.fetched_at, "
        "fetched_epoch=excluded.fetched_epoch",
        (provider, key, json.dumps(payload, ensure_ascii=False), _utcnow_iso(), time.time()),
    )
    conn.commit()


def quota_used(conn: sqlite3.Connection, provider: str, day: str | None = None) -> int:
    day = day or date.today().isoformat()
    row = conn.execute(
        "SELECT used FROM demand_quota WHERE provider=? AND day=?", (provider, day)
    ).fetchone()
    return int(row["used"]) if row else 0


def quota_bump(conn: sqlite3.Connection, provider: str, n: int = 1) -> int:
    day = date.today().isoformat()
    conn.execute(
        "INSERT INTO demand_quota(provider, day, used) VALUES(?,?,?) "
        "ON CONFLICT(provider, day) DO UPDATE SET used = used + excluded.used",
        (provider, day, n),
    )
    conn.commit()
    return quota_used(conn, provider, day)


__all__ = [
    "get_conn", "init_db", "get", "put", "quota_used", "quota_bump",
    "DEFAULT_DB", "DEFAULT_TTL_DAYS",
]
