from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


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


_METRICS_MIGRATION_COLUMNS = {
    "relative_citation": "REAL",
    "n_brand_mentions": "INTEGER",
    "brand_mention_rate": "REAL",
}

_RUNS_MIGRATION_COLUMNS = {
    "group_id": "TEXT",
    "question_set": "TEXT",
    "question_set_hash": "TEXT",
}

QUESTION_SET_HASH_LEN = 16


def _normalize_question_field(value: str) -> str:
    return unicodedata.normalize("NFC", str(value).strip())


def question_set_digest(rows: Iterable[tuple[str, str]]) -> str:
    """Identity of a question set: 16 hex chars over its `(query, lens)` pairs.

    The pairs are normalized (`.strip()` + NFC), joined as `query\\tlens` lines,
    sorted and newline-joined; the digest is the first 16 lowercase hex chars of
    the SHA-256 of that UTF-8 text. Order of the input is irrelevant — the same
    question set always hashes the same, whatever the CSV row order.
    """
    lines = sorted(
        f"{_normalize_question_field(query)}\t{_normalize_question_field(lens)}"
        for query, lens in rows
    )
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:QUESTION_SET_HASH_LEN]


def _identity_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, None)


def run_identity(run_row: Any) -> tuple[Optional[str], Optional[str]]:
    """Read `(question_set, question_set_hash)` off a `runs` row.

    Accepts anything key-addressable (`sqlite3.Row`, `dict`) or attribute-shaped;
    a missing column reads as `None` = identity unknown (every legacy run).
    """
    return (
        _identity_value(_row_value(run_row, "question_set")),
        _identity_value(_row_value(run_row, "question_set_hash")),
    )


