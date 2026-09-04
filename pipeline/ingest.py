from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any, Optional

from pydantic import ValidationError

from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    init_db,
    update_run_counts,
)
from pipeline.schema import QueryCapture


def _err(*args: Any) -> None:
    print(*args, file=sys.stderr)


def _field_path(loc: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in loc) if loc else ""


def _links_to_jsonable(links: list[Any]) -> list[dict[str, Any]]:
    return [{"rank": ln.rank, "url": ln.url, "domain": ln.domain} for ln in links]


def insert_capture(
    conn: sqlite3.Connection, run_id: int, cap: QueryCapture
) -> Optional[int]:
    cur = conn.execute(
        """
        INSERT INTO results (
            run_id, query, lens, captured_at,
            answer_text_md, screenshot_path, overview_present,
            sources_json, citations_json,
            target_source_ranks_json, target_citation_ranks_json,
            brand_in_answer_text, sentiment
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, query, lens) DO NOTHING
        RETURNING id
        """,
        (
            run_id,
            cap.query,
            cap.lens,
            cap.captured_at.isoformat(),
            cap.answer_text_md,
            cap.screenshot_path,
            1 if cap.overview_present else 0,
            json.dumps(_links_to_jsonable(cap.sources), ensure_ascii=False),
            json.dumps(_links_to_jsonable(cap.citations), ensure_ascii=False),
            json.dumps(list(cap.target_source_ranks)),
            json.dumps(list(cap.target_citation_ranks)),
            1 if cap.brand_in_answer_text else 0,
            cap.sentiment,
        ),
    )
    row = cur.fetchone()
    return int(row["id"]) if row is not None else None


def ingest_batch(
    conn: sqlite3.Connection, run_id: int, objects: list[Any]
) -> dict[str, Any]:
    ok: list[int] = []
    skipped: list[int] = []
    errors: list[dict[str, Any]] = []

    for index, raw in enumerate(objects):
        try:
            cap = QueryCapture.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            echoed_query = raw.get("query") if isinstance(raw, dict) else None
            errors.append(
                {
                    "index": index,
                    "query": echoed_query,
                    "field": _field_path(first.get("loc", ())),
                    "msg": first.get("msg", ""),
                }
            )
            continue
        if insert_capture(conn, run_id, cap) is None:
            skipped.append(index)
        else:
            ok.append(index)

    conn.commit()

    n_ok = conn.execute(
        "SELECT COUNT(*) FROM results WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    update_run_counts(conn, run_id, n_ok=n_ok)

    return {"run_id": run_id, "ok": ok, "skipped": skipped, "errors": errors}


def _read_stdin_array() -> list[Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("expected a JSON array on STDIN, got empty input")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(
            f"expected a JSON array on STDIN, got {type(data).__name__}"
        )
    return data


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.ingest",
        description=(
            "Create a run (--new-run) or ingest a QueryCapture batch (--run-id). "
            "See INTERFACES.md §3.1/§3.2."
        ),
    )
    parser.add_argument("--brand", help="Brand name (with --new-run).")
    parser.add_argument("--domain", help="Brand domain/URL (with --new-run).")
    parser.add_argument("--engine", help="Engine id, e.g. google (with --new-run).")
    parser.add_argument(
        "--new-run",
        action="store_true",
        help="Create a new run for --brand/--domain/--engine and print its id.",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        help="Existing run id to ingest a STDIN JSON array of QueryCapture into.",
    )
    parser.add_argument(
        "--group-id",
        help="Repeat-run group tag stamped on the new run (with --new-run only).",
    )
    parser.add_argument(
        "--question-set",
        help="Human label of the question set (with --new-run only), e.g. CSV basename.",
    )
    parser.add_argument(
        "--db",
        default="data/aeo.db",
        help="SQLite DB path (default: data/aeo.db).",
    )
    args = parser.parse_args(argv)

    if args.new_run == bool(args.run_id is not None):
        _err("ingest: choose exactly one mode: --new-run OR --run-id <N>")
        return 2
    if args.group_id and not args.new_run:
        _err("ingest: --group-id is only valid with --new-run")
        return 2
    if args.question_set and not args.new_run:
        _err("ingest: --question-set is only valid with --new-run")
        return 2

    conn = get_conn(args.db)
    try:
        init_db(conn)

        if args.new_run:
            if not (args.brand and args.domain and args.engine):
                _err("ingest: --new-run requires --brand, --domain and --engine")
                return 2
            brand_id = get_or_create_brand(conn, args.brand, args.domain)
            run_id = create_run(
                conn,
                brand_id,
                args.engine,
                group_id=args.group_id,
                question_set=args.question_set,
            )
            _err(f"ingest: created run {run_id} for brand {brand_id} ({args.engine})")
            print(json.dumps({"run_id": run_id}, ensure_ascii=False))
            return 0

        run = conn.execute(
            "SELECT id FROM runs WHERE id = ?", (args.run_id,)
        ).fetchone()
        if run is None:
            _err(f"ingest: run {args.run_id} not found")
            return 1

        try:
            objects = _read_stdin_array()
        except (ValueError, json.JSONDecodeError) as exc:
            _err(f"ingest: {exc}")
            return 1

        result = ingest_batch(conn, args.run_id, objects)
        _err(
            f"ingest: run {args.run_id} — {len(result['ok'])} ok, "
            f"{len(result['skipped'])} skipped, "
            f"{len(result['errors'])} errors of {len(objects)}"
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
