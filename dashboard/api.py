from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from pipeline.db import get_lens_sentiments

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
)
_DELTA_METRICS = (
    "overview_coverage",
    "visibility_in_sources",
    "visibility_in_citations",
    "avg_source_position",
    "avg_citation_position",
    "relative_citation",
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
                "n_runs": n_runs,
                "metrics": out_rows,
            }

        run_id = _latest_run_id(conn, brand_id, engine, only_done=True)
        if run_id is None:
            return {
                "brand_id": brand_id, "engine": engine, "period": period,
                "run": None, "prev_run": None, "metrics": [],
            }

        run = conn.execute(
            "SELECT id AS run_id, run_at, status, n_queries FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

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
        return {
            "brand_id": brand_id,
            "engine": engine,
            "period": period,
            "run": dict(run),
            "prev_run": prev_run,
            "metrics": out_rows,
        }
    finally:
        conn.close()


def _aggregate_period(
    conn: sqlite3.Connection, brand_id: int, engine: str, lens: Optional[str]
) -> list[dict]:
    sql = """
        SELECT m.lens,
               SUM(m.n_queries)    AS n_queries,
               SUM(m.n_overviews)  AS n_overviews,
               SUM(m.n_in_sources) AS n_in_sources,
               SUM(m.n_cited)      AS n_cited,
               SUM(CASE WHEN m.avg_source_position IS NOT NULL
                        THEN m.avg_source_position * m.n_in_sources END) AS sum_src_rank,
               SUM(CASE WHEN m.avg_citation_position IS NOT NULL
                        THEN m.avg_citation_position * m.n_cited END) AS sum_cit_rank
        FROM metrics m
        JOIN runs r ON r.id = m.run_id
        WHERE r.brand_id = ? AND r.engine = ? AND r.status = 'done'
    """
    params: list[Any] = [brand_id, engine]
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
        }
        for m in _DELTA_METRICS:
            payload[f"{m}_delta"] = None
            payload[f"{m}_prev"] = None
        rows.append(payload)
    return rows


@app.get("/api/timeseries")
def timeseries(
    brand_id: int = Query(...),
    engine: str = Query(...),
    lens: str = Query("all"),
) -> dict:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT r.id AS run_id, r.run_at, r.status,
                   m.lens, m.n_queries, m.n_overviews, m.overview_coverage,
                   m.n_in_sources, m.visibility_in_sources, m.n_cited,
                   m.visibility_in_citations, m.avg_source_position,
                   m.avg_citation_position, m.relative_citation
            FROM runs r
            JOIN metrics m ON m.run_id = r.id
            WHERE r.brand_id = ? AND r.engine = ? AND m.lens = ?
              AND r.status = 'done'
            ORDER BY r.run_at ASC, r.id ASC
            """,
            (brand_id, engine, lens),
        ).fetchall()
        return {
            "brand_id": brand_id,
            "engine": engine,
            "lens": lens,
            "points": [dict(r) for r in rows],
        }
    finally:
        conn.close()


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
    try:
        rows = conn.execute(
            """
            SELECT domain, is_brand, appearances_sources, appearances_citations,
                   avg_source_position, avg_citation_position
            FROM domain_stats WHERE run_id = ? AND lens = ?
            """,
            (run_id, lens),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        rows = []
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
        if "no such table" not in str(exc):
            raise
        rows = []
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


def _report_cli(
    brand: str, domain: str, engine: str, period: str, out: str, db: str, lang: str
) -> str:
    return (
        f"{sys.executable} -m report.generate "
        f"--brand {brand!r} --domain {domain} --engine {engine} "
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

    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "report.generate",
                "--brand", brand["name"],
                "--domain", brand["domain"],
                "--engine", engine,
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
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(exc), "command": cli},
        )

    if proc.returncode != 0 or not Path(out_path).exists():
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "report.generate failed",
                "stderr": proc.stderr[-2000:],
                "command": cli,
            },
        )

    filename = f"open-geo_{brand['domain']}_{engine}_{period}.pdf"
    return FileResponse(
        out_path,
        media_type="application/pdf",
        filename=filename,
    )
