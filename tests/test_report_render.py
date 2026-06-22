from __future__ import annotations

import io
import os
import warnings

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
    build_pdf,
    chart_funnel,
    chart_history,
    chart_lenses_grouped_bar,
    generate_report,
    lens_label,
    register_fonts,
    render_cover,
    render_footer,
    render_funnel,
    render_history,
    render_kpi_cards,
    render_lenses,
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
    doc_en = _doc(); doc_en.fill_background()
    render_footer(doc_en, ten, _report_data())
    doc_ru = _doc(); doc_ru.fill_background()
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

    def spy(c, rtl=False):
        doc_seen["rtl"] = rtl
        return original(c, rtl=rtl)

    G.Doc = spy
    try:
        build_pdf(data, str(tmp_path / "ar.pdf"), lang="ar")
    finally:
        G.Doc = original
        register_fonts(DEFAULT_LANG)
    assert doc_seen.get("rtl") is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
