from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from pipeline.aggregate import aggregate_run
from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    init_db,
    update_run_counts,
    upsert_lens_sentiment,
)

FIXTURE_DB = "data/_fixture_report.db"
BRAND = "Example"
DOMAIN = "https://www.example.com"
ENGINE = "google"
TARGET = "example.com"


def _link(rank: int, domain: str) -> dict:
    return {"rank": rank, "url": f"https://{domain}/page{rank}", "domain": domain}


def _insert_result(
    conn,
    run_id: int,
    query: str,
    lens: str,
    captured_at: str,
    overview_present: bool,
    source_domains: list[str],
    citation_domains: list[str],
    sentiment: str | None,
    brand_in_text: bool,
) -> None:
    sources = [_link(i + 1, d) for i, d in enumerate(source_domains)]
    citations = [_link(i + 1, d) for i, d in enumerate(citation_domains)]
    target_source_ranks = [i + 1 for i, d in enumerate(source_domains) if d == TARGET]
    target_citation_ranks = [i + 1 for i, d in enumerate(citation_domains) if d == TARGET]

    conn.execute(
        """
        INSERT INTO results (
            run_id, query, lens, captured_at, answer_text_md, screenshot_path,
            overview_present, sources_json, citations_json,
            target_source_ranks_json, target_citation_ranks_json,
            brand_in_answer_text, sentiment
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            query,
            lens,
            captured_at,
            None,
            None,
            1 if overview_present else 0,
            json.dumps(sources, ensure_ascii=False),
            json.dumps(citations, ensure_ascii=False),
            json.dumps(target_source_ranks),
            json.dumps(target_citation_ranks),
            1 if brand_in_text else 0,
            sentiment,
        ),
    )


def _seed_run(conn, brand_id: int, run_at: datetime, profile: str) -> int:
    run_id = create_run(conn, brand_id, ENGINE)
    conn.execute("UPDATE runs SET run_at = ? WHERE id = ?", (run_at.isoformat(), run_id))

    ts = run_at.isoformat()
    OTHER = ["globex.com", "wikipedia.org", "g2.com", "techradar.com", "nytimes.com"]

    sent_reco = "recommended as one of the top options, with a direct catalog link"
    sent_neutral = "mentioned neutrally among several options"
    sent_brief = "named briefly, without detail"

    if profile == "weaker":
        general = [
            (True, [OTHER[0], OTHER[1], TARGET], [], sent_neutral, True),
            (True, [OTHER[2], OTHER[3]], [], None, False),
            (True, [OTHER[0], OTHER[4]], [], None, False),
            (False, [], [], None, False),
            (False, [], [], None, False),
        ]
        branded = [
            (True, [TARGET, OTHER[0]], [TARGET], sent_reco, True),
            (True, [OTHER[1], TARGET], [TARGET], sent_neutral, True),
            (True, [TARGET, OTHER[2], OTHER[3]], [], sent_brief, True),
            (True, [OTHER[4], OTHER[0]], [], None, False),
        ]
        comparative = [
            (True, [OTHER[0], OTHER[1], TARGET], [TARGET], sent_neutral, True),
            (True, [OTHER[2], OTHER[3]], [], None, False),
            (True, [OTHER[4], OTHER[0]], [], None, False),
            (False, [], [], None, False),
        ]
    else:
        general = [
            (True, [TARGET, OTHER[1]], [TARGET], sent_reco, True),
            (True, [OTHER[0], TARGET], [TARGET], sent_neutral, True),
            (True, [OTHER[2], OTHER[3], TARGET], [], sent_brief, True),
            (True, [OTHER[0], OTHER[4]], [], None, False),
            (False, [], [], None, False),
        ]
        branded = [
            (True, [TARGET, OTHER[0]], [TARGET], sent_reco, True),
            (True, [TARGET, OTHER[1]], [TARGET], sent_reco, True),
            (True, [OTHER[2], TARGET], [TARGET], sent_neutral, True),
            (True, [TARGET, OTHER[3], OTHER[4]], [], sent_brief, True),
        ]
        comparative = [
            (True, [OTHER[0], TARGET], [TARGET], sent_reco, True),
            (True, [TARGET, OTHER[1], OTHER[2]], [TARGET], sent_neutral, True),
            (True, [OTHER[3], OTHER[4]], [], None, False),
            (True, [OTHER[0], OTHER[1]], [], None, False),
        ]

    blocks = {
        "general": (general, "best task tracking tools for teams"),
        "branded": (branded, f"{BRAND} reviews"),
        "comparative": (comparative, f"{BRAND} vs competitor which to choose"),
    }

    for lens, (rows, qbase) in blocks.items():
        for i, (ov, src, cit, sent, bit) in enumerate(rows):
            _insert_result(
                conn,
                run_id,
                query=f"{qbase} #{i + 1}",
                lens=lens,
                captured_at=ts,
                overview_present=ov,
                source_domains=src,
                citation_domains=cit,
                sentiment=sent,
                brand_in_text=bit,
            )

    conn.commit()

    n_total = len(general) + len(branded) + len(comparative)
    update_run_counts(conn, run_id, n_queries=n_total, n_ok=n_total, n_failed=0, status="done")
    aggregate_run(conn, run_id)

    summaries = {
        "general": "Surfaced among general options with mixed prominence.",
        "branded": "Owns its branded queries, frequently with a direct link.",
        "comparative": "Named alongside competitors without a decisive edge.",
        "all": "Strong on branded queries, neutral to mixed elsewhere.",
    }
    for lens, summary in summaries.items():
        upsert_lens_sentiment(conn, run_id, lens, summary)

    return run_id


def main() -> int:
    conn = get_conn(FIXTURE_DB)
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, BRAND, DOMAIN)

        now = datetime.now(timezone.utc)
        older = now - timedelta(days=7)
        newer = now - timedelta(days=1)

        run_old = _seed_run(conn, brand_id, older, "weaker")
        run_new = _seed_run(conn, brand_id, newer, "stronger")

        print(
            f"seeded fixture: db={FIXTURE_DB} brand_id={brand_id} "
            f"runs=[{run_old} (older/weaker), {run_new} (newer/stronger)]",
            file=sys.stderr,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
