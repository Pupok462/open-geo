from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.aggregate import aggregate_run, compute_run_metrics
from pipeline.db import create_run, get_conn, get_or_create_brand, init_db
from pipeline.ingest import insert_capture
from pipeline.schema import QueryCapture, normalize_domain

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
_CAP_SEQ = itertools.count()


def _valid_capture_dict() -> dict:
    return {
        "query": "best task tracking tools",
        "lens": "general",
        "engine": "google",
        "captured_at": "2026-06-18T20:15:30Z",
        "overview_present": True,
        "sources": [
            {"rank": 1, "url": "https://example.com/catalog/x", "domain": "example.com"},
        ],
        "citations": [],
        "target_source_ranks": [1],
        "target_citation_ranks": [],
        "brand_in_answer_text": True,
        "sentiment": "recommended as one of the options",
    }


def test_schema_valid_parses():
    cap = QueryCapture.model_validate(_valid_capture_dict())
    assert cap.lens == "general"
    assert cap.overview_present is True
    assert cap.target_source_ranks == [1]
    assert cap.sources[0].domain == "example.com"


def test_schema_bad_lens_raises():
    bad = _valid_capture_dict()
    bad["lens"] = "promotional"
    with pytest.raises(ValidationError) as exc_info:
        QueryCapture.model_validate(bad)
    assert exc_info.value.errors()[0]["loc"] == ("lens",)


def test_schema_missing_required_field_raises():
    bad = _valid_capture_dict()
    del bad["overview_present"]
    with pytest.raises(ValidationError) as exc_info:
        QueryCapture.model_validate(bad)
    err = exc_info.value.errors()[0]
    assert err["loc"] == ("overview_present",)
    assert err["type"] == "missing"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://www.Example.COM/catalog/running?utm=1", "example.com"),
        ("http://shop.example.co.uk/path", "example.co.uk"),
    ],
)
def test_normalize_domain_cases(raw, expected):
    assert normalize_domain(raw) == expected


