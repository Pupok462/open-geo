from __future__ import annotations

import io
import os
import warnings
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

import report.generate as G
from report.generate import (
    BG,
    FONT,
    FONT_BOLD,
    FONT_OBLIQUE,
    MARGIN,
    PAGE_H,
    PANEL,
    STROKE,
    Doc,
    LensMetrics,
    ReportData,
    _dejavu_dir,
    _install_footer_hook,
    _section_header,
    _style_axes,
    _wrap_text,
    build_combined_pdf,
    build_pdf,
    chart_funnel,
    chart_history,
    chart_lenses_grouped_bar,
    generate_report,
    lens_label,
    register_fonts,
    render_cover,
    render_engine_chapter,
    render_engine_matrix,
    render_footer,
    render_funnel,
    render_gaps,
    render_glossary,
    render_history,
    render_kpi_cards,
    render_lenses,
    render_results,
    render_sentiment,
)
from report.i18n import DEFAULT_LANG, Translator
from report.textshape import is_rtl, shape, shaping_available

BRAND = "Example"
DOMAIN = "example.com"
ENGINE = "google"

PNG_MAGIC = b"\x89PNG"
PDF_MAGIC = b"%PDF"


def _canvas() -> canvas.Canvas:
    register_fonts()
    return canvas.Canvas(io.BytesIO(), pagesize=A4)


def _doc() -> Doc:
    return Doc(_canvas())


def _lm(
    lens: str = "general",
    *,
    n_queries: int = 8,
    n_overviews: int = 6,
    overview_coverage=0.75,
    n_in_sources: int = 4,
    visibility_in_sources=0.5,
    n_cited: int = 3,
    visibility_in_citations=0.375,
    avg_source_position=2.0,
    avg_citation_position=1.5,
    relative_citation=0.75,
) -> LensMetrics:
    return LensMetrics(
        lens=lens,
        n_queries=n_queries,
        n_overviews=n_overviews,
        overview_coverage=overview_coverage,
        n_in_sources=n_in_sources,
        visibility_in_sources=visibility_in_sources,
        n_cited=n_cited,
        visibility_in_citations=visibility_in_citations,
        avg_source_position=avg_source_position,
        avg_citation_position=avg_citation_position,
        relative_citation=relative_citation,
    )


def _report_data(**overrides) -> ReportData:
    base = dict(
        brand_name=BRAND,
        brand_domain=DOMAIN,
        engine=ENGINE,
        period="today",
        run_id=2,
        run_at="2026-06-18T09:00:00Z",
        prev_run_id=1,
        prev_run_at="2026-06-11T09:00:00Z",
        metrics={
            "general": _lm("general"),
            "branded": _lm("branded", visibility_in_citations=None),
            "comparative": _lm(
                "comparative", n_in_sources=0, visibility_in_sources=0.0,
                avg_source_position=None, n_cited=0,
                visibility_in_citations=0.0, avg_citation_position=None,
                relative_citation=None,
            ),
            "all": _lm("all", n_queries=24, n_overviews=18),
        },
        prev_metrics={"all": _lm("all", n_queries=24, n_overviews=15)},
        sentiments={
            "general": [("how to choose", "recommended as a leading brand")],
            "branded": [("Example reviews", "named a reliable choice")],
        },
        history=[],
    )
    base.update(overrides)
    return ReportData(**base)


def _en() -> Translator:
    return Translator("en")


def test_dejavu_dir_is_existing_directory():
    d = _dejavu_dir()
    assert os.path.isdir(d)
    assert os.path.isfile(os.path.join(d, "DejaVuSans.ttf"))


def test_register_fonts_idempotent_and_registers_family():
    register_fonts()
    register_fonts()
    names = pdfmetrics.getRegisteredFontNames()
    assert FONT in names
    assert FONT_BOLD in names
    assert FONT_OBLIQUE in names


def test_lens_label_all_known_unknown():
    t = _en()
    assert lens_label(t, "all") == t.t("report.all_queries")
    assert lens_label(t, "general") == t.t("lens.general")
    assert lens_label(t, "totally_unknown") == "totally_unknown"


def test_chart_lenses_grouped_bar_from_seeded(seeded_db_path):
    from pipeline.db import get_conn, init_db

    conn = get_conn(seeded_db_path)
    try:
        init_db(conn)
        run_id = conn.execute(
            "SELECT id FROM runs ORDER BY run_at DESC, id DESC LIMIT 1"
        ).fetchone()["id"]
        metrics = G._load_metrics_for_run(conn, run_id)
    finally:
        conn.close()
    png = chart_lenses_grouped_bar(_en(), metrics)
    assert isinstance(png, bytes) and png[:4] == PNG_MAGIC and len(png) > 100


def test_chart_lenses_grouped_bar_none_rate_label_dash():
    m = {"general": _lm("general", visibility_in_sources=None)}
    png = chart_lenses_grouped_bar(_en(), m)
    assert png[:4] == PNG_MAGIC


@pytest.mark.filterwarnings("ignore:No artists with labels:UserWarning")
def test_chart_lenses_grouped_bar_empty_metrics_raises_on_legend():
    with pytest.raises(ValueError, match="number sections must be larger than 0"):
        chart_lenses_grouped_bar(_en(), {})


def test_chart_funnel_from_seeded_all(seeded_db_path):
    from pipeline.db import get_conn, init_db

    conn = get_conn(seeded_db_path)
    try:
        init_db(conn)
        run_id = conn.execute(
            "SELECT id FROM runs ORDER BY run_at DESC, id DESC LIMIT 1"
        ).fetchone()["id"]
        metrics = G._load_metrics_for_run(conn, run_id)
    finally:
        conn.close()
    png = chart_funnel(_en(), metrics["all"])
    assert png[:4] == PNG_MAGIC and len(png) > 100


def test_chart_funnel_zero_overviews_rates_dash_branch():
    m = _lm(
        "all", n_queries=0, n_overviews=0, overview_coverage=None,
        n_in_sources=0, visibility_in_sources=None, n_cited=0,
        visibility_in_citations=None, avg_source_position=None,
        avg_citation_position=None,
    )
    png = chart_funnel(_en(), m)
    assert png[:4] == PNG_MAGIC


def test_chart_history_two_entries_returns_png():
    hist = [
        ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]
    png = chart_history(_en(), hist)
    assert png is not None and png[:4] == PNG_MAGIC


def test_chart_history_one_entry_returns_none():
    assert chart_history(_en(), [("2026-05-12T09:00:00Z", {"all": _lm("all")})]) is None


def test_chart_history_empty_returns_none():
    assert chart_history(_en(), []) is None


