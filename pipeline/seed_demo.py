from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from pipeline.aggregate import aggregate_run
from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    update_run_counts,
    upsert_lens_sentiment,
)
from pipeline.ingest import insert_capture
from pipeline.schema import Link, QueryCapture, normalize_domain

DB_PATH = "data/aeo.db"
BRAND_NAME = "Example"
BRAND_DOMAIN = "example.com"
ENGINE = "google"
TARGET = normalize_domain(BRAND_DOMAIN)

_OTHER_DOMAINS = [
    "globex.com",
    "initech.com",
    "hooli.com",
    "g2.com",
    "capterra.com",
    "trustpilot.com",
    "reddit.com",
    "techradar.com",
    "pcmag.com",
    "producthunt.com",
]

_QUERIES = {
    "general": [
        "how to choose project management software",
        "best task tracking tools 2026",
        "which project management app for small teams",
        "kanban board software reviews",
        "cloud task manager vs spreadsheet which is better",
        "top project management apps for remote work",
        "which project tool scales best for growing teams",
        "how to choose a task tracker for a startup",
    ],
    "branded": [
        "Example app reviews",
        "Example pricing and plans",
        "Example help center and support",
        "Example free trial and onboarding",
        "Example integrations and API",
        "Example mobile app",
        "Example security and SSO",
        "compare Example plans",
    ],
    "comparative": [
        "Example vs Globex which is better",
        "Example vs Initech pricing",
        "should I pick Example or Hooli",
        "Example vs Globex feature comparison",
        "Example or Initech for remote teams",
        "Example vs Hooli customer reviews",
        "Example and Globex which to choose",
        "Example vs a free open-source tracker",
    ],
}

_SENTIMENTS_POS = [
    "recommended as a leading tool, mentioned with a direct link to the site",
    "named a reliable choice for project management",
    "listed first among the suitable options",
    "mentioned positively, noted for strong integrations",
]
_SENTIMENTS_NEUTRAL = [
    "mentioned neutrally among several alternatives",
    "listed alongside other popular tools",
    "named without a clear judgement, next to competitors",
]

_LENS_SUMMARIES = {
    "general": "Mostly mentioned neutrally among alternatives, occasionally recommended.",
    "branded": "Consistently surfaced as the authority on its own brand queries, often with a direct link to the site.",
    "comparative": "Named alongside competitors without a clear edge.",
    "all": "Visible across lenses: confident on branded queries, neutral elsewhere, and present but undifferentiated in comparisons.",
}


def _link(rank: int, domain: str, slug: str) -> Link:
    if domain == TARGET:
        url = f"https://{domain}/catalog/{slug}"
    else:
        url = f"https://www.{domain}/{slug}"
    return Link(rank=rank, url=url, domain=domain)


def _build_sources(
    rng: random.Random, n_sources: int, target_positions: list[int]
) -> list[Link]:
    pool = rng.sample(_OTHER_DOMAINS, k=min(len(_OTHER_DOMAINS), n_sources))
    links: list[Link] = []
    other_i = 0
    for rank in range(1, n_sources + 1):
        if rank in target_positions:
            links.append(_link(rank, TARGET, f"feature-{rank}"))
        else:
            dom = pool[other_i % len(pool)]
            other_i += 1
            links.append(_link(rank, dom, f"article-{rank}"))
    return links


def _make_capture(
    rng: random.Random,
    query: str,
    lens: str,
    captured_at: datetime,
    *,
    overview_present: bool,
    in_sources: bool,
    cited: bool,
    multi_rank: bool,
    n_idx: int,
) -> QueryCapture:
    screenshot = f"data/screenshots/seed/{lens}_{n_idx:03d}.png"

    if not overview_present:
        return QueryCapture(
            query=query,
            lens=lens,  # type: ignore[arg-type]
            engine=ENGINE,
            captured_at=captured_at,
            answer_text_md=None,
            screenshot_path=screenshot,
            overview_present=False,
            sources=[],
            citations=[],
            target_source_ranks=[],
            target_citation_ranks=[],
            brand_in_answer_text=False,
            sentiment=None,
        )

    n_sources = rng.randint(3, 6)

    if not in_sources:
        sources = _build_sources(rng, n_sources, target_positions=[])
        brand_in_text = rng.random() < 0.25
        target_present_anywhere = brand_in_text
        return QueryCapture(
            query=query,
            lens=lens,  # type: ignore[arg-type]
            engine=ENGINE,
            captured_at=captured_at,
            answer_text_md="Several project management tools from different vendors are compared.",
            screenshot_path=screenshot,
            overview_present=True,
            sources=sources,
            citations=[],
            target_source_ranks=[],
            target_citation_ranks=[],
            brand_in_answer_text=brand_in_text,
            sentiment=(rng.choice(_SENTIMENTS_NEUTRAL) if target_present_anywhere else None),
        )

    if multi_rank and n_sources >= 4:
        first = rng.randint(1, 2)
        second = rng.randint(3, n_sources)
        target_positions = sorted({first, second})
    else:
        target_positions = [rng.randint(1, n_sources)]

    sources = _build_sources(rng, n_sources, target_positions)
    source_domains = [link.domain for link in sources]

    if cited:
        n_cit = rng.randint(1, 2)
        citations = [_link(i + 1, TARGET, f"cit-{i + 1}") for i in range(n_cit)]
        target_citation_ranks = list(range(1, n_cit + 1))
    else:
        other_source_domains = [d for d in source_domains if d != TARGET]
        if other_source_domains and rng.random() < 0.5:
            dom = rng.choice(other_source_domains)
            citations = [_link(1, dom, "ref")]
        else:
            citations = []
        target_citation_ranks = []

    sentiment = rng.choice(_SENTIMENTS_POS if min(target_positions) == 1 else _SENTIMENTS_NEUTRAL)

    return QueryCapture(
        query=query,
        lens=lens,  # type: ignore[arg-type]
        engine=ENGINE,
        captured_at=captured_at,
        answer_text_md=(
            "Among the suitable options, **Example** is frequently mentioned — "
            "a well-known project management tool."
        ),
        screenshot_path=screenshot,
        overview_present=True,
        sources=sources,
        citations=citations,
        target_source_ranks=list(target_positions),
        target_citation_ranks=target_citation_ranks,
        brand_in_answer_text=True,
        sentiment=sentiment,
    )


