from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from pipeline.db import get_latest_audit, get_lens_sentiments
from pipeline.schema import normalize_domain

_REPO_ROOT = Path(__file__).resolve().parent.parent

_METRIC_COLS = (
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
    "n_brand_mentions",
    "brand_mention_rate",
)
_DELTA_METRICS = (
    "overview_coverage",
    "visibility_in_sources",
    "visibility_in_citations",
    "avg_source_position",
    "avg_citation_position",
    "relative_citation",
    "brand_mention_rate",
)

app = FastAPI(title="open-geo dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db_path() -> str:
    raw = os.environ.get("OPEN_GEO_DB", "data/aeo.db")
    p = Path(raw)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return str(p)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not Path(path).exists():
        raise HTTPException(
            status_code=503,
            detail=f"database not found at {path} (set OPEN_GEO_DB)",
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_mention_columns(conn: sqlite3.Connection) -> bool:
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(metrics)")}
    except sqlite3.OperationalError:
        return False
    return "n_brand_mentions" in cols and "brand_mention_rate" in cols


def _metrics_columns(conn: sqlite3.Connection) -> set[str]:
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(metrics)")}
    except sqlite3.OperationalError:
        return set()


def _has_group_column(conn: sqlite3.Connection) -> bool:
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    except sqlite3.OperationalError:
        return False
    return "group_id" in cols


_SPREAD_METRICS = (
    "overview_coverage",
    "visibility_in_sources",
    "visibility_in_citations",
    "relative_citation",
    "brand_mention_rate",
    "avg_source_position",
    "avg_citation_position",
)


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
    conn: sqlite3.Connection, run_ids: list[int]
) -> dict[str, dict[str, tuple[float, float]]]:
    marks = ",".join("?" * len(run_ids))
    rows = conn.execute(
        f"SELECT * FROM metrics WHERE run_id IN ({marks})", run_ids
    ).fetchall()
    acc: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        d = dict(r)
        lens_acc = acc.setdefault(d["lens"], {})
        for m in _SPREAD_METRICS:
            v = d.get(m)
            if v is not None:
                lens_acc.setdefault(m, []).append(float(v))
    return {
        lens: {m: (min(vs), max(vs)) for m, vs in per_metric.items()}
        for lens, per_metric in acc.items()
    }


def _loads(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


@app.get("/api/health")
def health() -> dict:
    path = _db_path()
    return {"ok": True, "db": path, "db_exists": Path(path).exists()}


@app.get("/api/brands")
def brands() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, name, domain FROM brands ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/engines")
def engines(brand_id: int = Query(...)) -> list[str]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT engine FROM runs WHERE brand_id = ? ORDER BY engine",
            (brand_id,),
        ).fetchall()
        return [r["engine"] for r in rows]
    finally:
        conn.close()


@app.get("/api/runs")
def runs(brand_id: int = Query(...), engine: Optional[str] = None) -> list[dict]:
    conn = _connect()
    try:
        sql = (
            "SELECT id AS run_id, run_at, status, engine, n_queries, n_ok, n_failed "
            "FROM runs WHERE brand_id = ?"
        )
        params: list[Any] = [brand_id]
        if engine:
            sql += " AND engine = ?"
            params.append(engine)
        sql += " ORDER BY run_at DESC, id DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _latest_run_id(
    conn: sqlite3.Connection,
    brand_id: int,
    engine: str,
    *,
    only_done: bool = False,
    before_run_at: Optional[str] = None,
    before_id: Optional[int] = None,
) -> Optional[int]:
    sql = "SELECT id, run_at FROM runs WHERE brand_id = ? AND engine = ?"
    params: list[Any] = [brand_id, engine]
    if only_done:
        sql += " AND status = 'done'"
    if before_run_at is not None:
        sql += " AND (run_at < ? OR (run_at = ? AND id < ?))"
        params.extend([before_run_at, before_run_at, before_id])
    sql += " ORDER BY run_at DESC, id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return int(row["id"]) if row else None


def _metrics_by_lens(conn: sqlite3.Connection, run_id: int) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM metrics WHERE run_id = ?", (run_id,)).fetchall()
    return {r["lens"]: dict(r) for r in rows}


