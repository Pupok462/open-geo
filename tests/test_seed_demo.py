from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from random import Random

import pytest

from pipeline import seed_demo as sd
from pipeline.schema import QueryCapture

AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TARGET = sd.TARGET


def test_link_target_domain_uses_catalog_path():
    link = sd._link(3, TARGET, "feature-3")
    assert link.url == f"https://{TARGET}/catalog/feature-3"
    assert link.rank == 3
    assert link.domain == TARGET
    assert "www." not in link.url


def test_link_other_domain_uses_www_path():
    link = sd._link(7, "wirecutter.com", "article-7")
    assert link.url == "https://www.wirecutter.com/article-7"
    assert link.rank == 7
    assert link.domain == "wirecutter.com"


def test_link_returns_valid_link_model():
    a = sd._link(1, TARGET, "s")
    b = sd._link(2, "ikea.com", "s")
    assert isinstance(a.rank, int) and isinstance(b.rank, int)
    assert a.domain == TARGET and b.domain == "ikea.com"


def test_build_sources_ranks_contiguous_1_to_n():
    links = sd._build_sources(Random(0), 5, target_positions=[2])
    assert [ln.rank for ln in links] == [1, 2, 3, 4, 5]
    assert len(links) == 5


def test_build_sources_target_only_at_given_positions():
    positions = [1, 3]
    links = sd._build_sources(Random(0), 5, target_positions=positions)
    target_ranks = [ln.rank for ln in links if ln.domain == TARGET]
    assert target_ranks == positions
    for ln in links:
        if ln.rank not in positions:
            assert ln.domain != TARGET


def test_build_sources_empty_positions_means_no_target():
    links = sd._build_sources(Random(0), 4, target_positions=[])
    assert all(ln.domain != TARGET for ln in links)
    assert [ln.rank for ln in links] == [1, 2, 3, 4]


def test_build_sources_target_url_is_catalog_form():
    links = sd._build_sources(Random(0), 3, target_positions=[2])
    target = next(ln for ln in links if ln.domain == TARGET)
    assert target.url == f"https://{TARGET}/catalog/feature-2"


def test_build_sources_n_exceeding_pool_recycles_other_domains():
    n = len(sd._OTHER_DOMAINS) + 4
    links = sd._build_sources(Random(0), n, target_positions=[1])
    assert [ln.rank for ln in links] == list(range(1, n + 1))
    assert sum(1 for ln in links if ln.domain == TARGET) == 1


def _mk(seed: int, **kw) -> QueryCapture:
    base = dict(
        query="q",
        lens="general",
        captured_at=AT,
        overview_present=True,
        in_sources=False,
        cited=False,
        multi_rank=False,
        n_idx=1,
    )
    base.update(kw)
    rng = Random(seed)
    return sd._make_capture(rng, base.pop("query"), base.pop("lens"), base.pop("captured_at"), **base)


def test_make_capture_no_overview_is_all_empty():
    cap = _mk(0, overview_present=False)
    assert isinstance(cap, QueryCapture)
    assert cap.overview_present is False
    assert cap.sources == []
    assert cap.citations == []
    assert cap.target_source_ranks == []
    assert cap.target_citation_ranks == []
    assert cap.brand_in_answer_text is False
    assert cap.sentiment is None
    assert cap.answer_text_md is None


def test_make_capture_overview_not_in_sources_brand_false():
    cap = _mk(0, overview_present=True, in_sources=False)
    assert cap.overview_present is True
    assert cap.target_source_ranks == []
    assert cap.target_citation_ranks == []
    assert cap.citations == []
    assert cap.sources
    assert all(ln.domain != TARGET for ln in cap.sources)
    assert cap.brand_in_answer_text is False
    assert cap.sentiment is None


def test_make_capture_overview_not_in_sources_brand_true():
    cap = _mk(4, overview_present=True, in_sources=False)
    assert cap.target_source_ranks == []
    assert cap.brand_in_answer_text is True
    assert cap.sentiment in sd._SENTIMENTS_NEUTRAL