def test_chart_history_missing_all_row_uses_none_value_branch():
    hist = [
        ("2026-05-12T09:00:00Z", {"general": _lm("general")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all")}),
    ]
    png = chart_history(_en(), hist)
    assert png is not None and png[:4] == PNG_MAGIC


def test_style_axes_and_fig_to_png_direct():
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(2, 2))
    ax.plot([0, 1, 2], [1, 2, 3])
    _style_axes(ax)
    assert ax.spines["top"].get_visible() is False
    assert ax.spines["right"].get_visible() is False
    png = G._fig_to_png(fig)
    assert png[:4] == PNG_MAGIC and len(png) > 100


def test_doc_init_cursor_at_top():
    doc = _doc()
    assert doc.y == pytest.approx(PAGE_H - MARGIN)


def test_doc_text_variants_and_shapes_do_not_raise():
    doc = _doc()
    doc.fill_background()
    doc.text("left", 10)
    doc.text("left-x", 10, color=STROKE, font=FONT_BOLD, x=100, dy=-2)
    doc.text_right("right", 9, STROKE, FONT, x_right=400)
    doc.text_center("center", 9, STROKE, FONT, cx=300, dy=1)
    doc.hline()
    doc.hline(color=BG, width=1.2, inset=4)
    doc.rounded_panel(50, doc.y, 120, 40, fill=PANEL, stroke=STROKE)
    doc.rounded_panel(50, doc.y, 120, 40, fill=PANEL, stroke=None)
    doc.accent_bar(50, doc.y, 16, STROKE)
    doc.move(5)


def test_doc_ensure_no_break_when_it_fits():
    doc = _doc()
    y0 = doc.y
    doc.ensure(10)
    assert doc.y == pytest.approx(y0)


def test_doc_ensure_triggers_new_page_when_too_tall():
    doc = _doc()
    doc.fill_background()
    doc.ensure(PAGE_H)
    assert doc.y == pytest.approx(PAGE_H - MARGIN)


def test_doc_new_page_resets_cursor():
    doc = _doc()
    doc.move(200)
    assert doc.y < PAGE_H - MARGIN
    doc.new_page()
    assert doc.y == pytest.approx(PAGE_H - MARGIN)


def test_doc_image_png_returns_positive_height():
    doc = _doc()
    png = chart_funnel(_en(), _lm("all"))
    used = doc.image_png(png, max_w=300)
    assert used > 0


def test_section_header_direct_multichar_number():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    _section_header(doc, "03b", "A Long Section Title")
    assert doc.y < y0


@pytest.mark.parametrize("period", ["today", "all"])
def test_render_cover_both_periods(period):
    from datetime import datetime

    doc = _doc()
    data = _report_data(period=period)
    render_cover(doc, _en(), data, datetime(2026, 6, 18, 9, 0, 0))
    assert doc.y == pytest.approx(MARGIN + 6 * 2.834645669, rel=0.2)


def test_render_kpi_cards_with_prev_compare():
    doc = _doc()
    doc.fill_background()
    render_kpi_cards(doc, _en(), _report_data())


def test_render_kpi_cards_no_prev_and_no_all_metrics():
    doc = _doc()
    doc.fill_background()
    data = _report_data(prev_run_at=None, prev_run_id=None, metrics={}, prev_metrics={})
    render_kpi_cards(doc, _en(), data)


def test_render_lenses_with_lenses_renders_chart():
    doc = _doc()
    doc.fill_background()
    render_lenses(doc, _en(), _report_data())


def test_render_lenses_no_real_lenses_skips_chart():
    doc = _doc()
    doc.fill_background()
    data = _report_data(metrics={"all": _lm("all")})
    render_lenses(doc, _en(), data)


def test_render_funnel_normal():
    doc = _doc()
    doc.fill_background()
    render_funnel(doc, _en(), _report_data())


def test_render_funnel_empty_branch():
    doc = _doc()
    doc.fill_background()
    data = _report_data(metrics={})
    render_funnel(doc, _en(), data)


def test_render_history_none_early_return():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_history(doc, _en(), _report_data(history=[]))
    assert doc.y == pytest.approx(y0)


def test_render_history_with_two_runs_renders():
    doc = _doc()
    doc.fill_background()
    hist = [
        ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]
    y0 = doc.y
    render_history(doc, _en(), _report_data(period="all", history=hist))
    assert doc.y < y0


def test_wrap_text_normal_sentence_single_line():
    c = _canvas()
    out = _wrap_text(c, "the quick brown fox", FONT, 10, 1000)
    assert out == ["the quick brown fox"]


def test_wrap_text_hard_break_single_long_token():
    c = _canvas()
    token = "x" * 400
    out = _wrap_text(c, token, FONT, 10, 50)
    assert len(out) > 1
    assert "".join(out) == token


def test_wrap_text_empty_string_returns_single_empty():
    c = _canvas()
    assert _wrap_text(c, "", FONT, 10, 200) == [""]


def test_wrap_text_flushes_cur_then_wraps_normal_word():
    c = _canvas()
    out = _wrap_text(c, "alpha beta gamma delta epsilon zeta", FONT, 9, 60)
    assert len(out) > 1
    assert " ".join(out).split() == "alpha beta gamma delta epsilon zeta".split()


def test_render_sentiment_with_data():
    doc = _doc()
    doc.fill_background()
    render_sentiment(doc, _en(), _report_data())


def test_render_sentiment_renders_lens_and_all_lead_lines():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    data = _report_data(
        sentiment_summaries={
            "all": "Visible across lenses, neutral overall.",
            "general": "Mostly neutral among alternatives.",
            "branded": "Owns its branded queries.",
        }
    )
    render_sentiment(doc, _en(), data)
    assert doc.y < y0


def test_render_sentiment_all_summary_without_per_query_snippets():
    doc = _doc()
    doc.fill_background()
    data = _report_data(
        sentiments={},
        sentiment_summaries={"all": "Overall qualitative rollup line."},
    )
    render_sentiment(doc, _en(), data)


def test_render_sentiment_long_summary_wraps_without_error():
    doc = _doc()
    doc.fill_background()
    long_line = "this lens was treated in a verbose qualitative way " * 8
    data = _report_data(
        sentiment_summaries={"all": long_line, "general": long_line}
    )
    render_sentiment(doc, _en(), data)
    assert doc.y <= PAGE_H - MARGIN


def test_render_sentiment_no_summaries_still_renders_snippets():
    doc = _doc()
    doc.fill_background()
    data = _report_data(sentiment_summaries={})
    render_sentiment(doc, _en(), data)


def test_render_sentiment_empty_branch():
    doc = _doc()
    doc.fill_background()
    data = _report_data(sentiments={})
    render_sentiment(doc, _en(), data)


def test_render_sentiment_extra_lens_and_empty_query():
    doc = _doc()
    doc.fill_background()
    data = _report_data(
        sentiments={
            "all": [("", "cited positively"), ("a real query", "neutral mention")],
            "weirdlens": [("q", "phrase")],
            "emptylens": [],
        }
    )
    render_sentiment(doc, _en(), data)


def test_render_sentiment_long_phrase_forces_page_break():
    doc = _doc()
    doc.fill_background()
    long_phrase = "lorem ipsum dolor sit amet " * 12
    snippets = [(f"query number {i}", long_phrase) for i in range(20)]
    data = _report_data(sentiments={"general": snippets})
    render_sentiment(doc, _en(), data)
    assert doc.y <= PAGE_H - MARGIN


def test_render_footer_direct():
    doc = _doc()
    doc.fill_background()
    render_footer(doc, _en(), _report_data())


def test_install_footer_hook_wraps_new_page():
    doc = _doc()
    doc.fill_background()
    original = doc.new_page
    _install_footer_hook(doc, _en(), _report_data())
    assert doc.new_page is not original
    doc.move(100)
    doc.new_page()
    assert doc.y == pytest.approx(PAGE_H - MARGIN)


@pytest.mark.slow
@pytest.mark.parametrize(
    "period,lang",
    [("today", "en"), ("all", "en"), ("all", "ru"), ("all", "zh"), ("today", "ar"), ("all", "ar")],
)
def test_build_pdf_writes_pdf(tmp_path, period, lang):
    data = _report_data(
        period=period,
        history=(
            [
                ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
                ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
            ]
            if period == "all"
            else []
        ),
    )
    out = tmp_path / f"out_{period}_{lang}.pdf"
    build_pdf(data, str(out), lang=lang)
    assert out.exists()
    assert out.read_bytes()[:4] == PDF_MAGIC


@pytest.mark.slow
def test_build_pdf_creates_missing_parent_dir(tmp_path):
    out = tmp_path / "nested" / "deep" / "report.pdf"
    assert not out.parent.exists()
    build_pdf(_report_data(), str(out))
    assert out.exists() and out.read_bytes()[:4] == PDF_MAGIC


@pytest.mark.slow
@pytest.mark.parametrize("period", ["today", "all"])
def test_generate_report_from_seeded(seeded_db_path, tmp_path, period):
    out = tmp_path / f"gen_{period}.pdf"
    data = generate_report(
        db_path=seeded_db_path,
        brand=BRAND,
        domain=DOMAIN,
        engine=ENGINE,
        period=period,
        out_path=str(out),
        lang="en",
    )
    assert out.exists() and out.read_bytes()[:4] == PDF_MAGIC
    assert data.brand_name == BRAND
    assert data.period == period
    if period == "all":
        assert len(data.history) >= 2


@pytest.mark.slow
def test_main_valid_returns_zero(seeded_db_path, tmp_path, capsys):
    out = tmp_path / "main.pdf"
    rc = G.main(
        [
            "--brand", BRAND,
            "--domain", DOMAIN,
            "--engine", ENGINE,
            "--period", "today",
            "--out", str(out),
            "--db", seeded_db_path,
        ]
    )
    assert rc == 0
    assert out.exists() and out.read_bytes()[:4] == PDF_MAGIC
    err = capsys.readouterr().err
    assert "OK ->" in err


def test_main_unknown_brand_returns_one(empty_db_path, tmp_path, capsys):
    out = tmp_path / "nope.pdf"
    rc = G.main(
        [
            "--brand", "NoSuchBrand",
            "--domain", "nosuch.example",
            "--engine", ENGINE,
            "--period", "today",
            "--out", str(out),
            "--db", empty_db_path,
        ]
    )
    assert rc == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "report.generate:" in err
    assert "brand not found" in err


def test_render_kpi_cards_forces_page_break_when_cursor_low():
    doc = _doc()
    doc.fill_background()
    doc.y = MARGIN + 20
    page0 = doc.c.getPageNumber()
    render_kpi_cards(doc, _en(), _report_data())
    assert doc.c.getPageNumber() > page0


def test_render_lenses_forces_chart_page_break_when_cursor_low():
    doc = _doc()
    doc.fill_background()
    doc.y = MARGIN + 30
    page0 = doc.c.getPageNumber()
    render_lenses(doc, _en(), _report_data())
    assert doc.c.getPageNumber() > page0


def test_render_funnel_forces_page_break_when_cursor_low():
    doc = _doc()
    doc.fill_background()
    doc.y = MARGIN + 25
    page0 = doc.c.getPageNumber()
    render_funnel(doc, _en(), _report_data())
    assert doc.c.getPageNumber() > page0


def test_render_history_forces_page_break_when_cursor_low():
    doc = _doc()
    doc.fill_background()
    doc.y = MARGIN + 25
    hist = [
        ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]
    page0 = doc.c.getPageNumber()
    render_history(doc, _en(), _report_data(period="all", history=hist))
    assert doc.c.getPageNumber() > page0


def test_chart_history_present_row_with_none_attr_value():
    hist = [
        ("2026-05-12T09:00:00Z", {"all": _lm("all", overview_coverage=None)}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]
    png = chart_history(_en(), hist)
    assert png is not None and png[:4] == PNG_MAGIC


def test_chart_history_all_none_series_still_renders():
    none_row = _lm(
        "all", overview_coverage=None, visibility_in_sources=None,
        visibility_in_citations=None,
    )
    hist = [
        ("2026-05-12T09:00:00Z", {"all": none_row}),
        ("2026-05-19T09:00:00Z", {"all": none_row}),
    ]
    png = chart_history(_en(), hist)
    assert png is not None and png[:4] == PNG_MAGIC


def test_chart_funnel_all_zero_counts_renders():
    m = _lm(
        "all", n_queries=0, n_overviews=0, overview_coverage=None,
        n_in_sources=0, visibility_in_sources=None, n_cited=0,
        visibility_in_citations=None, avg_source_position=None,
        avg_citation_position=None,
    )
    png = chart_funnel(_en(), m)
    assert png[:4] == PNG_MAGIC and len(png) > 100


def test_wrap_text_hard_break_then_trailing_word():
    c = _canvas()
    long_token = "z" * 120
    out = _wrap_text(c, long_token + " tail", FONT, 10, 50)
    assert len(out) > 1
    assert "tail" in out[-1]
    assert "".join(out).replace(" ", "") == long_token + "tail"


def test_wrap_text_unicode_long_token_hard_break_no_loss():
    c = _canvas()
    token = "ё" * 100
    out = _wrap_text(c, token, FONT, 10, 40)
    assert len(out) > 1
    assert "".join(out) == token


def test_wrap_text_collapses_internal_whitespace():
    c = _canvas()
    out = _wrap_text(c, "alpha   beta\tgamma\n\ndelta", FONT, 10, 1000)
    assert out == ["alpha beta gamma delta"]


def test_fig_to_png_closes_figure():
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(2, 2))
    ax.plot([0, 1, 2], [2, 1, 0])
    num = fig.number
    assert plt.fignum_exists(num)
    png = G._fig_to_png(fig)
    assert png[:4] == PNG_MAGIC
    assert not plt.fignum_exists(num)


def test_doc_image_png_height_is_proportional():
    from reportlab.lib.utils import ImageReader

    doc = _doc()
    png = chart_funnel(_en(), _lm("all"))
    iw, ih = ImageReader(io.BytesIO(png)).getSize()
    max_w = 300.0
    used = doc.image_png(png, max_w=max_w)
    assert used == pytest.approx(max_w / iw * ih, rel=1e-6)


def test_render_footer_localizes_report_name_only():
    ten, tru = _en(), Translator("ru")
    assert ten.t("report.footer_report_name") != tru.t("report.footer_report_name")
    assert ten.t("common.app_title") == tru.t("common.app_title")
    doc_en = _doc()
    doc_en.fill_background()
    render_footer(doc_en, ten, _report_data())
    doc_ru = _doc()
    doc_ru.fill_background()
    render_footer(doc_ru, tru, _report_data())


def test_section_header_advances_fixed_offset():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    _section_header(doc, "01", "Heading")
    assert (y0 - doc.y) == pytest.approx(36.0, abs=0.01)


@pytest.mark.slow
def test_build_pdf_embeds_font_and_paginates(tmp_path):
    import re

    out = tmp_path / "embed.pdf"
    data = _report_data(
        period="all",
        history=[
            ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
            ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
        ],
    )
    build_pdf(data, str(out))
    raw = out.read_bytes()
    assert raw[:4] == PDF_MAGIC
    assert b"DejaVuSans" in raw
    page_objs = re.findall(rb"/Type\s*/Page(?![s])", raw)
    assert len(page_objs) >= 2


@pytest.mark.slow
def test_generate_report_unknown_lang_falls_back(seeded_db_path, tmp_path):
    out = tmp_path / "xx.pdf"
    data = generate_report(
        db_path=seeded_db_path,
        brand=BRAND,
        domain=DOMAIN,
        engine=ENGINE,
        period="today",
        out_path=str(out),
        lang="zz",
    )
    assert out.exists() and out.read_bytes()[:4] == PDF_MAGIC
    assert data.brand_name == BRAND


@pytest.mark.slow
def test_main_period_all_unknown_lang_returns_zero(seeded_db_path, tmp_path, capsys):
    out = tmp_path / "main_all.pdf"
    rc = G.main(
        [
            "--brand", BRAND,
            "--domain", DOMAIN,
            "--engine", ENGINE,
            "--period", "all",
            "--lang", "zz",
            "--out", str(out),
            "--db", seeded_db_path,
        ]
    )
    assert rc == 0
    assert out.exists() and out.read_bytes()[:4] == PDF_MAGIC
    assert "OK ->" in capsys.readouterr().err


def test_main_bad_period_choice_exits_nonzero(seeded_db_path, tmp_path):
    with pytest.raises(SystemExit) as ei:
        G.main(
            [
                "--brand", BRAND,
                "--domain", DOMAIN,
                "--engine", ENGINE,
                "--period", "yesterday",
                "--out", str(tmp_path / "x.pdf"),
                "--db", seeded_db_path,
            ]
        )
    assert ei.value.code == 2


def test_render_cover_is_single_page_and_anchors_footer():
    from datetime import datetime

    doc = _doc()
    page0 = doc.c.getPageNumber()
    render_cover(doc, _en(), _report_data(period="today"), datetime(2026, 6, 18, 9, 0))
    assert doc.c.getPageNumber() == page0
    assert doc.y == pytest.approx(MARGIN + 6 * 2.834645669, abs=1.0)


def test_shaping_libs_available():
    assert shaping_available() is True


def test_is_rtl_classifies_arabic_only():
    assert is_rtl("ar") is True
    assert is_rtl("en") is False
    assert is_rtl("ru") is False
    assert is_rtl("zh") is False
    assert is_rtl(None) is False


def test_shape_transforms_arabic_and_is_identity_otherwise():
    src = "العربية"
    out = shape(src, "ar")
    assert out != src
    assert any(0xFB50 <= ord(ch) <= 0xFEFF for ch in out)
    assert shape(src, "en") == src
    assert shape(src, "zh") == src
    assert shape(src, None) == src
    assert shape("", "ar") == ""


def test_shape_leaves_latin_digits_untouched_under_ar():
    assert shape("example.com", "ar") == "example.com"
    assert shape("83%", "ar") == "83%"


def test_register_fonts_selects_cjk_for_zh():
    register_fonts("zh")
    try:
        assert G.FONT == "NotoSansSC"
        assert G.FONT_BOLD == "NotoSansSC-Bold"
        assert G.FONT_OBLIQUE == "NotoSansSC"
        names = pdfmetrics.getRegisteredFontNames()
        assert "NotoSansSC" in names and "NotoSansSC-Bold" in names
        assert G.plt.rcParams["font.family"] == ["Noto Sans SC", "DejaVu Sans"]
    finally:
        register_fonts(DEFAULT_LANG)


def test_register_fonts_selects_arabic_for_ar():
    register_fonts("ar")
    try:
        assert G.FONT == "NotoNaskhArabic"
        assert G.FONT_BOLD == "NotoNaskhArabic-Bold"
        assert G.plt.rcParams["font.family"] == ["Noto Naskh Arabic", "DejaVu Sans"]
    finally:
        register_fonts(DEFAULT_LANG)


def test_register_fonts_dejavu_for_en_and_ru():
    for lang in ("en", "ru"):
        register_fonts(lang)
        assert G.FONT == "DejaVuSans"
        assert G.FONT_BOLD == "DejaVuSans-Bold"
        assert G.FONT_OBLIQUE == "DejaVuSans-Oblique"
        assert G.plt.rcParams["font.family"] == ["DejaVu Sans"]


def test_register_fonts_falls_back_to_dejavu_when_bundled_fonts_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "_FONTS_DIR", str(tmp_path / "no_fonts_here"))
    register_fonts("zh")
    try:
        assert G.FONT == "DejaVuSans"
        assert G.plt.rcParams["font.family"] == ["DejaVu Sans"]
    finally:
        monkeypatch.undo()
        register_fonts(DEFAULT_LANG)


