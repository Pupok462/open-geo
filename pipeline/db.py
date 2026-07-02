from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: str = "data/aeo.db") -> sqlite3.Connection:
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    existing = _table_columns(conn, table)
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _ensure_results_unique_index(conn: sqlite3.Connection) -> None:
    have = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' "
        "AND name='idx_results_run_query_lens'"
    ).fetchone()
    if have is not None:
        return
    conn.execute(
        "DELETE FROM results WHERE id NOT IN ("
        "SELECT MIN(id) FROM results GROUP BY run_id, query, lens)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_results_run_query_lens "
        "ON results(run_id, query, lens)"
    )


_METRICS_MIGRATION_COLUMNS = {"relative_citation": "REAL"}


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS brands (
            id         INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            domain     TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(name, domain)
        );

        CREATE TABLE IF NOT EXISTS runs (
            id        INTEGER PRIMARY KEY,
            brand_id  INTEGER NOT NULL REFERENCES brands(id),
            engine    TEXT NOT NULL,
            run_at    TEXT NOT NULL,
            status    TEXT NOT NULL DEFAULT 'running',
            n_queries INTEGER NOT NULL DEFAULT 0,
            n_ok      INTEGER NOT NULL DEFAULT 0,
            n_failed  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS results (
            id                        INTEGER PRIMARY KEY,
            run_id                    INTEGER NOT NULL REFERENCES runs(id),
            query                     TEXT,
            lens                      TEXT,
            captured_at               TEXT,
            answer_text_md            TEXT,
            screenshot_path           TEXT,
            overview_present          INTEGER,
            sources_json              TEXT,
            citations_json            TEXT,
            target_source_ranks_json  TEXT,
            target_citation_ranks_json TEXT,
            brand_in_answer_text      INTEGER,
            sentiment                 TEXT
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id                      INTEGER PRIMARY KEY,
            run_id                  INTEGER NOT NULL REFERENCES runs(id),
            brand_id                INTEGER,
            engine                  TEXT,
            lens                    TEXT,
            n_queries               INTEGER,
            n_overviews             INTEGER,
            overview_coverage       REAL,
            n_in_sources            INTEGER,
            visibility_in_sources   REAL,
            n_cited                 INTEGER,
            visibility_in_citations REAL,
            avg_source_position     REAL,
            avg_citation_position   REAL,
            relative_citation       REAL,
            computed_at             TEXT
        );

        CREATE TABLE IF NOT EXISTS lens_sentiment (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL REFERENCES runs(id),
            lens        TEXT NOT NULL,
            summary     TEXT,
            computed_at TEXT NOT NULL,
            UNIQUE(run_id, lens)
        );

        CREATE TABLE IF NOT EXISTS domain_stats (
            id                    INTEGER PRIMARY KEY,
            run_id                INTEGER NOT NULL REFERENCES runs(id),
            brand_id              INTEGER,
            engine                TEXT,
            lens                  TEXT,
            domain                TEXT,
            is_brand              INTEGER,
            appearances_sources   INTEGER,
            appearances_citations INTEGER,
            sum_min_source_rank   REAL,
            sum_min_citation_rank REAL,
            avg_source_position   REAL,
            avg_citation_position REAL,
            computed_at           TEXT,
            UNIQUE(run_id, lens, domain)
        );

        CREATE INDEX IF NOT EXISTS idx_runs_brand_engine ON runs(brand_id, engine);
        CREATE INDEX IF NOT EXISTS idx_results_run        ON results(run_id);
        CREATE INDEX IF NOT EXISTS idx_metrics_run        ON metrics(run_id);
        CREATE INDEX IF NOT EXISTS idx_lens_sentiment_run ON lens_sentiment(run_id);
        CREATE INDEX IF NOT EXISTS idx_domain_stats_run   ON domain_stats(run_id);
        """
    )
    _ensure_columns(conn, "metrics", _METRICS_MIGRATION_COLUMNS)
    _ensure_results_unique_index(conn)
    conn.commit()


def get_or_create_brand(conn: sqlite3.Connection, name: str, domain: str) -> int:
    from pipeline.schema import normalize_domain

    norm_domain = normalize_domain(domain)

    row = conn.execute(
        "SELECT id FROM brands WHERE name = ? AND domain = ?",
        (name, norm_domain),
    ).fetchone()
    if row is not None:
        return int(row["id"])

    cur = conn.execute(
        "INSERT INTO brands (name, domain, created_at) VALUES (?, ?, ?)",
        (name, norm_domain, _utcnow_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def create_run(conn: sqlite3.Connection, brand_id: int, engine: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (brand_id, engine, run_at, status) VALUES (?, ?, ?, 'running')",
        (brand_id, engine, _utcnow_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_run_counts(
    conn: sqlite3.Connection,
    run_id: int,
    n_queries: Optional[int] = None,
    n_ok: Optional[int] = None,
    n_failed: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    sets: list[str] = []
    params: list[object] = []
    if n_queries is not None:
        sets.append("n_queries = ?")
        params.append(n_queries)
    if n_ok is not None:
        sets.append("n_ok = ?")
        params.append(n_ok)
    if n_failed is not None:
        sets.append("n_failed = ?")
        params.append(n_failed)
    if status is not None:
        sets.append("status = ?")
        params.append(status)

    if not sets:
        return

    params.append(run_id)
    conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()


def get_captured_keys(
    conn: sqlite3.Connection, run_id: int
) -> set[tuple[str, str]]:
    rows = conn.execute(
        "SELECT query, lens FROM results WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {(row["query"], row["lens"]) for row in rows}


def find_unfinished_run(
    conn: sqlite3.Connection, brand_id: int, engine: str
) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM runs WHERE brand_id = ? AND engine = ? AND status = 'running' "
        "ORDER BY run_at DESC, id DESC LIMIT 1",
        (brand_id, engine),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def upsert_lens_sentiment(
    conn: sqlite3.Connection,
    run_id: int,
    lens: str,
    summary: Optional[str],
) -> None:
    conn.execute(
        """
        INSERT INTO lens_sentiment (run_id, lens, summary, computed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(run_id, lens) DO UPDATE SET
            summary = excluded.summary,
            computed_at = excluded.computed_at
        """,
        (run_id, lens, summary, _utcnow_iso()),
    )
    conn.commit()


def get_lens_sentiments(conn: sqlite3.Connection, run_id: int) -> dict[str, str]:
    try:
        rows = conn.execute(
            "SELECT lens, summary FROM lens_sentiment WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {}
        raise
    return {row["lens"]: row["summary"] for row in rows if row["summary"] is not None}


def get_domain_stats(
    conn: sqlite3.Connection, run_id: int, lens: str = "all"
) -> list[dict]:
    try:
        rows = conn.execute(
            """
            SELECT domain, is_brand,
                   appearances_sources, appearances_citations,
                   sum_min_source_rank, sum_min_citation_rank,
                   avg_source_position, avg_citation_position
            FROM domain_stats
            WHERE run_id = ? AND lens = ?
            ORDER BY appearances_sources DESC, appearances_citations DESC, domain ASC
            """,
            (run_id, lens),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise
    return [dict(row) for row in rows]


__all__ = [
    "get_conn",
    "init_db",
    "get_or_create_brand",
    "create_run",
    "update_run_counts",
    "get_captured_keys",
    "find_unfinished_run",
    "upsert_lens_sentiment",
    "get_lens_sentiments",
    "get_domain_stats",
]