def test_make_capture_in_sources_single_rank():
    cap = _mk(2, lens="branded", overview_present=True, in_sources=True)
    assert len(cap.target_source_ranks) == 1
    rank = cap.target_source_ranks[0]
    placed = {ln.rank for ln in cap.sources if ln.domain == TARGET}
    assert placed == set(cap.target_source_ranks)
    assert 1 <= rank <= len(cap.sources)
    assert cap.brand_in_answer_text is True


def test_make_capture_in_sources_multi_rank_two_positions():
    cap = _mk(0, lens="branded", overview_present=True, in_sources=True, multi_rank=True)
    assert len(cap.sources) >= 4
    assert len(cap.target_source_ranks) == 2
    assert cap.target_source_ranks == sorted(cap.target_source_ranks)
    placed = sorted(ln.rank for ln in cap.sources if ln.domain == TARGET)
    assert placed == cap.target_source_ranks


def test_make_capture_multi_rank_falls_back_to_single_when_few_sources():
    cap = _mk(2, lens="branded", overview_present=True, in_sources=True, multi_rank=True)
    assert len(cap.sources) == 3
    assert len(cap.target_source_ranks) == 1


def test_make_capture_cited_true_target_citations_contiguous():
    cap = _mk(1, lens="branded", overview_present=True, in_sources=True, cited=True)
    assert cap.target_citation_ranks
    n = len(cap.target_citation_ranks)
    assert cap.target_citation_ranks == list(range(1, n + 1))
    assert all(ln.domain == TARGET for ln in cap.citations)
    assert [ln.rank for ln in cap.citations] == list(range(1, len(cap.citations) + 1))


def test_make_capture_cited_false_other_domain_citation():
    cap = _mk(0, lens="branded", overview_present=True, in_sources=True, cited=False)
    assert cap.target_citation_ranks == []
    assert len(cap.citations) == 1
    assert cap.citations[0].domain != TARGET


def test_make_capture_cited_false_no_citation():
    cap = _mk(2, lens="branded", overview_present=True, in_sources=True, cited=False)
    assert cap.target_citation_ranks == []
    assert cap.citations == []


def test_make_capture_sentiment_positive_when_rank_one():
    cap = _mk(1, lens="branded", overview_present=True, in_sources=True, cited=True)
    assert min(cap.target_source_ranks) == 1
    assert cap.sentiment in sd._SENTIMENTS_POS


def test_make_capture_sentiment_neutral_when_rank_above_one():
    cap = _mk(0, lens="branded", overview_present=True, in_sources=True, cited=True)
    assert min(cap.target_source_ranks) > 1
    assert cap.sentiment in sd._SENTIMENTS_NEUTRAL


def test_make_capture_screenshot_path_encodes_lens_and_index():
    cap = _mk(0, lens="comparative", overview_present=False, n_idx=7)
    assert cap.screenshot_path == "data/screenshots/seed/comparative_007.png"


@pytest.mark.parametrize("seed", range(12))
def test_make_capture_every_combination_validates(seed):
    combos = [
        dict(overview_present=False, in_sources=False, cited=False, multi_rank=False),
        dict(overview_present=True, in_sources=False, cited=False, multi_rank=False),
        dict(overview_present=True, in_sources=True, cited=False, multi_rank=False),
        dict(overview_present=True, in_sources=True, cited=True, multi_rank=False),
        dict(overview_present=True, in_sources=True, cited=True, multi_rank=True),
        dict(overview_present=True, in_sources=True, cited=False, multi_rank=True),
    ]
    for i, combo in enumerate(combos):
        cap = _mk(seed * 17 + i, lens="branded", **combo)
        assert QueryCapture.model_validate(cap.model_dump()) == cap
        appeared = bool(cap.target_source_ranks) or bool(cap.target_citation_ranks) or cap.brand_in_answer_text
        if not appeared:
            assert cap.sentiment is None


@pytest.mark.parametrize("run_idx", [0, 1, 2, 3, 4])
def test_build_run_captures_exactly_24(run_idx):
    caps = sd._build_run_captures(Random(20260618), run_idx, AT)
    assert len(caps) == 24
    lens_counts = {}
    for c in caps:
        lens_counts[c.lens] = lens_counts.get(c.lens, 0) + 1
    assert lens_counts == {"general": 8, "branded": 8, "comparative": 8}