@pytest.mark.slow
def test_build_pdf_zh_emits_no_missing_glyph_warnings(tmp_path):
    data = _report_data(
        period="all",
        history=[
            ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
            ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
        ],
    )
    out = tmp_path / "zh.pdf"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        build_pdf(data, str(out), lang="zh")
    missing = [w for w in caught if "missing from font" in str(w.message).lower()]
    assert not missing, [str(w.message) for w in missing[:5]]
    assert out.read_bytes()[:4] == PDF_MAGIC
    register_fonts(DEFAULT_LANG)


@pytest.mark.slow
def test_build_pdf_zh_embeds_cjk_font(tmp_path):
    out = tmp_path / "zh.pdf"
    build_pdf(_report_data(period="today"), str(out), lang="zh")
    raw = out.read_bytes()
    assert raw[:4] == PDF_MAGIC
    assert b"NotoSansSC" in raw
    register_fonts(DEFAULT_LANG)


@pytest.mark.slow
def test_build_pdf_ar_embeds_arabic_font(tmp_path):
    out = tmp_path / "ar.pdf"
    build_pdf(_report_data(period="today"), str(out), lang="ar")
    raw = out.read_bytes()
    assert raw[:4] == PDF_MAGIC
    assert b"NotoNaskhArabic" in raw
    register_fonts(DEFAULT_LANG)


