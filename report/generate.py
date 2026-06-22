from __future__ import annotations

import argparse
import io
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from pipeline.db import get_conn, get_domain_stats, get_lens_sentiments, init_db
from pipeline.schema import normalize_domain
from report.i18n import DEFAULT_LANG, Translator, available_codes
from report.textshape import is_rtl, shape


BG = "#0e1117"
PANEL = "#161b24"
PANEL_ALT = "#1d2430"
STROKE = "#2a3340"
INK = "#e6edf3"
INK_DIM = "#9aa7b4"
INK_FAINT = "#5d6b7a"

ACCENT = "#4fa9ff"
ACCENT_2 = "#7c6cff"
ACCENT_3 = "#22c79b"
GOOD = "#2fbf71"
BAD = "#f0556d"
WARN = "#e6b34d"

LENS_COLORS = {
    "general": ACCENT,
    "branded": ACCENT_2,
    "comparative": ACCENT_3,
}


def lens_label(t: Translator, lens: str) -> str:
    if lens == "all":
        return t.t("report.all_queries")
    key = f"lens.{lens}"
    return t.t(key) if t.has(key) else lens


FONT = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"
FONT_OBLIQUE = "DejaVuSans-Oblique"

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

_LENS_ORDER = ["general", "branded", "comparative"]

_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"
)

_DEJAVU_FACES = {
    "DejaVuSans": "DejaVuSans.ttf",
    "DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
    "DejaVuSans-Oblique": "DejaVuSans-Oblique.ttf",
}

_NOTO_FACES = {
    "NotoSansSC": "NotoSansSC-Regular.ttf",
    "NotoSansSC-Bold": "NotoSansSC-Bold.ttf",
    "NotoNaskhArabic": "NotoNaskhArabic-Regular.ttf",
    "NotoNaskhArabic-Bold": "NotoNaskhArabic-Bold.ttf",
}

_DEJAVU_STACK = ("DejaVuSans", "DejaVuSans-Bold", "DejaVuSans-Oblique", "DejaVu Sans")

_LANG_FONTS = {
    "zh": ("NotoSansSC", "NotoSansSC-Bold", "NotoSansSC", "Noto Sans SC"),
    "ar": ("NotoNaskhArabic", "NotoNaskhArabic-Bold", "NotoNaskhArabic", "Noto Naskh Arabic"),
}


def _dejavu_dir() -> str:
    return os.path.join(matplotlib.get_data_path(), "fonts", "ttf")


def _register_face(name: str, path: str) -> bool:
    if not os.path.isfile(path):
        return False
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, path))
    fm.fontManager.addfont(path)
    return True


def register_fonts(lang: str = DEFAULT_LANG) -> None:
    global FONT, FONT_BOLD, FONT_OBLIQUE
    ttf_dir = _dejavu_dir()
    for name, fname in _DEJAVU_FACES.items():
        _register_face(name, os.path.join(ttf_dir, fname))

    available = {
        name
        for name, fname in _NOTO_FACES.items()
        if _register_face(name, os.path.join(_FONTS_DIR, fname))
    }

    regular, bold, oblique, family = _DEJAVU_STACK
    spec = _LANG_FONTS.get(lang)
    if spec and spec[0] in available and spec[1] in available:
        regular, bold, oblique, family = spec
        families = [family, "DejaVu Sans"]
    else:
        families = ["DejaVu Sans"]

    FONT, FONT_BOLD, FONT_OBLIQUE = regular, bold, oblique
    plt.rcParams["font.family"] = families
    plt.rcParams["axes.unicode_minus"] = False


@dataclass
class LensMetrics:

    lens: str
    n_queries: int
    n_overviews: int
    overview_coverage: Optional[float]
    n_in_sources: int
    visibility_in_sources: Optional[float]
    n_cited: int
    visibility_in_citations: Optional[float]
    avg_source_position: Optional[float]
    avg_citation_position: Optional[float]
    relative_citation: Optional[float]


@dataclass
class ReportData:

    brand_name: str
    brand_domain: str
    engine: str
    period: str
    run_id: int
    run_at: str
    prev_run_id: Optional[int]
    prev_run_at: Optional[str]
    metrics: dict[str, LensMetrics]
    prev_metrics: dict[str, LensMetrics]
    sentiments: dict[str, list[tuple[str, str]]]
    history: list[tuple[str, dict[str, LensMetrics]]] = field(default_factory=list)
    sentiment_summaries: dict[str, str] = field(default_factory=dict)
    competitors: list[dict] = field(default_factory=list)


def _row_get(row: sqlite3.Row, key: str) -> Any:
    return row[key] if key in row.keys() else None


def _metrics_row_to_obj(row: sqlite3.Row) -> LensMetrics:
    return LensMetrics(
        lens=row["lens"],
        n_queries=int(row["n_queries"] or 0),
        n_overviews=int(row["n_overviews"] or 0),
        overview_coverage=row["overview_coverage"],
        n_in_sources=int(row["n_in_sources"] or 0),
        visibility_in_sources=row["visibility_in_sources"],
        n_cited=int(row["n_cited"] or 0),
        visibility_in_citations=row["visibility_in_citations"],
        avg_source_position=row["avg_source_position"],
        avg_citation_position=row["avg_citation_position"],
        relative_citation=_row_get(row, "relative_citation"),
    )