@app.get("/api/metrics")
def metrics(
    brand_id: int = Query(...),
    engine: str = Query(...),
    period: str = Query("today"),
    lens: Optional[str] = None,
) -> dict:
    if period not in ("today", "all"):
        raise HTTPException(status_code=400, detail="period must be 'today' or 'all'")

    order = {"all": 0, "general": 1, "branded": 2, "comparative": 3}
    conn = _connect()
    try:
        if period == "all":
            out_rows = _aggregate_period(conn, brand_id, engine, lens)
            latest_done_id = _latest_run_id(conn, brand_id, engine, only_done=True)
            summaries = (
                get_lens_sentiments(conn, latest_done_id) if latest_done_id else {}
            )
            for payload in out_rows:
                payload["sentiment_summary"] = summaries.get(payload["lens"])
            out_rows.sort(key=lambda r: (order.get(r["lens"], 99), r["lens"]))
            n_runs = conn.execute(
                "SELECT COUNT(*) AS c FROM runs WHERE brand_id=? AND engine=? AND status='done'",
                (brand_id, engine),
            ).fetchone()["c"]
            return {
                "brand_id": brand_id,
                "engine": engine,
                "period": period,
                "run": None,
                "prev_run": None,
                "group": None,
                "n_runs": n_runs,
                "metrics": out_rows,
            }

        run_id = _latest_run_id(conn, brand_id, engine, only_done=True)
        if run_id is None:
            return {
                "brand_id": brand_id, "engine": engine, "period": period,
                "run": None, "prev_run": None, "group": None, "metrics": [],
            }

        has_group = _has_group_column(conn)
        group_select = ", group_id" if has_group else ""
        run = conn.execute(
            f"SELECT id AS run_id, run_at, status, n_queries{group_select} "
            "FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        group_id = run["group_id"] if has_group else None
        if group_id:
            grp_ids = _group_run_ids(conn, brand_id, engine, group_id)
            if len(grp_ids) > 1:
                out_rows = _aggregate_period(
                    conn, brand_id, engine, lens, run_ids=grp_ids
                )
                spread = _group_spread(conn, grp_ids)
                summaries = get_lens_sentiments(conn, run_id)
                for payload in out_rows:
                    sp = spread.get(payload["lens"], {})
                    for m in _SPREAD_METRICS:
                        mn_mx = sp.get(m)
                        payload[f"{m}_min"] = mn_mx[0] if mn_mx else None
                        payload[f"{m}_max"] = mn_mx[1] if mn_mx else None
                    payload["sentiment_summary"] = summaries.get(payload["lens"])
                out_rows.sort(key=lambda r: (order.get(r["lens"], 99), r["lens"]))
                run_payload = dict(run)
                run_payload.pop("group_id", None)
                return {
                    "brand_id": brand_id,
                    "engine": engine,
                    "period": period,
                    "run": run_payload,
                    "prev_run": None,
                    "group": {
                        "group_id": group_id,
                        "n_repeats": len(grp_ids),
                        "run_ids": grp_ids,
                    },
                    "metrics": out_rows,
                }

        prev_id = _latest_run_id(
            conn, brand_id, engine,
            only_done=True, before_run_at=run["run_at"], before_id=run_id,
        )
        cur_by_lens = _metrics_by_lens(conn, run_id)
        prev_by_lens = _metrics_by_lens(conn, prev_id) if prev_id else {}
        summaries = get_lens_sentiments(conn, run_id)

        prev_run = None
        if prev_id:
            pr = conn.execute(
                "SELECT id AS run_id, run_at, status FROM runs WHERE id = ?",
                (prev_id,),
            ).fetchone()
            prev_run = dict(pr)

        out_rows = []
        for lns, row in cur_by_lens.items():
            if lens and lns != lens:
                continue
            payload: dict[str, Any] = {"lens": lns}
            for col in _METRIC_COLS:
                payload[col] = row.get(col)
            payload["sentiment_summary"] = summaries.get(lns)
            prev_row = prev_by_lens.get(lns)
            for m in _DELTA_METRICS:
                cur_v = row.get(m)
                prev_v = prev_row.get(m) if prev_row else None
                payload[f"{m}_delta"] = (
                    cur_v - prev_v if cur_v is not None and prev_v is not None else None
                )
                payload[f"{m}_prev"] = prev_v
            out_rows.append(payload)

        out_rows.sort(key=lambda r: (order.get(r["lens"], 99), r["lens"]))
        run_payload = dict(run)
        run_payload.pop("group_id", None)
        return {
            "brand_id": brand_id,
            "engine": engine,
            "period": period,
            "run": run_payload,
            "prev_run": prev_run,
            "group": None,
            "metrics": out_rows,
        }
    finally:
        conn.close()


def _aggregate_period(
    conn: sqlite3.Connection,
    brand_id: int,
    engine: str,
    lens: Optional[str],
    run_ids: Optional[list[int]] = None,
) -> list[dict]:
    has_mentions = _has_mention_columns(conn)
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
    if lens:
        sql += " AND m.lens = ?"
        params.append(lens)
    sql += " GROUP BY m.lens"

    rows: list[dict] = []
    for r in conn.execute(sql, params).fetchall():
        n_queries = int(r["n_queries"] or 0)
        n_overviews = int(r["n_overviews"] or 0)
        n_in_sources = int(r["n_in_sources"] or 0)
        n_cited = int(r["n_cited"] or 0)
        sum_src = r["sum_src_rank"]
        sum_cit = r["sum_cit_rank"]
        n_mentions = r["n_brand_mentions"] if has_mentions else None
        mention_nov = r["mention_nov"] if has_mentions else None
        payload: dict[str, Any] = {
            "lens": r["lens"],
            "n_queries": n_queries,
            "n_overviews": n_overviews,
            "overview_coverage": (n_overviews / n_queries) if n_queries else None,
            "n_in_sources": n_in_sources,
            "visibility_in_sources": (n_in_sources / n_overviews) if n_overviews else None,
            "n_cited": n_cited,
            "visibility_in_citations": (n_cited / n_overviews) if n_overviews else None,
            "avg_source_position": (sum_src / n_in_sources) if n_in_sources and sum_src is not None else None,
            "avg_citation_position": (sum_cit / n_cited) if n_cited and sum_cit is not None else None,
            "relative_citation": (n_cited / n_in_sources) if n_in_sources else None,
            "n_brand_mentions": int(n_mentions) if n_mentions is not None else None,
            "brand_mention_rate": (
                n_mentions / mention_nov
                if n_mentions is not None and mention_nov
                else None
            ),
        }
        for m in _DELTA_METRICS:
            payload[f"{m}_delta"] = None
            payload[f"{m}_prev"] = None
        rows.append(payload)
    return rows


def _weekly_rollup(points: list[dict]) -> list[dict]:
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for p in points:
        dt = datetime.fromisoformat(str(p["run_at"]).replace("Z", "+00:00"))
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
        b["n_queries"] += int(p["n_queries"] or 0)
        b["n_overviews"] += int(p["n_overviews"] or 0)
        b["n_in_sources"] += int(p["n_in_sources"] or 0)
        b["n_cited"] += int(p["n_cited"] or 0)
        if p["avg_source_position"] is not None:
            b["sum_src"] = (b["sum_src"] or 0.0) + p["avg_source_position"] * int(
                p["n_in_sources"] or 0
            )
        if p["avg_citation_position"] is not None:
            b["sum_cit"] = (b["sum_cit"] or 0.0) + p["avg_citation_position"] * int(
                p["n_cited"] or 0
            )
        if p.get("n_brand_mentions") is not None:
            b["n_mentions"] = (b["n_mentions"] or 0) + int(p["n_brand_mentions"])
            b["mention_nov"] += int(p["n_overviews"] or 0)

    out: list[dict] = []
    for (year, week), b in sorted(buckets.items()):
        nq, nov = b["n_queries"], b["n_overviews"]
        nis, nc = b["n_in_sources"], b["n_cited"]
        out.append(
            {
                "run_id": None,
                "run_at": f"{b['monday'].isoformat()}T00:00:00+00:00",
                "status": "done",
                "week": f"{year}-W{week:02d}",
                "n_runs": b["n_runs"],
                "lens": points[0]["lens"] if points else "all",
                "n_queries": nq,
                "n_overviews": nov,
                "overview_coverage": (nov / nq) if nq else None,
                "n_in_sources": nis,
                "visibility_in_sources": (nis / nov) if nov else None,
                "n_cited": nc,
                "visibility_in_citations": (nc / nov) if nov else None,
                "avg_source_position": (
                    b["sum_src"] / nis if nis and b["sum_src"] is not None else None
                ),
                "avg_citation_position": (
                    b["sum_cit"] / nc if nc and b["sum_cit"] is not None else None
                ),
                "relative_citation": (nc / nis) if nis else None,
                "n_brand_mentions": b["n_mentions"],
                "brand_mention_rate": (
                    b["n_mentions"] / b["mention_nov"]
                    if b["n_mentions"] is not None and b["mention_nov"]
                    else None
                ),
            }
        )
    return out


@app.get("/api/timeseries")
def timeseries(
    brand_id: int = Query(...),
    engine: str = Query(...),
    lens: str = Query("all"),
    bucket: str = Query("run"),
) -> dict:
    if bucket not in ("run", "week"):
        raise HTTPException(status_code=400, detail="bucket must be 'run' or 'week'")
    conn = _connect()
    try:
        available = _metrics_columns(conn)
        optional = (
            "relative_citation",
            "n_brand_mentions",
            "brand_mention_rate",
        )
        present = [name for name in optional if name in available]
        missing = [name for name in optional if name not in available]
        optional_select = "".join(f", m.{name}" for name in present)
        rows = conn.execute(
            f"""
            SELECT r.id AS run_id, r.run_at, r.status,
                   m.lens, m.n_queries, m.n_overviews, m.overview_coverage,
                   m.n_in_sources, m.visibility_in_sources, m.n_cited,
                   m.visibility_in_citations, m.avg_source_position,
                   m.avg_citation_position{optional_select}
            FROM runs r
            JOIN metrics m ON m.run_id = r.id
            WHERE r.brand_id = ? AND r.engine = ? AND m.lens = ?
              AND r.status = 'done'
            ORDER BY r.run_at ASC, r.id ASC
            """,
            (brand_id, engine, lens),
        ).fetchall()
        points = []
        for r in rows:
            p = dict(r)
            for name in missing:
                p[name] = None
            points.append(p)
        if bucket == "week":
            points = _weekly_rollup(points)
        return {
            "brand_id": brand_id,
            "engine": engine,
            "lens": lens,
            "bucket": bucket,
            "points": points,
        }
    finally:
        conn.close()


def _fetch_optional(
    conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]
) -> list[sqlite3.Row]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return []


