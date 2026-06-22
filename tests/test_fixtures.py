from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import dashboard.seed_fixture as dsf
import report._selftest_fixture as rsf
from pipeline.db import get_conn, get_or_create_brand, init_db
from pipeline.schema import Link

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _open(db_path: str) -> sqlite3.Connection:
    return get_conn(db_path)


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _run_status(conn: sqlite3.Connection, run_id: int) -> str:
    return conn.execute(
        "SELECT status FROM runs WHERE id = ?", (run_id,)
    ).fetchone()["status"]


def _metrics_for(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM metrics WHERE run_id = ?", (run_id,)
    ).fetchall()


def _lenses_for(conn: sqlite3.Connection, run_id: int) -> set[str]:
    return {
        r["lens"]
        for r in conn.execute(
            "SELECT DISTINCT lens FROM results WHERE run_id = ?", (run_id,)
        ).fetchall()
    }


def test_dash_iso_roundtrips_datetime():
    dt = datetime(2026, 6, 18, 20, 15, 30, tzinfo=timezone.utc)
    s = dsf._iso(dt)
    assert s == "2026-06-18T20:15:30+00:00"
    assert datetime.fromisoformat(s) == dt


def test_dash_link_shape():
    link = dsf._link(3, "https://example.com/x", "example.com")
    assert link == Link(rank=3, url="https://example.com/x", domain="example.com")
    assert link.model_dump() == {"rank": 3, "url": "https://example.com/x", "domain": "example.com"}


@pytest.fixture
def dash_db(tmp_path) -> str:
    p = tmp_path / "d.db"
    summary = dsf.seed(str(p))
    assert summary["db"] == str(p)
    assert dsf.FIXTURE_DB == "data/_fixture_dash.db"
    return str(p)


def test_dash_seed_summary_shape(dash_db):
    summary = dsf.seed(dash_db)

    assert set(summary) == {"db", "brands"}
    assert summary["db"] == dash_db

    brands = summary["brands"]
    assert len(brands) == 2
    assert [b["name"] for b in brands] == ["Example", "Globex"]
    assert [b["domain"] for b in brands] == ["example.com", "globex.com"]

    for b in brands:
        assert set(b) == {"id", "name", "domain", "runs"}
        assert isinstance(b["id"], int)
        assert len(b["runs"]) == 4
        assert len(set(b["runs"])) == 4

    all_runs = [rid for b in brands for rid in b["runs"]]
    assert len(set(all_runs)) == 8


def test_dash_seed_two_brands_persisted(dash_db):
    conn = _open(dash_db)
    try:
        names = [
            r["name"]
            for r in conn.execute("SELECT name FROM brands ORDER BY id").fetchall()
        ]
        assert names == ["Example", "Globex"]
        assert _count(conn, "brands") == 2
        assert _count(conn, "runs") == 8
    finally:
        conn.close()