@pytest.mark.slow
def test_build_pdf_en_does_not_embed_noto_fonts(tmp_path):
    out = tmp_path / "en.pdf"
    build_pdf(_report_data(period="all", history=[
        ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]), str(out), lang="en")
    raw = out.read_bytes()
    assert b"DejaVuSans" in raw
    assert b"NotoSansSC" not in raw
    assert b"NotoNaskhArabic" not in raw


@pytest.mark.slow
def test_build_pdf_ar_is_rtl_and_shapes_via_canvas(tmp_path):
    data = _report_data(period="today")
    doc_seen = {}
    original = G.Doc

    def spy(c, rtl=False, lang=DEFAULT_LANG):
        doc_seen["rtl"] = rtl
        doc_seen["lang"] = lang
        return original(c, rtl=rtl, lang=lang)

    G.Doc = spy
    try:
        build_pdf(data, str(tmp_path / "ar.pdf"), lang="ar")
    finally:
        G.Doc = original
        register_fonts(DEFAULT_LANG)
    assert doc_seen.get("rtl") is True
    assert doc_seen.get("lang") == "ar"


def test_resolve_brand_id_finds_prefix_brand_in_any_writing(tmp_path):
    from pipeline.db import get_conn, get_or_create_brand, init_db
    from report.generate import _resolve_brand_id

    db = str(tmp_path / "prefix.db")
    conn = get_conn(db)
    try:
        init_db(conn)
        bid = get_or_create_brand(conn, "MyProject", "https://GitHub.com/User/Repo/")
        found = _resolve_brand_id(conn, "MyProject", "github.com/user/repo")
        assert found == bid
        found2 = _resolve_brand_id(conn, "MyProject", "https://www.GITHUB.com/User/Repo")
        assert found2 == bid
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_build_combined_pdf_two_engines_writes_pdf(tmp_path):
    out = str(tmp_path / "combined.pdf")
    datas = [
        _report_data(engine="google"),
        _report_data(engine="chatgpt_search", run_id=9, prev_run_id=None, prev_run_at=None),
    ]
    build_combined_pdf(datas, out, lang="en")
    raw = Path(out).read_bytes()
    assert raw[:5] == b"%PDF-"
    assert len(raw) > 10_000


