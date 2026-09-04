"""Run-control CLI: the small orchestration queries the skill used to inline.

Four modes, each printing exactly one JSON object/array on STDOUT (human noise on
STDERR), per INTERFACES.md §3.7:

  --resume-check   is there an unfinished run of this brand+engine that holds a
                   subset of THIS question set?
  --pending        which (query, lens) rows of the CSV are not captured yet?
  --finalize       write the run's counts and terminal status.
  --sentiments     read back the per-query sentiments grouped by lens.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Any, Optional

from pipeline.db import (
    comparable,
    find_unfinished_run,
    get_captured_keys,
    get_conn,
    get_or_create_brand,
    init_db,
    question_set_digest,
    run_identity,
    set_run_question_set_hash,
    update_run_counts,
)

VALID_LENSES = {"general", "branded", "comparative"}
TERMINAL_STATUSES = {"done", "failed"}


def _err(*args: Any) -> None:
    print(*args, file=sys.stderr)


def read_question_keys(csv_path: str) -> list[tuple[str, str]]:
    """Read (query, lens) pairs from a questions CSV, preserving file order.

    Raises ValueError on a missing header, an unknown lens, or no data rows.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or not {"query", "lens"} <= set(
            name.strip() for name in reader.fieldnames
        ):
            raise ValueError(f"{csv_path}: header must contain 'query' and 'lens'")
        keys: list[tuple[str, str]] = []
        for lineno, row in enumerate(reader, start=2):
            query = (row.get("query") or "").strip()
            lens = (row.get("lens") or "").strip()
            if not query:
                raise ValueError(f"{csv_path}:{lineno}: empty query")
            if lens not in VALID_LENSES:
                raise ValueError(
                    f"{csv_path}:{lineno}: lens {lens!r} not in "
                    f"{sorted(VALID_LENSES)}"
                )
            keys.append((query, lens))
    if not keys:
        raise ValueError(f"{csv_path}: no data rows")
    return keys


