from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from audit.cache import is_fresh
from audit.checks import run_audit
from pipeline.db import get_conn, get_latest_audit, init_db, insert_audit
from pipeline.schema import normalize_domain

_STATUS_ORDER = {"fail": 0, "warn": 1, "skip": 2, "pass": 3}


def _err(*args: Any) -> None:
    print(*args, file=sys.stderr)


def _print_summary(payload: dict) -> None:
    engine = payload.get("engine") or "generic"
    _err(
        f"audit {payload['domain']} [{engine}]: "
        f"{payload['verdict'].upper()} (score {payload['score']}/100)"
    )
    blockers = payload.get("blockers") or []
    if blockers:
        _err(f"  blockers: {', '.join(blockers)}")
    for c in sorted(
        payload["checks"], key=lambda x: (_STATUS_ORDER[x["status"]], x["id"])
    ):
        if c["status"] == "pass":
            continue
        _err(f"  [{c['status']}] {c['id']} ({c['severity']}) {c['title']}: {c['detail']}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit.gate",
        description="Domain GEO-Audit Gate — see INTERFACES.md §7.",
    )
    parser.add_argument("--domain", required=True)
    parser.add_argument("--engine", default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--max-age", type=int, default=86400)
    parser.add_argument("--db", default="data/aeo.db")
    parser.add_argument("--no-db", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    domain = normalize_domain(args.domain)
    conn = None
    try:
        if not args.no_db:
            conn = get_conn(args.db)
            init_db(conn)
            if not args.no_cache:
                cached = get_latest_audit(conn, domain, args.engine)
                if cached is not None and is_fresh(cached["checked_at"], args.max_age):
                    print(cached["result_json"])
                    _print_summary(json.loads(cached["result_json"]))
                    return 0

        try:
            result = run_audit(args.domain, engine=args.engine, timeout=args.timeout)
        except Exception as exc:  # noqa: BLE001
            _err(f"audit: {exc}")
            return 1

        payload = result.model_dump(mode="json")
        out = json.dumps(payload, ensure_ascii=False)
        if conn is not None:
            insert_audit(
                conn,
                result.target,
                result.domain,
                result.engine,
                result.checked_at.isoformat(),
                result.verdict,
                result.score,
                not result.passed,
                out,
            )
        print(out)
        _print_summary(payload)
        return 0
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
