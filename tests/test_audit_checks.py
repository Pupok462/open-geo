from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from audit.bots import AI_CRAWLERS
from audit.checks import (
    _has_markdown_h1,
    _sitemap_valid,
    build_checks,
    run_audit,
)
from audit.fetch import Fetched, SiteArtifacts
from audit.html import HtmlAnalysis
from audit.robots import BotPolicy, RobotsAnalysis

_SITEMAP_XML = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://example.com/</loc></url></urlset>"
)


def _f(status=200, text="body", url="https://example.com/", scheme="https", redirects=0, error=None):
    return Fetched(
        url=url,
        final_url=url,
        status=status,
        ok=status == 200,
        headers={},
        text=text,
        error=error,
        redirects=redirects,
        scheme=scheme,
    )


def _unreachable(url="https://example.com/"):
    return Fetched(url=url, final_url=None, status=None, ok=False, headers={},
                   text=None, error="connect error", redirects=0, scheme=None)


def _artifacts(
    homepage=None,
    homepage_http=None,
    robots=None,
    sitemap=None,
    llms=None,
    security=None,
    target_page=None,
):
    return SiteArtifacts(
        target="example.com",
        domain="example.com",
        checked_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        homepage=homepage if homepage is not None else _f(),
        homepage_http=homepage_http if homepage_http is not None else _f(url="http://example.com/", scheme="https"),
        robots=robots if robots is not None else _f(url="https://example.com/robots.txt", text="User-agent: *\nAllow: /"),
        sitemap=sitemap if sitemap is not None else _f(url="https://example.com/sitemap.xml", text=_SITEMAP_XML),
        llms=llms if llms is not None else _f(url="https://example.com/llms.txt", text="# Example\n> x"),
        security=security if security is not None else _f(url="https://example.com/.well-known/security.txt", text="Contact: x"),
        target_page=target_page,
    )


def _robots(present=True, malformed=False, sitemaps=None, blocked=()):
    policies = [
        BotPolicy(ua=b.ua, operator=b.operator, tier=b.tier, allowed=b.ua not in blocked)
        for b in AI_CRAWLERS
    ]
    return RobotsAnalysis(
        fetched=True,
        present=present,
        malformed=malformed,
        sitemaps=list(sitemaps or []),
        policies=policies,
    )


def _html(**over):
    d = dict(
        raw_word_count=300, heading_count=2, empty_root_markers=[], framework=None,
        has_noscript=False, js_dependent=False, h1_count=1, has_main_or_article=True,
        heading_order_ok=True, title="T", meta_description="D", canonical="https://example.com/",
        lang="en", noindex=False, og_present=True, jsonld_types=["Organization"],
        jsonld_blocks=1, jsonld_invalid=0, has_organization=True, org_logo=True, org_sameas=1,
        has_about_link=True, has_contact_link=True, has_dates=True, has_feed=True,
    )
    d.update(over)
    return HtmlAnalysis(**d)


def _by_id(checks):
    return {c.id: c for c in checks}


def _build(artifacts=None, robots=None, home=None, page=None, engine="google"):
    artifacts = artifacts if artifacts is not None else _artifacts()
    robots = robots if robots is not None else _robots(sitemaps=["https://example.com/sitemap.xml"])
    home = home if home is not None else _html()
    page = page if page is not None else home
    return _by_id(build_checks(artifacts, robots, home, page, engine))


# ---- helpers ----

def test_sitemap_valid():
    assert _sitemap_valid(_SITEMAP_XML) is True
    assert _sitemap_valid("<not xml") is False
    assert _sitemap_valid("") is False
    assert _sitemap_valid(None) is False


def test_has_markdown_h1():
    assert _has_markdown_h1("# Title") is True
    assert _has_markdown_h1("intro\n## Section") is True
    assert _has_markdown_h1("no heading here") is False
    assert _has_markdown_h1("") is False
    assert _has_markdown_h1(None) is False


# ---- A1 ----

def test_a1_unreachable_fails():
    c = _build(artifacts=_artifacts(homepage=_unreachable()))["A1"]
    assert c.status == "fail" and c.severity == "blocker"