def _competitor_rows_today(
    conn: sqlite3.Connection, brand_id: int, engine: str, lens: str
) -> tuple[Optional[int], int, list[dict]]:
    run_id = _latest_run_id(conn, brand_id, engine, only_done=True)
    if run_id is None:
        return None, 0, []
    nov = conn.execute(
        "SELECT n_overviews FROM metrics WHERE run_id = ? AND lens = ?",
        (run_id, lens),
    ).fetchone()
    n_overviews = int(nov["n_overviews"]) if nov and nov["n_overviews"] is not None else 0
    rows = _fetch_optional(
        conn,
        """
        SELECT domain, is_brand, appearances_sources, appearances_citations,
               avg_source_position, avg_citation_position
        FROM domain_stats WHERE run_id = ? AND lens = ?
        """,
        (run_id, lens),
    )
    out = [
        {
            "domain": r["domain"],
            "is_brand": bool(r["is_brand"]),
            "appearances_sources": int(r["appearances_sources"] or 0),
            "appearances_citations": int(r["appearances_citations"] or 0),
            "avg_source_position": r["avg_source_position"],
            "avg_citation_position": r["avg_citation_position"],
        }
        for r in rows
    ]
    return run_id, n_overviews, out


def _competitor_rows_all(
    conn: sqlite3.Connection, brand_id: int, engine: str, lens: str
) -> tuple[int, list[dict]]:
    nov = conn.execute(
        """
        SELECT SUM(m.n_overviews) AS nov
        FROM metrics m JOIN runs r ON r.id = m.run_id
        WHERE r.brand_id = ? AND r.engine = ? AND r.status = 'done' AND m.lens = ?
        """,
        (brand_id, engine, lens),
    ).fetchone()
    n_overviews = int(nov["nov"]) if nov and nov["nov"] is not None else 0
    rows = _fetch_optional(
        conn,
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
    )
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
                "avg_source_position": (sum_s / app_s) if app_s and sum_s is not None else None,
                "avg_citation_position": (sum_c / app_c) if app_c and sum_c is not None else None,
            }
        )
    return n_overviews, out