def _new_run(db_path: Path) -> int:
    proc = subprocess.run(
        [
            str(PYTHON), "-m", "pipeline.ingest",
            "--db", str(db_path),
            "--brand", "Example", "--domain", "example.com",
            "--engine", "google", "--new-run",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["run_id"]


def _ingest(db_path: Path, run_id: int, batch: list) -> dict:
    proc = subprocess.run(
        [
            str(PYTHON), "-m", "pipeline.ingest",
            "--db", str(db_path), "--run-id", str(run_id),
        ],
        cwd=str(REPO_ROOT),
        input=json.dumps(batch),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_ingest_happy_path(tmp_path):
    db_path = tmp_path / "aeo.db"
    run_id = _new_run(db_path)

    batch = [_valid_capture_dict(), _valid_capture_dict()]
    batch[1]["lens"] = "branded"
    batch[1]["query"] = "Example pricing"

    result = _ingest(db_path, run_id, batch)

    assert result["run_id"] == run_id
    assert result["ok"] == [0, 1]
    assert result["skipped"] == []
    assert result["errors"] == []

    conn = get_conn(str(db_path))
    try:
        n_results = conn.execute(
            "SELECT COUNT(*) FROM results WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        assert n_results == 2

        run = conn.execute(
            "SELECT n_ok, status FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        assert run["n_ok"] == 2
        assert run["status"] == "running"
    finally:
        conn.close()


def test_ingest_error_feedback(tmp_path):
    db_path = tmp_path / "aeo.db"
    run_id = _new_run(db_path)

    good = _valid_capture_dict()
    bad = _valid_capture_dict()
    bad["lens"] = "nonsense"
    bad["query"] = "broken query"

    result = _ingest(db_path, run_id, [good, bad])

    assert result["ok"] == [0]

    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["index"] == 1
    assert err["field"] == "lens"
    assert err["query"] == "broken query"
    assert err["msg"]

    conn = get_conn(str(db_path))
    try:
        rows = conn.execute(
            "SELECT query FROM results WHERE run_id = ?", (run_id,)
        ).fetchall()
        assert [r["query"] for r in rows] == [good["query"]]

        run = conn.execute(
            "SELECT n_ok, status FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["n_ok"] == 1
        assert run["status"] == "running"
    finally:
        conn.close()


def _cap(
    *,
    lens: str,
    overview: bool,
    source_ranks: list[int],
    citation_ranks: list[int],
) -> QueryCapture:
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
            "sentiment": "ok" if source_ranks else None,
        }
    )


def test_aggregate_math(tmp_path):
    db_path = tmp_path / "aeo.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")

        caps = [
            _cap(lens="general", overview=True, source_ranks=[2, 4], citation_ranks=[2]),
            _cap(lens="general", overview=True, source_ranks=[5], citation_ranks=[]),
            _cap(lens="general", overview=False, source_ranks=[], citation_ranks=[]),
            _cap(lens="branded", overview=True, source_ranks=[], citation_ranks=[]),
            _cap(lens="comparative", overview=True, source_ranks=[], citation_ranks=[]),
        ]
        for c in caps:
            insert_capture(conn, run_id, c)
        conn.commit()

        rows = compute_run_metrics(conn, run_id)
        by_lens = {r["lens"]: r for r in rows}

        a = by_lens["all"]
        assert a["n_queries"] == 5
        assert a["n_overviews"] == 4
        assert a["overview_coverage"] == pytest.approx(0.8)
        assert a["n_in_sources"] == 2
        assert a["visibility_in_sources"] == pytest.approx(0.5)
        assert a["n_cited"] == 1
        assert a["visibility_in_citations"] == pytest.approx(0.25)
        assert a["avg_source_position"] == pytest.approx(3.5)
        assert a["avg_citation_position"] == pytest.approx(2.0)
        assert a["relative_citation"] == pytest.approx(0.5)

        g = by_lens["general"]
        assert g["n_queries"] == 3
        assert g["n_overviews"] == 2
        assert g["overview_coverage"] == pytest.approx(2 / 3)
        assert g["visibility_in_sources"] == pytest.approx(1.0)
        assert g["visibility_in_citations"] == pytest.approx(0.5)
        assert g["avg_source_position"] == pytest.approx(3.5)
        assert g["avg_citation_position"] == pytest.approx(2.0)
        assert g["relative_citation"] == pytest.approx(0.5)

        b = by_lens["branded"]
        assert b["n_overviews"] == 1
        assert b["n_in_sources"] == 0
        assert b["visibility_in_sources"] == pytest.approx(0.0)
        assert b["n_cited"] == 0
        assert b["visibility_in_citations"] == pytest.approx(0.0)
        assert b["avg_source_position"] is None
        assert b["avg_citation_position"] is None
        assert b["relative_citation"] is None

        c = by_lens["comparative"]
        assert c["n_in_sources"] == 0
        assert c["n_cited"] == 0
        assert c["avg_source_position"] is None
        assert c["avg_citation_position"] is None
        assert c["relative_citation"] is None
    finally:
        conn.close()


def test_funnel_relative_citation(tmp_path):
    db_path = tmp_path / "aeo.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")

        caps = [
            _cap(lens="general", overview=True, source_ranks=[1], citation_ranks=[1]),
            _cap(lens="general", overview=True, source_ranks=[2, 3], citation_ranks=[1]),
            _cap(lens="general", overview=True, source_ranks=[2], citation_ranks=[]),
            _cap(lens="general", overview=True, source_ranks=[], citation_ranks=[]),
            _cap(lens="branded", overview=True, source_ranks=[], citation_ranks=[]),
        ]
        for c in caps:
            insert_capture(conn, run_id, c)
        conn.commit()

        rows = compute_run_metrics(conn, run_id)
        by_lens = {r["lens"]: r for r in rows}

        g = by_lens["general"]
        assert g["n_queries"] == 4
        assert g["n_overviews"] == 4
        assert g["n_in_sources"] == 3
        assert g["n_cited"] == 2
        assert g["visibility_in_sources"] == pytest.approx(0.75)
        assert g["visibility_in_citations"] == pytest.approx(0.5)
        assert g["avg_source_position"] == pytest.approx(5 / 3)
        assert g["avg_citation_position"] == pytest.approx(1.0)
        assert g["n_cited"] <= g["n_in_sources"] <= g["n_overviews"] <= g["n_queries"]
        assert g["relative_citation"] == pytest.approx(2 / 3)
        assert 0.0 <= g["relative_citation"] <= 1.0

        b = by_lens["branded"]
        assert b["n_in_sources"] == 0
        assert b["relative_citation"] is None

        a = by_lens["all"]
        assert a["n_in_sources"] == 3
        assert a["n_cited"] == 2
        assert a["relative_citation"] == pytest.approx(2 / 3)
        assert a["n_cited"] <= a["n_in_sources"] <= a["n_overviews"] <= a["n_queries"]
    finally:
        conn.close()


def test_schema_citation_not_in_sources_raises():
    bad = _valid_capture_dict()
    bad["citations"] = [
        {"rank": 1, "url": "https://other.com/page", "domain": "other.com"},
    ]
    with pytest.raises(ValidationError) as exc_info:
        QueryCapture.model_validate(bad)
    assert "other.com" in str(exc_info.value)


def test_schema_citation_subset_of_sources_ok():
    ok = _valid_capture_dict()
    ok["sources"] = [
        {"rank": 1, "url": "https://example.com/catalog/x", "domain": "example.com"},
        {"rank": 2, "url": "https://wirecutter.com/g", "domain": "wirecutter.com"},
    ]
    ok["citations"] = [
        {"rank": 1, "url": "https://example.com/blog/y", "domain": "example.com"},
    ]
    cap = QueryCapture.model_validate(ok)
    assert [c.domain for c in cap.citations] == ["example.com"]


def test_aggregate_run_persists_and_is_idempotent(tmp_path):
    db_path = tmp_path / "aeo.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")

        caps = [
            _cap(lens="general", overview=True, source_ranks=[1, 3], citation_ranks=[1]),
            _cap(lens="general", overview=True, source_ranks=[2], citation_ranks=[]),
            _cap(lens="branded", overview=True, source_ranks=[], citation_ranks=[]),
        ]
        for c in caps:
            insert_capture(conn, run_id, c)
        conn.commit()

        summary = aggregate_run(conn, run_id)

        assert summary["run_id"] == run_id
        assert summary["brand_id"] == brand_id
        assert summary["engine"] == "google"
        lenses = [m["lens"] for m in summary["metrics"]]
        assert lenses[0] == "all"
        assert set(lenses) == {"all", "general", "branded"}
        for m in summary["metrics"]:
            assert "relative_citation" in m

        db_rows = conn.execute(
            "SELECT lens, n_in_sources, n_cited, relative_citation, computed_at "
            "FROM metrics WHERE run_id = ? ORDER BY lens",
            (run_id,),
        ).fetchall()
        assert len(db_rows) == 3
        persisted = {r["lens"]: r for r in db_rows}
        assert persisted["general"]["relative_citation"] == pytest.approx(0.5)
        assert persisted["branded"]["relative_citation"] is None
        for r in db_rows:
            assert r["computed_at"]

        aggregate_run(conn, run_id)
        n_after = conn.execute(
            "SELECT COUNT(*) FROM metrics WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        assert n_after == 3
    finally:
        conn.close()


def test_aggregate_empty_scope_overview_coverage_null(tmp_path):
    db_path = tmp_path / "aeo.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")

        rows = compute_run_metrics(conn, run_id)
        assert [r["lens"] for r in rows] == ["all"]
        a = rows[0]
        assert a["n_queries"] == 0
        assert a["n_overviews"] == 0
        assert a["overview_coverage"] is None
        assert a["visibility_in_sources"] is None
        assert a["relative_citation"] is None
    finally:
        conn.close()


def test_aggregate_run_not_found_raises(tmp_path):
    db_path = tmp_path / "aeo.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
        with pytest.raises(ValueError, match="run 999 not found"):
            compute_run_metrics(conn, 999)
        with pytest.raises(ValueError, match="run 999 not found"):
            aggregate_run(conn, 999)
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