def test_build_combined_pdf_single_engine_still_valid(tmp_path):
    out = str(tmp_path / "combined_one.pdf")
    build_combined_pdf([_report_data(engine="google")], out, lang="en")
    assert Path(out).read_bytes()[:5] == b"%PDF-"


def test_render_engine_matrix_handles_missing_all_row():
    doc = _doc()
    data = _report_data(engine="google")
    data.metrics.pop("all")
    render_engine_matrix(doc, _en(), [data])


def test_render_engine_chapter_moves_cursor_down():
    doc = _doc()
    y0 = doc.y
    render_engine_chapter(doc, _en(), "google")
    assert doc.y < y0


def test_main_engines_all_builds_combined_pdf(dash_fixture_db_path, tmp_path, capsys):
    out = str(tmp_path / "combined_cli.pdf")
    rc = G.main(
        [
            "--brand", "Example", "--domain", "example.com",
            "--engines", "all", "--period", "today",
            "--out", out, "--db", dash_fixture_db_path,
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert Path(out).read_bytes()[:5] == b"%PDF-"


def test_main_engine_and_engines_are_mutually_exclusive(tmp_path, capsys):
    rc = G.main(
        [
            "--brand", "X", "--domain", "x.com", "--engine", "google",
            "--engines", "all", "--period", "today",
            "--out", str(tmp_path / "x.pdf"),
        ]
    )
    capsys.readouterr()
    assert rc == 2
    rc2 = G.main(
        [
            "--brand", "X", "--domain", "x.com", "--period", "today",
            "--out", str(tmp_path / "y.pdf"),
        ]
    )
    capsys.readouterr()
    assert rc2 == 2


def _rr(query="q", lens="general", overview=True, src=None, cit=None, mention=False, sentiment=None):
    return G.ResultRow(
        query=query,
        lens=lens,
        overview_present=overview,
        source_ranks=list(src or []),
        citation_ranks=list(cit or []),
        brand_in_answer_text=mention,
        sentiment=sentiment,
    )


def _all_outcomes_rows():
    return [
        _rr("cited query", src=[1], cit=[1], mention=True, sentiment="positive"),
        _rr("sources query", src=[2]),
        _rr("mention query", mention=True),
        _rr("absent query", lens="comparative"),
        _rr("no answer query", lens="branded", overview=False),
    ]


def test_results_by_outcome_groups_every_row_once():
    grouped = G._results_by_outcome(_all_outcomes_rows())
    assert list(grouped) == list(G.RESULT_OUTCOMES)
    assert [len(v) for v in grouped.values()] == [1, 1, 1, 1, 1]


def test_render_results_renders_every_outcome_group():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_results(doc, _en(), _report_data(results=_all_outcomes_rows()))
    assert doc.y < y0


def test_render_results_empty_uses_dashboard_empty_string():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_results(doc, _en(), _report_data(results=[]))
    assert doc.y < y0


def test_results_legend_mentions_both_markers():
    t = _en()
    legend = G._results_legend(t)
    assert t.t("dashboard.results_overview_shown") in legend
    assert t.t("dashboard.results_mention_no") in legend
    assert G._mark_yes() in legend and G._mark_no() in legend


def test_result_row_without_sentiment_falls_back_to_brand_absent():
    t = _en()
    row = G._result_table_row(t, _rr("q", sentiment=None))
    assert row.cells[-1].text == t.t("dashboard.results_brand_absent")


def test_render_gaps_lists_only_absent_rows():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_gaps(doc, _en(), _report_data(results=_all_outcomes_rows()))
    assert doc.y < y0


def test_render_gaps_empty_branch():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_gaps(doc, _en(), _report_data(results=[_rr("cited", src=[1], cit=[1])]))
    assert doc.y < y0


def test_render_glossary_covers_all_seven_metrics():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_glossary(doc, _en(), _report_data())
    assert doc.y < y0
    assert len(G._GLOSSARY_METRICS) == 7


def test_funnel_invariant_text_uses_ascii_fallback_for_zh():
    register_fonts("zh")
    try:
        assert "<=" in G._funnel_invariant_text(Translator("zh"))
    finally:
        register_fonts("en")
    assert "⊆" in G._funnel_invariant_text(_en())


def test_lenses_table_has_dashboard_columns():
    t = _en()
    columns, rows = G._lenses_table(t, _report_data())
    labels = [c.label for c in columns]
    assert t.t("dashboard.lens_col_queries") in labels
    assert t.t("dashboard.lens_col_overview") in labels
    assert t.t("dashboard.lens_col_mentions") in labels
    assert len(rows[0].cells) == len(columns)


def test_weekly_table_marks_repeat_runs_with_badge():
    t = _en()
    weeks = [
        G.WeekPoint(week="2026-W20", monday="2026-05-11T00:00:00+00:00", n_runs=2, metrics=_lm("all")),
        G.WeekPoint(week="2026-W21", monday="2026-05-18T00:00:00+00:00", n_runs=1, metrics=_lm("all")),
    ]
    columns, rows = G._weekly_table(t, weeks)
    assert len(columns) == len(rows[0].cells)
    assert rows[0].cells[0].badge == "×2"
    assert rows[1].cells[0].badge is None


def test_render_history_draws_weekly_rollup_when_two_weeks():
    doc = _doc()
    doc.fill_background()
    hist = [
        ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]
    weekly = G._weekly_rollup(hist)
    y0 = doc.y
    render_history(doc, _en(), _report_data(period="all", history=hist, history_weekly=weekly))
    assert doc.y < y0
    assert len(weekly) == 2


def test_competitors_citations_inset_sorted_by_citations():
    t = _en()
    comps = [
        {"domain": "a.com", "is_brand": False, "appearances_sources": 9, "appearances_citations": 1,
         "avg_source_position": 1.0, "avg_citation_position": 2.0, "share_sources": 0.9, "share_citations": 0.1},
        {"domain": "b.com", "is_brand": True, "appearances_sources": 2, "appearances_citations": 5,
         "avg_source_position": 3.0, "avg_citation_position": 1.0, "share_sources": 0.2, "share_citations": 0.5},
        {"domain": "c.com", "is_brand": False, "appearances_sources": 4, "appearances_citations": 0,
         "avg_source_position": 2.0, "avg_citation_position": None, "share_sources": 0.4, "share_citations": 0.0},
    ]
    _, rows = G._competitors_citations_inset(t, _report_data(competitors=comps))
    assert [r.cells[0].text for r in rows] == ["b.com", "a.com"]
    assert rows[0].highlight is True


def test_audit_checks_grouped_by_category_in_order():
    audit = {
        "verdict": "ready",
        "score": 80,
        "checks": [
            {"id": "B1", "category": "B", "title": "b", "severity": "recommended", "status": "warn", "detail": "d"},
            {"id": "A1", "category": "A", "title": "a", "severity": "blocker", "status": "pass", "detail": "d"},
            {"id": "A2", "category": "A", "title": "a2", "severity": "blocker", "status": "fail", "detail": "d"},
        ],
    }
    groups = G._audit_checks_by_category(audit)
    assert [g[0] for g in groups] == ["A", "B"]
    assert [c["id"] for c in groups[0][1]] == ["A2", "A1"]


def test_audit_table_has_fix_column_with_remediation():
    t = _en()
    audit = {
        "checks": [
            {"id": "A3", "category": "A", "title": "robots", "severity": "blocker",
             "status": "fail", "detail": "blocked", "remediation": "Allow the search bot"}
        ]
    }
    columns, rows = G._audit_table(t, audit)
    assert columns[-1].label == t.t("audit.col_fix")
    assert rows[0].cells[-1].text == "Allow the search bot"


def test_fit_table_size_shrinks_for_a_wide_table():
    wide = [G.Column(f"Column header {i}") for i in range(9)]
    rows = [G.TableRow(cells=[G.Cell("value " + "x" * 8) for _ in range(9)])]
    narrow = [G.Column("A"), G.Column("B")]
    narrow_rows = [G.TableRow(cells=[G.Cell("1"), G.Cell("2")])]
    assert G.fit_table_size(wide, rows) < G.fit_table_size(narrow, narrow_rows)
    assert G.fit_table_size(narrow, narrow_rows) == G.T_TABLE


def test_glyph_falls_back_when_codepoint_missing():
    register_fonts("zh")
    try:
        assert G._glyph("✓", "•") == "•"
        assert G._mark_no() == "—"
    finally:
        register_fonts("en")
    assert G._glyph("✓", "•") == "✓"


def test_wrap_budget_widths_none_without_wrap_columns():
    columns = [G.Column("A"), G.Column("B")]
    assert G._wrap_budget_widths(columns, [100.0, 100.0], [100.0, 100.0]) is None


def test_wrap_budget_widths_none_when_fixed_columns_eat_the_frame():
    columns = [G.Column("A"), G.Column("B", wrap=True)]
    natural = [G.CONTENT_W, 200.0]
    floor = [G.CONTENT_W, 200.0]
    assert G._wrap_budget_widths(columns, natural, floor) is None


def test_wrap_budget_widths_caps_wrap_columns_at_natural():
    columns = [G.Column("A", wrap=True, grow=1.0), G.Column("B", wrap=True, grow=1.0)]
    natural = [40.0, 60.0]
    floor = [20.0, 30.0]
    widths = G._wrap_budget_widths(columns, natural, floor)
    assert widths == [40.0, 60.0]


def test_column_widths_falls_back_to_shrink_for_many_fixed_columns():
    columns = [G.Column(f"Very long column header {i}") for i in range(12)]
    rows = [G.TableRow(cells=[G.Cell("some value here") for _ in range(12)])]
    widths = G._column_widths(columns, rows, G.T_TABLE)
    assert len(widths) == 12
    assert sum(widths) == pytest.approx(G.CONTENT_W)


def test_column_widths_zero_grow_shares_slack_evenly():
    columns = [G.Column("A", grow=0.0), G.Column("B", grow=0.0)]
    rows = [G.TableRow(cells=[G.Cell("1"), G.Cell("2")])]
    widths = G._column_widths(columns, rows, G.T_TABLE)
    assert widths[0] == pytest.approx(widths[1], rel=0.01)
    assert sum(widths) == pytest.approx(G.CONTENT_W)


def test_paragraph_h_zero_for_empty_text():
    doc = _doc()
    assert G._paragraph_h(doc, "") == 0.0
    assert G._paragraph_h(doc, "some text") > 0.0


def test_glyph_falls_back_when_font_is_unknown():
    original = G.FONT
    G.FONT = "NoSuchFontRegistered"
    try:
        assert G._glyph("✓", "•") == "•"
    finally:
        G.FONT = original


def test_competitors_inset_computes_share_when_absent():
    t = _en()
    comps = [
        {"domain": "a.com", "is_brand": False, "appearances_sources": 3,
         "appearances_citations": 3, "avg_source_position": 1.0, "avg_citation_position": 1.0}
    ]
    data = _report_data(competitors=comps, metrics={"all": _lm("all", n_overviews=6)})
    _, rows = G._competitors_citations_inset(t, data)
    assert rows[0].cells[1].text == "50%"


def test_render_competitors_without_citations_skips_inset():
    doc = _doc()
    doc.fill_background()
    comps = [
        {"domain": "a.com", "is_brand": False, "appearances_sources": 3,
         "appearances_citations": 0, "avg_source_position": 1.0, "avg_citation_position": None,
         "share_sources": 0.5, "share_citations": 0.0}
    ]
    y0 = doc.y
    G.render_competitors(doc, _en(), _report_data(competitors=comps))
    assert doc.y < y0


def test_render_audit_skips_category_without_rows(monkeypatch):
    doc = _doc()
    doc.fill_background()
    audit = {
        "verdict": "ready",
        "score": 90,
        "checked_at": "2026-07-01T12:00:00",
        "blockers": ["A3"],
        "checks": [
            {"id": "A1", "category": "A", "title": "a", "severity": "blocker",
             "status": "pass", "detail": "d", "remediation": None}
        ],
    }
    real = G._audit_table

    def fake(t, a, checks=None):
        columns, rows = real(t, a, checks)
        return columns, ([] if checks else rows)

    monkeypatch.setattr(G, "_audit_table", fake)
    y0 = doc.y
    G.render_audit(doc, _en(), _report_data(audit=audit))
    assert doc.y < y0


def test_wrap_budget_widths_breaks_when_no_room_left():
    columns = [G.Column("A", wrap=True), G.Column("B", wrap=True)]
    widths = G._wrap_budget_widths(columns, [40.0, 60.0], [40.0, 60.0])
    assert widths == [40.0, 60.0]


def test_row_lines_empty_when_inner_width_is_zero():
    doc = _doc()
    columns = [G.Column("A")]
    row = G.TableRow(cells=[G.Cell("value")])
    assert G._row_lines(doc, columns, [1.0], row, G.T_TABLE, False) == [[""]]


def test_measure_and_min_height_zero_for_no_rows():
    doc = _doc()
    columns = [G.Column("A")]
    assert G.measure_table(doc, columns, []) == 0.0
    assert G.table_min_height(doc, columns, []) == 0.0


def test_draw_table_without_rows_prints_no_data():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    G.draw_table(doc, _en(), [G.Column("A")], [])
    assert doc.y < y0


def test_draw_caption_and_paragraph_ignore_empty_text():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    G.draw_caption(doc, "")
    G.draw_paragraph(doc, "")
    assert doc.y == pytest.approx(y0)


def test_glyph_falls_back_when_face_has_no_charmap(monkeypatch):
    class _Face:
        pass

    class _Font:
        face = _Face()

    monkeypatch.setattr(G.pdfmetrics, "getFont", lambda name: _Font())
    assert G._glyph("✓", "•") == "•"


def test_place_full_width_chart_scales_down_when_space_is_short():
    doc = _doc()
    doc.fill_background()
    png = chart_funnel(_en(), _lm("all"))
    full = G._chart_height(png)
    doc.y = MARGIN + full * 0.8
    page0 = doc.c.getPageNumber()
    G._place_full_width_chart(doc, png, G.GAP_S)
    assert doc.c.getPageNumber() == page0


def test_place_full_width_chart_breaks_page_when_space_is_tiny():
    doc = _doc()
    doc.fill_background()
    _install_footer_hook(doc, _en(), _report_data())
    png = chart_funnel(_en(), _lm("all"))
    doc.y = MARGIN + 20
    page0 = doc.c.getPageNumber()
    G._place_full_width_chart(doc, png, G.GAP_S)
    assert doc.c.getPageNumber() > page0


def test_render_kpi_cards_repeat_group_shows_spread_chips():
    doc = _doc()
    doc.fill_background()
    data = _report_data(
        n_repeats=3,
        group_id="g1",
        spread={"overview_coverage": (0.6, 0.8), "avg_source_position": (1.5, 2.5)},
    )
    y0 = doc.y
    render_kpi_cards(doc, _en(), data)
    assert doc.y < y0


def test_spread_chip_text_none_when_metric_missing():
    t = _en()
    cards = G._build_kpi_cards(t, _lm("all"), None, "en")
    assert G._spread_chip_text(t, cards[0], {}, "en") is None
    chip = G._spread_chip_text(t, cards[0], {"overview_coverage": (0.6, 0.8)}, "en")
    assert chip == "60%–80%"


def test_render_kpi_cards_period_all_uses_rollup_line():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_kpi_cards(doc, _en(), _report_data(period="all", n_runs=4))
    assert doc.y < y0


def test_competitors_table_computes_missing_shares():
    t = _en()
    comps = [
        {"domain": "a.com", "is_brand": True, "appearances_sources": 9,
         "appearances_citations": 3, "avg_source_position": 1.0, "avg_citation_position": 2.0}
    ]
    data = _report_data(competitors=comps, metrics={"all": _lm("all", n_overviews=18)})
    _, rows = G._competitors_table(t, data)
    assert rows[0].cells[1].text == "50%"
    assert rows[0].cells[2].text == "17%"


def _record_strings(doc):
    seen: list[tuple[int, float, str]] = []
    base = doc.c.drawString

    def rec(x, y, text, *a, **k):
        seen.append((doc.c.getPageNumber(), round(float(x), 2), str(text)))
        return base(x, y, text, *a, **k)

    doc.c.drawString = rec
    return seen


ARABIC_SAMPLE = "عاب"


def test_matplotlib_reorders_rtl_itself_so_charts_must_not_preshape():
    from matplotlib import _text_helpers
    from matplotlib.ft2font import FT2Font

    font = FT2Font(os.path.join(G._FONTS_DIR, "NotoNaskhArabic-Regular.ttf"))
    order = [item.char for item in _text_helpers.layout(ARABIC_SAMPLE, font)]
    assert (order == list(reversed(ARABIC_SAMPLE))) is G._mpl_lays_out_rtl()


def test_chart_text_leaves_arabic_raw_when_matplotlib_lays_it_out(monkeypatch):
    monkeypatch.setattr(G, "_MPL_RTL_LAYOUT", True)
    assert G._chart_text(ARABIC_SAMPLE, "ar") == ARABIC_SAMPLE


def test_chart_text_shapes_arabic_when_matplotlib_cannot(monkeypatch):
    monkeypatch.setattr(G, "_MPL_RTL_LAYOUT", False)
    out = G._chart_text(ARABIC_SAMPLE, "ar")
    assert out == shape(ARABIC_SAMPLE, "ar") != ARABIC_SAMPLE


def test_chart_text_never_double_shapes_arabic(monkeypatch):
    monkeypatch.setattr(G, "_MPL_RTL_LAYOUT", True)
    once = shape(ARABIC_SAMPLE, "ar")
    assert shape(once, "ar") != once
    assert G._chart_text(ARABIC_SAMPLE, "ar") != once


def test_chart_text_is_identity_for_non_rtl_languages(monkeypatch):
    for native in (True, False):
        monkeypatch.setattr(G, "_MPL_RTL_LAYOUT", native)
        for lang in ("en", "ru", "zh", None):
            assert G._chart_text("Answer coverage", lang) == "Answer coverage"
            assert G._chart_text("Покрытие ответами", lang) == "Покрытие ответами"


def test_charts_are_byte_stable_for_en_when_layout_probe_flips(monkeypatch):
    metrics = {"general": _lm("general"), "all": _lm("all")}
    monkeypatch.setattr(G, "_MPL_RTL_LAYOUT", True)
    native = chart_lenses_grouped_bar(_en(), metrics)
    monkeypatch.setattr(G, "_MPL_RTL_LAYOUT", False)
    shaped = chart_lenses_grouped_bar(_en(), metrics)
    assert native == shaped


def test_doc_text_w_measures_the_shaped_string_for_arabic():
    register_fonts("ar")
    try:
        doc = Doc(canvas.Canvas(io.BytesIO(), pagesize=A4), rtl=True, lang="ar")
        src = "العربية"
        assert doc.text_w(src, G.FONT, 10) == pytest.approx(
            pdfmetrics.stringWidth(shape(src, "ar"), G.FONT, 10)
        )
        assert doc.text_w(src, G.FONT, 10) != pytest.approx(
            pdfmetrics.stringWidth(src, G.FONT, 10)
        )
    finally:
        register_fonts(DEFAULT_LANG)


def test_doc_text_w_is_plain_width_for_latin():
    doc = _doc()
    assert doc.lang == DEFAULT_LANG
    assert doc.text_w("Cited", FONT_BOLD, 10) == pytest.approx(
        pdfmetrics.stringWidth("Cited", FONT_BOLD, 10)
    )


def test_draw_group_heading_places_the_count_next_to_the_title():
    doc = _doc()
    doc.fill_background()
    seen = _record_strings(doc)
    G._draw_group_heading(doc, "Cited", 9)
    assert [s for _, _, s in seen] == ["Cited", f"{G.GROUP_COUNT_SEP}9"]
    x_title, x_count = seen[0][1], seen[1][1]
    assert x_title == pytest.approx(MARGIN + 10, abs=0.5)
    assert x_count > x_title
    assert x_count < G.PAGE_W - MARGIN - 100


def test_draw_group_heading_without_count_draws_only_the_title():
    doc = _doc()
    doc.fill_background()
    seen = _record_strings(doc)
    G._draw_group_heading(doc, "Cited")
    assert [s for _, _, s in seen] == ["Cited"]


def test_draw_group_heading_count_text_wins_over_count():
    doc = _doc()
    doc.fill_background()
    seen = _record_strings(doc)
    G._draw_group_heading(doc, "By week", 5, count_text="5 weeks")
    assert [s for _, _, s in seen] == ["By week", f"{G.GROUP_COUNT_SEP}5 weeks"]


def test_draw_group_heading_truncates_a_title_that_would_push_the_count_out():
    doc = _doc()
    doc.fill_background()
    seen = _record_strings(doc)
    G._draw_group_heading(doc, "word " * 200, 9)
    title, count = seen[0][2], seen[1][2]
    end_x = seen[1][1] + pdfmetrics.stringWidth(count, FONT, 10)
    assert title.endswith("…")
    assert end_x <= G.PAGE_W - MARGIN + 0.5


def _long_table(n: int):
    columns = [G.Column("Query", wrap=True, grow=3.0), G.Column("Lens")]
    rows = [
        G.TableRow(cells=[G.Cell(f"query number {i}"), G.Cell("General")])
        for i in range(n)
    ]
    return columns, rows


def test_draw_table_repeats_the_group_heading_on_a_continuation_page():
    doc = _doc()
    doc.fill_background()
    columns, rows = _long_table(70)
    seen = _record_strings(doc)
    G.draw_table(doc, _en(), columns, rows, group_title="In sources, not cited")
    pages = sorted({p for p, _, _ in seen})
    assert len(pages) > 1
    later = [(p, s) for p, _, s in seen if p > pages[0]]
    assert ("In sources, not cited") in [s for _, s in later]
    assert any("continued" in s for _, s in later)


def test_draw_table_without_group_title_draws_no_continuation_heading():
    doc = _doc()
    doc.fill_background()
    columns, rows = _long_table(70)
    seen = _record_strings(doc)
    G.draw_table(doc, _en(), columns, rows)
    assert len({p for p, _, _ in seen}) > 1
    assert not any("continued" in s for _, _, s in seen)


def test_render_results_repeats_group_headings_across_pages():
    rows = [
        _rr(f"cited query number {i}", src=[1], cit=[1], mention=True, sentiment="ok")
        for i in range(60)
    ]
    doc = _doc()
    doc.fill_background()
    seen = _record_strings(doc)
    render_results(doc, _en(), _report_data(results=rows))
    assert sum(1 for _, _, s in seen if "continued" in s) >= 1


def test_render_history_counts_weeks_in_the_group_heading():
    doc = _doc()
    doc.fill_background()
    hist = [
        ("2026-05-12T09:00:00Z", {"all": _lm("all")}),
        ("2026-05-19T09:00:00Z", {"all": _lm("all", overview_coverage=0.9)}),
    ]
    weekly = G._weekly_rollup(hist)
    seen = _record_strings(doc)
    render_history(doc, _en(), _report_data(period="all", history=hist, history_weekly=weekly))
    assert any(s == f"{G.GROUP_COUNT_SEP}{len(weekly)} weeks" for _, _, s in seen)


def test_token_segments_break_after_punctuation_only():
    assert G._token_segments('{"@type":"Organization",') == [
        '{"',
        '@type"',
        ":",
        '"',
        'Organization"',
        ",",
    ]
    assert G._token_segments("plainword") == ["plainword"]


def test_token_segments_keep_dotted_and_decimal_tokens_whole():
    assert G._token_segments("logo.png") == ["logo.png"]
    assert G._token_segments("3.14") == ["3.14"]
    assert G._token_segments("1,234") == ["1,234"]
    assert G._token_segments("schema.org/") == ["schema.org/"]


def _jsonld_snippet() -> str:
    return (
        '<script type="application/ld+json">{"@context":"https://schema.org",'
        '"@type":"Organization","name":"<Brand>","logo":"https://example.com/logo.png"}'
        "</script>"
    )


def test_wrap_text_breaks_a_snippet_at_punctuation_not_inside_a_token():
    c = _canvas()
    snippet = _jsonld_snippet().replace(" ", "")
    out = _wrap_text(c, snippet, FONT, 7.5, 120.0)
    assert len(out) > 1
    assert "".join(out) == snippet
    for line in out[:-1]:
        assert line[-1] in G.TOKEN_BREAK_AFTER
    assert not any("logo." == line[-5:] for line in out[:-1])


def test_wrap_text_still_hard_breaks_a_token_without_punctuation():
    c = _canvas()
    token = "x" * 400
    out = _wrap_text(c, token, FONT, 10, 50)
    assert len(out) > 1
    assert "".join(out) == token


def _audit_with_snippet() -> dict:
    return {
        "verdict": "ready_with_notes",
        "score": 67,
        "checks": [
            {
                "id": "B1",
                "category": "B",
                "title": "Structured data (JSON-LD)",
                "severity": "recommended",
                "status": "fail",
                "detail": "No JSON-LD structured data found.",
                "remediation": _jsonld_snippet().replace(" ", ""),
            }
        ],
    }


def test_audit_table_renders_smaller_than_the_default_table():
    assert G.T_AUDIT_TABLE < G.T_TABLE


def test_audit_fix_column_gets_the_widest_share():
    columns, rows = G._audit_table(_en(), _audit_with_snippet())
    widths = G._column_widths(columns, rows, G.T_AUDIT_TABLE)
    assert widths[-1] == max(widths)
    assert widths[-1] > widths[3]
    assert sum(widths) == pytest.approx(G.CONTENT_W, abs=0.5)


def test_audit_fix_cell_wraps_without_splitting_a_token():
    doc = _doc()
    columns, rows = G._audit_table(_en(), _audit_with_snippet())
    widths = G._column_widths(columns, rows, G.T_AUDIT_TABLE)
    lines = G._row_lines(doc, columns, widths, rows[0], G.T_AUDIT_TABLE, False)[-1]
    assert len(lines) > 1
    assert "".join(lines) == _jsonld_snippet().replace(" ", "")
    for line in lines[:-1]:
        assert line[-1] in G.TOKEN_BREAK_AFTER


def _record_draws(doc):
    seen: list[tuple[float, float, str, str, float]] = []
    base = doc.c.drawString
    right = doc.c.drawRightString

    def rec(x, y, text, *a, **k):
        seen.append((float(x), float(y), str(text), doc.c._fontname, doc.c._fontsize))
        return base(x, y, text, *a, **k)

    def rec_right(x, y, text, *a, **k):
        w = pdfmetrics.stringWidth(str(text), doc.c._fontname, doc.c._fontsize)
        seen.append((float(x) - w, float(y), str(text), doc.c._fontname, doc.c._fontsize))
        return right(x, y, text, *a, **k)

    doc.c.drawString = rec
    doc.c.drawRightString = rec_right
    return seen


def test_render_audit_keeps_every_drawn_string_inside_the_frame():
    doc = _doc()
    doc.fill_background()
    seen = _record_draws(doc)
    G.render_audit(doc, _en(), _report_data(audit=_audit_with_snippet()))
    assert seen
    for x, y, text, font, size in seen:
        assert x >= MARGIN - 0.5
        assert x + pdfmetrics.stringWidth(text, font, size) <= G.PAGE_W - MARGIN + 0.5
        assert y >= MARGIN - 14.0