@app.get("/api/competitors")
def competitors(
    brand_id: int = Query(...),
    engine: str = Query(...),
    period: str = Query("today"),
    lens: str = Query("all"),
    sort: str = Query("sources"),
    limit: int = Query(15),
) -> dict:
    if period not in ("today", "all"):
        raise HTTPException(status_code=400, detail="period must be 'today' or 'all'")
    if sort not in ("sources", "citations"):
        raise HTTPException(status_code=400, detail="sort must be 'sources' or 'citations'")

    conn = _connect()
    try:
        run_payload = None
        if period == "all":
            n_overviews, rows = _competitor_rows_all(conn, brand_id, engine, lens)
        else:
            run_id, n_overviews, rows = _competitor_rows_today(conn, brand_id, engine, lens)
            if run_id is not None:
                rr = conn.execute(
                    "SELECT id AS run_id, run_at, status FROM runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                run_payload = dict(rr) if rr else None
    finally:
        conn.close()

    for d in rows:
        d["share_sources"] = d["appearances_sources"] / n_overviews if n_overviews else None
        d["share_citations"] = d["appearances_citations"] / n_overviews if n_overviews else None

    if sort == "citations":
        rows.sort(key=lambda d: (-d["appearances_citations"], -d["appearances_sources"], d["domain"]))
    else:
        rows.sort(key=lambda d: (-d["appearances_sources"], -d["appearances_citations"], d["domain"]))

    if limit and limit > 0:
        rows = rows[:limit]

    return {
        "brand_id": brand_id,
        "engine": engine,
        "period": period,
        "lens": lens,
        "n_overviews": n_overviews,
        "run": run_payload,
        "domains": rows,
    }


@app.get("/api/audit")
def audit(brand_id: int = Query(...), engine: Optional[str] = None) -> dict:
    conn = _connect()
    try:
        brand = conn.execute(
            "SELECT domain FROM brands WHERE id = ?", (brand_id,)
        ).fetchone()
        reg_domain = normalize_domain(brand["domain"]) if brand else ""
        row = get_latest_audit(conn, reg_domain, engine) if reg_domain else None
    finally:
        conn.close()

    result = None
    if row is not None:
        parsed = _loads(row["result_json"], None)
        if isinstance(parsed, dict):
            parsed.setdefault("checked_at", row["checked_at"])
            parsed.setdefault("verdict", row["verdict"])
            parsed.setdefault("score", row["score"])
            result = parsed

    return {
        "brand_id": brand_id,
        "engine": engine,
        "domain": reg_domain,
        "audit": result,
    }


@app.get("/api/engine_matrix")
def engine_matrix(
    brand_id: int = Query(...),
    period: str = Query("today"),
    lens: str = Query("all"),
) -> dict:
    if period not in ("today", "all"):
        raise HTTPException(status_code=400, detail="period must be 'today' or 'all'")

    conn = _connect()
    try:
        engine_rows = conn.execute(
            "SELECT DISTINCT engine FROM runs WHERE brand_id = ? ORDER BY engine",
            (brand_id,),
        ).fetchall()
        out: list[dict] = []
        for er in engine_rows:
            eng = er["engine"]
            entry: dict[str, Any] = {"engine": eng, "run": None, "n_runs": 0}
            for col in _METRIC_COLS:
                entry[col] = None
            entry["n_runs"] = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM runs "
                    "WHERE brand_id = ? AND engine = ? AND status = 'done'",
                    (brand_id, eng),
                ).fetchone()["c"]
            )
            if period == "all":
                rows = _aggregate_period(conn, brand_id, eng, lens)
                row = next((r for r in rows if r["lens"] == lens), None)
                if row is not None:
                    for col in _METRIC_COLS:
                        entry[col] = row.get(col)
            else:
                run_id = _latest_run_id(conn, brand_id, eng, only_done=True)
                if run_id is not None:
                    rr = conn.execute(
                        "SELECT id AS run_id, run_at, status FROM runs WHERE id = ?",
                        (run_id,),
                    ).fetchone()
                    entry["run"] = dict(rr) if rr else None
                    row = _metrics_by_lens(conn, run_id).get(lens)
                    if row is not None:
                        for col in _METRIC_COLS:
                            entry[col] = row.get(col)
            out.append(entry)
        return {"brand_id": brand_id, "period": period, "lens": lens, "engines": out}
    finally:
        conn.close()