def test_a1_no_https_redirect_warns():
    http = _f(url="http://example.com/", scheme="http", status=200)
    c = _build(artifacts=_artifacts(homepage_http=http))["A1"]
    assert c.status == "warn"


def test_a1_pass():
    assert _build()["A1"].status == "pass"


# ---- A2 ----

def test_a2_skip_when_unreachable():
    assert _build(artifacts=_artifacts(homepage=_unreachable()))["A2"].status == "skip"


def test_a2_fail_on_non_200():
    assert _build(artifacts=_artifacts(homepage=_f(status=404)))["A2"].status == "fail"


def test_a2_fail_on_bad_target_page():
    a = _artifacts(target_page=_f(status=404, url="https://example.com/repo"))
    assert _build(artifacts=a)["A2"].status == "fail"


def test_a2_warn_on_long_redirect_chain():
    assert _build(artifacts=_artifacts(homepage=_f(redirects=3)))["A2"].status == "warn"


def test_a2_pass():
    assert _build()["A2"].status == "pass"


# ---- A3 / A3b (engine-aware) ----

def test_a3_blocks_when_engine_search_bot_disallowed():
    c = _build(robots=_robots(blocked={"Googlebot"}), engine="google")["A3"]
    assert c.status == "fail" and c.severity == "blocker"
    assert c.remediation is not None


def test_a3_engine_aware_other_engine_not_blocked():
    checks = _build(robots=_robots(blocked={"Googlebot"}), engine="chatgpt_search")
    assert checks["A3"].status == "pass"
    assert checks["A3b"].status == "warn"
    assert "Googlebot" in checks["A3b"].detail


def test_a3b_skip_when_no_robots():
    assert _build(robots=_robots(present=False))["A3b"].status == "skip"


def test_a3b_warn_when_malformed():
    assert _build(robots=_robots(malformed=True))["A3b"].status == "warn"


def test_a3b_training_block_is_informational_not_a_warn():
    checks = _build(robots=_robots(blocked={"GPTBot"}), engine="google")
    assert checks["A3"].status == "pass"
    assert checks["A3b"].status == "pass"
    assert "GPTBot" in checks["A3b"].detail


def test_a3b_pass_clean():
    assert _build()["A3b"].status == "pass"


def test_a3_skips_when_robots_is_unreadable_instead_of_asserting_access():
    from audit.robots import analyze_robots

    for status in (500, 503, None):
        robots = analyze_robots(None, status)
        assert robots.unreadable is True
        checks = _build(robots=robots, engine="google")
        assert checks["A3"].status == "skip"
        assert checks["A3b"].status == "warn"
        assert "unverified" in checks["A3b"].detail or "not verified" in checks["A3"].detail


def test_a3_still_passes_when_robots_is_absent_404():
    from audit.robots import analyze_robots

    robots = analyze_robots(None, 404)
    assert robots.unreadable is False
    checks = _build(robots=robots, engine="google")
    assert checks["A3"].status == "pass"
    assert checks["A3b"].status == "skip"


def test_a3_skips_for_engine_without_a_published_search_bot():
    checks = _build(robots=_robots(blocked={"Googlebot"}), engine="deepseek")
    assert checks["A3"].status == "skip"
    assert checks["A3"].severity == "blocker"
    assert "deepseek" in checks["A3"].detail


def test_unmapped_engine_never_produces_a_blocker_from_robots():
    blocking_robots = "User-agent: Googlebot\nDisallow: /"
    blocked = run_audit(
        "example.com", engine="google", client=_client(robots=blocking_robots)
    )
    assert "A3" in blocked.blockers

    unmapped = run_audit(
        "example.com", engine="deepseek", client=_client(robots=blocking_robots)
    )
    assert "A3" not in unmapped.blockers
    assert unmapped.verdict != "blocked"


def test_a3b_reports_the_gating_bot_when_the_engine_is_unmapped():
    checks = _build(robots=_robots(blocked={"Googlebot"}), engine="deepseek")
    assert checks["A3b"].status == "warn"
    assert "Googlebot" in checks["A3b"].detail


