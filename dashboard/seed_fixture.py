from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from pipeline.aggregate import aggregate_run
from pipeline.db import create_run, get_conn, get_or_create_brand, init_db, update_run_counts
from pipeline.ingest import insert_capture
from pipeline.schema import Link, QueryCapture

FIXTURE_DB = "data/_fixture_dash.db"
ENGINE = "google"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _link(rank: int, url: str, domain: str) -> Link:
    return Link(rank=rank, url=url, domain=domain)


def _build_run_captures(
    run_at: datetime, domain: str, *, coverage_boost: int
) -> list[QueryCapture]:
    cap_at = run_at
    caps: list[QueryCapture] = []

    def add(
        query: str,
        lens: str,
        overview_present: bool,
        sources: list[Link],
        citations: list[Link],
        target_source_ranks: list[int],
        target_citation_ranks: list[int],
        brand_in_answer_text: bool,
        sentiment: str | None,
    ) -> None:
        caps.append(
            QueryCapture(
                query=query,
                lens=lens,  # type: ignore[arg-type]
                engine=ENGINE,
                captured_at=cap_at,
                answer_text_md="Example AI Overview answer…" if overview_present else None,
                screenshot_path=None,
                overview_present=overview_present,
                sources=sources,
                citations=citations,
                target_source_ranks=target_source_ranks,
                target_citation_ranks=target_citation_ranks,
                brand_in_answer_text=brand_in_answer_text,
                sentiment=sentiment,
            )
        )

    add(
        "best project management software for small teams", "general", True,
        [_link(1, "https://g2.com/a", "g2.com"),
         _link(2, f"https://{domain}/product", domain),
         _link(3, "https://capterra.com/g", "capterra.com")],
        [_link(1, f"https://{domain}/product", domain)],
        [2], [1], True,
        "recommended among suitable options, named with a link to the site",
    )
    add(
        "how to choose a task tracker for beginners", "general",
        coverage_boost >= 1,
        ([_link(1, "https://g2.com/x", "g2.com"),
          _link(2, f"https://{domain}/blog", domain)] if coverage_boost >= 1 else []),
        [],
        ([2] if coverage_boost >= 1 else []), [],
        coverage_boost >= 1,
        "mentioned neutrally among others" if coverage_boost >= 1 else None,
    )
    add(
        "kanban board software ratings", "general", True,
        [_link(1, "https://capterra.com/r", "capterra.com"),
         _link(2, "https://g2.com/r", "g2.com")],
        [], [], [], False, None,
    )
    add(
        "affordable task manager for a small team", "general",
        coverage_boost >= 2,
        ([_link(1, f"https://{domain}/value", domain)] if coverage_boost >= 2 else []),
        ([_link(1, f"https://{domain}/value", domain)] if coverage_boost >= 2 else []),
        ([1] if coverage_boost >= 2 else []),
        ([1] if coverage_boost >= 2 else []),
        coverage_boost >= 2,
        "named as a budget-friendly option" if coverage_boost >= 2 else None,
    )

    add(
        f"{domain} reviews", "branded", True,
        [_link(1, f"https://{domain}/reviews", domain),
         _link(2, "https://trustpilot.com/x", "trustpilot.com")],
        [_link(1, f"https://{domain}/reviews", domain)],
        [1], [1], True,
        "presented positively, direct link to the official site",
    )
    add(
        f"{domain} official website", "branded", True,
        [_link(1, f"https://{domain}/", domain)],
        [_link(1, f"https://{domain}/", domain)],
        [1], [1], True,
        "official site listed as the first source",
    )
    add(
        f"{domain} pricing and plans", "branded",
        coverage_boost >= 1,
        ([_link(1, f"https://{domain}/pricing", domain)] if coverage_boost >= 1 else []),
        [],
        ([1] if coverage_boost >= 1 else []), [],
        coverage_boost >= 1,
        "named as the source for the pricing guide" if coverage_boost >= 1 else None,
    )

    add(
        f"{domain} vs Initech which is better", "comparative", True,
        [_link(1, "https://initech.com/c", "initech.com"),
         _link(2, f"https://{domain}/compare", domain),
         _link(3, "https://capterra.com/c", "capterra.com")],
        [_link(1, "https://initech.com/c", "initech.com")],
        [2], [], True,
        "mentioned as a solid alternative, but Initech is described in more detail",
    )
    add(
        "best project management tools compared", "comparative", True,
        [_link(1, "https://initech.com/b", "initech.com"),
         _link(2, "https://hooli.com/b", "hooli.com")],
        [], [], [], False, None,
    )

    return caps


def _seed_run(
    conn: sqlite3.Connection,
    brand_id: int,
    run_at: datetime,
    domain: str,
    *,
    coverage_boost: int,
    status: str,
) -> int:
    run_id = create_run(conn, brand_id, ENGINE)
    conn.execute("UPDATE runs SET run_at = ? WHERE id = ?", (_iso(run_at), run_id))

    caps = _build_run_captures(run_at, domain, coverage_boost=coverage_boost)
    for cap in caps:
        insert_capture(conn, run_id, cap)
    conn.commit()

    n = len(caps)
    update_run_counts(conn, run_id, n_queries=n, n_ok=n, n_failed=0, status=status)

    if status == "done":
        aggregate_run(conn, run_id)
    return run_id


def seed(db_path: str = FIXTURE_DB) -> dict:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        for tbl in ("domain_stats", "lens_sentiment", "metrics", "results", "runs", "brands"):
            conn.execute(f"DELETE FROM {tbl}")
        conn.commit()

        now = datetime.now(timezone.utc).replace(microsecond=0)

        brands = [
            ("Example", "https://www.example.com"),
            ("Globex", "https://www.globex.com"),
        ]
        summary: dict = {"db": db_path, "brands": []}

        for name, url in brands:
            brand_id = get_or_create_brand(conn, name, url)
            domain = conn.execute(
                "SELECT domain FROM brands WHERE id = ?", (brand_id,)
            ).fetchone()["domain"]

            run_ids = []
            run_ids.append(_seed_run(conn, brand_id, now - timedelta(days=14),
                                     domain, coverage_boost=0, status="done"))
            run_ids.append(_seed_run(conn, brand_id, now - timedelta(days=7),
                                     domain, coverage_boost=1, status="done"))
            run_ids.append(_seed_run(conn, brand_id, now - timedelta(days=1),
                                     domain, coverage_boost=2, status="done"))
            run_ids.append(_seed_run(conn, brand_id, now,
                                     domain, coverage_boost=2, status="running"))

            summary["brands"].append(
                {"id": brand_id, "name": name, "domain": domain, "runs": run_ids}
            )

        return summary
    finally:
        conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else FIXTURE_DB
    out = seed(target)
    print(json.dumps(out, ensure_ascii=False, indent=2))
