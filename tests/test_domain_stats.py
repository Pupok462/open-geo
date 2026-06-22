from __future__ import annotations

import pytest

from pipeline.aggregate import (
    _compute_domain_scope,
    aggregate_run,
    compute_run_domain_stats,
)
from pipeline.db import (
    create_run,
    get_conn,
    get_domain_stats,
    get_or_create_brand,
    init_db,
)
from pipeline.ingest import insert_capture
from pipeline.schema import QueryCapture

BRAND = "acme.com"


def _cap(
    query: str,
    lens: str,
    sources: list[tuple[int, str]],
    citations: list[tuple[int, str]] | None = None,
    *,
    overview: bool = True,
) -> QueryCapture:
    citations = citations or []
    src_links = [{"rank": r, "url": f"https://{d}/{r}", "domain": d} for r, d in sources]
    cit_links = [{"rank": r, "url": f"https://{d}/c{r}", "domain": d} for r, d in citations]
    brand_src = sorted(r for r, d in sources if d == BRAND)
    brand_cit = sorted(r for r, d in citations if d == BRAND)
    return QueryCapture.model_validate(
        {
            "query": query,
            "lens": lens,
            "engine": "google",
            "captured_at": "2026-06-18T00:00:00Z",
            "overview_present": overview,
            "sources": src_links if overview else [],
            "citations": cit_links if overview else [],
            "target_source_ranks": brand_src if overview else [],
            "target_citation_ranks": brand_cit if overview else [],
            "brand_in_answer_text": bool(brand_src),
            "sentiment": "x" if brand_src else None,
        }
    )


def _run_with(db_path: str, caps: list[QueryCapture]) -> int:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        bid = get_or_create_brand(conn, "Acme", BRAND)
        rid = create_run(conn, bid, "google")
        for c in caps:
            insert_capture(conn, rid, c)
        conn.commit()
        aggregate_run(conn, rid)
    finally:
        conn.close()
    return rid


def _stats(db_path: str, run_id: int, lens: str = "all") -> dict[str, dict]:
    conn = get_conn(db_path)
    try:
        rows = get_domain_stats(conn, run_id, lens)
    finally:
        conn.close()
    return {r["domain"]: r for r in rows}, rows


def test_leaderboard_mini_example(empty_db_path):
    rid = _run_with(
        empty_db_path,
        [
            _cap("q1", "general", [(1, "sleepfoundation.org"), (2, BRAND), (3, "casper.com")]),
            _cap("q2", "general", [(1, "wirecutter.com"), (2, "casper.com"), (3, BRAND)]),
            _cap("q3", "general", [(1, "reddit.com"), (2, "casper.com")]),
        ],
    )
    by, rows = _stats(empty_db_path, rid)

    assert by["casper.com"]["appearances_sources"] == 3
    assert by["casper.com"]["avg_source_position"] == pytest.approx((3 + 2 + 2) / 3)
    assert by["casper.com"]["is_brand"] == 0

    assert by[BRAND]["appearances_sources"] == 2
    assert by[BRAND]["avg_source_position"] == pytest.approx((2 + 3) / 2)
    assert by[BRAND]["is_brand"] == 1

    for solo in ("sleepfoundation.org", "wirecutter.com", "reddit.com"):
        assert by[solo]["appearances_sources"] == 1
        assert by[solo]["avg_source_position"] == pytest.approx(1.0)

    assert rows[0]["domain"] == "casper.com"
    assert [r["domain"] for r in rows[:2]] == ["casper.com", BRAND]


def test_min_rank_per_query_and_presence_once(empty_db_path):
    rid = _run_with(
        empty_db_path,
        [_cap("q1", "general", [(1, BRAND), (4, "casper.com"), (2, "casper.com")])],
    )
    by, _ = _stats(empty_db_path, rid)
    assert by["casper.com"]["appearances_sources"] == 1
    assert by["casper.com"]["avg_source_position"] == pytest.approx(2.0)