def _load_metrics_for_run(conn: sqlite3.Connection, run_id: int) -> dict[str, LensMetrics]:
    rows = conn.execute(
        "SELECT * FROM metrics WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {r["lens"]: _metrics_row_to_obj(r) for r in rows}


def _resolve_brand_id(conn: sqlite3.Connection, name: str, domain: str) -> Optional[int]:
    norm = normalize_domain(domain)
    row = conn.execute(
        "SELECT id FROM brands WHERE name = ? AND domain = ?", (name, norm)
    ).fetchone()
    if row is not None:
        return int(row["id"])

    same_name = conn.execute(
        "SELECT domain FROM brands WHERE name = ? ORDER BY domain", (name,)
    ).fetchall()
    if same_name:
        domains = ", ".join(r["domain"] for r in same_name)
        raise ValueError(
            f"brand name {name!r} exists but not for domain {norm!r}; "
            f"known domain(s) for this name: {domains}. "
            f"Re-run with the matching --domain."
        )
    return None


def _completed_runs(
    conn: sqlite3.Connection, brand_id: int, engine: str
) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT r.id, r.run_at, r.status
        FROM runs r
        WHERE r.brand_id = ? AND r.engine = ?
          AND r.status = 'done'
          AND EXISTS (SELECT 1 FROM metrics m WHERE m.run_id = r.id)
        ORDER BY r.run_at DESC, r.id DESC
        """,
        (brand_id, engine),
    ).fetchall()
    return rows


def _load_sentiments(
    conn: sqlite3.Connection, run_id: int, per_lens: int = 4
) -> dict[str, list[tuple[str, str]]]:
    rows = conn.execute(
        """
        SELECT lens, query, sentiment, captured_at
        FROM results
        WHERE run_id = ?
          AND sentiment IS NOT NULL
          AND TRIM(sentiment) != ''
        ORDER BY captured_at DESC, id DESC
        """,
        (run_id,),
    ).fetchall()

    out: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for r in rows:
        lens = r["lens"]
        phrase = (r["sentiment"] or "").strip()
        if not phrase:
            continue
        bucket = out.setdefault(lens, [])
        seen_set = seen.setdefault(lens, set())
        if phrase in seen_set or len(bucket) >= per_lens:
            continue
        seen_set.add(phrase)
        bucket.append(((r["query"] or "").strip(), phrase))
    return out


def load_report_data(
    conn: sqlite3.Connection,
    brand_name: str,
    domain: str,
    engine: str,
    period: str,
) -> ReportData:
    brand_id = _resolve_brand_id(conn, brand_name, domain)
    if brand_id is None:
        raise ValueError(
            f"brand not found: name={brand_name!r} domain={domain!r}"
        )

    runs = _completed_runs(conn, brand_id, engine)
    if not runs:
        raise ValueError(
            f"no completed runs with metrics for brand {brand_name!r} "
            f"and engine {engine!r}"
        )

    focus = runs[0]
    focus_id = int(focus["id"])
    prev = runs[1] if len(runs) > 1 else None
    prev_id = int(prev["id"]) if prev is not None else None

    metrics = _load_metrics_for_run(conn, focus_id)
    prev_metrics = _load_metrics_for_run(conn, prev_id) if prev_id is not None else {}
    sentiments = _load_sentiments(conn, focus_id)
    sentiment_summaries = get_lens_sentiments(conn, focus_id)
    competitors = get_domain_stats(conn, focus_id, "all")[:15]

    brow = conn.execute(
        "SELECT name, domain FROM brands WHERE id = ?", (brand_id,)
    ).fetchone()
    display_domain = brow["domain"] if brow is not None else normalize_domain(domain)

    history: list[tuple[str, dict[str, LensMetrics]]] = []
    if period == "all":
        for r in reversed(runs):
            history.append((r["run_at"], _load_metrics_for_run(conn, int(r["id"]))))

    return ReportData(
        brand_name=brand_name,
        brand_domain=display_domain,
        engine=engine,
        period=period,
        run_id=focus_id,
        run_at=focus["run_at"],
        prev_run_id=prev_id,
        prev_run_at=(prev["run_at"] if prev is not None else None),
        metrics=metrics,
        prev_metrics=prev_metrics,
        sentiments=sentiments,
        history=history,
        sentiment_summaries=sentiment_summaries,
        competitors=competitors,
    )


_DECIMAL_COMMA_LANGS = {"ru"}


def _dec(s: str, lang: str) -> str:
    return s.replace(".", ",") if lang in _DECIMAL_COMMA_LANGS else s


def _pct(x: Optional[float], lang: str = DEFAULT_LANG) -> str:
    return "—" if x is None else _dec(f"{x * 100:.0f}%", lang)


def _num(x: Optional[float], digits: int = 1, lang: str = DEFAULT_LANG) -> str:
    return "—" if x is None else _dec(f"{x:.{digits}f}", lang)


def _fmt_dt(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return iso


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso


@dataclass
class Delta:

    text: str
    color: str
    arrow: str


def _delta_pct(
    t: Translator,
    cur: Optional[float],
    prev: Optional[float],
    higher_is_better: bool = True,
) -> Delta:
    if cur is None and prev is None:
        return Delta(t.t("common.dash"), INK_FAINT, "")
    if prev is None:
        return Delta(t.t("report.delta_new"), INK_DIM, "")
    if cur is None:
        return Delta(t.t("report.delta_no_data"), INK_DIM, "")
    diff = (cur - prev) * 100.0
    if abs(diff) < 0.5:
        return Delta(t.t("report.delta_zero_pp"), INK_DIM, "▬")
    improved = diff > 0 if higher_is_better else diff < 0
    color = GOOD if improved else BAD
    arrow = "▲" if diff > 0 else "▼"
    sign = "+" if diff > 0 else "−"
    return Delta(f"{sign}{abs(diff):.0f} {t.t('report.delta_pp_suffix')}", color, arrow)


def _delta_num(
    t: Translator,
    cur: Optional[float],
    prev: Optional[float],
    higher_is_better: bool = True,
    digits: int = 1,
) -> Delta:
    if cur is None and prev is None:
        return Delta(t.t("common.dash"), INK_FAINT, "")
    if prev is None:
        return Delta(t.t("report.delta_new"), INK_DIM, "")
    if cur is None:
        return Delta(t.t("report.delta_no_data"), INK_DIM, "")
    diff = cur - prev
    if abs(diff) < 10 ** (-digits) / 2:
        return Delta(t.t("report.delta_zero"), INK_DIM, "▬")
    improved = diff > 0 if higher_is_better else diff < 0
    color = GOOD if improved else BAD
    arrow = "▲" if diff > 0 else "▼"
    sign = "+" if diff > 0 else "−"
    return Delta(f"{sign}{_dec(f'{abs(diff):.{digits}f}', t.lang)}", color, arrow)


def _style_axes(ax) -> None:
    ax.set_facecolor("none")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(STROKE)
    ax.tick_params(colors=INK_DIM, labelsize=9, length=0)
    ax.yaxis.label.set_color(INK_DIM)
    ax.xaxis.label.set_color(INK_DIM)
    ax.grid(axis="y", color=STROKE, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=200,
        transparent=True,
        bbox_inches="tight",
        pad_inches=0.06,
    )
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def chart_lenses_grouped_bar(t: Translator, metrics: dict[str, LensMetrics]) -> bytes:
    lenses = [ln for ln in _LENS_ORDER if ln in metrics]
    groups = [
        (t.t("report.chart_group_coverage"), "overview_coverage", ACCENT),
        (t.t("report.chart_group_visibility_sources"), "visibility_in_sources", ACCENT_2),
        (t.t("report.chart_group_visibility_citations"), "visibility_in_citations", ACCENT_3),
    ]

    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    fig.patch.set_alpha(0)
    n_groups = len(groups)
    n_lenses = max(len(lenses), 1)
    bar_w = 0.8 / n_lenses
    x = list(range(n_groups))

    for li, lens in enumerate(lenses):
        vals = []
        for _, attr, _ in groups:
            v = getattr(metrics[lens], attr)
            vals.append((v or 0.0) * 100.0)
        offsets = [xi + (li - (n_lenses - 1) / 2) * bar_w for xi in x]
        bars = ax.bar(
            offsets,
            vals,
            width=bar_w * 0.92,
            color=LENS_COLORS.get(lens, ACCENT),
            label=shape(lens_label(t, lens), t.lang),
            edgecolor="none",
        )
        for rect, v, attr in zip(bars, vals, [g[1] for g in groups]):
            raw = getattr(metrics[lens], attr)
            label = "—" if raw is None else f"{v:.0f}"
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                rect.get_height() + 2,
                label,
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=INK_DIM,
            )

    ax.set_xticks(x)
    ax.set_xticklabels([shape(g[0], t.lang) for g in groups], fontsize=9, color=INK)
    ax.set_ylim(0, 109)
    ax.set_ylabel("%", color=INK_DIM)
    _style_axes(ax)
    leg = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.18),
        ncol=len(lenses),
        frameon=False,
        fontsize=9,
    )
    for txt in leg.get_texts():
        txt.set_color(INK)
    return _fig_to_png(fig)


def chart_funnel(t: Translator, m: LensMetrics) -> bytes:
    stages = [
        (t.t("report.funnel_stage_overview"), m.n_overviews, ACCENT),
        (t.t("report.funnel_stage_sources"), m.n_in_sources, ACCENT_2),
        (t.t("report.funnel_stage_cited"), m.n_cited, ACCENT_3),
    ]
    counts = [s[1] for s in stages]
    base = max(counts[0], 1)

    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    fig.patch.set_alpha(0)

    conv_text = (
        t.t("common.dash")
        if m.relative_citation is None
        else f"{m.relative_citation * 100:.0f}%"
    )
    conv_label = t.t("metrics.relative_citation.label")

    y_positions = list(range(len(stages)))[::-1]
    for (label, count, color), y in zip(stages, y_positions):
        width = count / base
        ax.barh(y, width, height=0.62, color=color, edgecolor="none")
        ax.barh(y, 1.0, height=0.62, color=PANEL_ALT, edgecolor="none", zorder=0)
        ax.barh(y, width, height=0.62, color=color, edgecolor="none", zorder=1)
        ax.text(
            -0.02, y, shape(label, t.lang), ha="right", va="center", fontsize=9.5, color=INK
        )
        ax.text(
            width + 0.015,
            y,
            f"{count}",
            ha="left",
            va="center",
            fontsize=10,
            color=INK,
            fontweight="bold",
        )

    if m.n_overviews > 0:
        src_rate: Optional[float] = m.n_in_sources / m.n_overviews
        cite_rate: Optional[float] = m.n_cited / m.n_overviews
    else:
        src_rate = cite_rate = None

    ax.set_xlim(0, 1.18)
    ax.set_ylim(-0.6, len(stages) - 0.4)
    ax.axis("off")

    src_text = t.t("common.dash") if src_rate is None else f"{src_rate * 100:.0f}%"
    cite_text = t.t("common.dash") if cite_rate is None else f"{cite_rate * 100:.0f}%"
    ax.text(
        0.5,
        -0.55,
        shape(t.t("report.funnel_rates", sources=src_text, citations=cite_text), t.lang),
        ha="center",
        va="center",
        fontsize=9,
        color=INK_DIM,
        transform=ax.get_yaxis_transform(),
    )
    ax.text(
        0.5,
        -0.92,
        shape(f"{conv_label}: {conv_text}", t.lang),
        ha="center",
        va="center",
        fontsize=9,
        color=ACCENT_3,
        fontweight="bold",
        transform=ax.get_yaxis_transform(),
    )
    return _fig_to_png(fig)


def chart_history(
    t: Translator, history: list[tuple[str, dict[str, LensMetrics]]]
) -> Optional[bytes]:
    if len(history) < 2:
        return None
    xs = list(range(len(history)))
    labels = [_fmt_date(run_at) for run_at, _ in history]

    series = [
        (t.t("report.chart_group_coverage"), "overview_coverage", ACCENT),
        (t.t("report.chart_group_visibility_sources"), "visibility_in_sources", ACCENT_2),
        (t.t("report.chart_group_visibility_citations"), "visibility_in_citations", ACCENT_3),
    ]

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    fig.patch.set_alpha(0)
    for name, attr, color in series:
        ys = []
        for _, mm_ in history:
            row = mm_.get("all")
            v = getattr(row, attr) if row is not None else None
            ys.append(None if v is None else v * 100.0)
        ax.plot(
            xs,
            ys,
            marker="o",
            markersize=5,
            linewidth=2.0,
            color=color,
            label=shape(name, t.lang),
        )

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=8.5, color=INK_DIM, rotation=0)
    ax.set_ylim(0, 109)
    ax.set_ylabel("%", color=INK_DIM)
    _style_axes(ax)
    leg = ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=3, frameon=False, fontsize=9)
    for txt in leg.get_texts():
        txt.set_color(INK)
    return _fig_to_png(fig)


class Doc:

    def __init__(self, c: canvas.Canvas, rtl: bool = False):
        self.c = c
        self.y = PAGE_H - MARGIN
        self.rtl = rtl

    def fill_background(self) -> None:
        self.c.setFillColor(BG)
        self.c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    def new_page(self) -> None:
        self.c.showPage()
        self.fill_background()
        self.y = PAGE_H - MARGIN

    def ensure(self, needed: float) -> None:
        if self.y - needed < MARGIN:
            self.new_page()

    def text(
        self,
        s: str,
        size: float,
        color: str = INK,
        font: Optional[str] = None,
        x: Optional[float] = None,
        dy: float = 0.0,
    ) -> None:
        self.c.setFillColor(color)
        self.c.setFont(font or FONT, size)
        if self.rtl and x is None:
            self.c.drawRightString(PAGE_W - MARGIN, self.y + dy, s)
        else:
            xx = MARGIN if x is None else x
            self.c.drawString(xx, self.y + dy, s)

    def text_right(self, s: str, size: float, color: str, font: str, x_right: float, dy: float = 0.0) -> None:
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawRightString(x_right, self.y + dy, s)

    def text_center(self, s: str, size: float, color: str, font: str, cx: float, dy: float = 0.0) -> None:
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawCentredString(cx, self.y + dy, s)

    def move(self, dy: float) -> None:
        self.y -= dy

    def hline(self, color: str = STROKE, width: float = 0.8, inset: float = 0.0) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(MARGIN + inset, self.y, PAGE_W - MARGIN - inset, self.y)

    def rounded_panel(
        self,
        x: float,
        y_top: float,
        w: float,
        h: float,
        fill: str = PANEL,
        stroke: Optional[str] = STROKE,
        radius: float = 6,
        line_width: float = 0.8,
    ) -> None:
        self.c.setFillColor(fill)
        if stroke is not None:
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(line_width)
        self.c.roundRect(
            x, y_top - h, w, h, radius, stroke=(1 if stroke else 0), fill=1
        )

    def accent_bar(self, x: float, y_top: float, h: float, color: str, w: float = 3) -> None:
        self.c.setFillColor(color)
        self.c.roundRect(x, y_top - h, w, h, w / 2, stroke=0, fill=1)

    def image_png(self, png: bytes, max_w: float) -> float:
        reader = ImageReader(io.BytesIO(png))
        iw, ih = reader.getSize()
        scale = max_w / iw
        draw_w = max_w
        draw_h = ih * scale
        self.c.drawImage(
            reader,
            MARGIN,
            self.y - draw_h,
            width=draw_w,
            height=draw_h,
            mask="auto",
            preserveAspectRatio=True,
        )
        return draw_h


def _section_header(doc: Doc, number: str, title: str) -> None:
    doc.ensure(40)
    doc.move(12)
    top = doc.y
    doc.accent_bar(MARGIN, top + 9, 16, ACCENT, w=3)
    num_x = MARGIN + 9
    doc.text(number, 11, ACCENT, FONT_BOLD, x=num_x, dy=0)
    num_w = pdfmetrics.stringWidth(number, FONT_BOLD, 11)
    doc.text(title, 14, INK, FONT_BOLD, x=num_x + num_w + 8, dy=-1)
    doc.move(10)
    doc.hline(STROKE, 0.8)
    doc.move(14)


def render_cover(doc: Doc, t: Translator, data: ReportData, generated_at: datetime) -> None:
    doc.fill_background()

    doc.c.setFillColor(PANEL)
    doc.c.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
    doc.c.setFillColor(ACCENT)
    doc.c.rect(0, PAGE_H - 4 * mm, PAGE_W * 0.42, 4 * mm, stroke=0, fill=1)

    cx = PAGE_W / 2

    doc.y = PAGE_H - 70 * mm
    doc.text_center(t.t("report.cover_eyebrow"), 12, ACCENT, FONT_BOLD, cx)
    doc.move(6 * mm)
    doc.text_center(t.t("report.cover_subtitle"), 10, INK_FAINT, FONT_OBLIQUE, cx)

    doc.move(22 * mm)
    doc.text_center(data.brand_name, 34, INK, FONT_BOLD, cx)
    doc.move(11 * mm)
    doc.text_center(data.brand_domain, 14, INK_DIM, FONT, cx)

    doc.move(26 * mm)
    card_w = PAGE_W - 2 * MARGIN - 30 * mm
    card_x = (PAGE_W - card_w) / 2
    card_top = doc.y
    card_h = 50 * mm
    doc.rounded_panel(card_x, card_top, card_w, card_h, fill=PANEL, stroke=STROKE, radius=10)

    engine_label = data.engine
    period_label = (
        t.t("report.cover_period_today")
        if data.period == "today"
        else t.t("report.cover_period_all")
    )

    rows = [
        (t.t("report.cover_engine"), engine_label),
        (t.t("report.cover_domain"), data.brand_domain),
        (t.t("report.cover_period"), period_label),
        (t.t("report.cover_generated"), generated_at.strftime("%d.%m.%Y %H:%M")),
    ]
    inner_x = card_x + 12 * mm
    inner_right = card_x + card_w - 12 * mm
    row_y = card_top - 12 * mm
    for label, value in rows:
        doc.c.setFillColor(INK_FAINT)
        doc.c.setFont(FONT, 10)
        doc.c.drawString(inner_x, row_y, label)
        doc.c.setFillColor(INK)
        doc.c.setFont(FONT_BOLD, 11)
        doc.c.drawRightString(inner_right, row_y, value)
        doc.c.setStrokeColor(STROKE)
        doc.c.setLineWidth(0.6)
        doc.c.line(inner_x, row_y - 3.5 * mm, inner_right, row_y - 3.5 * mm)
        row_y -= 11 * mm

    doc.y = MARGIN + 6 * mm
    doc.text_center(
        t.t("report.cover_brandline"),
        9,
        INK_FAINT,
        FONT,
        cx,
    )


def render_kpi_cards(doc: Doc, t: Translator, data: ReportData) -> None:
    _section_header(doc, "01", t.t("report.section_kpi"))

    cur = data.metrics.get("all")
    prev = data.prev_metrics.get("all")

    if data.prev_run_at:
        sub = t.t(
            "report.kpi_compare",
            current=_fmt_dt(data.run_at),
            previous=_fmt_dt(data.prev_run_at),
        )
    else:
        sub = t.t("report.kpi_no_prev", current=_fmt_dt(data.run_at))
    doc.text(sub, 9, INK_DIM, FONT)
    doc.move(16)

    def g(attr: str) -> Optional[float]:
        return getattr(cur, attr) if cur is not None else None

    def gp(attr: str) -> Optional[float]:
        return getattr(prev, attr) if prev is not None else None

    lang = t.lang
    lower_better = t.t("common.lower_is_better")
    cards = [
        {
            "label": t.t("metrics.overview_coverage.label"),
            "value": _pct(g("overview_coverage"), lang),
            "sub": t.t(
                "report.card_coverage_sub",
                n_overviews=(cur.n_overviews if cur else 0),
                n_queries=(cur.n_queries if cur else 0),
            ),
            "delta": _delta_pct(t, g("overview_coverage"), gp("overview_coverage"), higher_is_better=True),
            "accent": ACCENT,
        },
        {
            "label": t.t("metrics.visibility_in_sources.label"),
            "value": _pct(g("visibility_in_sources"), lang),
            "sub": t.t(
                "report.card_visibility_sub",
                numerator=(cur.n_in_sources if cur else 0),
                n_overviews=(cur.n_overviews if cur else 0),
            ),
            "delta": _delta_pct(t, g("visibility_in_sources"), gp("visibility_in_sources"), higher_is_better=True),
            "accent": ACCENT_2,
        },
        {
            "label": t.t("metrics.visibility_in_citations.label"),
            "value": _pct(g("visibility_in_citations"), lang),
            "sub": t.t(
                "report.card_visibility_sub",
                numerator=(cur.n_cited if cur else 0),
                n_overviews=(cur.n_overviews if cur else 0),
            ),
            "delta": _delta_pct(t, g("visibility_in_citations"), gp("visibility_in_citations"), higher_is_better=True),
            "accent": ACCENT_3,
        },
        {
            "label": t.t("metrics.avg_source_position.label"),
            "value": _num(g("avg_source_position"), 1, lang),
            "sub": lower_better,
            "delta": _delta_num(t, g("avg_source_position"), gp("avg_source_position"), higher_is_better=False, digits=1),
            "accent": WARN,
        },
        {
            "label": t.t("metrics.avg_citation_position.label"),
            "value": _num(g("avg_citation_position"), 1, lang),
            "sub": lower_better,
            "delta": _delta_num(t, g("avg_citation_position"), gp("avg_citation_position"), higher_is_better=False, digits=1),
            "accent": WARN,
        },
        {
            "label": t.t("metrics.relative_citation.label"),
            "value": _pct(g("relative_citation"), lang),
            "sub": f"{(cur.n_cited if cur else 0)} / {(cur.n_in_sources if cur else 0)}",
            "delta": _delta_pct(t, g("relative_citation"), gp("relative_citation"), higher_is_better=True),
            "accent": ACCENT_3,
        },
    ]

    gap = 6 * mm
    avail = PAGE_W - 2 * MARGIN
    card_w = (avail - gap) / 2
    card_h = 30 * mm

    n_rows = (len(cards) + 1) // 2
    doc.ensure(n_rows * card_h + (n_rows - 1) * gap + 4)
    top0 = doc.y
    positions = [
        (
            MARGIN + (i % 2) * (card_w + gap),
            top0 - (i // 2) * (card_h + gap),
        )
        for i in range(len(cards))
    ]

    for card, (cx0, top) in zip(cards, positions):
        doc.rounded_panel(cx0, top, card_w, card_h, fill=PANEL, stroke=STROKE, radius=8)
        doc.accent_bar(cx0 + 6, top - 7, 16, card["accent"], w=3)

        doc.c.setFillColor(INK_DIM)
        doc.c.setFont(FONT, 9.5)
        doc.c.drawString(cx0 + 14, top - 9 * mm + 4, card["label"])

        doc.c.setFillColor(INK)
        doc.c.setFont(FONT_BOLD, 26)
        doc.c.drawString(cx0 + 13, top - 19 * mm, card["value"])

        d: Delta = card["delta"]
        chip = f"{d.arrow} {d.text}".strip()
        doc.c.setFont(FONT_BOLD, 10)
        doc.c.setFillColor(d.color)
        doc.c.drawRightString(cx0 + card_w - 10, top - 18 * mm, chip)

        doc.c.setFillColor(INK_FAINT)
        doc.c.setFont(FONT, 8.5)
        doc.c.drawString(cx0 + 14, top - card_h + 5 * mm, card["sub"])

    doc.move(n_rows * card_h + (n_rows - 1) * gap + 6)


def render_lenses(doc: Doc, t: Translator, data: ReportData) -> None:
    _section_header(doc, "02", t.t("report.section_lenses"))

    lang = t.lang
    lenses = [ln for ln in _LENS_ORDER if ln in data.metrics]

    col_label_w = 40 * mm
    avail = PAGE_W - 2 * MARGIN
    metric_cols = [
        t.t("report.lenses_table_col_coverage"),
        t.t("report.lenses_table_col_visibility_sources"),
        t.t("report.lenses_table_col_visibility_citations"),
        t.t("report.lenses_table_col_position_sources"),
        t.t("report.lenses_table_col_position_citations"),
    ]
    n_metric = len(metric_cols)
    metric_w = (avail - col_label_w) / n_metric

    row_h = 9 * mm
    header_h = 8 * mm
    table_h = header_h + row_h * (len(lenses) + 1)
    doc.ensure(table_h + 6)

    top = doc.y
    doc.rounded_panel(MARGIN, top, avail, header_h, fill=PANEL_ALT, stroke=None, radius=4)
    doc.c.setFillColor(INK_DIM)
    doc.c.setFont(FONT_BOLD, 9)
    doc.c.drawString(MARGIN + 6, top - header_h + 3 * mm, t.t("report.lenses_table_col_type"))
    for i, mc in enumerate(metric_cols):
        cx_right = MARGIN + col_label_w + metric_w * (i + 1) - 6
        doc.c.drawRightString(cx_right, top - header_h + 3 * mm, mc)

    body_order = lenses + (["all"] if "all" in data.metrics else [])
    row_top = top - header_h
    for idx, lens in enumerate(body_order):
        m = data.metrics[lens]
        is_all = lens == "all"
        bg = PANEL if idx % 2 == 0 else BG
        if is_all:
            bg = PANEL_ALT
        doc.c.setFillColor(bg)
        doc.c.rect(MARGIN, row_top - row_h, avail, row_h, stroke=0, fill=1)

        dot_color = LENS_COLORS.get(lens, INK_FAINT)
        if not is_all:
            doc.c.setFillColor(dot_color)
            doc.c.circle(MARGIN + 9, row_top - row_h / 2, 2.0, stroke=0, fill=1)
        label = lens_label(t, lens)
        doc.c.setFillColor(INK if not is_all else INK)
        doc.c.setFont(FONT_BOLD if is_all else FONT, 9.5)
        doc.c.drawString(MARGIN + (6 if is_all else 15), row_top - row_h / 2 - 3, label)

        values = [
            _pct(m.overview_coverage, lang),
            _pct(m.visibility_in_sources, lang),
            _pct(m.visibility_in_citations, lang),
            _num(m.avg_source_position, 1, lang),
            _num(m.avg_citation_position, 1, lang),
        ]
        doc.c.setFont(FONT_BOLD if is_all else FONT, 9.5)
        for i, val in enumerate(values):
            cx_right = MARGIN + col_label_w + metric_w * (i + 1) - 6
            doc.c.setFillColor(INK)
            doc.c.drawRightString(cx_right, row_top - row_h / 2 - 3, val)

        row_top -= row_h

    doc.c.setStrokeColor(STROKE)
    doc.c.setLineWidth(0.8)
    doc.c.roundRect(MARGIN, top - table_h, avail, table_h, 4, stroke=1, fill=0)

    doc.y = top - table_h
    doc.move(6)
    doc.text(t.t("report.lenses_caption"), 8, INK_FAINT, FONT_OBLIQUE)
    doc.move(10)

    if lenses:
        png = chart_lenses_grouped_bar(t, data.metrics)
        chart_w = PAGE_W - 2 * MARGIN
        reader = ImageReader(io.BytesIO(png))
        iw, ih = reader.getSize()
        h = chart_w / iw * ih
        doc.ensure(h + 6)
        used = doc.image_png(png, chart_w)
        doc.move(used + 6)


def render_funnel(doc: Doc, t: Translator, data: ReportData) -> None:
    _section_header(doc, "03", t.t("report.section_funnel"))

    m = data.metrics.get("all")
    if m is None:
        doc.text(t.t("report.funnel_empty"), 10, INK_DIM, FONT)
        doc.move(12)
        return

    doc.text(
        t.t("report.funnel_intro"),
        9,
        INK_DIM,
        FONT,
    )
    doc.move(10)

    png = chart_funnel(t, m)
    chart_w = PAGE_W - 2 * MARGIN
    reader = ImageReader(io.BytesIO(png))
    iw, ih = reader.getSize()
    h = chart_w / iw * ih
    doc.ensure(h + 6)
    used = doc.image_png(png, chart_w)
    doc.move(used + 8)


def render_history(doc: Doc, t: Translator, data: ReportData) -> None:
    png = chart_history(t, data.history)
    if png is None:
        return
    _section_header(doc, "03b", t.t("report.section_history"))
    doc.text(
        t.t("report.history_intro"),
        9,
        INK_DIM,
        FONT,
    )
    doc.move(10)
    chart_w = PAGE_W - 2 * MARGIN
    reader = ImageReader(io.BytesIO(png))
    iw, ih = reader.getSize()
    h = chart_w / iw * ih
    doc.ensure(h + 6)
    used = doc.image_png(png, chart_w)
    doc.move(used + 8)


def _wrap_text(c: canvas.Canvas, text: str, font: str, size: float, max_w: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if pdfmetrics.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            if pdfmetrics.stringWidth(w, font, size) > max_w:
                piece = ""
                for ch in w:
                    if pdfmetrics.stringWidth(piece + ch, font, size) <= max_w:
                        piece += ch
                    else:
                        lines.append(piece)
                        piece = ch
                cur = piece
            else:
                cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def render_sentiment(doc: Doc, t: Translator, data: ReportData) -> None:
    _section_header(doc, "05", t.t("report.section_sentiment"))

    doc.text(
        t.t("report.sentiment_intro"),
        9,
        INK_DIM,
        FONT,
    )
    doc.move(14)

    avail = PAGE_W - 2 * MARGIN
    all_summary = data.sentiment_summaries.get("all")
    if all_summary:
        for ln_txt in _wrap_text(doc.c, all_summary, FONT_OBLIQUE, 9.5, avail):
            doc.ensure(13)
            doc.text(ln_txt, 9.5, INK_DIM, FONT_OBLIQUE)
            doc.move(12)
        doc.move(4)

    lenses_with_data = [ln for ln in _LENS_ORDER if data.sentiments.get(ln)]
    for ln in data.sentiments:
        if ln not in lenses_with_data:
            lenses_with_data.append(ln)

    if not lenses_with_data:
        doc.text(t.t("report.sentiment_empty"), 10, INK_DIM, FONT)
        doc.move(12)
        return

    by_query = t.t("report.sentiment_by_query")
    text_x = MARGIN + 10 * mm
    text_max_w = avail - 12 * mm

    for lens in lenses_with_data:
        snippets = data.sentiments.get(lens, [])
        if not snippets:
            continue
        color = LENS_COLORS.get(lens, INK_FAINT)

        doc.ensure(18)
        doc.c.setFillColor(color)
        doc.c.circle(MARGIN + 3, doc.y + 3, 2.4, stroke=0, fill=1)
        doc.text(lens_label(t, lens), 11, INK, FONT_BOLD, x=MARGIN + 9)
        doc.move(13)

        lens_summary = data.sentiment_summaries.get(lens)
        if lens_summary:
            for ln_txt in _wrap_text(doc.c, lens_summary, FONT_OBLIQUE, 9.5, text_max_w):
                doc.ensure(13)
                doc.c.setFillColor(INK_DIM)
                doc.c.setFont(FONT_OBLIQUE, 9.5)
                doc.c.drawString(MARGIN + 9, doc.y, ln_txt)
                doc.move(12)
            doc.move(3)

        for query, phrase in snippets:
            phrase_lines = _wrap_text(doc.c, phrase, FONT, 10, text_max_w)
            q_lines = []
            if query:
                q_lines = _wrap_text(doc.c, query, FONT_OBLIQUE, 8, text_max_w)
            block_h = len(phrase_lines) * 13 + len(q_lines) * 10 + 8
            doc.ensure(block_h + 2)

            top = doc.y
            doc.c.setStrokeColor(color)
            doc.c.setLineWidth(2)
            doc.c.line(MARGIN + 4, top + 2, MARGIN + 4, top - (block_h - 8) + 2)

            for ln_txt in phrase_lines:
                doc.c.setFillColor(INK)
                doc.c.setFont(FONT, 10)
                doc.c.drawString(text_x, doc.y, ln_txt)
                doc.move(13)
            for ln_txt in q_lines:
                doc.c.setFillColor(INK_FAINT)
                doc.c.setFont(FONT_OBLIQUE, 8)
                doc.c.drawString(text_x, doc.y, by_query + ln_txt if ln_txt == q_lines[0] else ln_txt)
                doc.move(10)
            doc.move(8)

        doc.move(4)


def render_competitors(doc: Doc, t: Translator, data: ReportData) -> None:
    _section_header(doc, "04", t.t("report.section_competitors"))

    doc.text(t.t("report.competitors_intro"), 9, INK_DIM, FONT)
    doc.move(12)

    comps = data.competitors
    if not comps:
        doc.text(t.t("report.competitors_empty"), 10, INK_DIM, FONT)
        doc.move(12)
        return

    lang = t.lang
    all_m = data.metrics.get("all")
    n_overviews = all_m.n_overviews if all_m is not None else 0

    avail = PAGE_W - 2 * MARGIN
    col_domain_w = 78 * mm
    metric_cols = [
        t.t("report.competitors_col_share_sources"),
        t.t("report.lenses_table_col_position_sources"),
        t.t("report.lenses_table_col_position_citations"),
    ]
    n_metric = len(metric_cols)
    metric_w = (avail - col_domain_w) / n_metric

    row_h = 8 * mm
    header_h = 8 * mm
    table_h = header_h + row_h * len(comps)
    doc.ensure(table_h + 6)

    top = doc.y
    doc.rounded_panel(MARGIN, top, avail, header_h, fill=PANEL_ALT, stroke=None, radius=4)
    doc.c.setFillColor(INK_DIM)
    doc.c.setFont(FONT_BOLD, 9)
    doc.c.drawString(MARGIN + 6, top - header_h + 3 * mm, t.t("report.competitors_col_domain"))
    for i, mc in enumerate(metric_cols):
        cx_right = MARGIN + col_domain_w + metric_w * (i + 1) - 6
        doc.c.drawRightString(cx_right, top - header_h + 3 * mm, mc)

    you = t.t("report.competitors_you")
    row_top = top - header_h
    for idx, d in enumerate(comps):
        is_brand = bool(d["is_brand"])
        bg = PANEL if idx % 2 == 0 else BG
        if is_brand:
            bg = PANEL_ALT
        doc.c.setFillColor(bg)
        doc.c.rect(MARGIN, row_top - row_h, avail, row_h, stroke=0, fill=1)

        if is_brand:
            doc.c.setFillColor(ACCENT)
            doc.c.circle(MARGIN + 9, row_top - row_h / 2, 2.0, stroke=0, fill=1)
        label = d["domain"]
        if is_brand:
            label = f"{label}  ({you})"
        doc.c.setFillColor(INK)
        doc.c.setFont(FONT_BOLD if is_brand else FONT, 9.5)
        doc.c.drawString(MARGIN + (15 if is_brand else 6), row_top - row_h / 2 - 3, label)

        share = (d["appearances_sources"] / n_overviews) if n_overviews else None
        values = [
            _pct(share, lang),
            _num(d["avg_source_position"], 1, lang),
            _num(d["avg_citation_position"], 1, lang),
        ]
        doc.c.setFont(FONT_BOLD if is_brand else FONT, 9.5)
        for i, val in enumerate(values):
            cx_right = MARGIN + col_domain_w + metric_w * (i + 1) - 6
            doc.c.setFillColor(INK)
            doc.c.drawRightString(cx_right, row_top - row_h / 2 - 3, val)

        row_top -= row_h

    doc.c.setStrokeColor(STROKE)
    doc.c.setLineWidth(0.8)
    doc.c.roundRect(MARGIN, top - table_h, avail, table_h, 4, stroke=1, fill=0)

    doc.y = top - table_h
    doc.move(6)
    doc.text(t.t("report.competitors_caption"), 8, INK_FAINT, FONT_OBLIQUE)
    doc.move(10)


def render_footer(doc: Doc, t: Translator, data: ReportData, page_label_only: bool = False) -> None:
    c = doc.c
    c.setStrokeColor(STROKE)
    c.setLineWidth(0.6)
    c.line(MARGIN, MARGIN - 4, PAGE_W - MARGIN, MARGIN - 4)
    c.setFillColor(INK_FAINT)
    c.setFont(FONT, 8)
    c.drawString(
        MARGIN,
        MARGIN - 12,
        f"{t.t('common.app_title')} · {data.brand_name} · {data.engine}",
    )
    c.drawRightString(PAGE_W - MARGIN, MARGIN - 12, t.t("report.footer_report_name"))


def _install_footer_hook(doc: Doc, t: Translator, data: ReportData) -> None:
    original_new_page = doc.new_page

    def new_page_with_footer() -> None:
        render_footer(doc, t, data)
        original_new_page()

    doc.new_page = new_page_with_footer  # type: ignore[assignment]


def _install_rtl_shaping(c: canvas.Canvas, lang: str) -> None:
    base_draw = c.drawString

    def draw(x: float, y: float, text: str, *a: Any, **k: Any) -> Any:
        return base_draw(x, y, shape(text, lang), *a, **k)

    def draw_right(x: float, y: float, text: str, *a: Any, **k: Any) -> Any:
        s = shape(text, lang)
        return base_draw(x - c.stringWidth(s, c._fontname, c._fontsize), y, s, *a, **k)

    def draw_centred(x: float, y: float, text: str, *a: Any, **k: Any) -> Any:
        s = shape(text, lang)
        return base_draw(x - c.stringWidth(s, c._fontname, c._fontsize) / 2.0, y, s, *a, **k)

    c.drawString = draw  # type: ignore[method-assign]
    c.drawRightString = draw_right  # type: ignore[method-assign]
    c.drawCentredString = draw_centred  # type: ignore[method-assign]


def build_pdf(
    data: ReportData,
    out_path: str,
    generated_at: Optional[datetime] = None,
    lang: str = DEFAULT_LANG,
) -> None:
    register_fonts(lang)
    rtl = is_rtl(lang)
    generated_at = generated_at or datetime.now()
    t = Translator(lang)

    parent = os.path.dirname(os.path.abspath(out_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    c = canvas.Canvas(out_path, pagesize=A4)
    if rtl:
        _install_rtl_shaping(c, lang)
    c.setTitle(f"{t.t('report.cover_subtitle')} — {data.brand_name}")
    c.setAuthor(t.t("common.app_title"))
    c.setSubject(t.t("report.cover_subtitle"))

    doc = Doc(c, rtl=rtl)

    render_cover(doc, t, data, generated_at)
    doc.new_page()

    _install_footer_hook(doc, t, data)

    render_kpi_cards(doc, t, data)
    render_lenses(doc, t, data)
    render_funnel(doc, t, data)
    if data.period == "all":
        render_history(doc, t, data)
    render_competitors(doc, t, data)
    render_sentiment(doc, t, data)

    render_footer(doc, t, data)
    c.showPage()
    c.save()


def generate_report(
    db_path: str,
    brand: str,
    domain: str,
    engine: str,
    period: str,
    out_path: str,
    lang: str = DEFAULT_LANG,
) -> ReportData:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        data = load_report_data(conn, brand, domain, engine, period)
    finally:
        conn.close()
    build_pdf(data, out_path, lang=lang)
    return data


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="report.generate",
        description="Generate the dark-themed AI-visibility PDF report.",
    )
    parser.add_argument("--brand", required=True, help="Brand name (as stored in the DB).")
    parser.add_argument("--domain", required=True, help="Target domain of the brand.")
    parser.add_argument("--engine", required=True, help="Engine identifier, e.g. google.")
    parser.add_argument(
        "--period",
        required=True,
        choices=["today", "all"],
        help="today = latest run; all = whole history (with the trend chart).",
    )
    parser.add_argument("--out", required=True, help="Output PDF path.")
    parser.add_argument(
        "--lang",
        default=DEFAULT_LANG,
        help=(
            "UI language code for report chrome (default: en). Registered: "
            + ", ".join(available_codes())
            + ". Unknown codes fall back to English."
        ),
    )
    parser.add_argument("--db", default="data/aeo.db", help="SQLite DB path (default: data/aeo.db).")
    args = parser.parse_args(argv)

    try:
        data = generate_report(
            db_path=args.db,
            brand=args.brand,
            domain=args.domain,
            engine=args.engine,
            period=args.period,
            out_path=args.out,
            lang=args.lang,
        )
    except ValueError as exc:
        print(f"report.generate: {exc}", file=sys.stderr)
        return 1

    print(
        f"report.generate: OK -> {args.out} "
        f"(brand={data.brand_name!r}, run_id={data.run_id}, "
        f"prev_run_id={data.prev_run_id}, period={data.period})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
