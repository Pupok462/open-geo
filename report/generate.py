from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
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

from pipeline.db import (
    find_brand_domains,
    find_brand_id,
    get_conn,
    get_domain_stats,
    get_latest_audit,
    get_lens_sentiments,
    init_db,
)
from pipeline.schema import normalize_domain, normalize_target
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
CONTENT_W = PAGE_W - 2 * MARGIN

T_COVER = 34
T_TITLE = 14
T_BODY = 11
T_TABLE = 9
T_AUDIT_TABLE = 7.5
T_CAPTION = 7.5

LEAD_BODY = 13.0
LEAD_TABLE = 12.0
LEAD_CAPTION = 10.0

GAP_XS = 4.0
GAP_S = 8.0
GAP_M = 14.0
GAP_L = 20.0

CELL_PAD = 6.0
SECTION_ADVANCE = 36.0

_LENS_ORDER = ["general", "branded", "comparative"]

RESULT_OUTCOMES = ("cited", "sources_only", "mention_only", "absent", "no_answer")

_SPREAD_METRICS = (
    "overview_coverage",
    "visibility_in_sources",
    "visibility_in_citations",
    "relative_citation",
    "brand_mention_rate",
    "avg_source_position",
    "avg_citation_position",
)

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
    n_brand_mentions: int = 0
    brand_mention_rate: Optional[float] = None


@dataclass
class ResultRow:

    query: str
    lens: str
    overview_present: bool
    source_ranks: list[int] = field(default_factory=list)
    citation_ranks: list[int] = field(default_factory=list)
    brand_in_answer_text: bool = False
    sentiment: Optional[str] = None


def result_outcome(row: ResultRow) -> str:
    if not row.overview_present:
        return "no_answer"
    if row.citation_ranks:
        return "cited"
    if row.source_ranks:
        return "sources_only"
    if row.brand_in_answer_text:
        return "mention_only"
    return "absent"


@dataclass
class WeekPoint:

    week: str
    monday: str
    n_runs: int
    metrics: LensMetrics


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
    audit: Optional[dict] = None
    results: list[ResultRow] = field(default_factory=list)
    n_runs: int = 1
    group_id: Optional[str] = None
    n_repeats: int = 1
    spread: dict[str, tuple[float, float]] = field(default_factory=dict)
    history_weekly: list[WeekPoint] = field(default_factory=list)


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
        n_brand_mentions=int(_row_get(row, "n_brand_mentions") or 0),
        brand_mention_rate=_row_get(row, "brand_mention_rate"),
    )