def test_citations_counted_separately(empty_db_path):
    rid = _run_with(
        empty_db_path,
        [_cap("q1", "general", [(1, BRAND), (2, "casper.com")], citations=[(1, BRAND)])],
    )
    by, _ = _stats(empty_db_path, rid)
    assert by[BRAND]["appearances_citations"] == 1
    assert by[BRAND]["avg_citation_position"] == pytest.approx(1.0)
    assert by["casper.com"]["appearances_citations"] == 0
    assert by["casper.com"]["avg_citation_position"] is None


def test_no_overview_rows_excluded(empty_db_path):
    rid = _run_with(
        empty_db_path,
        [
            _cap("q1", "general", [(1, "casper.com")], overview=False),
            _cap("q2", "general", [(1, "casper.com")], overview=True),
        ],
    )
    by, _ = _stats(empty_db_path, rid)
    assert by["casper.com"]["appearances_sources"] == 1


def test_per_lens_and_all_scope(empty_db_path):
    rid = _run_with(
        empty_db_path,
        [
            _cap("g1", "general", [(1, "casper.com")]),
            _cap("b1", "branded", [(1, "casper.com"), (2, BRAND)]),
        ],
    )
    all_by, _ = _stats(empty_db_path, rid, "all")
    gen_by, _ = _stats(empty_db_path, rid, "general")
    brd_by, _ = _stats(empty_db_path, rid, "branded")

    assert all_by["casper.com"]["appearances_sources"] == 2
    assert all_by[BRAND]["appearances_sources"] == 1
    assert set(gen_by) == {"casper.com"}
    assert set(brd_by) == {"casper.com", BRAND}


def test_aggregate_domain_stats_idempotent(empty_db_path):
    rid = _run_with(
        empty_db_path,
        [_cap("q1", "general", [(1, BRAND), (2, "casper.com")])],
    )
    conn = get_conn(empty_db_path)
    try:
        n1 = conn.execute(
            "SELECT COUNT(*) FROM domain_stats WHERE run_id = ?", (rid,)
        ).fetchone()[0]
        aggregate_run(conn, rid)
        n2 = conn.execute(
            "SELECT COUNT(*) FROM domain_stats WHERE run_id = ?", (rid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n1 == n2 > 0


def test_top_domains_in_aggregate_summary(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Acme", BRAND)
        rid = create_run(conn, bid, "google")
        insert_capture(conn, rid, _cap("q1", "general", [(1, BRAND), (2, "casper.com")]))
        conn.commit()
        summary = aggregate_run(conn, rid)
    finally:
        conn.close()
    assert "top_domains" in summary
    domains = {d["domain"] for d in summary["top_domains"]}
    assert {BRAND, "casper.com"} <= domains


def test_compute_run_domain_stats_returns_brand_domain(empty_db_path):
    rid = _run_with(empty_db_path, [_cap("q1", "general", [(1, BRAND)])])
    conn = get_conn(empty_db_path)
    try:
        out, brand_domain = compute_run_domain_stats(conn, rid)
    finally:
        conn.close()
    assert brand_domain == BRAND
    assert "all" in out


def test_compute_run_domain_stats_missing_run_raises(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        with pytest.raises(ValueError, match="run 999 not found"):
            compute_run_domain_stats(conn, 999)
    finally:
        conn.close()


def test_get_domain_stats_missing_table_returns_empty(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS domain_stats")
        conn.commit()
        assert get_domain_stats(conn, 1, "all") == []
    finally:
        conn.close()


def test_compute_domain_scope_normalizes_and_skips_bad_rows():
    rows = [
        {
            "overview_present": 1,
            "sources_json": '[{"rank": 1, "url": "x", "domain": "WWW.Casper.com"}, '
            '{"rank": 2, "domain": "acme.com"}, {"bad": true}, "nope"]',
            "citations_json": "not json",
        }
    ]
    out = _compute_domain_scope(rows, "acme.com")
    by = {r["domain"]: r for r in out}
    assert "casper.com" in by
    assert by["casper.com"]["appearances_sources"] == 1
    assert by["acme.com"]["is_brand"] == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