@app.get("/api/results")
def results(run_id: int = Query(...), lens: Optional[str] = None) -> dict:
    conn = _connect()
    try:
        run = conn.execute(
            "SELECT id AS run_id, brand_id, engine, run_at, status FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")

        sql = "SELECT * FROM results WHERE run_id = ?"
        params: list[Any] = [run_id]
        if lens:
            sql += " AND lens = ?"
            params.append(lens)
        sql += " ORDER BY id ASC"
        rows = conn.execute(sql, params).fetchall()

        out: list[dict] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "query": r["query"],
                    "lens": r["lens"],
                    "captured_at": r["captured_at"],
                    "overview_present": bool(r["overview_present"]),
                    "answer_text_md": r["answer_text_md"],
                    "screenshot_path": r["screenshot_path"],
                    "sources": _loads(r["sources_json"], []),
                    "citations": _loads(r["citations_json"], []),
                    "target_source_ranks": _loads(r["target_source_ranks_json"], []),
                    "target_citation_ranks": _loads(r["target_citation_ranks_json"], []),
                    "brand_in_answer_text": bool(r["brand_in_answer_text"]),
                    "sentiment": r["sentiment"],
                }
            )
        return {"run": dict(run), "lens": lens, "results": out}
    finally:
        conn.close()


_I18N_DIR = _REPO_ROOT / "i18n"