def comparable(
    a_label: Optional[str],
    a_hash: Optional[str],
    b_label: Optional[str],
    b_hash: Optional[str],
) -> str:
    """Do two runs measure the same question set? `same` | `different` | `unknown`.

    Hashes decide when both sides have one; otherwise two labels decide; anything
    else is `unknown`, which callers MUST treat as today's behavior (legacy runs
    carry no identity and must keep working). Only a `different` pair is refused.
    """
    a_label, a_hash = _identity_value(a_label), _identity_value(a_hash)
    b_label, b_hash = _identity_value(b_label), _identity_value(b_hash)

    if a_hash is not None and b_hash is not None:
        return "same" if a_hash == b_hash else "different"
    if a_hash is None and b_hash is None:
        if a_label is not None and b_label is not None:
            return "same" if a_label == b_label else "different"
    return "unknown"


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
            n_failed  INTEGER NOT NULL DEFAULT 0,
            group_id  TEXT,
            question_set      TEXT,
            question_set_hash TEXT
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
            n_brand_mentions        INTEGER,
            brand_mention_rate      REAL,
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

        CREATE TABLE IF NOT EXISTS audits (
            id          INTEGER PRIMARY KEY,
            target      TEXT NOT NULL,
            domain      TEXT NOT NULL,
            engine      TEXT,
            checked_at  TEXT NOT NULL,
            verdict     TEXT NOT NULL,
            score       INTEGER NOT NULL,
            blocked     INTEGER NOT NULL,
            result_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_runs_brand_engine ON runs(brand_id, engine);
        CREATE INDEX IF NOT EXISTS idx_results_run        ON results(run_id);
        CREATE INDEX IF NOT EXISTS idx_metrics_run        ON metrics(run_id);
        CREATE INDEX IF NOT EXISTS idx_lens_sentiment_run ON lens_sentiment(run_id);
        CREATE INDEX IF NOT EXISTS idx_domain_stats_run   ON domain_stats(run_id);
        CREATE INDEX IF NOT EXISTS idx_audits_domain       ON audits(domain, checked_at);
        """
    )
    _ensure_columns(conn, "metrics", _METRICS_MIGRATION_COLUMNS)
    _ensure_columns(conn, "runs", _RUNS_MIGRATION_COLUMNS)
    _ensure_results_unique_index(conn)
    backfill_question_set_identity(conn)
    conn.commit()


def normalize_brand_name(name: str) -> str:
    return " ".join(name.split())


def _brand_match_key(name: str) -> str:
    return normalize_brand_name(name).casefold()


def find_brand_id(
    conn: sqlite3.Connection, name: str, domain: str
) -> Optional[int]:
    from pipeline.schema import normalize_target

    norm_domain = normalize_target(domain)
    rows = conn.execute(
        "SELECT id, name FROM brands WHERE domain = ? ORDER BY id ASC",
        (norm_domain,),
    ).fetchall()
    if not rows:
        return None

    display = normalize_brand_name(name)
    for row in rows:
        if str(row["name"]) == display:
            return int(row["id"])

    key = _brand_match_key(name)
    for row in rows:
        if _brand_match_key(str(row["name"])) == key:
            return int(row["id"])
    return None


def find_brand_domains(conn: sqlite3.Connection, name: str) -> list[str]:
    key = _brand_match_key(name)
    rows = conn.execute("SELECT name, domain FROM brands ORDER BY domain").fetchall()
    return [
        str(row["domain"])
        for row in rows
        if _brand_match_key(str(row["name"])) == key
    ]


def get_or_create_brand(conn: sqlite3.Connection, name: str, domain: str) -> int:
    from pipeline.schema import normalize_target

    existing = find_brand_id(conn, name, domain)
    if existing is not None:
        return existing

    cur = conn.execute(
        "INSERT INTO brands (name, domain, created_at) VALUES (?, ?, ?)",
        (normalize_brand_name(name), normalize_target(domain), _utcnow_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def create_run(
    conn: sqlite3.Connection,
    brand_id: int,
    engine: str,
    group_id: Optional[str] = None,
    question_set: Optional[str] = None,
) -> int:
    """Open a run. `question_set` is the human label of the set being measured.

    The matching `question_set_hash` is NOT written here — no rows exist yet; it
    is derived from what was actually captured, at finalize
    (`set_run_question_set_hash`).
    """
    cur = conn.execute(
        "INSERT INTO runs (brand_id, engine, run_at, status, group_id, question_set) "
        "VALUES (?, ?, ?, 'running', ?, ?)",
        (brand_id, engine, _utcnow_iso(), group_id, question_set),
    )
    conn.commit()
    return int(cur.lastrowid)


def set_run_question_set_hash(
    conn: sqlite3.Connection, run_id: int, question_set_hash: Optional[str]
) -> None:
    conn.execute(
        "UPDATE runs SET question_set_hash = ? WHERE id = ?",
        (question_set_hash, run_id),
    )
    conn.commit()


_KNOWN_QUESTION_SET_LABELS = (
    ("astramed_questions.csv", "v1 · 08.08"),
    ("astramed_questions_v2.csv", "v2 · Вордстат 17.08"),
    ("astramed_questions_v3.csv", "v3 · разговорные 18.08"),
    ("astramed_questions_v4.csv", "v4 · долголетие 03.09"),
    ("core/astramed/astramed_questions_v4.csv", "v4 · долголетие 03.09"),
)


def _csv_question_keys(path: Path) -> list[tuple[str, str]]:
    import csv

    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        keys: list[tuple[str, str]] = []
        for row in reader:
            query = (row.get("query") or "").strip()
            lens = (row.get("lens") or "").strip()
            if query and lens:
                keys.append((query, lens))
        return keys


def _known_question_set_labels(repo_root: Optional[Path] = None) -> dict[str, str]:
    root = repo_root or Path(__file__).resolve().parent.parent
    out: dict[str, str] = {}
    for rel, label in _KNOWN_QUESTION_SET_LABELS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            keys = _csv_question_keys(path)
        except OSError:
            continue
        if keys:
            out[question_set_digest(keys)] = label
    return out


def backfill_question_set_identity(
    conn: sqlite3.Connection, repo_root: Optional[Path] = None
) -> int:
    """Stamp hash (and a known label) on runs that captured rows but have no identity.

    Idempotent. Runs with zero result rows stay unlabeled. Returns how many
    rows were updated.
    """
    if "question_set_hash" not in _table_columns(conn, "runs"):
        return 0
    labels = _known_question_set_labels(repo_root)
    rows = conn.execute(
        "SELECT id FROM runs WHERE status = 'done' "
        "AND (question_set_hash IS NULL OR question_set_hash = '')"
    ).fetchall()
    updated = 0
    for row in rows:
        run_id = int(row["id"])
        keys = get_captured_keys(conn, run_id)
        if not keys:
            continue
        digest = question_set_digest(keys)
        label = labels.get(digest)
        conn.execute(
            "UPDATE runs SET question_set_hash = ?, "
            "question_set = COALESCE(NULLIF(question_set, ''), ?) "
            "WHERE id = ?",
            (digest, label, run_id),
        )
        updated += 1
    if updated:
        conn.commit()
    return updated


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


def insert_audit(
    conn: sqlite3.Connection,
    target: str,
    domain: str,
    engine: Optional[str],
    checked_at: str,
    verdict: str,
    score: int,
    blocked: bool,
    result_json: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO audits
            (target, domain, engine, checked_at, verdict, score, blocked, result_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target,
            domain,
            engine,
            checked_at,
            verdict,
            score,
            1 if blocked else 0,
            result_json,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_latest_audit(
    conn: sqlite3.Connection, domain: str, engine: Optional[str] = None
) -> Optional[dict]:
    cols = (
        "target, domain, engine, checked_at, verdict, score, blocked, result_json"
    )
    try:
        if engine is not None:
            row = conn.execute(
                f"SELECT {cols} FROM audits WHERE domain = ? AND engine = ? "
                "ORDER BY checked_at DESC, id DESC LIMIT 1",
                (domain, engine),
            ).fetchone()
            return dict(row) if row is not None else None
        row = conn.execute(
            f"SELECT {cols} FROM audits WHERE domain = ? "
            "ORDER BY checked_at DESC, id DESC LIMIT 1",
            (domain,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise
    return dict(row) if row is not None else None


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
    "insert_audit",
    "get_latest_audit",
]
