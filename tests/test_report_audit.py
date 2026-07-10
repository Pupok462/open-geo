from __future__ import annotations

import io
from datetime import datetime

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from audit.schema import AuditResult, CheckResult
from pipeline.db import get_conn, init_db, insert_audit
from pipeline.schema import normalize_domain
from report.generate import (
    MARGIN,
    PAGE_H,
    Doc,
    LensMetrics,
    ReportData,
    build_pdf,
    load_report_data,
    register_fonts,
    render_audit,
    _truncate_to_width,
)
from report.i18n import Translator

BRAND = "Example"
DOMAIN = "example.com"
ENGINE = "google"

PDF_MAGIC = b"%PDF"


def _canvas() -> canvas.Canvas:
    register_fonts()
    return canvas.Canvas(io.BytesIO(), pagesize=A4)


def _doc() -> Doc:
    return Doc(_canvas())


def _en() -> Translator:
    return Translator("en")


def _lm(lens: str = "all") -> LensMetrics:
    return LensMetrics(
        lens=lens,
        n_queries=24,
        n_overviews=18,
        overview_coverage=0.75,
        n_in_sources=9,
        visibility_in_sources=0.5,
        n_cited=7,
        visibility_in_citations=0.39,
        avg_source_position=2.0,
        avg_citation_position=1.5,
        relative_citation=0.78,
    )


def _checks() -> list[CheckResult]:
    return [
        CheckResult(
            id="A1",
            category="A",
            title="HTTPS reachable",
            severity="blocker",
            status="pass",
            detail="Homepage answered 200 over HTTPS",
            remediation=None,
        ),
        CheckResult(
            id="A3",
            category="A",
            title="Search bot allowed in robots.txt",
            severity="blocker",
            status="fail",
            detail="robots.txt Disallow: / blocks the engine's search bot",
            remediation="Add an Allow rule for the engine bot user-agent",
        ),
        CheckResult(
            id="B1",
            category="B",
            title="Organization structured data",
            severity="recommended",
            status="warn",
            detail="No JSON-LD Organization block on the homepage " + "and lots more prose " * 12,
            remediation="Add an Organization JSON-LD snippet",
        ),
        CheckResult(
            id="C2",
            category="C",
            title="Wikidata / entity presence",
            severity="nice_to_have",
            status="skip",
            detail="Not evaluated for this domain",
            remediation=None,
        ),
    ]


def _audit_dict(engine: str = ENGINE, domain: str = DOMAIN) -> dict:
    result = AuditResult(
        target=domain,
        domain=normalize_domain(domain),
        engine=engine,
        checked_at=datetime(2026, 7, 1, 12, 0, 0),
        checks=_checks(),
    )
    return result.model_dump(mode="json")


def _report_data(**overrides) -> ReportData:
    base = dict(
        brand_name=BRAND,
        brand_domain=DOMAIN,
        engine=ENGINE,
        period="today",
        run_id=2,
        run_at="2026-06-18T09:00:00Z",
        prev_run_id=None,
        prev_run_at=None,
        metrics={"all": _lm("all")},
        prev_metrics={},
        sentiments={},
    )
    base.update(overrides)
    return ReportData(**base)


def _store_audit(db_path: str, engine: str = ENGINE, domain: str = DOMAIN) -> None:
    result = AuditResult(
        target=domain,
        domain=normalize_domain(domain),
        engine=engine,
        checked_at=datetime(2026, 7, 1, 12, 0, 0),
        checks=_checks(),
    )
    conn = get_conn(db_path)
    try:
        init_db(conn)
        insert_audit(
            conn,
            result.target,
            result.domain,
            engine,
            result.checked_at.isoformat(),
            result.verdict,
            result.score,
            result.verdict == "blocked",
            result.model_dump_json(),
        )
    finally:
        conn.close()


def test_reportdata_audit_defaults_to_none():
    rd = _report_data()
    assert rd.audit is None


def test_truncate_to_width_short_string_unchanged():
    register_fonts()
    from report.generate import FONT

    assert _truncate_to_width("short", FONT, 10, 1000) == "short"


def test_truncate_to_width_long_string_gets_ellipsis():
    register_fonts()
    from report.generate import FONT

    out = _truncate_to_width("x" * 400, FONT, 10, 40)
    assert out.endswith("…")
    assert len(out) < 401


def test_render_audit_none_branch_renders_empty_line():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_audit(doc, _en(), _report_data(audit=None))
    assert doc.y < y0


def test_render_audit_with_checks_covers_all_labels():
    doc = _doc()
    doc.fill_background()
    y0 = doc.y
    render_audit(doc, _en(), _report_data(audit=_audit_dict()))
    assert doc.y < y0