@pytest.mark.parametrize("run_idx", [0, 1, 2, 3, 4])
def test_build_run_captures_comparative_never_in_sources(run_idx):
    caps = sd._build_run_captures(Random(20260618), run_idx, AT)
    comparative = [c for c in caps if c.lens == "comparative"]
    assert len(comparative) == 8
    for c in comparative:
        assert c.target_source_ranks == []
        assert c.target_citation_ranks == []


@pytest.mark.parametrize("run_idx", [0, 1, 2, 3, 4])
def test_build_run_captures_general_last_query_no_overview(run_idx):
    caps = sd._build_run_captures(Random(20260618), run_idx, AT)
    general = [c for c in caps if c.lens == "general"]
    assert general[-1].overview_present is False
    assert any(not c.overview_present for c in caps)


def test_build_run_captures_captured_at_strictly_increasing():
    caps = sd._build_run_captures(Random(20260618), 0, AT)
    times = [c.captured_at for c in caps]
    assert times == sorted(times)
    assert all(t > AT for t in times)
    from datetime import timedelta
    assert times[0] == AT + timedelta(minutes=7)


def test_build_run_captures_branded_has_a_multi_rank_row():
    caps = sd._build_run_captures(Random(20260618), 0, AT)
    branded = [c for c in caps if c.lens == "branded"]
    assert any(len(c.target_source_ranks) >= 2 for c in branded)


def test_reset_db_removes_all_three_sidecar_files(tmp_path):
    base = tmp_path / "aeo.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(base) + suffix).write_text("x")
    for suffix in ("", "-wal", "-shm"):
        assert Path(str(base) + suffix).exists()

    sd._reset_db(str(base))

    for suffix in ("", "-wal", "-shm"):
        assert not Path(str(base) + suffix).exists()


def test_reset_db_partial_sidecars(tmp_path):
    base = tmp_path / "aeo.db"
    base.write_text("x")
    sd._reset_db(str(base))
    assert not base.exists()
    assert not Path(str(base) + "-wal").exists()


def test_reset_db_nonexistent_path_does_not_raise(tmp_path):
    missing = tmp_path / "nope.db"
    assert not missing.exists()
    sd._reset_db(str(missing))
    assert not missing.exists()