def test_dash_seed_run_status_split(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            statuses = sorted(_run_status(conn, rid) for rid in b["runs"])
            assert statuses == ["done", "done", "done", "running"]
    finally:
        conn.close()


def test_dash_seed_done_runs_have_metrics_running_does_not(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            done, running = [], []
            for rid in b["runs"]:
                (done if _run_status(conn, rid) == "done" else running).append(rid)
            assert len(done) == 3 and len(running) == 1

            for rid in done:
                rows = _metrics_for(conn, rid)
                assert rows, f"done run {rid} must have metrics"
                lenses = {r["lens"] for r in rows}
                assert "all" in lenses
                assert {"general", "branded", "comparative"} <= lenses

            assert _metrics_for(conn, running[0]) == []
    finally:
        conn.close()


def test_dash_seed_results_span_all_three_lenses(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            for rid in b["runs"]:
                assert _lenses_for(conn, rid) == {
                    "general",
                    "branded",
                    "comparative",
                }
                n = conn.execute(
                    "SELECT COUNT(*) FROM results WHERE run_id = ?", (rid,)
                ).fetchone()[0]
                assert n == 9
    finally:
        conn.close()


def test_dash_seed_run_counts_recorded(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            for rid in b["runs"]:
                row = conn.execute(
                    "SELECT n_queries, n_ok, n_failed FROM runs WHERE id = ?",
                    (rid,),
                ).fetchone()
                assert (row["n_queries"], row["n_ok"], row["n_failed"]) == (9, 9, 0)
    finally:
        conn.close()


def test_dash_seed_run_timestamps_strictly_increasing(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            ats = [
                conn.execute(
                    "SELECT run_at FROM runs WHERE id = ?", (rid,)
                ).fetchone()["run_at"]
                for rid in b["runs"]
            ]
            assert ats == sorted(ats)
            assert len(set(ats)) == 4
    finally:
        conn.close()


def test_dash_seed_coverage_boost_monotonic_overviews(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            done = [rid for rid in b["runs"] if _run_status(conn, rid) == "done"]
            done_sorted = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM runs WHERE id IN (%s) ORDER BY run_at"
                    % ",".join("?" * len(done)),
                    done,
                ).fetchall()
            ]
            n_overviews = [
                conn.execute(
                    "SELECT COUNT(*) FROM results "
                    "WHERE run_id = ? AND overview_present = 1",
                    (rid,),
                ).fetchone()[0]
                for rid in done_sorted
            ]
            assert n_overviews == [6, 8, 9]
            assert n_overviews[0] < n_overviews[1] < n_overviews[2]
    finally:
        conn.close()


def test_dash_seed_metrics_match_real_aggregate_math(dash_db):
    from pipeline.aggregate import compute_run_metrics

    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        b = summary["brands"][0]
        done = [rid for rid in b["runs"] if _run_status(conn, rid) == "done"]
        rid = done[0]
        fresh = {m["lens"]: m for m in compute_run_metrics(conn, rid)}
        stored = {r["lens"]: r for r in _metrics_for(conn, rid)}
        assert set(fresh) == set(stored)
        all_fresh = fresh["all"]
        all_stored = stored["all"]
        assert all_stored["n_queries"] == all_fresh["n_queries"]
        assert all_stored["n_overviews"] == all_fresh["n_overviews"]
        assert all_stored["n_in_sources"] == all_fresh["n_in_sources"]
        assert all_stored["n_cited"] == all_fresh["n_cited"]
        assert all_stored["overview_coverage"] == pytest.approx(
            all_fresh["overview_coverage"]
        )
    finally:
        conn.close()


def test_dash_seed_brand_domain_appears_in_sources(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            domain = b["domain"]
            rid = b["runs"][0]
            srcs_blobs = [
                r["sources_json"]
                for r in conn.execute(
                    "SELECT sources_json FROM results "
                    "WHERE run_id = ? AND lens = 'branded'",
                    (rid,),
                ).fetchall()
            ]
            joined = " ".join(srcs_blobs)
            assert domain in joined
    finally:
        conn.close()


def test_dash_reseed_same_path_is_idempotent(tmp_path):
    p = str(tmp_path / "reseed.db")
    first = dsf.seed(p)
    second = dsf.seed(p)

    conn = _open(p)
    try:
        assert _count(conn, "brands") == 2
        assert _count(conn, "runs") == 8
        assert _count(conn, "results") == 72
        names = [
            r["name"]
            for r in conn.execute("SELECT name FROM brands ORDER BY name").fetchall()
        ]
        assert names == ["Example", "Globex"]
    finally:
        conn.close()

    assert [b["name"] for b in first["brands"]] == [
        b["name"] for b in second["brands"]
    ]
    assert all(len(b["runs"]) == 4 for b in second["brands"])


@pytest.mark.slow
def test_dash_seed_cli_main_writes_to_given_path(tmp_path):
    target = tmp_path / "cli.db"
    proc = subprocess.run(
        [PYTHON, "-m", "dashboard.seed_fixture", str(target)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["db"] == str(target)
    assert [b["name"] for b in out["brands"]] == ["Example", "Globex"]
    assert target.exists()


def test_report_link_builds_url_from_rank_and_domain():
    link = rsf._link(2, "example.com")
    assert link == {"rank": 2, "url": "https://example.com/page2", "domain": "example.com"}


def test_report_insert_result_derives_target_ranks(empty_conn):
    init_db(empty_conn)
    brand_id = get_or_create_brand(empty_conn, rsf.BRAND, rsf.DOMAIN)
    run_id = rsf.create_run(empty_conn, brand_id, rsf.ENGINE)

    rsf._insert_result(
        empty_conn,
        run_id,
        query="q",
        lens="general",
        captured_at="2026-06-18T00:00:00+00:00",
        overview_present=True,
        source_domains=["other.com", rsf.TARGET, rsf.TARGET],
        citation_domains=[rsf.TARGET, "other.com"],
        sentiment="named",
        brand_in_text=True,
    )
    empty_conn.commit()

    row = empty_conn.execute(
        "SELECT * FROM results WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert json.loads(row["target_source_ranks_json"]) == [2, 3]
    assert json.loads(row["target_citation_ranks_json"]) == [1]
    assert row["overview_present"] == 1
    assert row["brand_in_answer_text"] == 1
    assert row["sentiment"] == "named"
    srcs = json.loads(row["sources_json"])
    assert [s["rank"] for s in srcs] == [1, 2, 3]
    assert srcs[1]["domain"] == rsf.TARGET
    assert srcs[1]["url"] == f"https://{rsf.TARGET}/page2"


def test_report_insert_result_target_absent_yields_empty_ranks(empty_conn):
    init_db(empty_conn)
    brand_id = get_or_create_brand(empty_conn, rsf.BRAND, rsf.DOMAIN)
    run_id = rsf.create_run(empty_conn, brand_id, rsf.ENGINE)

    rsf._insert_result(
        empty_conn,
        run_id,
        query="no-target",
        lens="comparative",
        captured_at="2026-06-18T00:00:00+00:00",
        overview_present=False,
        source_domains=["other.com", "rival.com"],
        citation_domains=[],
        sentiment=None,
        brand_in_text=False,
    )
    empty_conn.commit()

    row = empty_conn.execute(
        "SELECT * FROM results WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert json.loads(row["target_source_ranks_json"]) == []
    assert json.loads(row["target_citation_ranks_json"]) == []
    assert json.loads(row["citations_json"]) == []
    assert row["overview_present"] == 0
    assert row["brand_in_answer_text"] == 0
    assert row["sentiment"] is None


def _fresh_brand_conn(tmp_path, name="rep.db"):
    p = tmp_path / name
    conn = get_conn(str(p))
    init_db(conn)
    brand_id = get_or_create_brand(conn, rsf.BRAND, rsf.DOMAIN)
    return conn, brand_id


@pytest.mark.parametrize("profile", ["weaker", "stronger"])
def test_report_seed_run_profile_branches(tmp_path, profile):
    conn, brand_id = _fresh_brand_conn(tmp_path, f"{profile}.db")
    try:
        run_at = datetime(2026, 6, 18, tzinfo=timezone.utc)
        run_id = rsf._seed_run(conn, brand_id, run_at, profile)

        run = conn.execute(
            "SELECT status, n_queries, n_ok, n_failed, run_at FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["status"] == "done"
        assert (run["n_queries"], run["n_ok"], run["n_failed"]) == (13, 13, 0)
        assert run["run_at"] == run_at.isoformat()

        assert _lenses_for(conn, run_id) == {"general", "branded", "comparative"}
        assert _count(conn, "results") == 13

        mrows = {m["lens"]: m for m in _metrics_for(conn, run_id)}
        assert set(mrows) == {"all", "general", "branded", "comparative"}
        assert mrows["branded"]["n_overviews"] == 4
        assert mrows["branded"]["visibility_in_sources"] is not None
    finally:
        conn.close()


def test_report_seed_run_stronger_branded_visibility_ge_weaker(tmp_path):
    conn, brand_id = _fresh_brand_conn(tmp_path, "cmp.db")
    try:
        older = datetime(2026, 6, 11, tzinfo=timezone.utc)
        newer = datetime(2026, 6, 17, tzinfo=timezone.utc)
        weak_id = rsf._seed_run(conn, brand_id, older, "weaker")
        strong_id = rsf._seed_run(conn, brand_id, newer, "stronger")

        def branded_vis(run_id):
            return conn.execute(
                "SELECT visibility_in_sources FROM metrics "
                "WHERE run_id = ? AND lens = 'branded'",
                (run_id,),
            ).fetchone()["visibility_in_sources"]

        weak_vis = branded_vis(weak_id)
        strong_vis = branded_vis(strong_id)
        assert strong_vis >= weak_vis
        assert strong_vis == pytest.approx(1.0)
        assert weak_vis == pytest.approx(0.75)
    finally:
        conn.close()


def test_report_main_returns_zero_and_seeds_two_runs(tmp_path, monkeypatch, capsys):
    target = tmp_path / "r.db"
    monkeypatch.setattr(rsf, "FIXTURE_DB", str(target))

    rc = rsf.main()
    assert rc == 0
    assert target.exists()

    captured = capsys.readouterr()
    assert "seeded fixture" in captured.err
    assert captured.out == ""

    conn = _open(str(target))
    try:
        brands = conn.execute("SELECT id, name, domain FROM brands").fetchall()
        assert len(brands) == 1
        assert brands[0]["name"] == "Example"
        assert brands[0]["domain"] == "example.com"
        brand_id = brands[0]["id"]

        runs = conn.execute(
            "SELECT id, status, brand_id, run_at FROM runs ORDER BY run_at"
        ).fetchall()
        assert len(runs) == 2
        assert all(r["status"] == "done" for r in runs)
        assert all(r["brand_id"] == brand_id for r in runs)
        assert runs[0]["run_at"] < runs[1]["run_at"]

        for r in runs:
            lenses = {m["lens"] for m in _metrics_for(conn, r["id"])}
            assert lenses == {"all", "general", "branded", "comparative"}

        assert _count(conn, "results") == 26
    finally:
        conn.close()


def test_report_main_newer_run_is_stronger(tmp_path, monkeypatch):
    target = tmp_path / "r2.db"
    monkeypatch.setattr(rsf, "FIXTURE_DB", str(target))
    assert rsf.main() == 0

    conn = _open(str(target))
    try:
        runs = conn.execute(
            "SELECT id FROM runs ORDER BY run_at"
        ).fetchall()
        older_id, newer_id = runs[0]["id"], runs[1]["id"]

        def branded_vis(run_id):
            return conn.execute(
                "SELECT visibility_in_sources FROM metrics "
                "WHERE run_id = ? AND lens = 'branded'",
                (run_id,),
            ).fetchone()["visibility_in_sources"]

        assert branded_vis(newer_id) >= branded_vis(older_id)
    finally:
        conn.close()


def test_report_main_does_not_touch_default_fixture_path(tmp_path, monkeypatch):
    target = tmp_path / "redir.db"
    monkeypatch.setattr(rsf, "FIXTURE_DB", str(target))
    rsf.main()
    assert target.exists()
    assert str(target) != "data/_fixture_report.db"


def _dash_brand_conn(tmp_path, name="hard.db"):
    p = tmp_path / name
    conn = get_conn(str(p))
    init_db(conn)
    brand_id = get_or_create_brand(conn, "Example", "https://www.example.com")
    domain = conn.execute(
        "SELECT domain FROM brands WHERE id = ?", (brand_id,)
    ).fetchone()["domain"]
    return conn, brand_id, domain


def test_dash_iso_passthrough_keeps_microseconds():
    dt = datetime(2026, 6, 18, 20, 15, 30, 123456, tzinfo=timezone.utc)
    assert dsf._iso(dt) == "2026-06-18T20:15:30.123456+00:00"
    naive = datetime(2026, 1, 2, 3, 4, 5)
    assert dsf._iso(naive) == "2026-01-02T03:04:05"


def test_dash_link_rank_is_passthrough_int():
    assert dsf._link(1, "https://a.com/", "a.com") == Link(
        rank=1, url="https://a.com/", domain="a.com",
    )
    assert dsf._link(7, "u", "d").rank == 7


def test_dash_seed_run_direct_running_skips_aggregate(tmp_path):
    conn, brand_id, domain = _dash_brand_conn(tmp_path, "run.db")
    try:
        run_at = datetime(2026, 6, 18, tzinfo=timezone.utc)
        rid = dsf._seed_run(
            conn, brand_id, run_at, domain, coverage_boost=2, status="running"
        )
        assert isinstance(rid, int)
        assert _count(conn, "results") == 9
        assert _metrics_for(conn, rid) == []
        run = conn.execute(
            "SELECT status, n_queries, n_ok, n_failed FROM runs WHERE id = ?", (rid,)
        ).fetchone()
        assert run["status"] == "running"
        assert (run["n_queries"], run["n_ok"], run["n_failed"]) == (9, 9, 0)
    finally:
        conn.close()


def test_dash_seed_run_direct_done_aggregates(tmp_path):
    conn, brand_id, domain = _dash_brand_conn(tmp_path, "done.db")
    try:
        rid = dsf._seed_run(
            conn, brand_id, datetime(2026, 6, 18, tzinfo=timezone.utc),
            domain, coverage_boost=0, status="done",
        )
        mrows = {m["lens"] for m in _metrics_for(conn, rid)}
        assert mrows == {"all", "general", "branded", "comparative"}
    finally:
        conn.close()


@pytest.mark.parametrize(
    "boost, expected_overviews",
    [(0, 6), (1, 8), (2, 9), (3, 9)],
)
def test_dash_seed_run_boost_overview_count(tmp_path, boost, expected_overviews):
    conn, brand_id, domain = _dash_brand_conn(tmp_path, f"boost{boost}.db")
    try:
        rid = dsf._seed_run(
            conn, brand_id, datetime(2026, 6, 18, tzinfo=timezone.utc),
            domain, coverage_boost=boost, status="done",
        )
        n_ov = conn.execute(
            "SELECT COUNT(*) FROM results WHERE run_id = ? AND overview_present = 1",
            (rid,),
        ).fetchone()[0]
        assert n_ov == expected_overviews
    finally:
        conn.close()


def test_dash_seed_per_lens_boost_gradient(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            done_sorted = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM runs WHERE brand_id = ? AND status = 'done' "
                    "ORDER BY run_at",
                    (b["id"],),
                ).fetchall()
            ]
            grad = {"general": [], "branded": [], "comparative": []}
            for rid in done_sorted:
                for lens in grad:
                    grad[lens].append(
                        conn.execute(
                            "SELECT COUNT(*) FROM results WHERE run_id = ? "
                            "AND lens = ? AND overview_present = 1",
                            (rid, lens),
                        ).fetchone()[0]
                    )
            assert grad["general"] == [2, 3, 4]
            assert grad["branded"] == [2, 3, 3]
            assert grad["comparative"] == [2, 2, 2]
    finally:
        conn.close()


def test_dash_running_run_shares_boost2_inputs_but_no_metrics(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        for b in summary["brands"]:
            ordered = [
                (r["id"], r["status"])
                for r in conn.execute(
                    "SELECT id, status FROM runs WHERE brand_id = ? ORDER BY run_at",
                    (b["id"],),
                ).fetchall()
            ]
            assert [s for _, s in ordered] == ["done", "done", "done", "running"]
            done_boost2 = ordered[2][0]
            running = ordered[3][0]

            def overviews(rid):
                return conn.execute(
                    "SELECT COUNT(*) FROM results "
                    "WHERE run_id = ? AND overview_present = 1",
                    (rid,),
                ).fetchone()[0]

            assert overviews(running) == 9
            assert overviews(done_boost2) == 9
            assert _metrics_for(conn, running) == []
            assert _metrics_for(conn, done_boost2)
    finally:
        conn.close()


def test_dash_seed_sentiment_null_iff_overview_absent(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        b = summary["brands"][0]
        done_sorted = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM runs WHERE brand_id = ? AND status = 'done' "
                "ORDER BY run_at",
                (b["id"],),
            ).fetchall()
        ]
        boost0, boost1 = done_sorted[0], done_sorted[1]
        q = "how to choose a task tracker for beginners"

        r0 = conn.execute(
            "SELECT overview_present, sentiment FROM results "
            "WHERE run_id = ? AND query = ?",
            (boost0, q),
        ).fetchone()
        r1 = conn.execute(
            "SELECT overview_present, sentiment FROM results "
            "WHERE run_id = ? AND query = ?",
            (boost1, q),
        ).fetchone()

        assert r0["overview_present"] == 0
        assert r0["sentiment"] is None
        assert r1["overview_present"] == 1
        assert r1["sentiment"] == "mentioned neutrally among others"
    finally:
        conn.close()


def test_dash_seed_answer_text_md_present_iff_overview(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        rid = summary["brands"][0]["runs"][0]
        rows = conn.execute(
            "SELECT overview_present, answer_text_md FROM results WHERE run_id = ?",
            (rid,),
        ).fetchall()
        present = [r for r in rows if r["overview_present"] == 1]
        absent = [r for r in rows if r["overview_present"] == 0]
        assert present and absent
        assert all(r["answer_text_md"] == "Example AI Overview answer…" for r in present)
        assert all(r["answer_text_md"] is None for r in absent)
    finally:
        conn.close()


def test_dash_seed_metrics_match_real_aggregate_on_boost2_run(dash_db):
    from pipeline.aggregate import compute_run_metrics

    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        b = summary["brands"][0]
        done_sorted = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM runs WHERE brand_id = ? AND status = 'done' "
                "ORDER BY run_at",
                (b["id"],),
            ).fetchall()
        ]
        rid = done_sorted[2]
        fresh = {m["lens"]: m for m in compute_run_metrics(conn, rid)}
        stored = {r["lens"]: r for r in _metrics_for(conn, rid)}
        assert set(fresh) == set(stored) == {"all", "general", "branded", "comparative"}

        a = stored["all"]
        assert (a["n_queries"], a["n_overviews"]) == (9, 9)
        assert a["overview_coverage"] == pytest.approx(1.0)
        assert a["n_in_sources"] == 7
        assert a["visibility_in_sources"] == pytest.approx(7 / 9)
        assert a["n_cited"] == 4
        assert a["visibility_in_citations"] == pytest.approx(4 / 9)
        assert a["avg_source_position"] == pytest.approx(10 / 7)
        assert a["avg_citation_position"] == pytest.approx(1.0)

        for lens, s in stored.items():
            f = fresh[lens]
            for col in (
                "n_queries", "n_overviews", "n_in_sources", "n_cited",
            ):
                assert s[col] == f[col], (lens, col)
            for col in (
                "overview_coverage", "visibility_in_sources",
                "visibility_in_citations", "avg_source_position",
                "avg_citation_position",
            ):
                if f[col] is None:
                    assert s[col] is None, (lens, col)
                else:
                    assert s[col] == pytest.approx(f[col]), (lens, col)
    finally:
        conn.close()


def test_dash_seed_two_brands_produce_identical_metrics(dash_db):
    summary = dsf.seed(dash_db)
    conn = _open(dash_db)
    try:
        example, rest = summary["brands"][0], summary["brands"][1]

        def all_metrics_by_boost(b):
            done_sorted = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM runs WHERE brand_id = ? AND status = 'done' "
                    "ORDER BY run_at",
                    (b["id"],),
                ).fetchall()
            ]
            out = []
            for rid in done_sorted:
                row = conn.execute(
                    "SELECT n_queries, n_overviews, overview_coverage, n_in_sources, "
                    "visibility_in_sources, n_cited, visibility_in_citations, "
                    "avg_source_position, avg_citation_position "
                    "FROM metrics WHERE run_id = ? AND lens = 'all'",
                    (rid,),
                ).fetchone()
                out.append(tuple(row))
            return out

        assert all_metrics_by_boost(example) == all_metrics_by_boost(rest)
    finally:
        conn.close()


def test_report_link_url_uses_page_rank_suffix():
    assert rsf._link(1, "example.com")["url"] == "https://example.com/page1"
    assert rsf._link(10, "x.io")["url"] == "https://x.io/page10"
    lk = rsf._link(4, "globex.com")
    assert lk == {"rank": 4, "url": "https://globex.com/page4", "domain": "globex.com"}


def test_report_insert_result_duplicate_target_domains(empty_conn):
    init_db(empty_conn)
    brand_id = get_or_create_brand(empty_conn, rsf.BRAND, rsf.DOMAIN)
    run_id = rsf.create_run(empty_conn, brand_id, rsf.ENGINE)

    rsf._insert_result(
        empty_conn,
        run_id,
        query="dups",
        lens="branded",
        captured_at="2026-06-18T00:00:00+00:00",
        overview_present=True,
        source_domains=[rsf.TARGET, rsf.TARGET, "other.com", rsf.TARGET],
        citation_domains=["other.com", rsf.TARGET, rsf.TARGET],
        sentiment="named repeatedly",
        brand_in_text=True,
    )
    empty_conn.commit()

    row = empty_conn.execute(
        "SELECT * FROM results WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert json.loads(row["target_source_ranks_json"]) == [1, 2, 4]
    assert json.loads(row["target_citation_ranks_json"]) == [2, 3]
    srcs = json.loads(row["sources_json"])
    assert [s["rank"] for s in srcs] == [1, 2, 3, 4]
    assert [s["domain"] for s in srcs] == [rsf.TARGET, rsf.TARGET, "other.com", rsf.TARGET]


def test_report_insert_result_empty_lists_store_empty_json(empty_conn):
    init_db(empty_conn)
    brand_id = get_or_create_brand(empty_conn, rsf.BRAND, rsf.DOMAIN)
    run_id = rsf.create_run(empty_conn, brand_id, rsf.ENGINE)

    rsf._insert_result(
        empty_conn,
        run_id,
        query="empty",
        lens="general",
        captured_at="2026-06-18T00:00:00+00:00",
        overview_present=False,
        source_domains=[],
        citation_domains=[],
        sentiment=None,
        brand_in_text=False,
    )
    empty_conn.commit()

    row = empty_conn.execute(
        "SELECT * FROM results WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert row["sources_json"] == "[]"
    assert row["citations_json"] == "[]"
    assert json.loads(row["target_source_ranks_json"]) == []
    assert json.loads(row["target_citation_ranks_json"]) == []


@pytest.mark.parametrize(
    "profile, expected",
    [
        ("weaker", {
            "all": (10, 5, 3),
            "general": (3, 1, 0),
            "branded": (4, 3, 2),
            "comparative": (3, 1, 1),
        }),
        ("stronger", {
            "all": (12, 9, 7),
            "general": (4, 3, 2),
            "branded": (4, 4, 3),
            "comparative": (4, 2, 2),
        }),
    ],
)
def test_report_seed_run_full_metric_table(tmp_path, profile, expected):
    conn, brand_id = _fresh_brand_conn(tmp_path, f"full_{profile}.db")
    try:
        rid = rsf._seed_run(
            conn, brand_id, datetime(2026, 6, 18, tzinfo=timezone.utc), profile
        )
        m = {r["lens"]: r for r in _metrics_for(conn, rid)}
        assert set(m) == {"all", "general", "branded", "comparative"}
        for lens, (nov, nsrc, ncit) in expected.items():
            assert m[lens]["n_overviews"] == nov, (lens, "n_overviews")
            assert m[lens]["n_in_sources"] == nsrc, (lens, "n_in_sources")
            assert m[lens]["n_cited"] == ncit, (lens, "n_cited")
    finally:
        conn.close()


def test_report_stronger_dominates_weaker_on_all_rates(tmp_path):
    conn, brand_id = _fresh_brand_conn(tmp_path, "dom.db")
    try:
        weak = rsf._seed_run(
            conn, brand_id, datetime(2026, 6, 11, tzinfo=timezone.utc), "weaker"
        )
        strong = rsf._seed_run(
            conn, brand_id, datetime(2026, 6, 17, tzinfo=timezone.utc), "stronger"
        )

        def all_row(rid):
            return conn.execute(
                "SELECT * FROM metrics WHERE run_id = ? AND lens = 'all'", (rid,)
            ).fetchone()

        w, s = all_row(weak), all_row(strong)
        for col in (
            "overview_coverage", "visibility_in_sources", "visibility_in_citations",
        ):
            assert s[col] >= w[col], col
        assert s["avg_source_position"] <= w["avg_source_position"]
        assert w["visibility_in_sources"] == pytest.approx(0.5)
        assert s["visibility_in_sources"] == pytest.approx(0.75)
        assert w["overview_coverage"] == pytest.approx(10 / 13)
        assert s["overview_coverage"] == pytest.approx(12 / 13)
    finally:
        conn.close()


def test_report_seed_run_does_not_wipe_accumulates(tmp_path):
    conn, brand_id = _fresh_brand_conn(tmp_path, "acc.db")
    try:
        rsf._seed_run(conn, brand_id, datetime(2026, 6, 11, tzinfo=timezone.utc), "weaker")
        rsf._seed_run(conn, brand_id, datetime(2026, 6, 17, tzinfo=timezone.utc), "stronger")
        assert _count(conn, "brands") == 1
        assert _count(conn, "runs") == 2
        assert _count(conn, "results") == 26
        assert _count(conn, "metrics") == 8
    finally:
        conn.close()


def test_report_main_rerun_accumulates_runs_not_brands(tmp_path, monkeypatch):
    target = tmp_path / "rerun.db"
    monkeypatch.setattr(rsf, "FIXTURE_DB", str(target))

    assert rsf.main() == 0
    assert rsf.main() == 0

    conn = _open(str(target))
    try:
        assert _count(conn, "brands") == 1
        assert _count(conn, "runs") == 4
        assert _count(conn, "results") == 52
        run_ids = [r["id"] for r in conn.execute("SELECT id FROM runs").fetchall()]
        for rid in run_ids:
            lenses = {m["lens"] for m in _metrics_for(conn, rid)}
            assert lenses == {"all", "general", "branded", "comparative"}
    finally:
        conn.close()


def test_report_seed_run_returns_distinct_increasing_ids(tmp_path):
    conn, brand_id = _fresh_brand_conn(tmp_path, "ids.db")
    try:
        a = rsf._seed_run(conn, brand_id, datetime(2026, 6, 11, tzinfo=timezone.utc), "weaker")
        b = rsf._seed_run(conn, brand_id, datetime(2026, 6, 17, tzinfo=timezone.utc), "stronger")
        assert isinstance(a, int) and isinstance(b, int)
        assert b > a
        existing = {
            r["id"] for r in conn.execute("SELECT id FROM runs").fetchall()
        }
        assert {a, b} <= existing
    finally:
        conn.close()