# ---- A4 ----

def test_a4_pass_valid_and_referenced():
    assert _build()["A4"].status == "pass"


def test_a4_warn_valid_not_referenced():
    c = _build(robots=_robots(sitemaps=[]))["A4"]
    assert c.status == "warn"


def test_a4_warn_malformed_xml():
    a = _artifacts(sitemap=_f(url="https://example.com/sitemap.xml", text="<bad"))
    assert _build(artifacts=a)["A4"].status == "warn"


def test_a4_fail_absent():
    a = _artifacts(sitemap=_f(status=404, text=""))
    assert _build(artifacts=a)["A4"].status == "fail"


# ---- A5 ----

def test_a5_skip_when_unreadable():
    a = _artifacts(homepage=_unreachable())
    assert _build(artifacts=a)["A5"].status == "skip"


def test_a5_fail_spa_evidence_framework():
    page = _html(js_dependent=True, framework="Next", raw_word_count=0, heading_count=0)
    c = _build(page=page)["A5"]
    assert c.status == "fail" and c.severity == "blocker"


def test_a5_fail_spa_evidence_empty_root():
    page = _html(js_dependent=True, framework=None, empty_root_markers=["div#root"], raw_word_count=0)
    assert _build(page=page)["A5"].status == "fail"


def test_a5_warn_thin_content_no_spa_evidence():
    page = _html(js_dependent=True, framework=None, empty_root_markers=[], raw_word_count=19, heading_count=1)
    c = _build(page=page)["A5"]
    assert c.status == "warn" and c.severity == "blocker"


def test_a5_pass():
    assert _build()["A5"].status == "pass"


def test_a5_readable_via_target_page_only():
    a = _artifacts(homepage=_f(status=500, text=None),
                   target_page=_f(status=200, text="<html><body><h1>x</h1></body></html>", url="https://example.com/r"))
    page = _html(js_dependent=False)
    assert _build(artifacts=a, page=page)["A5"].status == "pass"


# ---- content checks: readable=False path ----

def test_content_checks_skip_when_unreadable():
    a = _artifacts(homepage=_f(status=500, text=None))
    checks = _build(artifacts=a)
    for cid in ("B1", "B2", "B3", "C1", "C2", "D1", "D2"):
        assert checks[cid].status == "skip", cid


# ---- B1 ----

def test_b1_fail_no_jsonld():
    assert _build(home=_html(jsonld_blocks=0, jsonld_types=[]))["B1"].status == "fail"


def test_b1_warn_invalid_block():
    assert _build(home=_html(jsonld_blocks=2, jsonld_invalid=1))["B1"].status == "warn"


def test_b1_warn_no_key_type():
    h = _html(jsonld_blocks=1, jsonld_invalid=0, jsonld_types=["Thing"], has_organization=False)
    assert _build(home=h)["B1"].status == "warn"


def test_b1_pass():
    assert _build()["B1"].status == "pass"


# ---- B2 ----

def test_b2_pass():
    assert _build()["B2"].status == "pass"


def test_b2_fail_no_headings():
    assert _build(home=_html(heading_count=0, h1_count=0))["B2"].status == "fail"


def test_b2_warn_multiple_h1():
    assert _build(home=_html(h1_count=2))["B2"].status == "warn"


def test_b2_warn_no_main_and_skip():
    assert _build(home=_html(has_main_or_article=False, heading_order_ok=False))["B2"].status == "warn"


# ---- B3 ----

def test_b3_fail_noindex():
    assert _build(home=_html(noindex=True))["B3"].status == "fail"


def test_b3_pass():
    assert _build()["B3"].status == "pass"


def test_b3_warn_missing_meta():
    assert _build(home=_html(meta_description=None, canonical=None))["B3"].status == "warn"


# ---- B4 ----

def test_b4_pass():
    assert _build()["B4"].status == "pass"