@app.get("/api/i18n")
def i18n_locales() -> Any:
    path = _I18N_DIR / "locales.json"
    if not path.exists():
        return [{"code": "en", "name": "English"}]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"i18n registry unreadable: {exc}")


@app.get("/api/i18n/{code}")
def i18n_locale(code: str) -> Any:
    safe = Path(code).name
    path = _I18N_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"locale '{code}' not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"locale '{code}' unreadable: {exc}")


def _unlink_quietly(path: str) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _report_cli(
    brand: str, domain: str, engine: str, period: str, out: str, db: str, lang: str
) -> str:
    engine_arg = "--engines all" if engine == "all" else f"--engine {engine}"
    return (
        f"{sys.executable} -m report.generate "
        f"--brand {brand!r} --domain {domain} {engine_arg} "
        f"--period {period} --lang {lang} --out {out} --db {db}"
    )


@app.post("/api/report")
def report(
    brand_id: int = Query(...),
    engine: str = Query(...),
    period: str = Query("all"),
    lang: str = Query("en"),
) -> Any:
    if period not in ("today", "all"):
        raise HTTPException(status_code=400, detail="period must be 'today' or 'all'")

    conn = _connect()
    try:
        brand = conn.execute(
            "SELECT name, domain FROM brands WHERE id = ?", (brand_id,)
        ).fetchone()
    finally:
        conn.close()
    if brand is None:
        raise HTTPException(status_code=404, detail=f"brand {brand_id} not found")

    db_path = _db_path()
    out_path = str(Path(tempfile.gettempdir()) / f"open_geo_report_{uuid.uuid4().hex}.pdf")
    cli = _report_cli(brand["name"], brand["domain"], engine, period, out_path, db_path, lang)

    report_pkg = _REPO_ROOT / "report" / "generate.py"
    if not report_pkg.exists():
        return JSONResponse(
            status_code=501,
            content={
                "status": "not_implemented",
                "message": "report.generate is not available; run the command manually.",
                "command": cli,
            },
        )

    engine_args = (
        ["--engines", "all"] if engine == "all" else ["--engine", engine]
    )
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "report.generate",
                "--brand", brand["name"],
                "--domain", brand["domain"],
                *engine_args,
                "--period", period,
                "--lang", lang,
                "--out", out_path,
                "--db", db_path,
            ],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        _unlink_quietly(out_path)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(exc), "command": cli},
        )

    if proc.returncode != 0 or not Path(out_path).exists():
        _unlink_quietly(out_path)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "report.generate failed",
                "stderr": proc.stderr[-2000:],
                "command": cli,
            },
        )

    engine_slug = "all-engines" if engine == "all" else engine
    filename = f"open-geo_{brand['domain'].replace('/', '-')}_{engine_slug}_{period}.pdf"
    return FileResponse(
        out_path,
        media_type="application/pdf",
        filename=filename,
        background=BackgroundTask(_unlink_quietly, out_path),
    )