def test_render_audit_empty_checks_still_renders_verdict():
    doc = _doc()
    doc.fill_background()
    audit = {"verdict": "ready", "score": 100, "checks": []}
    render_audit(doc, _en(), _report_data(audit=audit))


def test_render_audit_unknown_labels_fall_back_verbatim():
    doc = _doc()
    doc.fill_background()
    audit = {
        "verdict": "mystery",
        "score": 42,
        "checks": [
            {
                "id": "Z9",
                "category": "A",
                "title": "weird row",
                "severity": "unknown_sev",
                "status": "unknown_status",
                "detail": "no idea",
            }
        ],
    }
    render_audit(doc, _en(), _report_data(audit=audit))


def test_render_audit_forces_page_break_when_cursor_low():
    doc = _doc()
    doc.fill_background()
    doc.y = MARGIN + 25
    page0 = doc.c.getPageNumber()
    render_audit(doc, _en(), _report_data(audit=_audit_dict()))
    assert doc.c.getPageNumber() > page0


@pytest.mark.parametrize("lang", ["en", "ru", "zh", "ar"])
def test_render_audit_localized_chrome_does_not_raise(lang):
    register_fonts(lang)
    try:
        doc = Doc(canvas.Canvas(io.BytesIO(), pagesize=A4))
        doc.fill_background()
        render_audit(doc, Translator(lang), _report_data(audit=_audit_dict()))
        assert doc.y <= PAGE_H - MARGIN
    finally:
        register_fonts("en")


def test_load_report_data_populates_audit_when_present(seeded_db_path):
    _store_audit(seeded_db_path)
    conn = get_conn(seeded_db_path)
    try:
        data = load_report_data(conn, BRAND, "example.com", ENGINE, "today")
    finally:
        conn.close()
    assert isinstance(data.audit, dict)
    assert data.audit["verdict"] == "blocked"
    assert data.audit["score"] == _audit_dict()["score"]
    assert any(c["id"] == "A3" for c in data.audit["checks"])


def test_load_report_data_audit_none_when_absent(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        data = load_report_data(conn, BRAND, "example.com", ENGINE, "today")
    finally:
        conn.close()
    assert data.audit is None


def test_load_report_data_audit_matches_url_prefix_registrable_domain(empty_db_path):
    from pipeline.db import (
        create_run,
        get_or_create_brand,
        update_run_counts,
    )

    conn = get_conn(empty_db_path)
    try:
        bid = get_or_create_brand(conn, "Repo", "https://github.com/user/repo")
        rid = create_run(conn, bid, ENGINE)
        update_run_counts(conn, rid, n_queries=1, n_ok=1, n_failed=0, status="done")
        conn.execute(
            """
            INSERT INTO metrics
                (run_id, brand_id, engine, lens, n_queries, n_overviews,
                 overview_coverage, n_in_sources, visibility_in_sources, n_cited,
                 visibility_in_citations, avg_source_position, avg_citation_position,
                 relative_citation, computed_at)
            VALUES (?, ?, ?, 'all', 10, 8, 0.8, 4, 0.5, 2, 0.25, 2.5, 1.5, 0.5,
                    '2026-06-01T00:00:00Z')
            """,
            (rid, bid, ENGINE),
        )
        conn.commit()
    finally:
        conn.close()

    _store_audit(empty_db_path, domain="github.com")

    conn = get_conn(empty_db_path)
    try:
        data = load_report_data(conn, "Repo", "github.com/user/repo", ENGINE, "today")
    finally:
        conn.close()
    assert isinstance(data.audit, dict)
    assert data.audit["domain"] == "github.com"


@pytest.mark.slow
def test_build_pdf_with_audit_writes_pdf(tmp_path):
    out = tmp_path / "with_audit.pdf"
    build_pdf(_report_data(audit=_audit_dict()), str(out))
    assert out.exists()
    assert out.read_bytes()[:4] == PDF_MAGIC


@pytest.mark.slow
def test_build_pdf_without_audit_writes_pdf(tmp_path):
    out = tmp_path / "no_audit.pdf"
    build_pdf(_report_data(audit=None), str(out))
    assert out.exists()
    assert out.read_bytes()[:4] == PDF_MAGIC


@pytest.mark.slow
def test_generate_report_end_to_end_with_stored_audit(seeded_db_path, tmp_path):
    from report.generate import generate_report

    _store_audit(seeded_db_path)
    out = tmp_path / "gen_audit.pdf"
    data = generate_report(
        db_path=seeded_db_path,
        brand=BRAND,
        domain=DOMAIN,
        engine=ENGINE,
        period="today",
        out_path=str(out),
        lang="en",
    )
    assert out.exists() and out.read_bytes()[:4] == PDF_MAGIC
    assert isinstance(data.audit, dict)
    register_fonts("en")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