def _build_run_captures(
    rng: random.Random, run_idx: int, run_at: datetime
) -> list[QueryCapture]:
    captures: list[QueryCapture] = []
    n_idx = 0

    overview_rate = 0.60 + 0.06 * run_idx
    in_sources_rate = 0.35 + 0.08 * run_idx

    for lens, queries in _QUERIES.items():
        for q_i, query in enumerate(queries):
            n_idx += 1
            captured_at = run_at + timedelta(minutes=7 * n_idx)

            overview_present = rng.random() < overview_rate
            if q_i == len(queries) - 1 and lens == "general":
                overview_present = False

            if lens == "comparative":
                in_sources = False
                cited = False
                multi_rank = False
            elif lens == "branded" and q_i == 0:
                overview_present = True
                in_sources = True
                cited = True
                multi_rank = True
            else:
                in_sources = overview_present and (rng.random() < in_sources_rate)
                cited = in_sources and (rng.random() < 0.55)
                multi_rank = in_sources and lens == "branded" and (q_i % 3 == 0)

            captures.append(
                _make_capture(
                    rng,
                    query,
                    lens,
                    captured_at,
                    overview_present=overview_present,
                    in_sources=in_sources,
                    cited=cited,
                    multi_rank=multi_rank,
                    n_idx=n_idx,
                )
            )

    return captures


def _reset_db(db_path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(db_path + suffix)
        if p.exists():
            p.unlink()
            print(f"seed_demo: removed {p}", file=sys.stderr)


def seed(db_path: str = DB_PATH, *, reset: bool = False, seed_value: int = 20260618) -> dict[str, Any]:
    if reset:
        _reset_db(db_path)

    rng = random.Random(seed_value)

    conn = get_conn(db_path)
    try:
        from pipeline.db import init_db

        init_db(conn)
        brand_id = get_or_create_brand(conn, BRAND_NAME, BRAND_DOMAIN)

        n_runs = 5
        base = datetime(2026, 5, 12, 9, 0, 0, tzinfo=timezone.utc)
        latest_summary: Optional[dict[str, Any]] = None

        for run_idx in range(n_runs):
            run_at = base + timedelta(days=7 * run_idx)
            run_id = create_run(conn, brand_id, ENGINE)
            conn.execute(
                "UPDATE runs SET run_at = ? WHERE id = ?",
                (run_at.isoformat(), run_id),
            )
            conn.commit()

            captures = _build_run_captures(rng, run_idx, run_at)
            for cap in captures:
                insert_capture(conn, run_id, cap)
            conn.commit()

            update_run_counts(
                conn,
                run_id,
                n_queries=len(captures),
                n_ok=len(captures),
                n_failed=0,
                status="done",
            )

            latest_summary = aggregate_run(conn, run_id)

            lenses_present = {cap.lens for cap in captures}
            for lens in ("general", "branded", "comparative"):
                if lens in lenses_present:
                    upsert_lens_sentiment(conn, run_id, lens, _LENS_SUMMARIES[lens])
            upsert_lens_sentiment(conn, run_id, "all", _LENS_SUMMARIES["all"])

            print(
                f"seed_demo: run {run_id} ({run_at.date()}) — {len(captures)} results, metrics filled",
                file=sys.stderr,
            )

        counts = {
            "brands": conn.execute("SELECT COUNT(*) FROM brands").fetchone()[0],
            "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "results": conn.execute("SELECT COUNT(*) FROM results").fetchone()[0],
            "metrics": conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0],
        }

        latest_all = None
        if latest_summary is not None:
            latest_all = next(
                (m for m in latest_summary["metrics"] if m["lens"] == "all"), None
            )

        return {
            "db_path": db_path,
            "brand": {"id": brand_id, "name": BRAND_NAME, "domain": TARGET},
            "counts": counts,
            "latest_run_id": latest_summary["run_id"] if latest_summary else None,
            "latest_all_metrics": latest_all,
        }
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.seed_demo",
        description="Seed data/aeo.db with a realistic multi-run demo dataset for Example.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete data/aeo.db (+ -wal/-shm) before seeding.",
    )
    parser.add_argument(
        "--db",
        default=DB_PATH,
        help="SQLite DB path (default: data/aeo.db).",
    )
    args = parser.parse_args(argv)

    summary = seed(args.db, reset=args.reset)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
