from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.aggregate import (
    _compute_scope,
    _row_citation_ranks,
    _row_in_sources,
    aggregate_run,
    compute_run_metrics,
    main,
)
from pipeline.db import create_run, get_conn, get_or_create_brand, init_db
from pipeline.ingest import insert_capture
from pipeline.schema import QueryCapture

REPO_ROOT = Path(__file__).resolve().parent.parent

_CAP_SEQ = itertools.count()


def _cap(
    *,
    lens: str = "general",
    overview: bool = True,
    source_ranks: list[int] | None = None,
    citation_ranks: list[int] | None = None,
) -> QueryCapture:
    source_ranks = source_ranks or []
    citation_ranks = citation_ranks or []
    sources = [
        {"rank": r, "url": f"https://example.com/{r}", "domain": "example.com"}
        for r in source_ranks
    ]
    citations = [
        {"rank": r, "url": f"https://example.com/c{r}", "domain": "example.com"}
        for r in citation_ranks
    ]
    return QueryCapture.model_validate(
        {
            "query": f"{lens}-q{next(_CAP_SEQ)}",
            "lens": lens,
            "engine": "google",
            "captured_at": "2026-06-18T00:00:00Z",
            "overview_present": overview,
            "sources": sources,
            "citations": citations,
            "target_source_ranks": source_ranks,
            "target_citation_ranks": citation_ranks,
            "brand_in_answer_text": bool(source_ranks),
            "sentiment": "ok" if (source_ranks or citation_ranks) else None,
        }
    )


def _fresh_run(db_path: str, caps: list[QueryCapture]) -> tuple[int, int]:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        for c in caps:
            insert_capture(conn, run_id, c)
        conn.commit()
    finally:
        conn.close()
    return run_id, brand_id


_PARSE_FNS = [
    ("source", _row_in_sources, "target_source_ranks_json"),
    ("citation", _row_citation_ranks, "target_citation_ranks_json"),
]


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, []),
        ("", []),
        ("[]", []),
        ("[1, 2]", [1, 2]),
        ("[3]", [3]),
        ("[1,,", []),
        ("{not json", []),
        ("{}", []),
        ("5", []),
        ("null", []),
        ('"x"', []),
        ("[2.0, 1.0]", [2, 1]),
    ],
)
def test_parse_helpers_all_branches(kind, fn, col, raw, expected):
    assert fn({col: raw}) == expected


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
def test_parse_helpers_zero_is_falsy_but_valid(kind, fn, col):
    assert fn({col: "[0, 2]"}) == [0, 2]


def test_parse_helpers_are_distinct_columns():
    row = {
        "target_source_ranks_json": "[1, 2]",
        "target_citation_ranks_json": "[9]",
    }
    assert _row_in_sources(row) == [1, 2]
    assert _row_citation_ranks(row) == [9]


def _row(overview, src="[]", cit="[]"):
    return {
        "overview_present": overview,
        "target_source_ranks_json": src,
        "target_citation_ranks_json": cit,
    }


def test_scope_empty_everything_none_or_zero():
    s = _compute_scope([])
    assert s["n_queries"] == 0
    assert s["n_overviews"] == 0
    assert s["overview_coverage"] is None
    assert s["n_in_sources"] == 0
    assert s["n_cited"] == 0
    assert s["visibility_in_sources"] is None
    assert s["visibility_in_citations"] is None
    assert s["avg_source_position"] is None
    assert s["avg_citation_position"] is None
    assert s["relative_citation"] is None


def test_scope_no_overview_rows_coverage_zero_visibility_none():
    rows = [_row(0), _row(0, src="[1]", cit="[1]")]
    s = _compute_scope(rows)
    assert s["n_queries"] == 2
    assert s["n_overviews"] == 0
    assert s["overview_coverage"] == pytest.approx(0.0)
    assert s["n_in_sources"] == 0
    assert s["n_cited"] == 0
    assert s["visibility_in_sources"] is None
    assert s["visibility_in_citations"] is None
    assert s["avg_source_position"] is None
    assert s["avg_citation_position"] is None


def test_scope_overview_present_stored_as_null_counts_as_zero():
    rows = [_row(1, src="[1]"), _row(None, src="[2]")]
    s = _compute_scope(rows)
    assert s["n_queries"] == 2
    assert s["n_overviews"] == 1
    assert s["n_in_sources"] == 1
    assert s["visibility_in_sources"] == pytest.approx(1.0)
    assert s["avg_source_position"] == pytest.approx(1.0)


