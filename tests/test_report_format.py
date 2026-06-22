from __future__ import annotations

import sqlite3

import pytest

from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    init_db,
    update_run_counts,
)
from report import generate as g
from report.generate import (
    BAD,
    GOOD,
    INK_DIM,
    INK_FAINT,
    LensMetrics,
    ReportData,
    _completed_runs,
    _dec,
    _delta_num,
    _delta_pct,
    _fmt_date,
    _fmt_dt,
    _load_metrics_for_run,
    _load_sentiments,
    _metrics_row_to_obj,
    _num,
    _pct,
    _resolve_brand_id,
    lens_label,
    load_report_data,
)
from report.i18n import Translator

ENGINE = "google"


@pytest.fixture
def t_en() -> Translator:
    return Translator("en")


@pytest.fixture
def t_ru() -> Translator:
    return Translator("ru")


_METRIC_COLS = (
    "run_id",
    "brand_id",
    "engine",
    "lens",
    "n_queries",
    "n_overviews",
    "overview_coverage",
    "n_in_sources",
    "visibility_in_sources",
    "n_cited",
    "visibility_in_citations",
    "avg_source_position",
    "avg_citation_position",
    "relative_citation",
    "computed_at",
)


def _insert_metric(conn: sqlite3.Connection, **kw) -> None:
    defaults = {
        "engine": ENGINE,
        "lens": "all",
        "n_queries": 10,
        "n_overviews": 8,
        "overview_coverage": 0.8,
        "n_in_sources": 4,
        "visibility_in_sources": 0.5,
        "n_cited": 2,
        "visibility_in_citations": 0.25,
        "avg_source_position": 2.5,
        "avg_citation_position": 1.5,
        "relative_citation": 0.5,
        "computed_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(kw)
    cols = ", ".join(_METRIC_COLS)
    placeholders = ", ".join("?" for _ in _METRIC_COLS)
    conn.execute(
        f"INSERT INTO metrics ({cols}) VALUES ({placeholders})",
        tuple(defaults[c] for c in _METRIC_COLS),
    )


_RESULT_COLS = (
    "run_id",
    "query",
    "lens",
    "captured_at",
    "answer_text_md",
    "screenshot_path",
    "overview_present",
    "sources_json",
    "citations_json",
    "target_source_ranks_json",
    "target_citation_ranks_json",
    "brand_in_answer_text",
    "sentiment",
)


def _insert_result(conn: sqlite3.Connection, **kw) -> None:
    defaults = {
        "query": "q",
        "lens": "general",
        "captured_at": "2026-06-01T00:00:00Z",
        "answer_text_md": None,
        "screenshot_path": None,
        "overview_present": 1,
        "sources_json": "[]",
        "citations_json": "[]",
        "target_source_ranks_json": "[]",
        "target_citation_ranks_json": "[]",
        "brand_in_answer_text": 0,
        "sentiment": None,
    }
    defaults.update(kw)
    cols = ", ".join(_RESULT_COLS)
    placeholders = ", ".join("?" for _ in _RESULT_COLS)
    conn.execute(
        f"INSERT INTO results ({cols}) VALUES ({placeholders})",
        tuple(defaults[c] for c in _RESULT_COLS),
    )


def test_lens_label_all_uses_all_queries(t_en):
    assert lens_label(t_en, "all") == t_en.t("report.all_queries") == "All queries"


def test_lens_label_known_lens_localized(t_en, t_ru):
    assert lens_label(t_en, "general") == t_en.t("lens.general") == "General"
    assert lens_label(t_ru, "branded") == t_ru.t("lens.branded") == "Брендовые"


def test_lens_label_unknown_returns_verbatim(t_en):
    assert not t_en.has("lens.weird")
    assert lens_label(t_en, "weird") == "weird"


def test_dec_en_unchanged():
    assert _dec("1.5", "en") == "1.5"


def test_dec_ru_swaps_dot_for_comma():
    assert _dec("1.5", "ru") == "1,5"


def test_dec_unknown_lang_unchanged():
    assert _dec("3.14", "de") == "3.14"


def test_pct_none_is_dash():
    assert _pct(None) == "—"


def test_pct_half_is_50():
    assert _pct(0.5) == "50%"


def test_pct_one_is_100():
    assert _pct(1.0) == "100%"


def test_pct_rounds_to_whole_number():
    assert _pct(0.756) == "76%"


def test_pct_ru_whole_number_has_no_separator():
    assert _pct(0.5, "ru") == "50%"


def test_num_none_is_dash():
    assert _num(None) == "—"


def test_num_default_one_digit():
    assert _num(3.5) == "3.5"


def test_num_ru_decimal_comma():
    assert _num(3.5, lang="ru") == "3,5"


def test_num_zero_digits_rounds():
    assert _num(3.5, digits=0) == "4"
    assert _num(2.4, digits=0) == "2"


def test_num_two_digits():
    assert _num(2.345, digits=2) == "2.35"


def test_fmt_dt_none_is_dash():
    assert _fmt_dt(None) == "—"


def test_fmt_dt_empty_string_is_dash():
    assert _fmt_dt("") == "—"


def test_fmt_dt_valid_iso_with_z():
    assert _fmt_dt("2026-06-18T20:15:30Z") == "18.06.2026 20:15"


def test_fmt_dt_valid_iso_with_offset():
    assert _fmt_dt("2026-06-18T20:15:30+00:00") == "18.06.2026 20:15"


def test_fmt_dt_unparseable_returns_verbatim():
    assert _fmt_dt("not-a-date") == "not-a-date"


def test_fmt_date_none_is_dash():
    assert _fmt_date(None) == "—"


def test_fmt_date_empty_string_is_dash():
    assert _fmt_date("") == "—"


def test_fmt_date_valid_iso():
    assert _fmt_date("2026-06-18T20:15:30Z") == "18.06.2026"


def test_fmt_date_unparseable_returns_verbatim():
    assert _fmt_date("garbage") == "garbage"


def test_delta_pct_both_none_is_dash(t_en):
    d = _delta_pct(t_en, None, None)
    assert d.text == t_en.t("common.dash") == "—"
    assert d.color == INK_FAINT
    assert d.arrow == ""


def test_delta_pct_prev_none_is_new(t_en):
    d = _delta_pct(t_en, 0.5, None)
    assert d.text == t_en.t("report.delta_new") == "new"
    assert d.color == INK_DIM
    assert d.arrow == ""


def test_delta_pct_cur_none_is_no_data(t_en):
    d = _delta_pct(t_en, None, 0.5)
    assert d.text == t_en.t("report.delta_no_data") == "no data"
    assert d.color == INK_DIM
    assert d.arrow == ""


def test_delta_pct_below_half_pp_is_zero(t_en):
    d = _delta_pct(t_en, 0.502, 0.500)
    assert d.text == t_en.t("report.delta_zero_pp") == "0 pp"
    assert d.color == INK_DIM
    assert d.arrow == "▬"


def test_delta_pct_improved_higher_is_better(t_en):
    d = _delta_pct(t_en, 0.70, 0.50, higher_is_better=True)
    assert d.color == GOOD
    assert d.arrow == "▲"
    assert d.text.startswith("+")
    assert d.text == "+20 pp"


def test_delta_pct_worsened_higher_is_better(t_en):
    d = _delta_pct(t_en, 0.30, 0.50, higher_is_better=True)
    assert d.color == BAD
    assert d.arrow == "▼"
    assert d.text == "−20 pp"


def test_delta_pct_lower_is_better_drop_is_good(t_en):
    d = _delta_pct(t_en, 0.30, 0.50, higher_is_better=False)
    assert d.color == GOOD
    assert d.arrow == "▼"
    assert d.text == "−20 pp"


def test_delta_pct_lower_is_better_rise_is_bad(t_en):
    d = _delta_pct(t_en, 0.70, 0.50, higher_is_better=False)
    assert d.color == BAD
    assert d.arrow == "▲"
    assert d.text == "+20 pp"


def test_delta_pct_ru_suffix(t_ru):
    d = _delta_pct(t_ru, 0.70, 0.50, higher_is_better=True)
    assert d.text == "+20 пп"


def test_delta_num_both_none_is_dash(t_en):
    d = _delta_num(t_en, None, None, higher_is_better=False)
    assert d.text == t_en.t("common.dash")
    assert d.color == INK_FAINT
    assert d.arrow == ""


def test_delta_num_prev_none_is_new(t_en):
    d = _delta_num(t_en, 2.0, None, higher_is_better=False)
    assert d.text == t_en.t("report.delta_new")
    assert d.color == INK_DIM
    assert d.arrow == ""


def test_delta_num_cur_none_is_no_data(t_en):
    d = _delta_num(t_en, None, 2.0, higher_is_better=False)
    assert d.text == t_en.t("report.delta_no_data")
    assert d.color == INK_DIM
    assert d.arrow == ""


def test_delta_num_below_threshold_is_zero(t_en):
    d = _delta_num(t_en, 2.34, 2.30, higher_is_better=False, digits=1)
    assert d.text == t_en.t("report.delta_zero") == "0"
    assert d.color == INK_DIM
    assert d.arrow == "▬"


def test_delta_num_position_improved_lower_is_better(t_en):
    d = _delta_num(t_en, 1.5, 2.5, higher_is_better=False, digits=1)
    assert d.color == GOOD
    assert d.arrow == "▼"
    assert d.text == "−1.0"


def test_delta_num_position_worsened_lower_is_better(t_en):
    d = _delta_num(t_en, 3.5, 2.5, higher_is_better=False, digits=1)
    assert d.color == BAD
    assert d.arrow == "▲"
    assert d.text == "+1.0"


def test_delta_num_higher_is_better_branch(t_en):
    d = _delta_num(t_en, 3.0, 2.0, higher_is_better=True, digits=1)
    assert d.color == GOOD
    assert d.arrow == "▲"
    assert d.text == "+1.0"


def test_delta_num_ru_decimal_comma(t_ru):
    d = _delta_num(t_ru, 1.3, 2.5, higher_is_better=False, digits=1)
    assert d.text == "−1,2"


def test_delta_num_digits_zero_threshold(t_en):
    d = _delta_num(t_en, 3.0, 3.4, higher_is_better=False, digits=0)
    assert d.text == t_en.t("report.delta_zero")
    assert d.arrow == "▬"
    d2 = _delta_num(t_en, 3.0, 4.0, higher_is_better=False, digits=0)
    assert d2.text == "−1"
    assert d2.color == GOOD


def test_metrics_row_to_obj_coerces_counts_and_keeps_none_rates(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        _insert_metric(
            conn,
            run_id=rid,
            brand_id=bid,
            lens="all",
            n_queries=None,
            n_overviews="7",
            overview_coverage=None,
            n_in_sources="0",
            visibility_in_sources=None,
            n_cited=0,
            visibility_in_citations=None,
            avg_source_position=None,
            avg_citation_position=None,
            relative_citation=None,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM metrics WHERE run_id = ?", (rid,)
        ).fetchone()
        lm = _metrics_row_to_obj(row)
        assert isinstance(lm, LensMetrics)
        assert lm.lens == "all"
        assert lm.n_queries == 0 and isinstance(lm.n_queries, int)
        assert lm.n_overviews == 7
        assert lm.n_in_sources == 0
        assert lm.n_cited == 0
        assert lm.overview_coverage is None
        assert lm.visibility_in_sources is None
        assert lm.visibility_in_citations is None
        assert lm.avg_source_position is None
        assert lm.avg_citation_position is None
        assert lm.relative_citation is None
    finally:
        conn.close()


def test_load_metrics_for_run_maps_lens_to_object(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        _insert_metric(conn, run_id=rid, brand_id=bid, lens="all", overview_coverage=0.8)
        _insert_metric(conn, run_id=rid, brand_id=bid, lens="general", overview_coverage=0.9)
        _insert_metric(conn, run_id=rid, brand_id=bid, lens="branded", overview_coverage=0.7)
        conn.commit()
        out = _load_metrics_for_run(conn, rid)
        assert set(out.keys()) == {"all", "general", "branded"}
        assert all(isinstance(v, LensMetrics) for v in out.values())
        assert out["general"].overview_coverage == pytest.approx(0.9)
        assert out["all"].overview_coverage == pytest.approx(0.8)
    finally:
        conn.close()


def test_load_metrics_for_run_empty_when_no_rows(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        assert _load_metrics_for_run(conn, 999) == {}
    finally:
        conn.close()


def test_resolve_brand_id_exact_match(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        bid = _resolve_brand_id(conn, "Example", "https://www.example.com/foo")
        assert bid == 1
    finally:
        conn.close()


def test_resolve_brand_id_wrong_domain_raises_with_known_domains(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        with pytest.raises(ValueError, match="example.com"):
            _resolve_brand_id(conn, "Example", "totally-different.example")
    finally:
        conn.close()


def test_resolve_brand_id_unknown_name_is_none(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        assert _resolve_brand_id(conn, "NoSuchBrand", "example.com") is None
    finally:
        conn.close()


def test_resolve_brand_id_same_name_different_domain_no_arbitrary_pick(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        first = get_or_create_brand(conn, "Dup", "one.example")
        second = get_or_create_brand(conn, "Dup", "two.example")
        conn.commit()
        assert second > first
        with pytest.raises(ValueError) as exc:
            _resolve_brand_id(conn, "Dup", "mismatch.example")
        msg = str(exc.value)
        assert "one.example" in msg and "two.example" in msg
        assert _resolve_brand_id(conn, "Dup", "two.example") == second
        assert _resolve_brand_id(conn, "Dup", "one.example") == first
    finally:
        conn.close()


def test_completed_runs_only_runs_with_metrics_newest_first(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        runs = _completed_runs(conn, 1, ENGINE)
        assert len(runs) == 5
        assert all(isinstance(r, sqlite3.Row) for r in runs)
        run_ats = [r["run_at"] for r in runs]
        assert run_ats == sorted(run_ats, reverse=True)
        assert run_ats[0] == "2026-06-09T09:00:00+00:00"
    finally:
        conn.close()


def test_completed_runs_excludes_runs_without_metrics(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        with_metrics = create_run(conn, bid, ENGINE)
        without_metrics = create_run(conn, bid, ENGINE)  # noqa: F841 — intentionally bare
        update_run_counts(conn, with_metrics, status="done")
        update_run_counts(conn, without_metrics, status="done")
        _insert_metric(conn, run_id=with_metrics, brand_id=bid, lens="all")
        conn.commit()
        runs = _completed_runs(conn, bid, ENGINE)
        ids = [int(r["id"]) for r in runs]
        assert ids == [with_metrics]
    finally:
        conn.close()


def test_completed_runs_excludes_non_done_status(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        done_run = create_run(conn, bid, ENGINE)
        running_run = create_run(conn, bid, ENGINE)
        failed_run = create_run(conn, bid, ENGINE)
        update_run_counts(conn, done_run, status="done")
        update_run_counts(conn, running_run, status="running")
        update_run_counts(conn, failed_run, status="failed")
        for rid in (done_run, running_run, failed_run):
            _insert_metric(conn, run_id=rid, brand_id=bid, lens="all")
        conn.commit()
        runs = _completed_runs(conn, bid, ENGINE)
        ids = [int(r["id"]) for r in runs]
        assert ids == [done_run]
        assert all(r["status"] == "done" for r in runs)
    finally:
        conn.close()


def test_completed_runs_wrong_engine_is_empty(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        assert _completed_runs(conn, 1, "bing_copilot") == []
    finally:
        conn.close()


def test_completed_runs_tie_break_by_id_desc(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        r1 = create_run(conn, bid, ENGINE)
        r2 = create_run(conn, bid, ENGINE)
        same = "2026-06-01T00:00:00+00:00"
        conn.execute("UPDATE runs SET run_at = ? WHERE id IN (?, ?)", (same, r1, r2))
        update_run_counts(conn, r1, status="done")
        update_run_counts(conn, r2, status="done")
        _insert_metric(conn, run_id=r1, brand_id=bid, lens="all")
        _insert_metric(conn, run_id=r2, brand_id=bid, lens="all")
        conn.commit()
        runs = _completed_runs(conn, bid, ENGINE)
        assert [int(r["id"]) for r in runs] == [r2, r1]
    finally:
        conn.close()


def test_load_sentiments_groups_by_lens_newest_first(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        _insert_result(conn, run_id=rid, lens="general", query="old",
                       captured_at="2026-06-01T08:00:00Z", sentiment="oldest")
        _insert_result(conn, run_id=rid, lens="general", query="mid",
                       captured_at="2026-06-01T10:00:00Z", sentiment="middle")
        _insert_result(conn, run_id=rid, lens="general", query="new",
                       captured_at="2026-06-01T12:00:00Z", sentiment="newest")
        _insert_result(conn, run_id=rid, lens="branded", query="b",
                       captured_at="2026-06-01T09:00:00Z", sentiment="brand phrase")
        conn.commit()
        out = _load_sentiments(conn, rid)
        assert set(out.keys()) == {"general", "branded"}
        assert [ph for _q, ph in out["general"]] == ["newest", "middle", "oldest"]
        assert out["general"][0] == ("new", "newest")
        assert out["branded"] == [("b", "brand phrase")]
    finally:
        conn.close()


def test_load_sentiments_dedups_identical_phrase_within_lens(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        _insert_result(conn, run_id=rid, lens="general", query="q1",
                       captured_at="2026-06-01T12:00:00Z", sentiment="same phrase")
        _insert_result(conn, run_id=rid, lens="general", query="q2",
                       captured_at="2026-06-01T11:00:00Z", sentiment="same phrase")
        _insert_result(conn, run_id=rid, lens="general", query="q3",
                       captured_at="2026-06-01T10:00:00Z", sentiment="other phrase")
        conn.commit()
        out = _load_sentiments(conn, rid)
        phrases = [ph for _q, ph in out["general"]]
        assert phrases == ["same phrase", "other phrase"]
        assert out["general"][0][0] == "q1"
    finally:
        conn.close()


def test_load_sentiments_caps_at_per_lens_default_four(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        for i in range(6):
            _insert_result(
                conn, run_id=rid, lens="general", query=f"q{i}",
                captured_at=f"2026-06-01T{10 + i:02d}:00:00Z",
                sentiment=f"phrase {i}",
            )
        conn.commit()
        out = _load_sentiments(conn, rid)
        assert len(out["general"]) == 4
        assert [q for q, _ph in out["general"]] == ["q5", "q4", "q3", "q2"]
    finally:
        conn.close()


def test_load_sentiments_custom_per_lens(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        for i in range(5):
            _insert_result(
                conn, run_id=rid, lens="general", query=f"q{i}",
                captured_at=f"2026-06-01T{10 + i:02d}:00:00Z",
                sentiment=f"phrase {i}",
            )
        conn.commit()
        out = _load_sentiments(conn, rid, per_lens=2)
        assert len(out["general"]) == 2
    finally:
        conn.close()


def test_load_sentiments_skips_null_and_empty(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        _insert_result(conn, run_id=rid, lens="general", query="null", sentiment=None)
        _insert_result(conn, run_id=rid, lens="general", query="blank", sentiment="   ")
        _insert_result(conn, run_id=rid, lens="general", query="good",
                       captured_at="2026-06-01T12:00:00Z", sentiment="real phrase")
        conn.commit()
        out = _load_sentiments(conn, rid)
        assert out == {"general": [("good", "real phrase")]}
    finally:
        conn.close()


def test_load_sentiments_empty_run_is_empty_dict(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        assert _load_sentiments(conn, 12345) == {}
    finally:
        conn.close()


def test_load_sentiments_strips_padding_on_kept_phrase(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        _insert_result(conn, run_id=rid, lens="general", query="  q  ",
                       captured_at="2026-06-01T12:00:00Z",
                       sentiment="   padded phrase   ")
        conn.commit()
        out = _load_sentiments(conn, rid)
        assert out == {"general": [("q", "padded phrase")]}
    finally:
        conn.close()


def test_load_sentiments_tab_only_passes_sql_but_strips_empty(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        rid = create_run(conn, bid, ENGINE)
        whitespace_only = "\t\t\t"
        sql_keeps, py_empties = conn.execute(
            "SELECT TRIM(?) != '', ?", (whitespace_only, whitespace_only)
        ).fetchone()
        assert bool(sql_keeps) is True
        assert whitespace_only.strip() == ""

        _insert_result(conn, run_id=rid, lens="general", query="ws",
                       captured_at="2026-06-01T13:00:00Z", sentiment=whitespace_only)
        _insert_result(conn, run_id=rid, lens="general", query="real",
                       captured_at="2026-06-01T12:00:00Z", sentiment="kept phrase")
        _insert_result(conn, run_id=rid, lens="branded", query="ws2",
                       captured_at="2026-06-01T11:00:00Z", sentiment="\n\n")
        conn.commit()

        out = _load_sentiments(conn, rid)
        assert out == {"general": [("real", "kept phrase")]}
        assert "branded" not in out
        assert isinstance(out, dict)
        assert all(isinstance(snip, tuple) for snip in out["general"])
    finally:
        conn.close()


def test_lensmetrics_construction_holds_fields():
    lm = LensMetrics(
        lens="general",
        n_queries=10,
        n_overviews=8,
        overview_coverage=0.8,
        n_in_sources=4,
        visibility_in_sources=0.5,
        n_cited=2,
        visibility_in_citations=0.25,
        avg_source_position=2.5,
        avg_citation_position=1.5,
        relative_citation=0.5,
    )
    assert lm.lens == "general"
    assert lm.n_overviews == 8
    assert lm.avg_citation_position == 1.5
    assert lm.relative_citation == 0.5


def test_reportdata_history_defaults_to_empty_list():
    rd = ReportData(
        brand_name="Example",
        brand_domain="example.com",
        engine=ENGINE,
        period="today",
        run_id=1,
        run_at="2026-06-01T00:00:00Z",
        prev_run_id=None,
        prev_run_at=None,
        metrics={},
        prev_metrics={},
        sentiments={},
    )
    assert rd.history == []
    rd2 = ReportData(
        brand_name="B", brand_domain="b.com", engine=ENGINE, period="all",
        run_id=2, run_at="x", prev_run_id=None, prev_run_at=None,
        metrics={}, prev_metrics={}, sentiments={},
    )
    rd.history.append(("x", {}))
    assert rd2.history == []


def test_load_report_data_today_resolves_prev_run(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        data = load_report_data(conn, "Example", "https://www.example.com", ENGINE, "today")
        assert data.period == "today"
        assert data.run_id == 5
        assert data.run_at == "2026-06-09T09:00:00+00:00"
        assert data.prev_run_id == 4
        assert data.prev_run_at == "2026-06-02T09:00:00+00:00"
        assert "all" in data.metrics
        assert "all" in data.prev_metrics
        assert set(data.sentiments).issubset({"general", "branded", "comparative"})
        assert data.sentiments
        assert data.brand_domain == "example.com"
        assert data.history == []
    finally:
        conn.close()


def test_load_report_data_all_fills_history_oldest_to_newest(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        data = load_report_data(conn, "Example", "example.com", ENGINE, "all")
        assert data.period == "all"
        assert len(data.history) == 5
        hist_dates = [run_at for run_at, _m in data.history]
        assert hist_dates == sorted(hist_dates)
        assert hist_dates[0] == "2026-05-12T09:00:00+00:00"
        assert hist_dates[-1] == "2026-06-09T09:00:00+00:00"
        for _run_at, m in data.history:
            assert "all" in m
            assert all(isinstance(v, LensMetrics) for v in m.values())
    finally:
        conn.close()


def test_load_report_data_single_run_has_no_prev(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Solo", "solo.example")
        rid = create_run(conn, bid, ENGINE)
        update_run_counts(conn, rid, n_queries=1, n_ok=1, n_failed=0, status="done")
        _insert_metric(conn, run_id=rid, brand_id=bid, lens="all")
        conn.commit()
        data = load_report_data(conn, "Solo", "solo.example", ENGINE, "today")
        assert data.run_id == rid
        assert data.prev_run_id is None
        assert data.prev_run_at is None
        assert data.prev_metrics == {}
    finally:
        conn.close()


def test_load_report_data_display_domain_from_db_row(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "https://WWW.Example.com/x")
        rid = create_run(conn, bid, ENGINE)
        update_run_counts(conn, rid, n_queries=1, n_ok=1, n_failed=0, status="done")
        _insert_metric(conn, run_id=rid, brand_id=bid, lens="all")
        conn.commit()
        data = load_report_data(conn, "Example", "https://WWW.Example.com/x", ENGINE, "today")
        assert data.brand_domain == "example.com"
    finally:
        conn.close()


def test_load_report_data_unknown_brand_raises(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        with pytest.raises(ValueError, match="brand not found"):
            load_report_data(conn, "Ghost", "ghost.example", ENGINE, "today")
    finally:
        conn.close()


def test_load_report_data_brand_without_runs_raises(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        get_or_create_brand(conn, "Empty", "empty.example")
        conn.commit()
        with pytest.raises(ValueError, match="no completed runs with metrics"):
            load_report_data(conn, "Empty", "empty.example", ENGINE, "today")
    finally:
        conn.close()


def test_load_report_data_run_with_no_metrics_treated_as_no_run(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Example", "example.com")
        create_run(conn, bid, ENGINE)
        conn.commit()
        with pytest.raises(ValueError, match="no completed runs with metrics"):
            load_report_data(conn, "Example", "example.com", ENGINE, "today")
    finally:
        conn.close()


def test_reportdata_sentiment_summaries_defaults_to_empty_dict():
    rd = ReportData(
        brand_name="Example",
        brand_domain="example.com",
        engine=ENGINE,
        period="today",
        run_id=1,
        run_at="2026-06-01T00:00:00Z",
        prev_run_id=None,
        prev_run_at=None,
        metrics={},
        prev_metrics={},
        sentiments={},
    )
    assert rd.sentiment_summaries == {}
    rd2 = ReportData(
        brand_name="B", brand_domain="b.com", engine=ENGINE, period="all",
        run_id=2, run_at="x", prev_run_id=None, prev_run_at=None,
        metrics={}, prev_metrics={}, sentiments={},
    )
    rd.sentiment_summaries["all"] = "x"
    assert rd2.sentiment_summaries == {}


def test_load_report_data_populates_sentiment_summaries(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        data = load_report_data(conn, "Example", "example.com", ENGINE, "today")
        assert data.sentiment_summaries
        assert set(data.sentiment_summaries).issubset(
            {"general", "branded", "comparative", "all"}
        )
        assert "all" in data.sentiment_summaries
        assert all(isinstance(v, str) and v for v in data.sentiment_summaries.values())
    finally:
        conn.close()


def test_load_report_data_summaries_match_focus_run(seeded_db_path):
    from pipeline.db import get_lens_sentiments

    conn = get_conn(seeded_db_path)
    try:
        data = load_report_data(conn, "Example", "example.com", ENGINE, "today")
        direct = get_lens_sentiments(conn, data.run_id)
    finally:
        conn.close()
    assert data.sentiment_summaries == direct


def test_load_report_data_summaries_empty_when_absent(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Solo", "solo.example")
        rid = create_run(conn, bid, ENGINE)
        update_run_counts(conn, rid, n_queries=1, n_ok=1, n_failed=0, status="done")
        _insert_metric(conn, run_id=rid, brand_id=bid, lens="all")
        conn.commit()
        data = load_report_data(conn, "Solo", "solo.example", ENGINE, "today")
        assert data.sentiment_summaries == {}
    finally:
        conn.close()