def test_b4_warn_no_heading():
    a = _artifacts(llms=_f(url="https://example.com/llms.txt", text="no heading"))
    assert _build(artifacts=a)["B4"].status == "warn"


def test_b4_fail_absent():
    a = _artifacts(llms=_f(status=404, text=""))
    assert _build(artifacts=a)["B4"].status == "fail"


# ---- C1 ----

def test_c1_pass():
    assert _build()["C1"].status == "pass"


def test_c1_warn_one():
    assert _build(home=_html(has_contact_link=False))["C1"].status == "warn"


def test_c1_fail_none():
    assert _build(home=_html(has_about_link=False, has_contact_link=False))["C1"].status == "fail"


# ---- C2 ----

def test_c2_pass():
    assert _build()["C2"].status == "pass"


def test_c2_warn_org_without_logo():
    assert _build(home=_html(org_logo=False))["C2"].status == "warn"


def test_c2_fail_no_org():
    assert _build(home=_html(has_organization=False, org_logo=False, org_sameas=0))["C2"].status == "fail"


# ---- D1/D2/D3 ----

def test_d1():
    assert _build()["D1"].status == "pass"
    assert _build(home=_html(has_dates=False))["D1"].status == "fail"


def test_d2():
    assert _build()["D2"].status == "pass"
    assert _build(home=_html(has_feed=False))["D2"].status == "fail"


def test_d3_pass_and_fail():
    assert _build()["D3"].status == "pass"
    a = _artifacts(security=_f(status=404, text=""))
    assert _build(artifacts=a)["D3"].status == "fail"


# ---- run_audit integration (MockTransport) ----

_HEALTHY = (
    '<!doctype html><html lang="en"><head><title>T</title>'
    '<meta name="description" content="d"><link rel="canonical" href="https://example.com/">'
    '<meta property="og:title" content="x">'
    '<link rel="alternate" type="application/rss+xml" href="/f">'
    '<script type="application/ld+json">{"@type":"Organization","logo":"l","sameAs":["s"]}</script>'
    '</head><body><main><h1>Hi</h1><p>' + ("word " * 250) + '</p>'
    '<a href="/about">About</a><a href="/contact">Contact</a>'
    '<time datetime="2026-01-01">t</time></main></body></html>'
)


def _client(robots="User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml", html=_HEALTHY, extra=None):
    def handler(req):
        u = str(req.url)
        if u.endswith("/robots.txt"):
            return httpx.Response(200, text=robots)
        if u.endswith("/sitemap.xml"):
            return httpx.Response(200, text=_SITEMAP_XML)
        if u.endswith("/llms.txt"):
            return httpx.Response(200, text="# Example")
        if u.endswith("/security.txt"):
            return httpx.Response(200, text="Contact: x")
        if u.startswith("http://"):
            return httpx.Response(301, headers={"location": "https://example.com/"})
        if extra is not None:
            return extra(req)
        return httpx.Response(200, text=html)
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_run_audit_healthy_is_ready():
    r = run_audit("example.com", engine="google", client=_client())
    assert r.verdict == "ready"
    assert r.passed is True
    assert r.domain == "example.com"


def test_run_audit_blocked_on_robots():
    r = run_audit("example.com", engine="google", client=_client(robots="User-agent: Googlebot\nDisallow: /"))
    assert r.verdict == "blocked"
    assert "A3" in r.blockers


def test_run_audit_spa_blocked_on_a5():
    spa = '<!doctype html><html><head><title>a</title></head><body><div id="root"></div><script src="/_next/static/x.js"></script></body></html>'
    r = run_audit("example.com", engine="google", client=_client(html=spa))
    assert "A5" in r.blockers


def test_run_audit_target_prefix_uses_target_page():
    def extra(req):
        u = str(req.url)
        if u == "https://github.com/user/repo/":
            return httpx.Response(200, text=_HEALTHY)
        return httpx.Response(200, text=_HEALTHY)
    client = _client(extra=extra)
    r = run_audit("github.com/user/repo", engine="google", client=client)
    assert r.domain == "github.com"
    assert r.target == "github.com/user/repo"