def test_scope_n_in_sources_zero_visibility_zero_avg_none():
    rows = [_row(1), _row(1)]
    s = _compute_scope(rows)
    assert s["n_overviews"] == 2
    assert s["n_in_sources"] == 0
    assert s["visibility_in_sources"] == pytest.approx(0.0)
    assert s["avg_source_position"] is None
    assert s["n_cited"] == 0
    assert s["visibility_in_citations"] == pytest.approx(0.0)
    assert s["avg_citation_position"] is None


def test_scope_n_cited_zero_but_in_sources_positive():
    rows = [_row(1, src="[2]"), _row(1, src="[3]")]
    s = _compute_scope(rows)
    assert s["n_in_sources"] == 2
    assert s["visibility_in_sources"] == pytest.approx(1.0)
    assert s["avg_source_position"] == pytest.approx(2.5)
    assert s["n_cited"] == 0
    assert s["visibility_in_citations"] == pytest.approx(0.0)
    assert s["avg_citation_position"] is None


def test_scope_avg_uses_min_of_multi_ranks():
    rows = [
        _row(1, src="[4, 2]", cit="[3, 1]"),
        _row(1, src="[5]", cit="[6]"),
    ]
    s = _compute_scope(rows)
    assert s["avg_source_position"] == pytest.approx((2 + 5) / 2)
    assert s["avg_citation_position"] == pytest.approx((1 + 6) / 2)


def test_scope_funnel_relative_citation_conversion():
    rows = [
        _row(1, src="[3]", cit="[2]"),
        _row(1, src="[3]", cit="[]"),
    ]
    s = _compute_scope(rows)
    assert s["n_overviews"] == 2
    assert s["n_in_sources"] == 2
    assert s["n_cited"] == 1
    assert s["n_cited"] <= s["n_in_sources"] <= s["n_overviews"]
    assert s["visibility_in_sources"] == pytest.approx(1.0)
    assert s["visibility_in_citations"] == pytest.approx(0.5)
    assert s["avg_source_position"] == pytest.approx(3.0)
    assert s["avg_citation_position"] == pytest.approx(2.0)
    assert s["relative_citation"] == pytest.approx(0.5)
    assert 0.0 <= s["relative_citation"] <= 1.0


def test_scope_relative_citation_null_guard_when_no_sources():
    rows = [
        _row(1, src="[]", cit="[]"),
        _row(1, src="[]", cit="[]"),
    ]
    s = _compute_scope(rows)
    assert s["n_overviews"] == 2
    assert s["n_in_sources"] == 0
    assert s["n_cited"] == 0
    assert s["relative_citation"] is None
    assert s["visibility_in_sources"] == pytest.approx(0.0)
    assert s["visibility_in_citations"] == pytest.approx(0.0)


