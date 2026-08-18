from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pipeline.db import get_conn, get_latest_audit, init_db
from pipeline.schema import normalize_domain

SCHEMA_VERSION = "open-geo.run-artifact.v1"
_LENS_ORDER = ("all", "general", "branded", "comparative")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(raw: Optional[str], default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _ordered_lenses(values: set[str]) -> list[str]:
    ordered = [lens for lens in _LENS_ORDER if lens in values]
    ordered.extend(sorted(values - set(_LENS_ORDER)))
    return ordered


def _metrics(conn: sqlite3.Connection, run_id: int) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM metrics WHERE run_id = ?", (run_id,)
    ).fetchall()
    by_lens = {str(row["lens"]): dict(row) for row in rows}
    return {lens: by_lens[lens] for lens in _ordered_lenses(set(by_lens))}


def _lens_sentiment(
    conn: sqlite3.Connection, run_id: int
) -> dict[str, Optional[str]]:
    rows = conn.execute(
        "SELECT lens, summary FROM lens_sentiment WHERE run_id = ?", (run_id,)
    ).fetchall()
    by_lens = {str(row["lens"]): row["summary"] for row in rows}
    return {lens: by_lens[lens] for lens in _ordered_lenses(set(by_lens))}


def _results(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM results WHERE run_id = ? ORDER BY id ASC", (run_id,)
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "query": row["query"],
                "lens": row["lens"],
                "captured_at": row["captured_at"],
                "overview_present": bool(row["overview_present"]),
                "sources": _loads(row["sources_json"], []),
                "citations": _loads(row["citations_json"], []),
                "target_source_ranks": _loads(
                    row["target_source_ranks_json"], []
                ),
                "target_citation_ranks": _loads(
                    row["target_citation_ranks_json"], []
                ),
                "answer_text_md": row["answer_text_md"],
                "brand_in_answer_text": bool(row["brand_in_answer_text"]),
                "sentiment": row["sentiment"],
                "screenshot_path": row["screenshot_path"],
            }
        )
    return out


def _domain_stats(
    conn: sqlite3.Connection, run_id: int
) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT lens, domain, is_brand, appearances_sources,
               appearances_citations, avg_source_position,
               avg_citation_position
        FROM domain_stats
        WHERE run_id = ?
        ORDER BY lens ASC, appearances_sources DESC,
                 appearances_citations DESC, domain ASC
        """,
        (run_id,),
    ).fetchall()
    by_lens: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_lens.setdefault(str(row["lens"]), []).append(
            {
                "domain": row["domain"],
                "is_brand": bool(row["is_brand"]),
                "appearances_sources": row["appearances_sources"],
                "appearances_citations": row["appearances_citations"],
                "avg_source_position": row["avg_source_position"],
                "avg_citation_position": row["avg_citation_position"],
            }
        )
    return {lens: by_lens[lens] for lens in _ordered_lenses(set(by_lens))}


def _latest_audit(
    conn: sqlite3.Connection, target: str, engine: str
) -> Optional[dict[str, Any]]:
    audit = get_latest_audit(conn, normalize_domain(target), engine)
    if audit is None:
        return None
    payload = _loads(audit.pop("result_json", None), {})
    audit["blocked"] = bool(audit["blocked"])
    audit["result"] = payload
    return audit


def build_run_artifact(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT r.id, r.run_at, r.status, r.engine, r.group_id,
               r.n_queries, r.n_ok, r.n_failed,
               b.id AS brand_id, b.name AS brand_name, b.domain AS target
        FROM runs r
        JOIN brands b ON b.id = r.brand_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"run {run_id} not found")

    engine = str(row["engine"])
    target = str(row["target"])
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow_iso(),
        "run": {
            "id": int(row["id"]),
            "run_at": row["run_at"],
            "status": row["status"],
            "engine": engine,
            "group_id": row["group_id"],
            "n_queries": int(row["n_queries"] or 0),
            "n_ok": int(row["n_ok"] or 0),
            "n_failed": int(row["n_failed"] or 0),
        },
        "brand": {
            "id": int(row["brand_id"]),
            "name": row["brand_name"],
            "target": target,
        },
        "metrics": _metrics(conn, run_id),
        "lens_sentiment": _lens_sentiment(conn, run_id),
        "results": _results(conn, run_id),
        "domain_stats": _domain_stats(conn, run_id),
        "audit": _latest_audit(conn, target, engine),
    }


def write_run_artifact(
    conn: sqlite3.Connection, run_id: int, out_path: str | Path
) -> Path:
    destination = Path(out_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_run_artifact(conn, run_id)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, destination)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.artifact",
        description=(
            "Export one completed open-geo run as a portable JSON artifact "
            "for agent-to-agent workflow composition."
        ),
    )
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--db", default="data/aeo.db")
    parser.add_argument(
        "--out",
        help="Output JSON path (default: reports/run-<run-id>.json).",
    )
    args = parser.parse_args(argv)
    out = args.out or f"reports/run-{args.run_id}.json"

    conn = get_conn(args.db)
    try:
        init_db(conn)
        path = write_run_artifact(conn, args.run_id, out)
    except ValueError as exc:
        print(f"artifact: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": args.run_id,
                "artifact_path": str(path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