def _dedup(keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def resume_check(
    conn: Any, brand: str, domain: str, engine: str, csv_path: str
) -> dict[str, Any]:
    brand_id = get_or_create_brand(conn, brand, domain)
    run_id = find_unfinished_run(conn, brand_id, engine)
    out: dict[str, Any] = {
        "run_id": run_id,
        "resumable": False,
        "run_at": None,
        "n_captured": 0,
        "n_missing": 0,
    }
    if run_id is None:
        return out

    row = conn.execute(
        "SELECT run_at, question_set, question_set_hash FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    csv_keys = read_question_keys(csv_path)
    wanted = set(csv_keys)
    captured = get_captured_keys(conn, run_id)
    csv_hash = question_set_digest(csv_keys)
    run_label, run_hash = run_identity(row)
    identity = comparable(run_label, run_hash, None, csv_hash)
    subset = captured <= wanted
    out.update(
        run_at=row["run_at"] if row is not None else None,
        n_captured=len(captured),
        resumable=subset and identity != "different",
        n_missing=len(wanted - captured),
    )
    return out


def pending_rows(conn: Any, run_id: int, csv_path: str) -> dict[str, Any]:
    wanted = _dedup(read_question_keys(csv_path))
    captured = get_captured_keys(conn, run_id)
    pending = [list(key) for key in wanted if key not in captured]
    return {
        "run_id": run_id,
        "n_total": len(wanted),
        "n_captured": len(wanted) - len(pending),
        "n_pending": len(pending),
        "pending": pending,
    }


def lens_sentiments(conn: Any, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT lens, query, sentiment FROM results WHERE run_id = ? "
        "ORDER BY lens, id",
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _run_exists(conn: Any, run_id: int) -> bool:
    return (
        conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
        is not None
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline.run",
        description=(
            "Run-control queries for the orchestrator: resume-check, pending rows, "
            "finalize, sentiments. See INTERFACES.md §3.7."
        ),
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--resume-check",
        action="store_true",
        help="Is there an unfinished run holding a subset of this CSV?",
    )
    mode.add_argument(
        "--pending",
        action="store_true",
        help="Which (query, lens) rows of the CSV are not captured yet?",
    )
    mode.add_argument(
        "--finalize", action="store_true", help="Write run counts and status."
    )
    mode.add_argument(
        "--sentiments",
        action="store_true",
        help="Read back per-query sentiments for the run.",
    )

    p.add_argument("--brand", help="Brand name (with --resume-check).")
    p.add_argument("--domain", help="Brand domain/URL (with --resume-check).")
    p.add_argument("--engine", help="Engine id (with --resume-check).")
    p.add_argument("--csv", help="questions.csv (with --resume-check / --pending).")
    p.add_argument("--run-id", type=int, help="Existing run id.")
    p.add_argument("--n-queries", type=int, help="Rows attempted (with --finalize).")
    p.add_argument("--n-ok", type=int, help="Rows captured (with --finalize).")
    p.add_argument(
        "--n-failed",
        type=int,
        help="Rows never accepted (with --finalize); defaults to n-queries - n-ok.",
    )
    p.add_argument(
        "--status",
        choices=sorted(TERMINAL_STATUSES),
        help="Terminal status (with --finalize).",
    )
    p.add_argument("--db", default="data/aeo.db", help="SQLite DB path.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.resume_check and not (
        args.brand and args.domain and args.engine and args.csv
    ):
        _err("run: --resume-check requires --brand, --domain, --engine and --csv")
        return 2
    if args.pending and not (args.run_id and args.csv):
        _err("run: --pending requires --run-id and --csv")
        return 2
    if args.finalize and not (
        args.run_id is not None
        and args.n_queries is not None
        and args.n_ok is not None
        and args.status
    ):
        _err("run: --finalize requires --run-id, --n-queries, --n-ok and --status")
        return 2
    if args.sentiments and args.run_id is None:
        _err("run: --sentiments requires --run-id")
        return 2

    conn = get_conn(args.db)
    try:
        init_db(conn)

        if args.resume_check:
            try:
                out = resume_check(
                    conn, args.brand, args.domain, args.engine, args.csv
                )
            except (OSError, ValueError) as exc:
                _err(f"run: {exc}")
                return 1
            _err(
                f"run: resume-check — run_id={out['run_id']} "
                f"resumable={out['resumable']} missing={out['n_missing']}"
            )
            print(json.dumps(out, ensure_ascii=False))
            return 0

        if args.pending:
            if not _run_exists(conn, args.run_id):
                _err(f"run: run {args.run_id} not found")
                return 1
            try:
                out = pending_rows(conn, args.run_id, args.csv)
            except (OSError, ValueError) as exc:
                _err(f"run: {exc}")
                return 1
            _err(
                f"run: run {args.run_id} — {out['n_pending']} pending "
                f"of {out['n_total']}"
            )
            print(json.dumps(out, ensure_ascii=False))
            return 0

        if args.finalize:
            if not _run_exists(conn, args.run_id):
                _err(f"run: run {args.run_id} not found")
                return 1
            n_failed = (
                args.n_failed
                if args.n_failed is not None
                else args.n_queries - args.n_ok
            )
            update_run_counts(
                conn,
                run_id=args.run_id,
                n_queries=args.n_queries,
                n_ok=args.n_ok,
                n_failed=n_failed,
                status=args.status,
            )
            captured = get_captured_keys(conn, args.run_id)
            if captured:
                set_run_question_set_hash(
                    conn, args.run_id, question_set_digest(captured)
                )
            out = {
                "run_id": args.run_id,
                "n_queries": args.n_queries,
                "n_ok": args.n_ok,
                "n_failed": n_failed,
                "status": args.status,
            }
            _err(f"run: finalized run {args.run_id} as {args.status}")
            print(json.dumps(out, ensure_ascii=False))
            return 0

        if not _run_exists(conn, args.run_id):
            _err(f"run: run {args.run_id} not found")
            return 1
        rows = lens_sentiments(conn, args.run_id)
        _err(f"run: run {args.run_id} — {len(rows)} sentiment rows")
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