def _load_metrics_for_run(conn: sqlite3.Connection, run_id: int) -> dict[str, LensMetrics]:
    rows = conn.execute(
        "SELECT * FROM metrics WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {r["lens"]: _metrics_row_to_obj(r) for r in rows}


def _metrics_columns(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r["name"] for r in conn.execute("PRAGMA table_info(metrics)").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _has_group_column(conn: sqlite3.Connection) -> bool:
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    except sqlite3.OperationalError:
        return False
    return "group_id" in cols


def _aggregate_period_metrics(
    conn: sqlite3.Connection,
    brand_id: int,
    engine: str,
    run_ids: Optional[list[int]] = None,
) -> dict[str, LensMetrics]:
    has_mentions = "n_brand_mentions" in _metrics_columns(conn)
    mention_select = (
        """,
               SUM(m.n_brand_mentions) AS n_brand_mentions,
               SUM(CASE WHEN m.n_brand_mentions IS NOT NULL
                        THEN m.n_overviews END) AS mention_nov
        """
        if has_mentions
        else "\n"
    )
    sql = f"""
        SELECT m.lens,
               SUM(m.n_queries)    AS n_queries,
               SUM(m.n_overviews)  AS n_overviews,
               SUM(m.n_in_sources) AS n_in_sources,
               SUM(m.n_cited)      AS n_cited,
               SUM(CASE WHEN m.avg_source_position IS NOT NULL
                        THEN m.avg_source_position * m.n_in_sources END) AS sum_src_rank,
               SUM(CASE WHEN m.avg_citation_position IS NOT NULL
                        THEN m.avg_citation_position * m.n_cited END) AS sum_cit_rank{mention_select}
        FROM metrics m
        JOIN runs r ON r.id = m.run_id
        WHERE r.brand_id = ? AND r.engine = ? AND r.status = 'done'
    """
    params: list[Any] = [brand_id, engine]
    if run_ids:
        sql += f" AND m.run_id IN ({','.join('?' * len(run_ids))})"
        params.extend(run_ids)
    sql += " GROUP BY m.lens"

    out: dict[str, LensMetrics] = {}
    for r in conn.execute(sql, params).fetchall():
        n_queries = int(r["n_queries"] or 0)
        n_overviews = int(r["n_overviews"] or 0)
        n_in_sources = int(r["n_in_sources"] or 0)
        n_cited = int(r["n_cited"] or 0)
        sum_src = r["sum_src_rank"]
        sum_cit = r["sum_cit_rank"]
        n_mentions = r["n_brand_mentions"] if has_mentions else None
        mention_nov = r["mention_nov"] if has_mentions else None
        out[r["lens"]] = LensMetrics(
            lens=r["lens"],
            n_queries=n_queries,
            n_overviews=n_overviews,
            overview_coverage=(n_overviews / n_queries) if n_queries else None,
            n_in_sources=n_in_sources,
            visibility_in_sources=(n_in_sources / n_overviews) if n_overviews else None,
            n_cited=n_cited,
            visibility_in_citations=(n_cited / n_overviews) if n_overviews else None,
            avg_source_position=(
                (sum_src / n_in_sources)
                if n_in_sources and sum_src is not None
                else None
            ),
            avg_citation_position=(
                (sum_cit / n_cited) if n_cited and sum_cit is not None else None
            ),
            relative_citation=(n_cited / n_in_sources) if n_in_sources else None,
            n_brand_mentions=int(n_mentions) if n_mentions is not None else 0,
            brand_mention_rate=(
                n_mentions / mention_nov
                if n_mentions is not None and mention_nov
                else None
            ),
        )
    return out


def _group_run_ids(
    conn: sqlite3.Connection, brand_id: int, engine: str, group_id: str
) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM runs WHERE brand_id = ? AND engine = ? AND group_id = ? "
        "AND status = 'done' ORDER BY run_at ASC, id ASC",
        (brand_id, engine, group_id),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def _group_spread(
    conn: sqlite3.Connection, run_ids: list[int], lens: str = "all"
) -> dict[str, tuple[float, float]]:
    if not run_ids:
        return {}
    marks = ",".join("?" * len(run_ids))
    rows = conn.execute(
        f"SELECT * FROM metrics WHERE run_id IN ({marks}) AND lens = ?",
        [*run_ids, lens],
    ).fetchall()
    acc: dict[str, list[float]] = {}
    for r in rows:
        d = dict(r)
        for m in _SPREAD_METRICS:
            v = d.get(m)
            if v is not None:
                acc.setdefault(m, []).append(float(v))
    return {m: (min(vs), max(vs)) for m, vs in acc.items()}


def _weekly_rollup(history: list[tuple[str, dict[str, LensMetrics]]]) -> list[WeekPoint]:
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for run_at, per_lens in history:
        m = per_lens.get("all")
        if m is None:
            continue
        try:
            dt = datetime.fromisoformat(str(run_at).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        iso = dt.date().isocalendar()
        key = (iso[0], iso[1])
        b = buckets.setdefault(
            key,
            {
                "monday": dt.date() - timedelta(days=dt.date().isoweekday() - 1),
                "n_runs": 0,
                "n_queries": 0,
                "n_overviews": 0,
                "n_in_sources": 0,
                "n_cited": 0,
                "sum_src": None,
                "sum_cit": None,
                "n_mentions": None,
                "mention_nov": 0,
            },
        )
        b["n_runs"] += 1
        b["n_queries"] += int(m.n_queries or 0)
        b["n_overviews"] += int(m.n_overviews or 0)
        b["n_in_sources"] += int(m.n_in_sources or 0)
        b["n_cited"] += int(m.n_cited or 0)
        if m.avg_source_position is not None:
            b["sum_src"] = (b["sum_src"] or 0.0) + m.avg_source_position * int(
                m.n_in_sources or 0
            )
        if m.avg_citation_position is not None:
            b["sum_cit"] = (b["sum_cit"] or 0.0) + m.avg_citation_position * int(
                m.n_cited or 0
            )
        if m.n_brand_mentions is not None:
            b["n_mentions"] = (b["n_mentions"] or 0) + int(m.n_brand_mentions)
            b["mention_nov"] += int(m.n_overviews or 0)

    out: list[WeekPoint] = []
    for (year, week), b in sorted(buckets.items()):
        nq, nov = b["n_queries"], b["n_overviews"]
        nis, nc = b["n_in_sources"], b["n_cited"]
        out.append(
            WeekPoint(
                week=f"{year}-W{week:02d}",
                monday=f"{b['monday'].isoformat()}T00:00:00+00:00",
                n_runs=b["n_runs"],
                metrics=LensMetrics(
                    lens="all",
                    n_queries=nq,
                    n_overviews=nov,
                    overview_coverage=(nov / nq) if nq else None,
                    n_in_sources=nis,
                    visibility_in_sources=(nis / nov) if nov else None,
                    n_cited=nc,
                    visibility_in_citations=(nc / nov) if nov else None,
                    avg_source_position=(
                        b["sum_src"] / nis if nis and b["sum_src"] is not None else None
                    ),
                    avg_citation_position=(
                        b["sum_cit"] / nc if nc and b["sum_cit"] is not None else None
                    ),
                    relative_citation=(nc / nis) if nis else None,
                    n_brand_mentions=int(b["n_mentions"] or 0),
                    brand_mention_rate=(
                        b["n_mentions"] / b["mention_nov"]
                        if b["n_mentions"] is not None and b["mention_nov"]
                        else None
                    ),
                ),
            )
        )
    return out


def _int_list(raw: Optional[str]) -> list[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for v in parsed:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _load_results(conn: sqlite3.Connection, run_id: int) -> list[ResultRow]:
    rows = conn.execute(
        """
        SELECT query, lens, overview_present, target_source_ranks_json,
               target_citation_ranks_json, brand_in_answer_text, sentiment
        FROM results WHERE run_id = ? ORDER BY id ASC
        """,
        (run_id,),
    ).fetchall()
    out: list[ResultRow] = []
    for r in rows:
        sentiment = (r["sentiment"] or "").strip() or None
        out.append(
            ResultRow(
                query=(r["query"] or "").strip(),
                lens=r["lens"] or "",
                overview_present=bool(r["overview_present"]),
                source_ranks=_int_list(r["target_source_ranks_json"]),
                citation_ranks=_int_list(r["target_citation_ranks_json"]),
                brand_in_answer_text=bool(r["brand_in_answer_text"]),
                sentiment=sentiment,
            )
        )
    return out


def _load_competitors_period(
    conn: sqlite3.Connection, brand_id: int, engine: str, lens: str = "all"
) -> list[dict]:
    try:
        rows = conn.execute(
            """
            SELECT d.domain,
                   MAX(d.is_brand) AS is_brand,
                   SUM(d.appearances_sources) AS app_s,
                   SUM(d.appearances_citations) AS app_c,
                   SUM(d.sum_min_source_rank) AS sum_s,
                   SUM(d.sum_min_citation_rank) AS sum_c
            FROM domain_stats d JOIN runs r ON r.id = d.run_id
            WHERE r.brand_id = ? AND r.engine = ? AND r.status = 'done' AND d.lens = ?
            GROUP BY d.domain
            """,
            (brand_id, engine, lens),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise
    out: list[dict] = []
    for r in rows:
        app_s = int(r["app_s"] or 0)
        app_c = int(r["app_c"] or 0)
        sum_s = r["sum_s"]
        sum_c = r["sum_c"]
        out.append(
            {
                "domain": r["domain"],
                "is_brand": bool(r["is_brand"]),
                "appearances_sources": app_s,
                "appearances_citations": app_c,
                "avg_source_position": (
                    (sum_s / app_s) if app_s and sum_s is not None else None
                ),
                "avg_citation_position": (
                    (sum_c / app_c) if app_c and sum_c is not None else None
                ),
            }
        )
    out.sort(
        key=lambda d: (-d["appearances_sources"], -d["appearances_citations"], d["domain"])
    )
    return out


def _with_shares(comps: list[dict], n_overviews: int) -> list[dict]:
    for d in comps:
        d["share_sources"] = (
            d.get("appearances_sources", 0) / n_overviews if n_overviews else None
        )
        d["share_citations"] = (
            d.get("appearances_citations", 0) / n_overviews if n_overviews else None
        )
    return comps


def _resolve_brand_id(conn: sqlite3.Connection, name: str, domain: str) -> Optional[int]:
    norm = normalize_target(domain)
    brand_id = find_brand_id(conn, name, domain)
    if brand_id is not None:
        return brand_id

    same_name = find_brand_domains(conn, name)
    if same_name:
        domains = ", ".join(same_name)
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
    results = _load_results(conn, focus_id)

    group_id: Optional[str] = None
    if _has_group_column(conn):
        grow = conn.execute(
            "SELECT group_id FROM runs WHERE id = ?", (focus_id,)
        ).fetchone()
        group_id = grow["group_id"] if grow is not None else None

    n_runs = 1
    n_repeats = 1
    spread: dict[str, tuple[float, float]] = {}

    if period == "all":
        folded = _aggregate_period_metrics(conn, brand_id, engine)
        if folded:
            metrics = folded
        n_runs = len(runs)
        prev_id, prev = None, None
        prev_metrics = {}
    elif group_id:
        grp_ids = _group_run_ids(conn, brand_id, engine, group_id)
        if len(grp_ids) > 1:
            folded = _aggregate_period_metrics(conn, brand_id, engine, run_ids=grp_ids)
            if folded:
                metrics = folded
            spread = _group_spread(conn, grp_ids, "all")
            n_repeats = len(grp_ids)
            n_runs = len(grp_ids)
            prev_id, prev = None, None
            prev_metrics = {}

    if period == "all":
        competitors = _load_competitors_period(conn, brand_id, engine, "all")[:15]
        denom_metrics = metrics.get("all")
    else:
        competitors = get_domain_stats(conn, focus_id, "all")[:15]
        denom_metrics = _load_metrics_for_run(conn, focus_id).get("all")
    competitors = _with_shares(
        competitors, denom_metrics.n_overviews if denom_metrics is not None else 0
    )

    brow = conn.execute(
        "SELECT name, domain FROM brands WHERE id = ?", (brand_id,)
    ).fetchone()
    display_domain = brow["domain"] if brow is not None else normalize_target(domain)

    audit_row = get_latest_audit(conn, normalize_domain(domain), engine)
    audit: Optional[dict] = None
    if audit_row is not None:
        parsed = json.loads(audit_row["result_json"])
        if isinstance(parsed, dict):
            parsed.setdefault("checked_at", audit_row["checked_at"])
            parsed.setdefault("verdict", audit_row["verdict"])
            parsed.setdefault("score", audit_row["score"])
            parsed.setdefault("target", audit_row["target"])
            parsed.setdefault("domain", audit_row["domain"])
            audit = parsed

    history: list[tuple[str, dict[str, LensMetrics]]] = []
    history_weekly: list[WeekPoint] = []
    if period == "all":
        for r in reversed(runs):
            history.append((r["run_at"], _load_metrics_for_run(conn, int(r["id"]))))
        history_weekly = _weekly_rollup(history)

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
        audit=audit,
        results=results,
        n_runs=n_runs,
        group_id=group_id,
        n_repeats=n_repeats,
        spread=spread,
        history_weekly=history_weekly,
    )


_DECIMAL_COMMA_LANGS = {"ru"}


def _dec(s: str, lang: str) -> str:
    return s.replace(".", ",") if lang in _DECIMAL_COMMA_LANGS else s


def _pct(x: Optional[float], lang: str = DEFAULT_LANG) -> str:
    return "—" if x is None else _dec(f"{x * 100:.0f}%", lang)


def _num(x: Optional[float], digits: int = 1, lang: str = DEFAULT_LANG) -> str:
    return "—" if x is None else _dec(f"{x:.{digits}f}", lang)


def _fmt_iso(iso: Optional[str], fmt: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime(fmt)
    except (ValueError, TypeError):
        return iso


def _fmt_dt(iso: Optional[str]) -> str:
    return _fmt_iso(iso, "%d.%m.%Y %H:%M")


def _fmt_date(iso: Optional[str]) -> str:
    return _fmt_iso(iso, "%d.%m.%Y")


@dataclass
class Delta:

    text: str
    color: str
    arrow: str


def _delta_none_case(
    t: Translator, cur: Optional[float], prev: Optional[float]
) -> Optional[Delta]:
    if cur is None and prev is None:
        return Delta(t.t("common.dash"), INK_FAINT, "")
    if prev is None:
        return Delta(t.t("report.delta_new"), INK_DIM, "")
    if cur is None:
        return Delta(t.t("report.delta_no_data"), INK_DIM, "")
    return None


def _delta_dir(diff: float, higher_is_better: bool) -> tuple[str, str, str]:
    improved = diff > 0 if higher_is_better else diff < 0
    color = GOOD if improved else BAD
    arrow = "▲" if diff > 0 else "▼"
    sign = "+" if diff > 0 else "−"
    return color, arrow, sign


def _delta_pct(
    t: Translator,
    cur: Optional[float],
    prev: Optional[float],
    higher_is_better: bool = True,
) -> Delta:
    nd = _delta_none_case(t, cur, prev)
    if nd is not None:
        return nd
    diff = (cur - prev) * 100.0
    if abs(diff) < 0.5:
        return Delta(t.t("report.delta_zero_pp"), INK_DIM, "▬")
    color, arrow, sign = _delta_dir(diff, higher_is_better)
    return Delta(f"{sign}{abs(diff):.0f} {t.t('report.delta_pp_suffix')}", color, arrow)


def _delta_num(
    t: Translator,
    cur: Optional[float],
    prev: Optional[float],
    higher_is_better: bool = True,
    digits: int = 1,
) -> Delta:
    nd = _delta_none_case(t, cur, prev)
    if nd is not None:
        return nd
    diff = cur - prev
    if abs(diff) < 10 ** (-digits) / 2:
        return Delta(t.t("report.delta_zero"), INK_DIM, "▬")
    color, arrow, sign = _delta_dir(diff, higher_is_better)
    return Delta(f"{sign}{_dec(f'{abs(diff):.{digits}f}', t.lang)}", color, arrow)


def _mpl_lays_out_rtl() -> bool:
    try:
        from matplotlib.ft2font import FT2Font
    except Exception:
        return False
    return hasattr(FT2Font, "_layout")


_MPL_RTL_LAYOUT = _mpl_lays_out_rtl()


def _chart_text(text: str, lang: Optional[str]) -> str:
    if _MPL_RTL_LAYOUT:
        return text
    return shape(text, lang)


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
            label=_chart_text(lens_label(t, lens), t.lang),
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
    ax.set_xticklabels([_chart_text(g[0], t.lang) for g in groups], fontsize=9, color=INK)
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
        ax.barh(y, 1.0, height=0.62, color=PANEL_ALT, edgecolor="none", zorder=0)
        ax.barh(y, width, height=0.62, color=color, edgecolor="none", zorder=1)
        ax.text(
            -0.02, y, _chart_text(label, t.lang), ha="right", va="center", fontsize=9.5, color=INK
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
        _chart_text(t.t("report.funnel_rates", sources=src_text, citations=cite_text), t.lang),
        ha="center",
        va="center",
        fontsize=9,
        color=INK_DIM,
        transform=ax.get_yaxis_transform(),
    )
    ax.text(
        0.5,
        -0.92,
        _chart_text(f"{conv_label}: {conv_text}", t.lang),
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
            label=_chart_text(name, t.lang),
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

    def __init__(self, c: canvas.Canvas, rtl: bool = False, lang: str = DEFAULT_LANG):
        self.c = c
        self.y = PAGE_H - MARGIN
        self.rtl = rtl
        self.lang = lang or DEFAULT_LANG

    def text_w(self, s: str, font: str, size: float) -> float:
        return pdfmetrics.stringWidth(shape(s, self.lang), font, size)

    def fill_background(self) -> None:
        self.c.setFillColor(BG)
        self.c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    def new_page(self) -> None:
        self.c.showPage()
        self.fill_background()
        self.y = PAGE_H - MARGIN

    def fits(self, needed: float) -> bool:
        return self.y - needed >= MARGIN

    def ensure(self, needed: float) -> None:
        if not self.fits(needed):
            self.new_page()

    def keep_with(self, header_h: float, block_h: float) -> None:
        self.ensure(header_h + block_h)

    def space_left(self) -> float:
        return self.y - MARGIN

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


@dataclass
class Cell:

    text: str
    color: Optional[str] = None
    badge: Optional[str] = None
    bold: bool = False


@dataclass
class Column:

    label: str
    align: str = "left"
    wrap: bool = False
    grow: float = 1.0


@dataclass
class TableRow:

    cells: list[Any]
    highlight: bool = False
    marker: Optional[str] = None


ROW_PAD = 5.0
MIN_COL_W = 13 * mm
MARKER_INDENT = 9.0
WRAP_FLOOR_CAP = 0.25 * CONTENT_W
FIT_EPS = 0.6


def _as_cell(value: Any) -> Cell:
    return value if isinstance(value, Cell) else Cell(str(value))


def _cell_font(cell: Cell, row: TableRow) -> str:
    return FONT_BOLD if (cell.bold or row.highlight) else FONT


def _cell_text(cell: Cell) -> str:
    return cell.text if cell.text is not None else ""


def _badge_w(cell: Cell, size: float) -> float:
    if not cell.badge:
        return 0.0
    return pdfmetrics.stringWidth(cell.badge, FONT_BOLD, size - 1.5) + 12.0


def _shrink_to_fit(widths: list[float], lower: list[float]) -> list[float]:
    excess = sum(widths) - CONTENT_W
    if excess <= 0:
        return list(widths)
    room = [max(0.0, widths[i] - lower[i]) for i in range(len(widths))]
    pool = sum(room)
    if pool <= 0:
        return list(widths)
    take = min(excess, pool)
    return [widths[i] - take * room[i] / pool for i in range(len(widths))]


def _column_metrics(
    columns: list[Column], rows: list[TableRow], size: float
) -> tuple[list[float], list[float], list[float]]:
    has_marker = any(r.marker for r in rows)
    natural: list[float] = []
    floor: list[float] = []
    hard_min: list[float] = []

    for i, col in enumerate(columns):
        indent = MARKER_INDENT if (i == 0 and has_marker) else 0.0
        head_w = (
            pdfmetrics.stringWidth(col.label, FONT_BOLD, size) + 2 * CELL_PAD + FIT_EPS
        )
        nat = head_w
        longest_word = 0.0
        for row in rows:
            cell = _as_cell(row.cells[i]) if i < len(row.cells) else Cell("")
            text = _cell_text(cell)
            font = _cell_font(cell, row)
            w = (
                pdfmetrics.stringWidth(text, font, size)
                + _badge_w(cell, size)
                + 2 * CELL_PAD
                + indent
                + FIT_EPS
            )
            nat = max(nat, w)
            for word in text.split():
                longest_word = max(longest_word, pdfmetrics.stringWidth(word, font, size))
        head_word = max(
            (pdfmetrics.stringWidth(word, FONT_BOLD, size) for word in col.label.split()),
            default=0.0,
        ) + 2 * CELL_PAD + FIT_EPS
        natural.append(nat)
        floor.append(
            min(
                nat,
                max(
                    head_word,
                    min(longest_word + 2 * CELL_PAD + indent + FIT_EPS, WRAP_FLOOR_CAP),
                ),
            )
            if col.wrap
            else nat
        )
        hard_min.append(min(nat, max(MIN_COL_W, head_word)))

    return natural, floor, hard_min


_TABLE_SIZE_STEPS = (T_TABLE, 8.5, 8.0, 7.5, 7.0)


def fit_table_size(
    columns: list[Column],
    rows: list[TableRow],
    steps: tuple[float, ...] = _TABLE_SIZE_STEPS,
) -> float:
    for size in steps:
        _, floor, _ = _column_metrics(columns, rows, size)
        if sum(floor) <= CONTENT_W:
            return size
    return steps[-1]


def _wrap_budget_widths(
    columns: list[Column], natural: list[float], floor: list[float]
) -> Optional[list[float]]:
    wrap_idx = [i for i, col in enumerate(columns) if col.wrap]
    if not wrap_idx:
        return None
    fixed = sum(natural[i] for i in range(len(columns)) if i not in wrap_idx)
    budget = CONTENT_W - fixed
    if budget < sum(floor[i] for i in wrap_idx):
        return None

    widths = list(natural)
    pending = list(wrap_idx)
    for i in pending:
        widths[i] = floor[i]
    extra = budget - sum(floor[i] for i in wrap_idx)
    while pending and extra > 0.5:
        weights = [max(columns[i].grow, 0.01) for i in pending]
        wsum = sum(weights)
        capped: list[int] = []
        used = 0.0
        for i, weight in zip(pending, weights):
            room = natural[i] - widths[i]
            take = min(room, extra * weight / wsum)
            widths[i] += take
            used += take
            if natural[i] - widths[i] <= 0.5:
                capped.append(i)
        extra -= used
        if used <= 0.5:
            break
        pending = [i for i in pending if i not in capped]
    return widths


def _resolve_size(
    columns: list[Column], rows: list[TableRow], size: Optional[float]
) -> float:
    return fit_table_size(columns, rows) if size is None else size


def _column_widths(
    columns: list[Column], rows: list[TableRow], size: float
) -> list[float]:
    n = len(columns)
    natural, floor, hard_min = _column_metrics(columns, rows, size)

    total = sum(natural)
    if total <= CONTENT_W:
        slack = CONTENT_W - total
        weights = [max(c.grow, 0.0) for c in columns]
        wsum = sum(weights)
        if wsum <= 0:
            weights = [1.0] * n
            wsum = float(n)
        widths = [natural[i] + slack * weights[i] / wsum for i in range(n)]
    else:
        widths = _wrap_budget_widths(columns, natural, floor)
        if widths is None:
            widths = _shrink_to_fit(natural, floor)
            if sum(widths) > CONTENT_W:
                widths = _shrink_to_fit(widths, hard_min)
            if sum(widths) > CONTENT_W:
                scale = CONTENT_W / sum(widths)
                widths = [w * scale for w in widths]

    drift = CONTENT_W - sum(widths)
    widest = max(range(n), key=lambda i: widths[i])
    widths[widest] += drift
    return widths


def _row_lines(
    doc: Doc,
    columns: list[Column],
    widths: list[float],
    row: TableRow,
    size: float,
    has_marker: bool,
) -> list[list[str]]:
    out: list[list[str]] = []
    for i, col in enumerate(columns):
        cell = _as_cell(row.cells[i]) if i < len(row.cells) else Cell("")
        text = _cell_text(cell)
        font = _cell_font(cell, row)
        indent = MARKER_INDENT if (i == 0 and has_marker) else 0.0
        inner = widths[i] - 2 * CELL_PAD - indent - _badge_w(cell, size)
        if inner <= 0:
            out.append([""])
        elif col.wrap:
            out.append(_wrap_text(doc.c, text, font, size, inner))
        else:
            out.append([_truncate_to_width(text, font, size, inner)])
    return out


@dataclass
class TableLayout:

    widths: list[float]
    header_lines: list[list[str]]
    header_h: float
    heights: list[float]
    lines: list[list[list[str]]]


def _table_layout(
    doc: Doc, columns: list[Column], rows: list[TableRow], size: float
) -> TableLayout:
    widths = _column_widths(columns, rows, size)
    has_marker = any(r.marker for r in rows)
    header_lines = [
        _wrap_text(doc.c, col.label, FONT_BOLD, size, max(widths[i] - 2 * CELL_PAD, 1.0))
        for i, col in enumerate(columns)
    ]
    header_h = max((len(ls) for ls in header_lines), default=1) * LEAD_TABLE + 2 * ROW_PAD
    lines: list[list[list[str]]] = []
    heights: list[float] = []
    for row in rows:
        row_lines = _row_lines(doc, columns, widths, row, size, has_marker)
        n_lines = max((len(ls) for ls in row_lines), default=1)
        lines.append(row_lines)
        heights.append(n_lines * LEAD_TABLE + 2 * ROW_PAD)
    return TableLayout(widths, header_lines, header_h, heights, lines)


def measure_table(
    doc: Doc, columns: list[Column], rows: list[TableRow], size: Optional[float] = None
) -> float:
    if not rows:
        return 0.0
    layout = _table_layout(doc, columns, rows, _resolve_size(columns, rows, size))
    return layout.header_h + sum(layout.heights)


def table_min_height(
    doc: Doc, columns: list[Column], rows: list[TableRow], size: Optional[float] = None
) -> float:
    if not rows:
        return 0.0
    layout = _table_layout(doc, columns, rows, _resolve_size(columns, rows, size))
    return layout.header_h + layout.heights[0]


def _draw_table_header(
    doc: Doc, columns: list[Column], layout: TableLayout, size: float
) -> None:
    top = doc.y
    doc.rounded_panel(
        MARGIN, top, CONTENT_W, layout.header_h, fill=PANEL_ALT, stroke=None, radius=4
    )
    doc.c.setFillColor(INK_DIM)
    doc.c.setFont(FONT_BOLD, size)
    x = MARGIN
    for i, (col, w) in enumerate(zip(columns, layout.widths)):
        baseline = top - ROW_PAD - LEAD_TABLE + 3.5
        for line in layout.header_lines[i]:
            if col.align == "right":
                doc.c.drawRightString(x + w - CELL_PAD, baseline, line)
            else:
                doc.c.drawString(x + CELL_PAD, baseline, line)
            baseline -= LEAD_TABLE
        x += w
    doc.y = top - layout.header_h


def _draw_badge(doc: Doc, x: float, baseline: float, text: str, size: float) -> None:
    small = size - 1.5
    w = pdfmetrics.stringWidth(text, FONT_BOLD, small) + 8.0
    doc.c.setStrokeColor(ACCENT)
    doc.c.setFillColor(PANEL_ALT)
    doc.c.setLineWidth(0.7)
    doc.c.roundRect(x, baseline - 2.5, w, small + 4.5, 3, stroke=1, fill=1)
    doc.c.setFillColor(ACCENT)
    doc.c.setFont(FONT_BOLD, small)
    doc.c.drawString(x + 4.0, baseline, text)


def _draw_table_row(
    doc: Doc,
    columns: list[Column],
    widths: list[float],
    row: TableRow,
    row_lines: list[list[str]],
    row_h: float,
    size: float,
    zebra_index: int,
    zebra: bool,
    has_marker: bool,
) -> None:
    top = doc.y
    if row.highlight:
        bg = PANEL_ALT
    elif zebra and zebra_index % 2 == 0:
        bg = PANEL
    else:
        bg = BG
    doc.c.setFillColor(bg)
    doc.c.rect(MARGIN, top - row_h, CONTENT_W, row_h, stroke=0, fill=1)

    x = MARGIN
    for i, (col, w) in enumerate(zip(columns, widths)):
        cell = _as_cell(row.cells[i]) if i < len(row.cells) else Cell("")
        font = _cell_font(cell, row)
        indent = MARKER_INDENT if (i == 0 and has_marker) else 0.0
        if i == 0 and row.marker:
            doc.c.setFillColor(row.marker)
            doc.c.circle(x + CELL_PAD + 2.0, top - ROW_PAD - LEAD_TABLE / 2 + 1.0, 2.0, stroke=0, fill=1)
        color = cell.color or INK
        baseline = top - ROW_PAD - LEAD_TABLE + 3.5
        for line in row_lines[i]:
            doc.c.setFillColor(color)
            doc.c.setFont(font, size)
            if col.align == "right":
                doc.c.drawRightString(x + w - CELL_PAD, baseline, line)
            else:
                doc.c.drawString(x + CELL_PAD + indent, baseline, line)
            baseline -= LEAD_TABLE
        if cell.badge:
            last = row_lines[i][-1] if row_lines[i] else ""
            bx = x + CELL_PAD + indent + pdfmetrics.stringWidth(last, font, size) + 5.0
            _draw_badge(doc, bx, top - ROW_PAD - LEAD_TABLE + 3.5, cell.badge, size)
        x += w

    doc.y = top - row_h
    doc.c.setStrokeColor(STROKE)
    doc.c.setLineWidth(0.8)
    doc.c.line(MARGIN, doc.y, PAGE_W - MARGIN, doc.y)


def draw_table(
    doc: Doc,
    t: Translator,
    columns: list[Column],
    rows: list[TableRow],
    caption: Optional[str] = None,
    size: Optional[float] = None,
    zebra: bool = True,
    group_title: Optional[str] = None,
    group_color: str = ACCENT,
) -> None:
    if not rows:
        doc.text(t.t("common.no_data"), 10, INK_DIM, FONT)
        doc.move(LEAD_BODY)
        return

    size = _resolve_size(columns, rows, size)
    layout = _table_layout(doc, columns, rows, size)
    heights = layout.heights
    has_marker = any(r.marker for r in rows)

    doc.ensure(layout.header_h + heights[0])
    segment_top = doc.y
    _draw_table_header(doc, columns, layout, size)

    for idx, row in enumerate(rows):
        if not doc.fits(heights[idx]):
            _close_table_segment(doc, segment_top)
            doc.new_page()
            if group_title:
                _draw_group_heading(
                    doc,
                    group_title,
                    color=group_color,
                    count_text=_tf(t, "report.table_continued", "continued"),
                )
            segment_top = doc.y
            _draw_table_header(doc, columns, layout, size)
        _draw_table_row(
            doc,
            columns,
            layout.widths,
            row,
            layout.lines[idx],
            heights[idx],
            size,
            idx,
            zebra,
            has_marker,
        )

    _close_table_segment(doc, segment_top)
    doc.move(GAP_S)
    if caption:
        draw_caption(doc, caption)


def _close_table_segment(doc: Doc, segment_top: float) -> None:
    doc.c.setStrokeColor(STROKE)
    doc.c.setLineWidth(0.8)
    doc.c.roundRect(
        MARGIN, doc.y, CONTENT_W, segment_top - doc.y, 4, stroke=1, fill=0
    )


def draw_caption(doc: Doc, text: str) -> None:
    if not text:
        return
    for line in _wrap_text(doc.c, text, FONT_OBLIQUE, T_CAPTION, CONTENT_W):
        doc.ensure(LEAD_CAPTION)
        doc.text(line, T_CAPTION, INK_FAINT, FONT_OBLIQUE)
        doc.move(LEAD_CAPTION)
    doc.move(GAP_XS)


def draw_paragraph(
    doc: Doc,
    text: str,
    size: float = 9.0,
    color: str = INK_DIM,
    font: Optional[str] = None,
    lead: float = 11.5,
) -> None:
    if not text:
        return
    use_font = font or FONT
    for line in _wrap_text(doc.c, text, use_font, size, CONTENT_W):
        doc.ensure(lead)
        doc.text(line, size, color, use_font)
        doc.move(lead)


def _section_header(doc: Doc, number: str, title: str, next_block_h: float = 0.0) -> None:
    doc.keep_with(SECTION_ADVANCE + 6.0, next_block_h)
    doc.move(12)
    top = doc.y
    doc.accent_bar(MARGIN, top + 9, 16, ACCENT, w=3)
    num_x = MARGIN + 9
    doc.text(number, T_BODY, ACCENT, FONT_BOLD, x=num_x, dy=0)
    num_w = pdfmetrics.stringWidth(number, FONT_BOLD, T_BODY)
    doc.text(title, T_TITLE, INK, FONT_BOLD, x=num_x + num_w + 8, dy=-1)
    doc.move(10)
    doc.hline(STROKE, 0.8)
    doc.move(14)


def _tf(t: Translator, key: str, fallback: str, **vars: Any) -> str:
    if not t.has(key):
        return fallback
    return t.t(key, **vars)


def _cover_headline_cards(t: Translator, data: ReportData) -> list[tuple[str, str, str]]:
    m = data.metrics.get("all")
    lang = t.lang
    return [
        (
            t.t("metrics.overview_coverage.label"),
            _pct(m.overview_coverage if m else None, lang),
            ACCENT,
        ),
        (
            t.t("metrics.visibility_in_sources.label"),
            _pct(m.visibility_in_sources if m else None, lang),
            ACCENT_2,
        ),
        (
            t.t("metrics.visibility_in_citations.label"),
            _pct(m.visibility_in_citations if m else None, lang),
            ACCENT_3,
        ),
    ]


def render_cover(doc: Doc, t: Translator, data: ReportData, generated_at: datetime) -> None:
    doc.fill_background()

    doc.c.setFillColor(PANEL)
    doc.c.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
    doc.c.setFillColor(ACCENT)
    doc.c.rect(0, PAGE_H - 4 * mm, PAGE_W * 0.42, 4 * mm, stroke=0, fill=1)

    cx = PAGE_W / 2

    doc.y = PAGE_H - 58 * mm
    eyebrow = t.t("report.cover_eyebrow")
    subtitle = t.t("report.cover_subtitle")
    doc.text_center(eyebrow, 12, ACCENT, FONT_BOLD, cx)
    if subtitle.casefold() != eyebrow.casefold():
        doc.move(6 * mm)
        doc.text_center(subtitle, 10, INK_FAINT, FONT_OBLIQUE, cx)
        doc.move(18 * mm)
    else:
        doc.move(24 * mm)
    doc.text_center(data.brand_name, T_COVER, INK, FONT_BOLD, cx)
    doc.move(10 * mm)
    doc.text_center(data.brand_domain, T_TITLE, INK_DIM, FONT, cx)

    doc.move(16 * mm)
    cards = _cover_headline_cards(t, data)
    gap = 5 * mm
    card_w = (CONTENT_W - gap * (len(cards) - 1)) / len(cards)
    card_h = 30 * mm
    top = doc.y
    for i, (label, value, color) in enumerate(cards):
        x = MARGIN + i * (card_w + gap)
        doc.rounded_panel(x, top, card_w, card_h, fill=PANEL, stroke=STROKE, radius=8)
        doc.accent_bar(x + 7, top - 7, 14, color, w=3)
        doc.c.setFillColor(INK)
        doc.c.setFont(FONT_BOLD, 26)
        doc.c.drawCentredString(x + card_w / 2, top - 15 * mm, value)
        doc.c.setFillColor(INK_DIM)
        doc.c.setFont(FONT, 8.5)
        for j, line in enumerate(_wrap_text(doc.c, label, FONT, 8.5, card_w - 10 * mm)):
            doc.c.drawCentredString(x + card_w / 2, top - 21 * mm - j * 10, line)

    doc.y = top - card_h
    doc.move(10 * mm)

    card_w2 = CONTENT_W
    card_x = MARGIN
    card_top = doc.y

    period_label = (
        t.t("report.cover_period_today")
        if data.period == "today"
        else t.t("report.cover_period_all")
    )
    if data.n_runs > 1:
        period_label = f"{period_label} · {data.n_runs}"

    rows = [
        (t.t("report.cover_engine"), data.engine),
        (t.t("report.cover_domain"), data.brand_domain),
        (t.t("report.cover_period"), period_label),
        (t.t("report.cover_generated"), generated_at.strftime("%d.%m.%Y %H:%M")),
    ]
    row_step = 9 * mm
    card_h2 = row_step * len(rows) + 6 * mm
    doc.rounded_panel(card_x, card_top, card_w2, card_h2, fill=PANEL, stroke=STROKE, radius=10)

    inner_x = card_x + 8 * mm
    inner_right = card_x + card_w2 - 8 * mm
    row_y = card_top - 8 * mm
    for idx, (label, value) in enumerate(rows):
        doc.c.setFillColor(INK_FAINT)
        doc.c.setFont(FONT, 10)
        doc.c.drawString(inner_x, row_y, label)
        doc.c.setFillColor(INK)
        doc.c.setFont(FONT_BOLD, 11)
        doc.c.drawRightString(
            inner_right,
            row_y,
            _truncate_to_width(str(value), FONT_BOLD, 11, card_w2 - 16 * mm - 60),
        )
        if idx < len(rows) - 1:
            doc.c.setStrokeColor(STROKE)
            doc.c.setLineWidth(0.6)
            doc.c.line(inner_x, row_y - 3.5 * mm, inner_right, row_y - 3.5 * mm)
        row_y -= row_step

    doc.y = MARGIN + 6 * mm
    doc.text_center(
        t.t("report.cover_brandline"),
        9,
        INK_FAINT,
        FONT,
        cx,
    )


def _build_kpi_cards(t: Translator, cur, prev, lang: str) -> list[dict]:
    def g(attr: str) -> Optional[float]:
        return getattr(cur, attr) if cur is not None else None

    def gp(attr: str) -> Optional[float]:
        return getattr(prev, attr) if prev is not None else None

    lower_better = t.t("common.lower_is_better")
    return [
        {
            "attr": "overview_coverage",
            "ratio": True,
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
            "attr": "visibility_in_sources",
            "ratio": True,
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
            "attr": "visibility_in_citations",
            "ratio": True,
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
            "attr": "avg_source_position",
            "ratio": False,
            "label": t.t("metrics.avg_source_position.label"),
            "value": _num(g("avg_source_position"), 1, lang),
            "sub": lower_better,
            "delta": _delta_num(t, g("avg_source_position"), gp("avg_source_position"), higher_is_better=False, digits=1),
            "accent": WARN,
        },
        {
            "attr": "avg_citation_position",
            "ratio": False,
            "label": t.t("metrics.avg_citation_position.label"),
            "value": _num(g("avg_citation_position"), 1, lang),
            "sub": lower_better,
            "delta": _delta_num(t, g("avg_citation_position"), gp("avg_citation_position"), higher_is_better=False, digits=1),
            "accent": WARN,
        },
        {
            "attr": "relative_citation",
            "ratio": True,
            "label": t.t("metrics.relative_citation.label"),
            "value": _pct(g("relative_citation"), lang),
            "sub": f"{(cur.n_cited if cur else 0)} / {(cur.n_in_sources if cur else 0)}",
            "delta": _delta_pct(t, g("relative_citation"), gp("relative_citation"), higher_is_better=True),
            "accent": ACCENT_3,
        },
        {
            "attr": "brand_mention_rate",
            "ratio": True,
            "label": t.t("metrics.brand_mention_rate.label"),
            "value": _pct(g("brand_mention_rate"), lang),
            "sub": t.t(
                "report.card_visibility_sub",
                numerator=(cur.n_brand_mentions if cur else 0),
                n_overviews=(cur.n_overviews if cur else 0),
            ),
            "delta": _delta_pct(t, g("brand_mention_rate"), gp("brand_mention_rate"), higher_is_better=True),
            "accent": ACCENT,
        },
    ]


_DELTA_DIRECTION_KEY = {"▲": "report.delta_up", "▼": "report.delta_down", "▬": "report.delta_flat"}
_DELTA_DIRECTION_FALLBACK = {"▲": "up", "▼": "down", "▬": "flat"}


def _delta_chip_text(t: Translator, d: Delta) -> str:
    word = ""
    key = _DELTA_DIRECTION_KEY.get(d.arrow)
    if key is not None:
        word = _tf(t, key, _DELTA_DIRECTION_FALLBACK[d.arrow])
    return " ".join(part for part in (d.arrow, d.text, word) if part)


def _spread_chip_text(t: Translator, card: dict, spread: dict, lang: str) -> Optional[str]:
    bounds = spread.get(card["attr"])
    if bounds is None:
        return None
    lo, hi = bounds
    fmt = (lambda v: _pct(v, lang)) if card["ratio"] else (lambda v: _num(v, 1, lang))
    return f"{fmt(lo)}–{fmt(hi)}"


def _lens_strip_values(
    data: ReportData, attr: str
) -> list[tuple[str, Optional[float]]]:
    out: list[tuple[str, Optional[float]]] = []
    for lens in _LENS_ORDER:
        m = data.metrics.get(lens)
        out.append((lens, getattr(m, attr) if m is not None else None))
    return out


def _lens_short(t: Translator, lens: str) -> str:
    key = f"lens.short_{lens}"
    return t.t(key) if t.has(key) else lens_label(t, lens)


def _draw_lens_strip(
    doc: Doc, t: Translator, data: ReportData, card: dict, x: float, y: float, w: float, lang: str
) -> None:
    values = _lens_strip_values(data, card["attr"])
    if not values:
        return
    col_w = min(w / len(values), 74.0)
    for i, (lens, value) in enumerate(values):
        cx0 = x + i * col_w
        color = LENS_COLORS.get(lens, INK_FAINT)
        if card["ratio"]:
            track_w = col_w - 8
            doc.c.setFillColor(PANEL_ALT)
            doc.c.rect(cx0, y + 9, track_w, 3, stroke=0, fill=1)
            if value is not None:
                doc.c.setFillColor(color)
                doc.c.rect(cx0, y + 9, track_w * max(0.0, min(1.0, value)), 3, stroke=0, fill=1)
        else:
            doc.c.setFillColor(color)
            doc.c.circle(cx0 + 2, y + 10.5, 2.0, stroke=0, fill=1)
        text = _pct(value, lang) if card["ratio"] else _num(value, 1, lang)
        doc.c.setFillColor(INK_DIM)
        doc.c.setFont(FONT, 7.0)
        doc.c.drawString(cx0 if card["ratio"] else cx0 + 6, y, _lens_short(t, lens))
        doc.c.setFillColor(INK)
        doc.c.setFont(FONT_BOLD, 7.5)
        doc.c.drawRightString(cx0 + col_w - 8, y, text)


def _draw_kpi_card(
    doc: Doc,
    t: Translator,
    data: ReportData,
    card: dict,
    x: float,
    top: float,
    w: float,
    h: float,
    lang: str,
) -> None:
    doc.rounded_panel(x, top, w, h, fill=PANEL, stroke=STROKE, radius=8)
    doc.accent_bar(x + 6, top - 7, 16, card["accent"], w=3)

    label_w = w - 24
    doc.c.setFillColor(INK_DIM)
    doc.c.setFont(FONT, 9.5)
    doc.c.drawString(
        x + 14, top - 9 * mm + 4, _truncate_to_width(card["label"], FONT, 9.5, label_w)
    )

    doc.c.setFillColor(INK)
    doc.c.setFont(FONT_BOLD, 24)
    doc.c.drawString(x + 13, top - 18 * mm, card["value"])

    chip = _spread_chip_text(t, card, data.spread, lang) if data.n_repeats > 1 else None
    chip_text: Optional[str] = None
    chip_color = INK_DIM
    if chip is not None:
        chip_text = f"{_tf(t, 'report.spread_chip', 'spread')} {chip}"
    elif data.n_repeats == 1 and data.period != "all":
        d: Delta = card["delta"]
        chip_text = _delta_chip_text(t, d)
        chip_color = d.color
    if chip_text:
        doc.c.setFont(FONT_BOLD, 9)
        doc.c.setFillColor(chip_color)
        doc.c.drawRightString(
            x + w - 10,
            top - 17 * mm,
            _truncate_to_width(chip_text, FONT_BOLD, 9, w * 0.5),
        )

    doc.c.setFillColor(INK_FAINT)
    doc.c.setFont(FONT, 8.5)
    doc.c.drawString(
        x + 14,
        top - 22 * mm,
        _truncate_to_width(card["sub"], FONT, 8.5, w - 24),
    )

    _draw_lens_strip(doc, t, data, card, x + 13, top - h + 6 * mm, w - 26, lang)


def render_kpi_cards(doc: Doc, t: Translator, data: ReportData) -> None:
    cur = data.metrics.get("all")
    prev = data.prev_metrics.get("all")
    lang = t.lang
    cards = _build_kpi_cards(t, cur, prev, lang)

    gap = 5 * mm
    card_w = (CONTENT_W - gap) / 2
    card_h = 34 * mm

    _section_header(doc, "01", t.t("report.section_kpi"), next_block_h=card_h + 18)

    if data.n_repeats > 1:
        sub = _tf(
            t,
            "report.kpi_repeat_group",
            f"repeat group: {data.n_repeats} runs · min–max spread instead of deltas",
            n=data.n_repeats,
        )
    elif data.period == "all":
        sub = _tf(
            t,
            "report.period_rollup",
            f"whole period: {data.n_runs} completed runs rolled up · latest run {_fmt_dt(data.run_at)}",
            n_runs=data.n_runs,
        )
    elif data.prev_run_at:
        sub = t.t(
            "report.kpi_compare",
            current=_fmt_dt(data.run_at),
            previous=_fmt_dt(data.prev_run_at),
        )
    else:
        sub = t.t("report.kpi_no_prev", current=_fmt_dt(data.run_at))
    draw_paragraph(doc, sub, 9, INK_DIM, FONT)
    doc.move(GAP_S)

    for i in range(0, len(cards), 2):
        pair = cards[i : i + 2]
        doc.ensure(card_h + gap)
        top = doc.y
        if len(pair) == 1:
            _draw_kpi_card(doc, t, data, pair[0], MARGIN, top, CONTENT_W, card_h, lang)
        else:
            for j, card in enumerate(pair):
                _draw_kpi_card(
                    doc, t, data, card, MARGIN + j * (card_w + gap), top, card_w, card_h, lang
                )
        doc.y = top - card_h
        doc.move(gap)

    doc.move(GAP_XS)


_CHART_MIN_SCALE = 0.62


def _chart_height(png: bytes, width: float = CONTENT_W) -> float:
    reader = ImageReader(io.BytesIO(png))
    iw, ih = reader.getSize()
    return width / iw * ih


def _place_full_width_chart(doc: Doc, png: bytes, move_after: float) -> None:
    h = _chart_height(png)
    room = doc.space_left() - move_after
    if h + 6 > room:
        if room >= h * _CHART_MIN_SCALE:
            scaled_w = CONTENT_W * (room - 6) / h
            used = doc.image_png(png, min(CONTENT_W, scaled_w))
            doc.move(used + move_after)
            return
        doc.ensure(h + 6)
    used = doc.image_png(png, CONTENT_W)
    doc.move(used + move_after)


_MAX_RESERVE = PAGE_H - 2 * MARGIN - 30.0
_GROUP_HEAD_H = 18.0


def _reserve(*parts: float) -> float:
    return min(sum(parts), _MAX_RESERVE)


def _glyph(text: str, fallback: str) -> str:
    try:
        face = pdfmetrics.getFont(FONT).face
    except Exception:
        return fallback
    charmap = getattr(face, "charToGlyph", None)
    if not charmap:
        return fallback
    return text if all(ord(ch) in charmap for ch in text) else fallback


def _mark_yes() -> str:
    return _glyph("✓", "•")


def _mark_no() -> str:
    return "—"


def _paragraph_h(doc: Doc, text: str, size: float = 9.0, lead: float = 11.5) -> float:
    if not text:
        return 0.0
    return len(_wrap_text(doc.c, text, FONT, size, CONTENT_W)) * lead


GROUP_COUNT_SEP = " · "


def _draw_group_heading(
    doc: Doc,
    title: str,
    count: Optional[int] = None,
    color: str = ACCENT,
    count_text: Optional[str] = None,
) -> None:
    doc.move(GAP_XS)
    doc.c.setFillColor(color)
    doc.c.circle(MARGIN + 3, doc.y + 3, 2.4, stroke=0, fill=1)
    x = MARGIN + 10
    label = count_text if count_text is not None else (None if count is None else str(count))
    if label:
        title = _truncate_to_width(title, FONT_BOLD, 10, _group_title_budget(doc, label))
    doc.text(title, 10, INK, FONT_BOLD, x=x)
    if label:
        x += doc.text_w(title, FONT_BOLD, 10)
        doc.text(f"{GROUP_COUNT_SEP}{label}", 10, INK_DIM, FONT, x=x)
    doc.move(14)


def _group_title_budget(doc: Doc, label: str) -> float:
    tail = doc.text_w(f"{GROUP_COUNT_SEP}{label}", FONT, 10)
    return max(CONTENT_W - 10.0 - tail, MIN_COL_W)


def _lenses_table(t: Translator, data: ReportData) -> tuple[list[Column], list[TableRow]]:
    lang = t.lang
    columns = [
        Column(t.t("report.lenses_table_col_type"), grow=2.0),
        Column(t.t("dashboard.lens_col_queries"), align="right", wrap=True, grow=0.3),
        Column(t.t("dashboard.lens_col_overview"), align="right", wrap=True, grow=0.3),
        Column(t.t("report.lenses_table_col_coverage"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_visibility_sources"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_visibility_citations"), align="right", wrap=True, grow=0.4),
        Column(t.t("dashboard.lens_col_mentions"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_position_sources"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_position_citations"), align="right", wrap=True, grow=0.4),
    ]
    order = [ln for ln in _LENS_ORDER if ln in data.metrics]
    if "all" in data.metrics:
        order.append("all")
    rows: list[TableRow] = []
    for lens in order:
        m = data.metrics[lens]
        is_all = lens == "all"
        rows.append(
            TableRow(
                cells=[
                    Cell(lens_label(t, lens)),
                    Cell(str(m.n_queries)),
                    Cell(str(m.n_overviews)),
                    Cell(_pct(m.overview_coverage, lang)),
                    Cell(_pct(m.visibility_in_sources, lang)),
                    Cell(_pct(m.visibility_in_citations, lang)),
                    Cell(_pct(m.brand_mention_rate, lang)),
                    Cell(_num(m.avg_source_position, 1, lang)),
                    Cell(_num(m.avg_citation_position, 1, lang)),
                ],
                highlight=is_all,
                marker=None if is_all else LENS_COLORS.get(lens, INK_FAINT),
            )
        )
    return columns, rows


def render_lenses(doc: Doc, t: Translator, data: ReportData) -> None:
    columns, rows = _lenses_table(t, data)
    lenses = [ln for ln in _LENS_ORDER if ln in data.metrics]
    png = chart_lenses_grouped_bar(t, data.metrics) if lenses else None
    caption_h = _paragraph_h(doc, t.t("report.lenses_caption"), T_CAPTION, LEAD_CAPTION)
    chart_h = (_chart_height(png) + 6 + GAP_S) if png is not None else 0.0
    _section_header(
        doc,
        "02",
        t.t("report.section_lenses"),
        next_block_h=_reserve(
            measure_table(doc, columns, rows) + GAP_S + caption_h, chart_h
        ),
    )
    draw_table(doc, t, columns, rows, caption=t.t("report.lenses_caption"))

    if png is not None:
        _place_full_width_chart(doc, png, GAP_S)


def render_funnel(doc: Doc, t: Translator, data: ReportData) -> None:
    m = data.metrics.get("all")
    if m is None:
        _section_header(doc, "03", t.t("report.section_funnel"), next_block_h=2 * LEAD_BODY)
        doc.text(t.t("report.funnel_empty"), 10, INK_DIM, FONT)
        doc.move(LEAD_BODY)
        return

    png = chart_funnel(t, m)
    intro_h = _paragraph_h(doc, t.t("report.funnel_intro"))
    _section_header(
        doc,
        "03",
        t.t("report.section_funnel"),
        next_block_h=_reserve(intro_h + GAP_XS, _chart_height(png) + 6 + GAP_S),
    )
    draw_paragraph(doc, t.t("report.funnel_intro"))
    doc.move(GAP_XS)
    _place_full_width_chart(doc, png, GAP_S)


def _weekly_table(
    t: Translator, weeks: list[WeekPoint]
) -> tuple[list[Column], list[TableRow]]:
    lang = t.lang
    columns = [
        Column(t.t("dashboard.chart_bucket_week"), grow=1.6),
        Column(t.t("report.lenses_table_col_coverage"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_visibility_sources"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_visibility_citations"), align="right", wrap=True, grow=0.4),
        Column(t.t("dashboard.lens_col_mentions"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_position_sources"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_position_citations"), align="right", wrap=True, grow=0.4),
    ]
    rows: list[TableRow] = []
    for point in weeks:
        m = point.metrics
        rows.append(
            TableRow(
                cells=[
                    Cell(point.week, badge=f"×{point.n_runs}" if point.n_runs > 1 else None),
                    Cell(_pct(m.overview_coverage, lang)),
                    Cell(_pct(m.visibility_in_sources, lang)),
                    Cell(_pct(m.visibility_in_citations, lang)),
                    Cell(_pct(m.brand_mention_rate, lang)),
                    Cell(_num(m.avg_source_position, 1, lang)),
                    Cell(_num(m.avg_citation_position, 1, lang)),
                ]
            )
        )
    return columns, rows


def render_history(doc: Doc, t: Translator, data: ReportData) -> None:
    png = chart_history(t, data.history)
    if png is None:
        return
    weeks = data.history_weekly if len(data.history_weekly) > 1 else []
    intro_h = _paragraph_h(doc, t.t("report.history_intro"))
    _section_header(
        doc,
        "04",
        t.t("report.section_history"),
        next_block_h=_reserve(intro_h + GAP_XS, _chart_height(png) + 6 + GAP_S),
    )
    draw_paragraph(doc, t.t("report.history_intro"))
    doc.move(GAP_XS)
    _place_full_width_chart(doc, png, GAP_S)

    if not weeks:
        return
    columns, rows = _weekly_table(t, weeks)
    doc.keep_with(
        _GROUP_HEAD_H, _reserve(table_min_height(doc, columns, rows))
    )
    week_title = t.t("dashboard.chart_bucket_week")
    _draw_group_heading(
        doc,
        week_title,
        count_text=_tf(
            t, "report.group_count_weeks", f"{len(weeks)} weeks", n=len(weeks)
        ),
    )
    draw_table(doc, t, columns, rows, group_title=week_title)


TOKEN_BREAK_AFTER = ",;:/\\|&?!=+*.\"'>)]}"
TOKEN_BREAK_NOT_BEFORE_ALNUM = ".,"


def _token_segments(word: str) -> list[str]:
    segments: list[str] = []
    cur = ""
    for i, ch in enumerate(word):
        cur += ch
        if ch not in TOKEN_BREAK_AFTER:
            continue
        nxt = word[i + 1] if i + 1 < len(word) else ""
        if ch in TOKEN_BREAK_NOT_BEFORE_ALNUM and nxt.isalnum():
            continue
        segments.append(cur)
        cur = ""
    if cur:
        segments.append(cur)
    return segments or [word]


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
                for seg in _token_segments(w):
                    if piece and pdfmetrics.stringWidth(piece + seg, font, size) <= max_w:
                        piece += seg
                        continue
                    if piece:
                        lines.append(piece)
                        piece = ""
                    if pdfmetrics.stringWidth(seg, font, size) <= max_w:
                        piece = seg
                        continue
                    for ch in seg:
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
    _section_header(doc, "06", t.t("report.section_sentiment"), next_block_h=4 * LEAD_BODY)

    draw_paragraph(doc, t.t("report.sentiment_intro"))
    doc.move(GAP_S)

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


def _ranks_text(t: Translator, ranks: list[int]) -> str:
    return ", ".join(str(r) for r in ranks) if ranks else t.t("common.dash")


def _results_columns(t: Translator) -> list[Column]:
    return [
        Column(t.t("dashboard.results_col_query"), wrap=True, grow=3.0),
        Column(t.t("dashboard.results_col_lens"), grow=0.5),
        Column(t.t("dashboard.results_col_overview"), grow=0.2),
        Column(t.t("dashboard.results_col_source_ranks"), align="right", wrap=True, grow=0.3),
        Column(t.t("dashboard.results_col_citation_ranks"), align="right", wrap=True, grow=0.3),
        Column(t.t("dashboard.results_col_mention"), grow=0.2),
        Column(t.t("dashboard.results_col_sentiment"), wrap=True, grow=1.5),
    ]


def _result_table_row(t: Translator, row: ResultRow) -> TableRow:
    yes, no = _mark_yes(), _mark_no()
    sentiment = row.sentiment
    if sentiment:
        sentiment_cell = Cell(sentiment)
    else:
        sentiment_cell = Cell(t.t("dashboard.results_brand_absent"), color=INK_FAINT)
    return TableRow(
        cells=[
            Cell(row.query),
            Cell(lens_label(t, row.lens), color=INK_DIM),
            Cell(
                yes if row.overview_present else no,
                color=GOOD if row.overview_present else INK_FAINT,
                bold=row.overview_present,
            ),
            Cell(_ranks_text(t, row.source_ranks)),
            Cell(_ranks_text(t, row.citation_ranks)),
            Cell(
                yes if row.brand_in_answer_text else no,
                color=GOOD if row.brand_in_answer_text else INK_FAINT,
                bold=row.brand_in_answer_text,
            ),
            sentiment_cell,
        ],
        marker=LENS_COLORS.get(row.lens, INK_FAINT),
    )


def _results_legend(t: Translator) -> str:
    yes, no = _mark_yes(), _mark_no()
    parts = [
        f"{t.t('dashboard.results_col_overview')}: "
        f"{yes} {t.t('dashboard.results_overview_shown')} · "
        f"{no} {t.t('dashboard.results_overview_absent')}",
        f"{t.t('dashboard.results_col_mention')}: "
        f"{yes} {t.t('dashboard.results_mention_yes')} · "
        f"{no} {t.t('dashboard.results_mention_no')}",
    ]
    return "   ".join(parts)


def _results_by_outcome(results: list[ResultRow]) -> dict[str, list[ResultRow]]:
    grouped: dict[str, list[ResultRow]] = {key: [] for key in RESULT_OUTCOMES}
    for row in results:
        grouped.setdefault(result_outcome(row), []).append(row)
    return grouped


_OUTCOME_COLOR = {
    "cited": ACCENT_3,
    "sources_only": ACCENT_2,
    "mention_only": ACCENT,
    "absent": BAD,
    "no_answer": INK_FAINT,
}


def render_results(doc: Doc, t: Translator, data: ReportData) -> None:
    columns = _results_columns(t)
    grouped = _results_by_outcome(data.results)
    first = next(
        (grouped[key] for key in RESULT_OUTCOMES if grouped.get(key)), []
    )
    first_h = (
        table_min_height(doc, columns, [_result_table_row(t, first[0])]) if first else 0.0
    )
    _section_header(
        doc,
        "07",
        t.t("report.section_results"),
        next_block_h=_reserve(
            _paragraph_h(doc, t.t("report.results_intro")) + GAP_XS,
            _GROUP_HEAD_H + first_h,
        ),
    )
    draw_paragraph(doc, t.t("report.results_intro"))
    doc.move(GAP_XS)

    if not data.results:
        doc.text(t.t("dashboard.results_empty"), 10, INK_DIM, FONT)
        doc.move(LEAD_BODY)
        return

    draw_caption(doc, _results_legend(t))

    for key in RESULT_OUTCOMES:
        chunk = grouped.get(key) or []
        if not chunk:
            continue
        rows = [_result_table_row(t, row) for row in chunk]
        doc.keep_with(_GROUP_HEAD_H, _reserve(table_min_height(doc, columns, rows)))
        group_title = t.t(f"dashboard.results_filter_{key}")
        group_color = _OUTCOME_COLOR.get(key, ACCENT)
        _draw_group_heading(doc, group_title, len(chunk), group_color)
        draw_table(
            doc,
            t,
            columns,
            rows,
            group_title=group_title,
            group_color=group_color,
        )


def render_gaps(doc: Doc, t: Translator, data: ReportData) -> None:
    gaps = [row for row in data.results if result_outcome(row) == "absent"]
    columns = [
        Column(t.t("dashboard.results_col_query"), wrap=True, grow=4.0),
        Column(t.t("dashboard.results_col_lens"), grow=0.6),
    ]
    rows = [
        TableRow(
            cells=[Cell(row.query), Cell(lens_label(t, row.lens), color=INK_DIM)],
            marker=LENS_COLORS.get(row.lens, INK_FAINT),
        )
        for row in gaps
    ]
    _section_header(
        doc,
        "08",
        t.t("report.section_gaps"),
        next_block_h=_reserve(
            _paragraph_h(doc, t.t("report.gaps_intro")) + GAP_XS,
            table_min_height(doc, columns, rows) if rows else 2 * LEAD_BODY,
        ),
    )
    draw_paragraph(doc, t.t("report.gaps_intro"))
    doc.move(GAP_XS)

    if not rows:
        doc.text(t.t("report.gaps_empty"), 10, INK_DIM, FONT)
        doc.move(LEAD_BODY)
        return

    draw_table(doc, t, columns, rows)


_GLOSSARY_METRICS = (
    "overview_coverage",
    "visibility_in_sources",
    "visibility_in_citations",
    "avg_source_position",
    "avg_citation_position",
    "relative_citation",
    "brand_mention_rate",
)


def _funnel_invariant_text(t: Translator) -> str:
    subset = _glyph("⊆", "<=")
    chain = f" {subset} ".join(
        ["cited", "in_sources", "overviews", "queries"]
    )
    return f"{t.t('report.section_funnel')}: {chain}"


def render_glossary(doc: Doc, t: Translator, data: ReportData) -> None:
    first_label = t.t(f"metrics.{_GLOSSARY_METRICS[0]}.label")
    first_hint = t.t(f"metrics.{_GLOSSARY_METRICS[0]}.hint")
    _section_header(
        doc,
        "10",
        t.t("report.section_glossary"),
        next_block_h=_reserve(
            _paragraph_h(doc, t.t("report.glossary_intro")) + GAP_XS,
            13.0 + _paragraph_h(doc, first_hint, 8.5, 11.0),
        ),
    )
    draw_paragraph(doc, t.t("report.glossary_intro"))
    doc.move(GAP_S)

    invariant = _funnel_invariant_text(t)
    invariant_h = GAP_XS + LEAD_BODY
    last = _GLOSSARY_METRICS[-1]
    for metric_id in _GLOSSARY_METRICS:
        label = t.t(f"metrics.{metric_id}.label")
        hint = t.t(f"metrics.{metric_id}.hint")
        block_h = 13.0 + _paragraph_h(doc, hint, 8.5, 11.0) + GAP_S
        if metric_id == last:
            block_h += invariant_h
        doc.ensure(min(block_h, _MAX_RESERVE))
        doc.text(label, 10, INK, FONT_BOLD)
        doc.move(13)
        draw_paragraph(doc, hint, 8.5, INK_DIM, FONT, 11.0)
        doc.move(GAP_S)

    doc.move(GAP_XS)
    doc.text(invariant, 9.5, ACCENT_3, FONT_BOLD)
    doc.move(LEAD_BODY)


def _competitors_table(
    t: Translator, data: ReportData
) -> tuple[list[Column], list[TableRow]]:
    lang = t.lang
    all_m = data.metrics.get("all")
    n_overviews = all_m.n_overviews if all_m is not None else 0
    you = t.t("report.competitors_you")

    columns = [
        Column(t.t("report.competitors_col_domain"), grow=2.5),
        Column(t.t("report.competitors_col_share_sources"), align="right", wrap=True, grow=0.4),
        Column(
            _tf(t, "report.competitors_col_share_citations", "In citations"),
            align="right",
            wrap=True,
            grow=0.4,
        ),
        Column(t.t("report.lenses_table_col_position_sources"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_position_citations"), align="right", wrap=True, grow=0.4),
    ]

    rows: list[TableRow] = []
    for d in data.competitors:
        is_brand = bool(d.get("is_brand"))
        share_s = d.get("share_sources")
        share_c = d.get("share_citations")
        if share_s is None and n_overviews:
            share_s = d.get("appearances_sources", 0) / n_overviews
        if share_c is None and n_overviews:
            share_c = d.get("appearances_citations", 0) / n_overviews
        rows.append(
            TableRow(
                cells=[
                    Cell(d["domain"], badge=you if is_brand else None),
                    Cell(_pct(share_s, lang)),
                    Cell(_pct(share_c, lang)),
                    Cell(_num(d.get("avg_source_position"), 1, lang)),
                    Cell(_num(d.get("avg_citation_position"), 1, lang)),
                ],
                highlight=is_brand,
                marker=ACCENT if is_brand else None,
            )
        )
    return columns, rows


def _competitors_citations_inset(
    t: Translator, data: ReportData, limit: int = 5
) -> tuple[list[Column], list[TableRow]]:
    lang = t.lang
    all_m = data.metrics.get("all")
    n_overviews = all_m.n_overviews if all_m is not None else 0
    you = t.t("report.competitors_you")

    def share_c(d: dict) -> Optional[float]:
        value = d.get("share_citations")
        if value is None and n_overviews:
            value = d.get("appearances_citations", 0) / n_overviews
        return value

    ranked = [d for d in data.competitors if d.get("appearances_citations", 0) > 0]
    ranked.sort(
        key=lambda d: (
            -d.get("appearances_citations", 0),
            d.get("avg_citation_position") or 999.0,
            d["domain"],
        )
    )
    ranked = ranked[:limit]

    columns = [
        Column(t.t("report.competitors_col_domain"), grow=2.5),
        Column(t.t("dashboard.competitors_col_citations"), align="right", wrap=True, grow=0.5),
        Column(t.t("report.lenses_table_col_position_citations"), align="right", wrap=True, grow=0.5),
    ]
    rows: list[TableRow] = []
    for d in ranked:
        is_brand = bool(d.get("is_brand"))
        rows.append(
            TableRow(
                cells=[
                    Cell(d["domain"], badge=you if is_brand else None),
                    Cell(_pct(share_c(d), lang)),
                    Cell(_num(d.get("avg_citation_position"), 1, lang)),
                ],
                highlight=is_brand,
                marker=ACCENT if is_brand else None,
            )
        )
    return columns, rows


def render_competitors(doc: Doc, t: Translator, data: ReportData) -> None:
    columns, rows = _competitors_table(t, data)
    _section_header(
        doc,
        "05",
        t.t("report.section_competitors"),
        next_block_h=_reserve(
            _paragraph_h(doc, t.t("report.competitors_intro")) + GAP_XS,
            table_min_height(doc, columns, rows),
        ),
    )
    draw_paragraph(doc, t.t("report.competitors_intro"))
    doc.move(GAP_XS)

    if not rows:
        doc.text(t.t("report.competitors_empty"), 10, INK_DIM, FONT)
        doc.move(LEAD_BODY)
        return

    draw_table(doc, t, columns, rows, caption=t.t("report.competitors_caption"))

    inset_columns, inset_rows = _competitors_citations_inset(t, data)
    if not inset_rows:
        return
    doc.keep_with(
        _GROUP_HEAD_H, _reserve(table_min_height(doc, inset_columns, inset_rows))
    )
    inset_title = _tf(t, "report.competitors_top_citations", "Top domains by citations")
    _draw_group_heading(doc, inset_title, len(inset_rows), ACCENT_3)
    draw_table(
        doc,
        t,
        inset_columns,
        inset_rows,
        group_title=inset_title,
        group_color=ACCENT_3,
    )


_AUDIT_STATUS_RANK = {"fail": 0, "warn": 1, "skip": 2, "pass": 3}

_AUDIT_STATUS_COLOR = {
    "pass": GOOD,
    "warn": WARN,
    "fail": BAD,
    "skip": INK_FAINT,
}


def _truncate_to_width(s: str, font: str, size: float, max_w: float) -> str:
    if pdfmetrics.stringWidth(s, font, size) <= max_w + 0.05:
        return s
    ellipsis = "…"
    while s and pdfmetrics.stringWidth(s + ellipsis, font, size) > max_w:
        s = s[:-1]
    return s + ellipsis


def _audit_checks_by_category(audit: dict) -> list[tuple[str, list[dict]]]:
    grouped: dict[str, list[dict]] = {}
    for c in audit.get("checks", []):
        grouped.setdefault(str(c.get("category", "") or "—"), []).append(c)
    return [
        (
            category,
            sorted(
                items,
                key=lambda c: (
                    _AUDIT_STATUS_RANK.get(c.get("status"), 99),
                    str(c.get("id", "")),
                ),
            ),
        )
        for category, items in sorted(grouped.items())
    ]


def _audit_table(
    t: Translator, audit: dict, checks: Optional[list[dict]] = None
) -> tuple[list[Column], list[TableRow]]:
    if checks is None:
        checks = audit.get("checks", [])
    checks = sorted(
        checks,
        key=lambda c: (_AUDIT_STATUS_RANK.get(c.get("status"), 99), str(c.get("id", ""))),
    )
    columns = [
        Column(t.t("audit.col_check"), wrap=True, grow=0.8),
        Column(t.t("audit.col_severity"), wrap=True, grow=0.2),
        Column(t.t("audit.col_status"), grow=0.2),
        Column(t.t("audit.col_detail"), wrap=True, grow=1.2),
        Column(t.t("audit.col_fix"), wrap=True, grow=3.0),
    ]
    rows: list[TableRow] = []
    for c in checks:
        status = str(c.get("status", ""))
        severity = str(c.get("severity", ""))
        status_color = _AUDIT_STATUS_COLOR.get(status, INK_DIM)
        sev_key = f"audit.severity_{severity}"
        status_key = f"audit.status_{status}"
        rows.append(
            TableRow(
                cells=[
                    Cell(str(c.get("title", ""))),
                    Cell(t.t(sev_key) if t.has(sev_key) else severity, color=INK_DIM),
                    Cell(
                        t.t(status_key) if t.has(status_key) else status,
                        color=status_color,
                        bold=True,
                    ),
                    Cell(str(c.get("detail", "")), color=INK_DIM),
                    Cell(str(c.get("remediation") or ""), color=INK_FAINT),
                ],
                marker=status_color,
            )
        )
    return columns, rows


def _audit_category_title(t: Translator, category: str) -> str:
    key = f"audit.category_{category}"
    label = t.t(key) if t.has(key) else ""
    return f"{category} · {label}" if label else category


def render_audit(doc: Doc, t: Translator, data: ReportData) -> None:
    audit = data.audit
    if audit is None:
        _section_header(doc, "09", t.t("report.section_audit"), next_block_h=3 * LEAD_BODY)
        draw_paragraph(doc, t.t("report.audit_intro"))
        doc.move(GAP_XS)
        doc.text(t.t("report.audit_empty"), 10, INK_DIM, FONT)
        doc.move(LEAD_BODY)
        return

    groups = _audit_checks_by_category(audit)
    columns, _ = _audit_table(t, audit, [])
    first_rows: list[TableRow] = []
    if groups:
        _, first_rows = _audit_table(t, audit, groups[0][1][:1])
    _section_header(
        doc,
        "09",
        t.t("report.section_audit"),
        next_block_h=_reserve(
            _paragraph_h(doc, t.t("report.audit_intro")) + GAP_XS,
            3 * LEAD_BODY,
            _GROUP_HEAD_H,
            table_min_height(doc, columns, first_rows, T_AUDIT_TABLE)
            if first_rows
            else 0.0,
        ),
    )
    draw_paragraph(doc, t.t("report.audit_intro"))
    doc.move(GAP_XS)

    verdict = str(audit.get("verdict", ""))
    verdict_key = f"audit.verdict_{verdict}"
    verdict_label = t.t(verdict_key) if t.has(verdict_key) else verdict
    doc.text(
        t.t("report.audit_verdict_line", verdict=verdict_label, score=audit.get("score", "")),
        10,
        INK,
        FONT_BOLD,
    )
    doc.move(13)

    checked_at = audit.get("checked_at")
    if checked_at:
        doc.text(
            t.t("dashboard.audit_checked_at", datetime=_fmt_dt(str(checked_at))),
            9,
            INK_DIM,
            FONT,
        )
        doc.move(12)

    blockers = [str(b) for b in (audit.get("blockers") or [])]
    if blockers:
        draw_paragraph(
            doc,
            f"{t.t('audit.blockers')}: {', '.join(blockers)}",
            9,
            BAD,
            FONT_BOLD,
            11.5,
        )
    doc.move(GAP_XS)

    for category, checks in groups:
        _, rows = _audit_table(t, audit, checks)
        if not rows:
            continue
        doc.keep_with(
            _GROUP_HEAD_H, _reserve(table_min_height(doc, columns, rows, T_AUDIT_TABLE))
        )
        category_title = _audit_category_title(t, category)
        category_color = BAD if category == "A" else ACCENT
        _draw_group_heading(doc, category_title, len(rows), category_color)
        draw_table(
            doc,
            t,
            columns,
            rows,
            size=T_AUDIT_TABLE,
            group_title=category_title,
            group_color=category_color,
        )

    draw_caption(doc, t.t("report.audit_caption"))


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
    page_no = str(c.getPageNumber())
    c.setFont(FONT_BOLD, 8)
    c.drawRightString(PAGE_W - MARGIN, MARGIN - 12, page_no)
    page_w = pdfmetrics.stringWidth(page_no, FONT_BOLD, 8)
    c.setFont(FONT, 8)
    c.drawRightString(
        PAGE_W - MARGIN - page_w - 10, MARGIN - 12, t.t("report.footer_report_name")
    )


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


def render_body(doc: Doc, t: Translator, data: ReportData) -> None:
    render_kpi_cards(doc, t, data)
    render_lenses(doc, t, data)
    render_funnel(doc, t, data)
    if data.period == "all":
        render_history(doc, t, data)
    render_competitors(doc, t, data)
    render_sentiment(doc, t, data)
    render_results(doc, t, data)
    render_gaps(doc, t, data)
    render_audit(doc, t, data)


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

    doc = Doc(c, rtl=rtl, lang=lang)

    render_cover(doc, t, data, generated_at)
    doc.new_page()

    _install_footer_hook(doc, t, data)

    render_body(doc, t, data)
    render_glossary(doc, t, data)

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


_CHAPTER_MIN_ROOM = 260.0


def render_engine_chapter(doc: Doc, t: Translator, engine: str) -> None:
    doc.ensure(60)
    doc.move(18)
    top = doc.y
    doc.accent_bar(MARGIN, top + 12, 22, ACCENT_2, w=4)
    doc.text(
        t.t("report.engine_chapter", engine=engine),
        18,
        INK,
        FONT_BOLD,
        x=MARGIN + 12,
        dy=-2,
    )
    doc.move(16)
    doc.hline(STROKE, 1.0)
    doc.move(16)


def _engine_matrix_table(
    t: Translator, datas: list[ReportData]
) -> tuple[list[Column], list[TableRow]]:
    lang = t.lang
    columns = [
        Column(t.t("report.matrix_col_engine"), grow=1.6),
        Column(t.t("report.lenses_table_col_coverage"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_visibility_sources"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.lenses_table_col_visibility_citations"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.matrix_col_mention"), align="right", wrap=True, grow=0.4),
        Column(t.t("dashboard.matrix_col_relative"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.matrix_col_pos_src"), align="right", wrap=True, grow=0.4),
        Column(t.t("report.matrix_col_pos_cit"), align="right", wrap=True, grow=0.4),
    ]
    rows: list[TableRow] = []
    for data in datas:
        m = data.metrics.get("all")
        rows.append(
            TableRow(
                cells=[
                    Cell(data.engine, bold=True),
                    Cell(_pct(m.overview_coverage if m else None, lang)),
                    Cell(_pct(m.visibility_in_sources if m else None, lang)),
                    Cell(_pct(m.visibility_in_citations if m else None, lang)),
                    Cell(_pct(m.brand_mention_rate if m else None, lang)),
                    Cell(_pct(m.relative_citation if m else None, lang)),
                    Cell(_num(m.avg_source_position if m else None, 1, lang)),
                    Cell(_num(m.avg_citation_position if m else None, 1, lang)),
                ]
            )
        )
    return columns, rows


def render_engine_matrix(doc: Doc, t: Translator, datas: list[ReportData]) -> None:
    columns, rows = _engine_matrix_table(t, datas)
    _section_header(
        doc,
        "00",
        t.t("report.section_engines"),
        next_block_h=table_min_height(doc, columns, rows),
    )
    draw_table(doc, t, columns, rows, caption=t.t("report.engines_caption"))


def build_combined_pdf(
    datas: list[ReportData],
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

    engines_label = ", ".join(d.engine for d in datas)
    shim = replace(datas[0], engine=engines_label)
    c.setTitle(f"{t.t('report.cover_subtitle')} — {shim.brand_name}")
    c.setAuthor(t.t("common.app_title"))
    c.setSubject(t.t("report.cover_subtitle"))

    doc = Doc(c, rtl=rtl, lang=lang)

    render_cover(doc, t, shim, generated_at)
    doc.new_page()

    _install_footer_hook(doc, t, shim)

    render_engine_matrix(doc, t, datas)

    for index, data in enumerate(datas):
        if index > 0 or doc.space_left() < _CHAPTER_MIN_ROOM:
            doc.new_page()
        render_engine_chapter(doc, t, data.engine)
        render_body(doc, t, data)

    doc.new_page()
    render_glossary(doc, t, shim)

    render_footer(doc, t, shim)
    c.showPage()
    c.save()


def resolve_engines(
    conn: sqlite3.Connection, brand: str, domain: str, engines_arg: str
) -> list[str]:
    if engines_arg.strip().lower() == "all":
        brand_id = _resolve_brand_id(conn, brand, domain)
        if brand_id is None:
            raise ValueError(f"brand not found: name={brand!r} domain={domain!r}")
        rows = conn.execute(
            "SELECT DISTINCT engine FROM runs WHERE brand_id = ? AND status = 'done' "
            "ORDER BY engine",
            (brand_id,),
        ).fetchall()
        engines = [r["engine"] for r in rows]
    else:
        engines = [e.strip() for e in engines_arg.split(",") if e.strip()]
    if not engines:
        raise ValueError("no engines to combine (no completed runs for this brand)")
    return engines


def generate_combined_report(
    db_path: str,
    brand: str,
    domain: str,
    engines_arg: str,
    period: str,
    out_path: str,
    lang: str = DEFAULT_LANG,
) -> tuple[list[ReportData], list[tuple[str, str]]]:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        engines = resolve_engines(conn, brand, domain, engines_arg)
        datas: list[ReportData] = []
        skipped: list[tuple[str, str]] = []
        for eng in engines:
            try:
                datas.append(load_report_data(conn, brand, domain, eng, period))
            except ValueError as exc:
                skipped.append((eng, str(exc)))
    finally:
        conn.close()
    if not datas:
        raise ValueError(
            "no engine has completed runs with metrics for this brand: "
            + "; ".join(f"{e}: {msg}" for e, msg in skipped)
        )
    build_combined_pdf(datas, out_path, lang=lang)
    return datas, skipped


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="report.generate",
        description="Generate the dark-themed AI-visibility PDF report.",
    )
    parser.add_argument("--brand", required=True, help="Brand name (as stored in the DB).")
    parser.add_argument("--domain", required=True, help="Target domain of the brand.")
    parser.add_argument("--engine", help="Engine identifier, e.g. google (single-engine report).")
    parser.add_argument(
        "--engines",
        help=(
            "Combined multi-engine report: comma-separated engine ids, or 'all' for "
            "every engine with completed runs for this brand. Mutually exclusive "
            "with --engine."
        ),
    )
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

    if bool(args.engine) == bool(args.engines):
        print(
            "report.generate: choose exactly one mode: --engine <id> OR --engines <a,b|all>",
            file=sys.stderr,
        )
        return 2

    if args.engines:
        try:
            datas, skipped = generate_combined_report(
                db_path=args.db,
                brand=args.brand,
                domain=args.domain,
                engines_arg=args.engines,
                period=args.period,
                out_path=args.out,
                lang=args.lang,
            )
        except ValueError as exc:
            print(f"report.generate: {exc}", file=sys.stderr)
            return 1
        for eng, msg in skipped:
            print(f"report.generate: skipped engine {eng}: {msg}", file=sys.stderr)
        print(
            f"report.generate: OK -> {args.out} "
            f"(brand={datas[0].brand_name!r}, combined engines="
            f"{[d.engine for d in datas]}, period={args.period})",
            file=sys.stderr,
        )
        return 0

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