def test_compute_run_metrics_missing_run_raises(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        with pytest.raises(ValueError, match="run 999 not found"):
            compute_run_metrics(conn, 999)
    finally:
        conn.close()


def test_compute_run_metrics_zero_results_only_all_row(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()

    assert [r["lens"] for r in rows] == ["all"]
    all_row = rows[0]
    assert all_row["n_queries"] == 0
    assert all_row["overview_coverage"] is None
    assert all_row["visibility_in_sources"] is None
    assert all_row["visibility_in_citations"] is None
    assert all_row["avg_source_position"] is None
    assert all_row["avg_citation_position"] is None


def test_compute_run_metrics_all_row_is_first(empty_db_path):
    run_id, _ = _fresh_run(
        empty_db_path,
        [_cap(lens="branded"), _cap(lens="general")],
    )
    conn = get_conn(empty_db_path)
    try:
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()
    assert rows[0]["lens"] == "all"


def test_compute_run_metrics_documented_lens_order(empty_db_path):
    run_id, _ = _fresh_run(
        empty_db_path,
        [
            _cap(lens="comparative"),
            _cap(lens="branded"),
            _cap(lens="general"),
        ],
    )
    conn = get_conn(empty_db_path)
    try:
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()
    assert [r["lens"] for r in rows] == ["all", "general", "branded", "comparative"]


def test_compute_run_metrics_unexpected_lens_sorted_after_known(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        insert_capture(conn, run_id, _cap(lens="general"))
        for odd in ("zzz", "aaa"):
            conn.execute(
                """
                INSERT INTO results (
                    run_id, query, lens, captured_at, overview_present,
                    sources_json, citations_json,
                    target_source_ranks_json, target_citation_ranks_json,
                    brand_in_answer_text, sentiment
                ) VALUES (?, ?, ?, ?, 1, '[]', '[]', '[]', '[]', 0, NULL)
                """,
                (run_id, f"{odd}-q", odd, "2026-06-18T00:00:00Z"),
            )
        conn.commit()
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()

    assert [r["lens"] for r in rows] == ["all", "general", "aaa", "zzz"]


def test_compute_run_metrics_all_spans_every_lens(empty_db_path):
    run_id, _ = _fresh_run(
        empty_db_path,
        [
            _cap(lens="general", overview=True, source_ranks=[1]),
            _cap(lens="branded", overview=True, source_ranks=[]),
            _cap(lens="general", overview=False),
        ],
    )
    conn = get_conn(empty_db_path)
    try:
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()
    by_lens = {r["lens"]: r for r in rows}
    assert by_lens["all"]["n_queries"] == 3
    assert by_lens["all"]["n_overviews"] == 2
    assert by_lens["general"]["n_queries"] == 2
    assert by_lens["branded"]["n_queries"] == 1


def _metric_count(db_path: str, run_id: int) -> int:
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_aggregate_run_missing_run_raises(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        with pytest.raises(ValueError, match="run 4242 not found"):
            aggregate_run(conn, 4242)
    finally:
        conn.close()


def test_aggregate_run_persists_one_row_per_metric(empty_db_path):
    run_id, brand_id = _fresh_run(
        empty_db_path,
        [_cap(lens="general"), _cap(lens="branded"), _cap(lens="comparative")],
    )
    conn = get_conn(empty_db_path)
    try:
        summary = aggregate_run(conn, run_id)
    finally:
        conn.close()

    assert summary["run_id"] == run_id
    assert summary["brand_id"] == brand_id
    assert summary["engine"] == "google"
    assert [m["lens"] for m in summary["metrics"]] == [
        "all", "general", "branded", "comparative"
    ]
    assert _metric_count(empty_db_path, run_id) == len(summary["metrics"]) == 4


def test_aggregate_run_idempotent_no_duplicate_rows(empty_db_path):
    run_id, _ = _fresh_run(
        empty_db_path, [_cap(lens="general"), _cap(lens="branded")]
    )
    conn = get_conn(empty_db_path)
    try:
        first = aggregate_run(conn, run_id)
        n_after_first = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        second = aggregate_run(conn, run_id)
        n_after_second = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        lens_rows = conn.execute(
            "SELECT lens FROM metrics WHERE run_id = ? ORDER BY lens", (run_id,)
        ).fetchall()
    finally:
        conn.close()

    assert n_after_first == 3
    assert n_after_second == 3
    assert [m["lens"] for m in first["metrics"]] == [m["lens"] for m in second["metrics"]]
    lenses = [r["lens"] for r in lens_rows]
    assert sorted(lenses) == lenses
    assert len(set(lenses)) == len(lenses)


def test_aggregate_run_persisted_columns_equal_computed(empty_db_path):
    caps = [
        _cap(lens="general", overview=True, source_ranks=[2, 4], citation_ranks=[1]),
        _cap(lens="general", overview=True, source_ranks=[5], citation_ranks=[]),
        _cap(lens="general", overview=False),
        _cap(lens="branded", overview=True, source_ranks=[], citation_ranks=[]),
    ]
    run_id, brand_id = _fresh_run(empty_db_path, caps)

    conn = get_conn(empty_db_path)
    try:
        summary = aggregate_run(conn, run_id)
        persisted = conn.execute(
            """
            SELECT lens, brand_id, engine,
                   n_queries, n_overviews, overview_coverage,
                   n_in_sources, visibility_in_sources,
                   n_cited, visibility_in_citations,
                   avg_source_position, avg_citation_position,
                   relative_citation
            FROM metrics WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    persisted_by_lens = {row["lens"]: row for row in persisted}
    computed_by_lens = {m["lens"]: m for m in summary["metrics"]}
    assert set(persisted_by_lens) == set(computed_by_lens)

    numeric_cols = [
        "n_queries", "n_overviews", "overview_coverage",
        "n_in_sources", "visibility_in_sources",
        "n_cited", "visibility_in_citations",
        "avg_source_position", "avg_citation_position",
        "relative_citation",
    ]
    for lens, prow in persisted_by_lens.items():
        comp = computed_by_lens[lens]
        assert prow["brand_id"] == brand_id
        assert prow["engine"] == "google"
        for col in numeric_cols:
            pv, cv = prow[col], comp[col]
            if cv is None:
                assert pv is None, f"{lens}.{col}: expected NULL, got {pv!r}"
            else:
                assert pv == pytest.approx(cv), f"{lens}.{col}: {pv!r} != {cv!r}"

    branded = persisted_by_lens["branded"]
    assert branded["n_in_sources"] == 0
    assert branded["visibility_in_sources"] == pytest.approx(0.0)
    assert branded["avg_source_position"] is None
    assert branded["avg_citation_position"] is None
    assert branded["relative_citation"] is None
    assert "relative_citation" in computed_by_lens["all"]
    assert computed_by_lens["all"]["relative_citation"] == pytest.approx(0.5)
    assert persisted_by_lens["all"]["relative_citation"] == pytest.approx(0.5)


def test_aggregate_run_on_seeded_db_matches_recompute(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        run_id = conn.execute("SELECT MIN(id) AS m FROM runs").fetchone()["m"]
        before = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        computed = compute_run_metrics(conn, run_id)
        summary = aggregate_run(conn, run_id)
        after = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert before == after == len(computed)
    assert [m["lens"] for m in summary["metrics"]] == [m["lens"] for m in computed]
    for a, b in zip(summary["metrics"], computed):
        assert a == b


def test_main_valid_returns_zero_and_prints_json(empty_db_path, capsys):
    run_id, brand_id = _fresh_run(
        empty_db_path, [_cap(lens="general"), _cap(lens="branded")]
    )
    rc = main(["--run-id", str(run_id), "--db", empty_db_path])
    assert rc == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["run_id"] == run_id
    assert payload["brand_id"] == brand_id
    assert payload["engine"] == "google"
    assert [m["lens"] for m in payload["metrics"]] == ["all", "general", "branded"]

    assert _metric_count(empty_db_path, run_id) == 3


def test_main_missing_run_returns_one_and_logs_stderr(empty_db_path, capsys):
    rc = main(["--run-id", "777", "--db", empty_db_path])
    assert rc == 1

    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "aggregate: run 777 not found" in captured.err


def test_main_requires_run_id_argparse(empty_db_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--db", empty_db_path])
    assert exc.value.code == 2
    assert "run-id" in capsys.readouterr().err


def test_main_creates_db_when_absent(tmp_path, capsys):
    fresh = tmp_path / "brand_new.db"
    assert not fresh.exists()
    rc = main(["--run-id", "1", "--db", str(fresh)])
    assert rc == 1
    assert fresh.exists()
    assert "run 1 not found" in capsys.readouterr().err


@pytest.mark.slow
def test_main_subprocess_end_to_end(empty_db_path):
    run_id, _ = _fresh_run(empty_db_path, [_cap(lens="general")])
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.aggregate",
         "--run-id", str(run_id), "--db", empty_db_path],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["run_id"] == run_id
    assert payload["metrics"][0]["lens"] == "all"


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
@pytest.mark.parametrize(
    "raw, exc",
    [
        ('["a"]', ValueError),
        ("[null]", TypeError),
        ("[[1]]", TypeError),
        ("[{}]", TypeError),
        ("[1, null]", TypeError),
    ],
)
def test_parse_helpers_wellformed_but_noncoercible_list_raises(kind, fn, col, raw, exc):
    with pytest.raises(exc):
        fn({col: raw})


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
def test_parse_helpers_json_bools_coerce_to_ints(kind, fn, col):
    assert fn({col: "[true, false, true]"}) == [1, 0, 1]


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
def test_parse_helpers_floats_truncate_toward_zero(kind, fn, col):
    assert fn({col: "[1.9, 2.5, -1.9]"}) == [1, 2, -1]


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
def test_parse_helpers_whitespace_padded_json_ok(kind, fn, col):
    assert fn({col: "  \n [1, 2] \t "}) == [1, 2]


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
def test_parse_helpers_negative_ints_survive(kind, fn, col):
    assert fn({col: "[-3, -1, -2]"}) == [-3, -1, -2]


@pytest.mark.parametrize("kind, fn, col", _PARSE_FNS, ids=[p[0] for p in _PARSE_FNS])
def test_parse_helpers_json_false_literal_is_falsy_but_decodes(kind, fn, col):
    assert fn({col: "false"}) == []


def test_scope_overview_present_literal_zero_int_excluded():
    rows = [_row(1, src="[1]"), _row(0, src="[2]")]
    s = _compute_scope(rows)
    assert s["n_overviews"] == 1
    assert s["n_in_sources"] == 1
    assert s["avg_source_position"] == pytest.approx(1.0)


def test_scope_overview_present_python_bool_true_counts():
    s = _compute_scope([_row(True, src="[2]")])
    assert s["n_overviews"] == 1
    assert s["visibility_in_sources"] == pytest.approx(1.0)


def test_scope_negative_ranks_min_picks_most_negative():
    rows = [_row(1, src="[-3, -1]", cit="[-5, -2]")]
    s = _compute_scope(rows)
    assert s["avg_source_position"] == pytest.approx(-3.0)
    assert s["avg_citation_position"] == pytest.approx(-5.0)


def test_scope_single_overview_no_channels_all_position_none():
    s = _compute_scope([_row(1)])
    assert s["n_overviews"] == 1
    assert s["visibility_in_sources"] == pytest.approx(0.0)
    assert s["visibility_in_citations"] == pytest.approx(0.0)
    assert s["avg_source_position"] is None
    assert s["avg_citation_position"] is None


def test_compute_run_metrics_is_pure_does_not_persist(empty_db_path):
    run_id, _ = _fresh_run(empty_db_path, [_cap(lens="general")])
    conn = get_conn(empty_db_path)
    try:
        compute_run_metrics(conn, run_id)
        compute_run_metrics(conn, run_id)
        n_metrics = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_metrics == 0


def test_compute_run_metrics_only_unexpected_lenses_sorted(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        for odd in ("mmm", "aaa", "zzz"):
            conn.execute(
                """
                INSERT INTO results (
                    run_id, query, lens, captured_at, overview_present,
                    sources_json, citations_json,
                    target_source_ranks_json, target_citation_ranks_json,
                    brand_in_answer_text, sentiment
                ) VALUES (?, ?, ?, ?, 1, '[]', '[]', '[]', '[]', 0, NULL)
                """,
                (run_id, f"{odd}-q", odd, "2026-06-18T00:00:00Z"),
            )
        conn.commit()
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()
    assert [r["lens"] for r in rows] == ["all", "aaa", "mmm", "zzz"]


def test_compute_run_metrics_empty_string_lens_sorts_first_among_unexpected(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        insert_capture(conn, run_id, _cap(lens="general"))
        for odd in ("bbb", ""):
            conn.execute(
                """
                INSERT INTO results (
                    run_id, query, lens, captured_at, overview_present,
                    sources_json, citations_json,
                    target_source_ranks_json, target_citation_ranks_json,
                    brand_in_answer_text, sentiment
                ) VALUES (?, ?, ?, ?, 1, '[]', '[]', '[]', '[]', 0, NULL)
                """,
                (run_id, f"{odd or 'empty'}-q", odd, "2026-06-18T00:00:00Z"),
            )
        conn.commit()
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()
    assert [r["lens"] for r in rows] == ["all", "general", "", "bbb"]


def test_compute_run_metrics_partial_known_lenses_preserve_order(empty_db_path):
    run_id, _ = _fresh_run(
        empty_db_path,
        [_cap(lens="comparative"), _cap(lens="general")],
    )
    conn = get_conn(empty_db_path)
    try:
        rows = compute_run_metrics(conn, run_id)
    finally:
        conn.close()
    assert [r["lens"] for r in rows] == ["all", "general", "comparative"]


def test_aggregate_run_writes_valid_iso_computed_at(empty_db_path):
    from datetime import datetime

    run_id, _ = _fresh_run(empty_db_path, [_cap(lens="general"), _cap(lens="branded")])
    conn = get_conn(empty_db_path)
    try:
        aggregate_run(conn, run_id)
        stamps = [
            r["computed_at"]
            for r in conn.execute(
                "SELECT computed_at FROM metrics WHERE run_id = ?", (run_id,)
            ).fetchall()
        ]
    finally:
        conn.close()
    assert len(stamps) == 3
    assert len(set(stamps)) == 1
    datetime.fromisoformat(stamps[0])


def test_aggregate_run_identity_taken_from_run_row_not_results(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        b1 = get_or_create_brand(conn, "Example", "example.com")
        b2 = get_or_create_brand(conn, "Globex", "globex.com")
        assert b1 != b2
        run_id = create_run(conn, b2, "perplexity")
        insert_capture(conn, run_id, _cap(lens="general"))
        conn.commit()
        summary = aggregate_run(conn, run_id)
        prow = conn.execute(
            "SELECT brand_id, engine FROM metrics WHERE run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    assert summary["brand_id"] == b2
    assert summary["engine"] == "perplexity"
    assert prow["brand_id"] == b2
    assert prow["engine"] == "perplexity"


def test_aggregate_run_idempotent_across_fresh_connection(empty_db_path):
    run_id, _ = _fresh_run(
        empty_db_path, [_cap(lens="general"), _cap(lens="branded")]
    )
    c1 = get_conn(empty_db_path)
    try:
        aggregate_run(c1, run_id)
    finally:
        c1.close()
    c2 = get_conn(empty_db_path)
    try:
        aggregate_run(c2, run_id)
        n = c2.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        lenses = [
            r["lens"]
            for r in c2.execute(
                "SELECT lens FROM metrics WHERE run_id = ?", (run_id,)
            ).fetchall()
        ]
    finally:
        c2.close()
    assert n == 3
    assert len(set(lenses)) == len(lenses) == 3


def test_aggregate_run_seeded_recompute_changes_only_timestamp(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        run_id = conn.execute("SELECT MIN(id) AS m FROM runs").fetchone()["m"]
        cols = (
            "lens, n_queries, n_overviews, overview_coverage, n_in_sources, "
            "visibility_in_sources, n_cited, visibility_in_citations, "
            "avg_source_position, avg_citation_position"
        )
        before = {
            r["lens"]: tuple(r[c] for c in cols.split(", "))
            for r in conn.execute(
                f"SELECT {cols} FROM metrics WHERE run_id = ?", (run_id,)
            ).fetchall()
        }
        aggregate_run(conn, run_id)
        after = {
            r["lens"]: tuple(r[c] for c in cols.split(", "))
            for r in conn.execute(
                f"SELECT {cols} FROM metrics WHERE run_id = ?", (run_id,)
            ).fetchall()
        }
    finally:
        conn.close()
    assert before == after


def test_main_run_id_zero_is_present_not_missing(empty_db_path, capsys):
    rc = main(["--run-id", "0", "--db", empty_db_path])
    assert rc == 1
    err = capsys.readouterr().err
    assert "run 0 not found" in err


def test_main_unicode_round_trips_via_ensure_ascii_false(empty_db_path, capsys):
    conn = get_conn(empty_db_path)
    try:
        brand_id = get_or_create_brand(conn, "Экзампл", "example.com")
        run_id = create_run(conn, brand_id, "движок_ИИ")
        insert_capture(conn, run_id, _cap(lens="general"))
        conn.commit()
    finally:
        conn.close()

    rc = main(["--run-id", str(run_id), "--db", empty_db_path])
    assert rc == 0
    raw_out = capsys.readouterr().out
    assert "движок_ИИ" in raw_out
    assert "\\u" not in raw_out
    assert json.loads(raw_out)["engine"] == "движок_ИИ"


def test_main_default_db_is_data_aeo_db_without_running():
    import argparse

    parser = argparse.ArgumentParser(prog="pipeline.aggregate")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--db", default="data/aeo.db")
    ns = parser.parse_args(["--run-id", "1"])
    assert ns.db == "data/aeo.db"
    import pipeline.aggregate as agg

    src = Path(agg.__file__).read_text(encoding="utf-8")
    assert '"data/aeo.db"' in src


def test_main_returns_int_not_none(empty_db_path, capsys):
    run_id, _ = _fresh_run(empty_db_path, [_cap(lens="general")])
    rc = main(["--run-id", str(run_id), "--db", empty_db_path])
    capsys.readouterr()
    assert isinstance(rc, int) and rc == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