def _count(db_path: str, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_seed_return_shape_and_exact_counts(tmp_path):
    p = tmp_path / "seeded.db"
    out = sd.seed(str(p), reset=True)

    assert out["db_path"] == str(p)
    assert out["brand"] == {"id": 1, "name": sd.BRAND_NAME, "domain": TARGET}

    counts = out["counts"]
    assert counts["brands"] == 1
    assert counts["runs"] == 5
    assert counts["results"] == 120
    assert counts["results"] == 5 * 24
    assert counts["metrics"] > 0
    assert counts["metrics"] == 20

    assert out["latest_run_id"] == 5

    latest = out["latest_all_metrics"]
    assert latest is not None
    assert latest["lens"] == "all"
    assert latest["n_queries"] == 24

    assert _count(str(p), "results") == 120
    assert _count(str(p), "runs") == 5
    assert _count(str(p), "brands") == 1


def test_seed_is_deterministic_across_two_fresh_dbs(tmp_path):
    p1 = tmp_path / "a.db"
    p2 = tmp_path / "b.db"
    r1 = sd.seed(str(p1), reset=True)
    r2 = sd.seed(str(p2), reset=True)

    assert r1["counts"] == r2["counts"]
    assert r1["latest_all_metrics"] == r2["latest_all_metrics"]
    assert r1["latest_run_id"] == r2["latest_run_id"]
    assert r1["brand"] == r2["brand"]

    def _all_results(db_path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                "SELECT run_id, query, lens, overview_present, "
                "target_source_ranks_json, target_citation_ranks_json, sentiment "
                "FROM results ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

    assert _all_results(str(p1)) == _all_results(str(p2))


def test_seed_metrics_have_an_all_row_per_run(tmp_path):
    p = tmp_path / "seeded.db"
    out = sd.seed(str(p), reset=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        all_rows = conn.execute(
            "SELECT * FROM metrics WHERE lens = 'all' ORDER BY run_id"
        ).fetchall()
        assert len(all_rows) == 5
        latest_db = dict(all_rows[-1])
    finally:
        conn.close()
    summary = out["latest_all_metrics"]
    assert latest_db["n_queries"] == summary["n_queries"]
    assert latest_db["n_overviews"] == summary["n_overviews"]
    assert latest_db["n_in_sources"] == summary["n_in_sources"]


def test_seed_comparative_lens_scope_has_zero_in_sources(tmp_path):
    p = tmp_path / "seeded.db"
    sd.seed(str(p), reset=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT n_in_sources, visibility_in_sources, avg_source_position "
            "FROM metrics WHERE lens = 'comparative'"
        ).fetchall()
        assert len(rows) == 5
        for r in rows:
            assert r["n_in_sources"] == 0
            assert r["avg_source_position"] is None
    finally:
        conn.close()


def test_seed_default_db_path_is_data_aeo_db():
    assert sd.DB_PATH == "data/aeo.db"


def test_seed_reset_removes_preexisting_db(tmp_path):
    p = tmp_path / "old.db"
    p.write_text("not a sqlite database at all")
    assert p.exists()

    out = sd.seed(str(p), reset=True)
    assert out["counts"]["results"] == 120
    assert _count(str(p), "results") == 120


def test_seed_without_reset_on_fresh_path(tmp_path):
    p = tmp_path / "fresh.db"
    out = sd.seed(str(p))
    assert out["counts"]["runs"] == 5
    assert out["counts"]["results"] == 120


def test_main_reset_returns_zero_and_prints_json(tmp_path, capsys):
    p = tmp_path / "cli.db"
    rc = sd.main(["--db", str(p), "--reset"])
    assert rc == 0

    out = capsys.readouterr().out
    summary = json.loads(out)
    assert summary["counts"]["runs"] == 5
    assert summary["counts"]["results"] == 120
    assert summary["counts"]["brands"] == 1
    assert summary["brand"]["domain"] == TARGET
    assert summary["latest_run_id"] == 5


def test_main_without_reset(tmp_path, capsys):
    p = tmp_path / "cli2.db"
    rc = sd.main(["--db", str(p)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["results"] == 120


def test_main_stdout_is_single_json_object(tmp_path, capsys):
    p = tmp_path / "cli3.db"
    sd.main(["--db", str(p), "--reset"])
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert set(obj) == {"db_path", "brand", "counts", "latest_run_id", "latest_all_metrics"}


@pytest.mark.slow
def test_main_subprocess_end_to_end(tmp_path):
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    p = tmp_path / "sub.db"
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.seed_demo", "--db", str(p), "--reset"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["counts"]["results"] == 120
    assert summary["counts"]["runs"] == 5


def test_seed_empty_run_loop_returns_none_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "range", lambda *a, **k: [], raising=False)

    p = tmp_path / "empty.db"
    out = sd.seed(str(p), reset=True)

    assert out["latest_run_id"] is None
    assert out["latest_all_metrics"] is None

    assert out["db_path"] == str(p)
    assert out["brand"] == {"id": 1, "name": sd.BRAND_NAME, "domain": TARGET}
    assert out["counts"] == {"brands": 1, "runs": 0, "results": 0, "metrics": 0}
    assert set(out) == {"db_path", "brand", "counts", "latest_run_id", "latest_all_metrics"}
    assert _count(str(p), "brands") == 1
    assert _count(str(p), "runs") == 0


def test_seed_empty_loop_monkeypatch_is_local(tmp_path):
    p = tmp_path / "after.db"
    out = sd.seed(str(p), reset=True)
    assert out["counts"]["runs"] == 5
    assert out["counts"]["results"] == 120
    assert out["latest_run_id"] == 5


def test_link_slug_is_inserted_verbatim_target_branch():
    link = sd._link(2, TARGET, "проект-ürün/路")
    assert link.url == f"https://{TARGET}/catalog/проект-ürün/路"
    assert link.rank == 2 and link.domain == TARGET


def test_link_slug_is_inserted_verbatim_other_branch():
    link = sd._link(9, "reddit.com", "r/ProjectManagement")
    assert link.url == "https://www.reddit.com/r/ProjectManagement"
    assert link.rank == 9 and link.domain == "reddit.com"


def test_link_target_match_is_exact_not_substring():
    other = "notexample.com"
    assert other != TARGET
    link = sd._link(1, other, "s")
    assert link.url == f"https://www.{other}/s"


def test_build_sources_n_zero_is_empty_list():
    links = sd._build_sources(Random(0), 0, target_positions=[])
    assert links == []


def test_build_sources_n_one_single_rank():
    links = sd._build_sources(Random(0), 1, target_positions=[1])
    assert len(links) == 1
    assert links[0].rank == 1
    assert links[0].domain == TARGET


def test_build_sources_position_out_of_range_never_places_target():
    links = sd._build_sources(Random(0), 3, target_positions=[5])
    assert [ln.rank for ln in links] == [1, 2, 3]
    assert all(ln.domain != TARGET for ln in links)


def test_build_sources_duplicate_positions_place_target_once_per_rank():
    links = sd._build_sources(Random(0), 4, target_positions=[2, 2])
    assert [ln.rank for ln in links] == [1, 2, 3, 4]
    target_ranks = [ln.rank for ln in links if ln.domain == TARGET]
    assert target_ranks == [2]


def test_build_sources_all_ranks_are_target_when_every_position_listed():
    n = 4
    links = sd._build_sources(Random(0), n, target_positions=[1, 2, 3, 4])
    assert all(ln.domain == TARGET for ln in links)
    assert [ln.rank for ln in links] == [1, 2, 3, 4]
    assert links[2].url == f"https://{TARGET}/catalog/feature-3"


def test_build_sources_other_domains_drawn_from_pool():
    links = sd._build_sources(Random(7), 5, target_positions=[3])
    for ln in links:
        if ln.domain != TARGET:
            assert ln.domain in sd._OTHER_DOMAINS


def test_make_capture_preserves_unicode_query_and_engine():
    cap = _mk(0, query="проект 项目 🚀 best?", overview_present=False)
    assert cap.query == "проект 项目 🚀 best?"
    assert cap.engine == sd.ENGINE == "google"


def test_make_capture_lens_is_passed_through():
    for lens in ("general", "branded", "comparative"):
        cap = _mk(0, lens=lens, overview_present=False)
        assert cap.lens == lens


def test_make_capture_cited_true_link_ranks_align_with_rank_array():
    cap = _mk(0, lens="branded", in_sources=True, cited=True)
    assert cap.target_citation_ranks == [ln.rank for ln in cap.citations]
    assert cap.target_citation_ranks == [1, 2]
    assert all(ln.domain == TARGET for ln in cap.citations)
    assert cap.citations[0].url == f"https://{TARGET}/catalog/cit-1"


def test_make_capture_cited_true_single_citation_seed():
    cap = _mk(3, lens="branded", in_sources=True, cited=True)
    assert cap.target_citation_ranks == [1]
    assert len(cap.citations) == 1
    assert cap.citations[0].domain == TARGET


def test_make_capture_not_in_sources_sentiment_iff_brand_named():
    for seed in range(20):
        cap = _mk(seed, lens="branded", overview_present=True, in_sources=False)
        assert cap.target_source_ranks == []
        assert cap.target_citation_ranks == []
        assert cap.citations == []
        if cap.brand_in_answer_text:
            assert cap.sentiment in sd._SENTIMENTS_NEUTRAL
        else:
            assert cap.sentiment is None


def test_make_capture_in_sources_answer_text_mentions_brand():
    cap = _mk(1, lens="branded", in_sources=True, cited=True)
    assert cap.brand_in_answer_text is True
    assert cap.answer_text_md is not None
    assert "Example" in cap.answer_text_md


def test_make_capture_in_sources_ranks_within_bounds_many_seeds():
    from datetime import datetime as _dt, timezone as _tz
    at = _dt(2026, 1, 1, tzinfo=_tz.utc)
    for seed in range(25):
        cap = sd._make_capture(
            Random(seed), "q", "branded", at,
            overview_present=True, in_sources=True, cited=False,
            multi_rank=True, n_idx=1,
        )
        placed = sorted(ln.rank for ln in cap.sources if ln.domain == TARGET)
        assert placed == cap.target_source_ranks
        assert cap.target_source_ranks
        for rk in cap.target_source_ranks:
            assert 1 <= rk <= len(cap.sources)


@pytest.mark.parametrize("run_idx", [0, 1, 2, 3, 4])
def test_build_run_captures_branded_multi_rank_every_run(run_idx):
    caps = sd._build_run_captures(Random(20260618), run_idx, AT)
    branded = [c for c in caps if c.lens == "branded"]
    assert any(len(c.target_source_ranks) >= 2 for c in branded)


@pytest.mark.parametrize("run_idx", [0, 1, 2, 3, 4])
def test_build_run_captures_comparative_may_name_brand_but_never_sourced(run_idx):
    caps = sd._build_run_captures(Random(20260618), run_idx, AT)
    comparative = [c for c in caps if c.lens == "comparative"]
    for c in comparative:
        assert c.target_source_ranks == []
        assert c.target_citation_ranks == []
        if c.brand_in_answer_text:
            assert c.sentiment in sd._SENTIMENTS_NEUTRAL
        else:
            assert c.sentiment is None
    assert any(c.brand_in_answer_text for c in comparative)


@pytest.mark.parametrize("run_idx", [0, 1, 2, 3, 4])
def test_build_run_captures_captured_at_uniform_7min_stride(run_idx):
    from datetime import timedelta
    caps = sd._build_run_captures(Random(20260618), run_idx, AT)
    times = [c.captured_at for c in caps]
    assert times[0] == AT + timedelta(minutes=7)
    deltas = {(times[i] - times[i - 1]) for i in range(1, len(times))}
    assert deltas == {timedelta(minutes=7)}


def test_build_run_captures_has_overview_present_and_absent_rows():
    caps = sd._build_run_captures(Random(20260618), 2, AT)
    flags = {c.overview_present for c in caps}
    assert flags == {True, False}


def test_build_run_captures_general_only_last_is_forced_false():
    caps = sd._build_run_captures(Random(20260618), 4, AT)
    general = [c for c in caps if c.lens == "general"]
    assert general[-1].overview_present is False
    assert any(c.overview_present for c in general[:-1])


def test_seed_full_metric_rows_identical_across_two_dbs(tmp_path):
    p1 = tmp_path / "m1.db"
    p2 = tmp_path / "m2.db"
    sd.seed(str(p1), reset=True)
    sd.seed(str(p2), reset=True)

    cols = (
        "run_id, brand_id, engine, lens, n_queries, n_overviews, overview_coverage, "
        "n_in_sources, visibility_in_sources, n_cited, visibility_in_citations, "
        "avg_source_position, avg_citation_position"
    )

    def _metrics(db_path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                f"SELECT {cols} FROM metrics ORDER BY run_id, lens"
            ).fetchall()
        finally:
            conn.close()

    rows1 = _metrics(str(p1))
    rows2 = _metrics(str(p2))
    assert rows1 == rows2
    assert len(rows1) == 20


def test_seed_comparative_scope_zero_sources_zero_cited(tmp_path):
    p = tmp_path / "s.db"
    sd.seed(str(p), reset=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT n_overviews, n_in_sources, n_cited, visibility_in_sources, "
            "visibility_in_citations, avg_source_position, avg_citation_position "
            "FROM metrics WHERE lens = 'comparative' ORDER BY run_id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 5
    for r in rows:
        assert r["n_in_sources"] == 0
        assert r["n_cited"] == 0
        assert r["avg_source_position"] is None
        assert r["avg_citation_position"] is None
        if r["n_overviews"] > 0:
            assert r["visibility_in_sources"] == 0.0
            assert r["visibility_in_citations"] == 0.0
        else:
            assert r["visibility_in_sources"] is None
            assert r["visibility_in_citations"] is None


def test_seed_all_row_aggregates_match_lens_sums(tmp_path):
    p = tmp_path / "agg.db"
    out = sd.seed(str(p), reset=True)
    run_id = out["latest_run_id"]
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT lens, n_queries, n_overviews, n_in_sources, n_cited "
            "FROM metrics WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    by_lens = {r["lens"]: r for r in rows}
    lenses = ["general", "branded", "comparative"]
    for field in ("n_queries", "n_overviews", "n_in_sources", "n_cited"):
        assert by_lens["all"][field] == sum(by_lens[l][field] for l in lenses)
    assert by_lens["all"]["n_queries"] == 24


def test_seed_runs_have_distinct_increasing_run_at(tmp_path):
    p = tmp_path / "dates.db"
    sd.seed(str(p), reset=True)
    conn = sqlite3.connect(p)
    try:
        run_ats = [r[0] for r in conn.execute(
            "SELECT run_at FROM runs ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()
    assert len(run_ats) == 5
    assert run_ats == sorted(run_ats)
    assert len(set(run_ats)) == 5
    assert run_ats[0].startswith("2026-05-12")


def test_seed_all_runs_marked_done(tmp_path):
    p = tmp_path / "done.db"
    sd.seed(str(p), reset=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        runs = conn.execute(
            "SELECT status, n_queries, n_ok, n_failed FROM runs ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert len(runs) == 5
    for r in runs:
        assert r["status"] == "done"
        assert r["n_queries"] == 24
        assert r["n_ok"] == 24
        assert r["n_failed"] == 0


def test_seed_latest_all_metrics_matches_db_row(tmp_path):
    p = tmp_path / "latest.db"
    out = sd.seed(str(p), reset=True)
    summary = out["latest_all_metrics"]
    run_id = out["latest_run_id"]
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM metrics WHERE run_id = ? AND lens = 'all'", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    for field in (
        "n_queries", "n_overviews", "overview_coverage", "n_in_sources",
        "visibility_in_sources", "n_cited", "visibility_in_citations",
        "avg_source_position", "avg_citation_position",
    ):
        assert summary[field] == row[field], field


def test_seed_custom_seed_value_changes_data_but_keeps_counts(tmp_path):
    p_def = tmp_path / "def.db"
    p_alt = tmp_path / "alt.db"
    out_def = sd.seed(str(p_def), reset=True)
    out_alt = sd.seed(str(p_alt), reset=True, seed_value=999)

    assert out_def["counts"] == out_alt["counts"] == {
        "brands": 1, "runs": 5, "results": 120, "metrics": 20
    }

    def _content(db_path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                "SELECT overview_present, target_source_ranks_json, sentiment "
                "FROM results ORDER BY id"
            ).fetchall()
        finally:
            conn.close()

    assert _content(str(p_def)) != _content(str(p_alt))


def test_seed_reuse_same_path_without_reset_appends_more_runs(tmp_path):
    p = tmp_path / "reuse.db"
    sd.seed(str(p), reset=False)
    out2 = sd.seed(str(p), reset=False)
    assert out2["counts"]["brands"] == 1
    assert out2["counts"]["runs"] == 10
    assert out2["counts"]["results"] == 240
    assert out2["latest_run_id"] == 10


def test_seed_writes_lens_sentiment_rows_per_run(tmp_path):
    p = tmp_path / "ls.db"
    sd.seed(str(p), reset=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT run_id, lens, summary FROM lens_sentiment ORDER BY run_id, lens"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 5 * 4
    for r in rows:
        assert r["summary"]
    per_run = {}
    for r in rows:
        per_run.setdefault(r["run_id"], set()).add(r["lens"])
    for lenses in per_run.values():
        assert lenses == {"general", "branded", "comparative", "all"}


def test_seed_lens_sentiment_loadable_via_helper(tmp_path):
    from pipeline.db import get_conn, get_lens_sentiments

    p = tmp_path / "ls2.db"
    out = sd.seed(str(p), reset=True)
    run_id = out["latest_run_id"]
    conn = get_conn(str(p))
    try:
        got = get_lens_sentiments(conn, run_id)
    finally:
        conn.close()
    assert set(got) == {"general", "branded", "comparative", "all"}
    assert got["all"] == sd._LENS_SUMMARIES["all"]
    assert got["branded"] == sd._LENS_SUMMARIES["branded"]


def test_seed_lens_sentiment_deterministic_across_two_dbs(tmp_path):
    p1 = tmp_path / "ls_a.db"
    p2 = tmp_path / "ls_b.db"
    sd.seed(str(p1), reset=True)
    sd.seed(str(p2), reset=True)

    def _rows(db_path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                "SELECT run_id, lens, summary FROM lens_sentiment ORDER BY run_id, lens"
            ).fetchall()
        finally:
            conn.close()

    assert _rows(str(p1)) == _rows(str(p2))
