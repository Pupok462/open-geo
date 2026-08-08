from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from audit import bots
from audit.fetch import SiteArtifacts, gather
from audit.html import HtmlAnalysis, analyze_html
from audit.robots import RobotsAnalysis, analyze_robots
from audit.schema import AuditResult, CheckResult

ROBOTS_ALLOW = (
    "User-agent: Googlebot\n"
    "Allow: /\n"
    "User-agent: OAI-SearchBot\n"
    "Allow: /\n"
    "Sitemap: https://<domain>/sitemap.xml"
)
ORG_JSONLD = (
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Organization",'
    '"name":"<Brand>","url":"https://<domain>/",'
    '"logo":"https://<domain>/logo.png",'
    '"sameAs":["https://www.linkedin.com/company/<brand>"]}</script>'
)
LLMS_MIN = (
    "# <Brand>\n"
    "> One-sentence description of what <Brand> is.\n"
    "## Docs\n"
    "- [Getting started](https://<domain>/docs): setup and first steps"
)

_KEY_SCHEMA_TYPES = {
    "Organization",
    "WebSite",
    "Article",
    "BlogPosting",
    "FAQPage",
    "Product",
    "BreadcrumbList",
    "HowTo",
}


def _c(
    id: str,
    category: str,
    title: str,
    severity: str,
    status: str,
    detail: str,
    remediation: Optional[str] = None,
) -> CheckResult:
    return CheckResult(
        id=id,
        category=category,
        title=title,
        severity=severity,
        status=status,
        detail=detail,
        remediation=remediation,
    )


def _sitemap_valid(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return False
    try:
        ET.fromstring(text)
        return True
    except ET.ParseError:
        return False


def _has_markdown_h1(text: Optional[str]) -> bool:
    if not text:
        return False
    return any(line.lstrip().startswith("#") for line in text.splitlines())


def _check_a1(artifacts: SiteArtifacts) -> CheckResult:
    hp = artifacts.homepage
    if hp.status is None:
        return _c(
            "A1", "A", "Domain resolves & HTTPS valid", "blocker", "fail",
            f"{hp.url} unreachable: {hp.error or 'no response'}.",
            "Serve a valid TLS certificate and a reachable homepage over HTTPS.",
        )
    http = artifacts.homepage_http
    if http.status is not None and http.scheme is not None and http.scheme != "https":
        return _c(
            "A1", "A", "Domain resolves & HTTPS valid", "blocker", "warn",
            "HTTPS is reachable but http:// does not redirect to https://.",
            "Add a 301 redirect from http:// to https://.",
        )
    return _c(
        "A1", "A", "Domain resolves & HTTPS valid", "blocker", "pass",
        "Domain resolves and serves valid HTTPS.",
    )


def _check_a2(artifacts: SiteArtifacts) -> CheckResult:
    hp = artifacts.homepage
    if hp.status is None:
        return _c("A2", "A", "Homepage returns 200", "blocker", "skip",
                  "Homepage unreachable (see A1).")
    tp = artifacts.target_page
    if hp.status != 200:
        return _c("A2", "A", "Homepage returns 200", "blocker", "fail",
                  f"Homepage returned HTTP {hp.status}.",
                  "Serve HTTP 200 at the canonical homepage.")
    if tp is not None and tp.status is not None and tp.status != 200:
        return _c("A2", "A", "Homepage returns 200", "blocker", "fail",
                  f"Target page {tp.url} returned HTTP {tp.status}.",
                  "Ensure the target URL returns HTTP 200.")
    if hp.redirects > 2:
        return _c("A2", "A", "Homepage returns 200", "blocker", "warn",
                  f"Homepage 200 but reached via {hp.redirects} redirects.",
                  "Shorten the redirect chain to the canonical homepage.")
    return _c("A2", "A", "Homepage returns 200", "blocker", "pass",
              "Homepage returns HTTP 200.")


def _check_a3(robots: RobotsAnalysis, engine: Optional[str]) -> CheckResult:
    label = engine or "generic"
    if robots.unreadable:
        return _c(
            "A3", "A", "robots.txt allows the engine's search bot", "blocker", "skip",
            "robots.txt could not be read (server error or timeout), so crawl access "
            "was not verified. Crawlers treat an unreadable robots.txt as a full "
            "disallow, so re-check once it serves 200 or 404.",
            "Serve /robots.txt with HTTP 200 (or 404 if you have none).",
        )
    if not bots.is_engine_mapped(engine):
        return _c(
            "A3", "A", "robots.txt allows the engine's search bot", "blocker", "skip",
            f"No published search-bot user-agent is mapped for '{label}', so robots.txt "
            f"cannot be graded as a citation blocker for this engine. Other search bots "
            f"are still reported by A3b.",
            ROBOTS_ALLOW,
        )
    gua = bots.gating_ua(engine)
    pol = next((p for p in robots.policies if p.ua == gua), None)
    allowed = pol.allowed if pol is not None else True
    if not allowed:
        return _c(
            "A3", "A", "robots.txt allows the engine's search bot", "blocker", "fail",
            f"robots.txt disallows {gua} (the search bot for {label}) from '/'.",
            ROBOTS_ALLOW,
        )
    return _c(
        "A3", "A", "robots.txt allows the engine's search bot", "blocker", "pass",
        f"{gua} (the search bot for {label}) may fetch '/'.",
    )


def _check_a3b(robots: RobotsAnalysis, engine: Optional[str]) -> CheckResult:
    gua = bots.gating_ua(engine) if bots.is_engine_mapped(engine) else None
    other = [
        p.ua for p in robots.policies
        if p.tier == "search" and not p.allowed and p.ua != gua
    ]
    training = [p.ua for p in robots.policies if p.tier == "training" and not p.allowed]
    tnote = (
        f" Training bots blocked (a policy choice, not a citation block): {', '.join(training)}."
        if training else ""
    )
    if robots.unreadable:
        return _c("A3b", "A", "robots.txt hygiene", "recommended", "warn",
                  "robots.txt could not be read (server error or timeout) — crawl "
                  "access is unverified, not confirmed.",
                  "Serve /robots.txt with HTTP 200 (or 404 if you have none).")
    if not robots.present:
        return _c("A3b", "A", "robots.txt hygiene", "recommended", "skip",
                  "No robots.txt — everything is allowed." + tnote)
    if robots.malformed:
        return _c("A3b", "A", "robots.txt hygiene", "recommended", "warn",
                  "robots.txt could not be parsed." + tnote)
    if other:
        return _c("A3b", "A", "robots.txt hygiene", "recommended", "warn",
                  f"Other search bots blocked: {', '.join(other)}." + tnote,
                  ROBOTS_ALLOW)
    return _c("A3b", "A", "robots.txt hygiene", "recommended", "pass",
              "No other search bots blocked." + tnote)


def _check_a4(artifacts: SiteArtifacts, robots: RobotsAnalysis) -> CheckResult:
    sm = artifacts.sitemap
    if sm.status == 200 and _sitemap_valid(sm.text):
        if robots.sitemaps:
            return _c("A4", "A", "sitemap.xml present & referenced", "recommended", "pass",
                      "sitemap.xml is valid XML and referenced in robots.txt.")
        return _c("A4", "A", "sitemap.xml present & referenced", "recommended", "warn",
                  "sitemap.xml is valid but not referenced in robots.txt.",
                  "Add a `Sitemap:` line to robots.txt.")
    if sm.status == 200:
        return _c("A4", "A", "sitemap.xml present & referenced", "recommended", "warn",
                  "sitemap.xml is present but not well-formed XML.",
                  "Serve a valid XML sitemap at /sitemap.xml.")
    return _c("A4", "A", "sitemap.xml present & referenced", "recommended", "fail",
              "No sitemap.xml found.",
              "Publish /sitemap.xml and reference it in robots.txt.")


def _check_a5(artifacts: SiteArtifacts, page: HtmlAnalysis) -> CheckResult:
    hp = artifacts.homepage
    tp = artifacts.target_page
    readable = (hp.status == 200 and hp.text is not None) or (
        tp is not None and tp.status == 200 and tp.text is not None
    )
    if not readable:
        return _c("A5", "A", "Content in raw HTML (SSR)", "blocker", "skip",
                  "Could not read page HTML (see A1/A2).")
    if not page.js_dependent:
        return _c("A5", "A", "Content in raw HTML (SSR)", "blocker", "pass",
                  f"Primary content is present in the raw HTML ({page.raw_word_count} words).")
    spa_evidence = bool(page.empty_root_markers) or page.framework is not None
    fw = f" ({page.framework})" if page.framework else ""
    if spa_evidence:
        return _c(
            "A5", "A", "Content in raw HTML (SSR)", "blocker", "fail",
            f"Primary content is JS-rendered{fw}: an SPA shell with {page.raw_word_count} "
            "words in the raw HTML.",
            "Server-render or pre-render the primary content so it is in the initial HTML.",
        )
    return _c(
        "A5", "A", "Content in raw HTML (SSR)", "blocker", "warn",
        f"Thin raw HTML ({page.raw_word_count} words, {page.heading_count} headings) with no "
        "server-rendered main block — verify the content is not JS-only.",
        "Ensure the primary content is server-rendered / present in the initial HTML.",
    )


def _content_checks(
    artifacts: SiteArtifacts, home: HtmlAnalysis, readable: bool
) -> list[CheckResult]:
    out: list[CheckResult] = []

    if not readable:
        out.append(_c("B1", "B", "Structured data (JSON-LD)", "recommended", "skip",
                      "Homepage HTML unavailable."))
    elif home.jsonld_blocks == 0:
        out.append(_c("B1", "B", "Structured data (JSON-LD)", "recommended", "fail",
                      "No JSON-LD structured data found.", ORG_JSONLD))
    elif home.jsonld_invalid > 0:
        out.append(_c("B1", "B", "Structured data (JSON-LD)", "recommended", "warn",
                      f"{home.jsonld_invalid} of {home.jsonld_blocks} JSON-LD blocks are invalid JSON.",
                      ORG_JSONLD))
    elif not (set(home.jsonld_types) & _KEY_SCHEMA_TYPES):
        found = ", ".join(home.jsonld_types) or "none"
        out.append(_c("B1", "B", "Structured data (JSON-LD)", "recommended", "warn",
                      f"JSON-LD present but no key entity type (found: {found}).", ORG_JSONLD))
    else:
        keys = ", ".join(t for t in home.jsonld_types if t in _KEY_SCHEMA_TYPES)
        out.append(_c("B1", "B", "Structured data (JSON-LD)", "recommended", "pass",
                      f"Valid JSON-LD present: {keys}."))

    if not readable:
        out.append(_c("B2", "B", "Semantic HTML", "recommended", "skip",
                      "Homepage HTML unavailable."))
    elif home.h1_count == 1 and home.has_main_or_article and home.heading_order_ok:
        out.append(_c("B2", "B", "Semantic HTML", "recommended", "pass",
                      "Single <h1>, a <main>/<article>, and sane heading order."))
    elif home.heading_count == 0:
        out.append(_c("B2", "B", "Semantic HTML", "recommended", "fail",
                      "No headings found in the page.",
                      "Add a single <h1> and wrap primary content in <main>/<article>."))
    else:
        issues = []
        if home.h1_count != 1:
            issues.append(f"{home.h1_count} <h1> elements")
        if not home.has_main_or_article:
            issues.append("no <main>/<article>")
        if not home.heading_order_ok:
            issues.append("heading levels skip")
        out.append(_c("B2", "B", "Semantic HTML", "recommended", "warn",
                      "; ".join(issues) + ".",
                      "Use exactly one <h1>, a <main>/<article>, and a non-skipping heading order."))

    if not readable:
        out.append(_c("B3", "B", "Meta basics", "recommended", "skip",
                      "Homepage HTML unavailable."))
    elif home.noindex:
        out.append(_c("B3", "B", "Meta basics", "recommended", "fail",
                      "Homepage is marked noindex (asks search engines to exclude it).",
                      "Remove the noindex robots meta from indexable pages."))
    elif home.title and home.meta_description and home.canonical:
        out.append(_c("B3", "B", "Meta basics", "recommended", "pass",
                      "Title, description and canonical present; not noindex."))
    else:
        missing = [
            name for name, val in (
                ("title", home.title),
                ("description", home.meta_description),
                ("canonical", home.canonical),
            ) if not val
        ]
        out.append(_c("B3", "B", "Meta basics", "recommended", "warn",
                      f"Missing meta: {', '.join(missing)}.",
                      "Add a unique <title>, a meta description and a canonical link."))

    llms = artifacts.llms
    if llms.status == 200 and _has_markdown_h1(llms.text):
        out.append(_c("B4", "B", "llms.txt present", "nice_to_have", "pass",
                      "/llms.txt is present with a top-level heading."))
    elif llms.status == 200:
        out.append(_c("B4", "B", "llms.txt present", "nice_to_have", "warn",
                      "/llms.txt is present but has no top-level heading.", LLMS_MIN))
    else:
        out.append(_c("B4", "B", "llms.txt present", "nice_to_have", "fail",
                      "No /llms.txt found.", LLMS_MIN))

    if not readable:
        out.append(_c("C1", "C", "About / Contact pages", "recommended", "skip",
                      "Homepage HTML unavailable."))
    elif home.has_about_link and home.has_contact_link:
        out.append(_c("C1", "C", "About / Contact pages", "recommended", "pass",
                      "About and Contact links found."))
    elif home.has_about_link or home.has_contact_link:
        out.append(_c("C1", "C", "About / Contact pages", "recommended", "warn",
                      "Only one of About / Contact is linked.",
                      "Link both an About and a Contact page from the homepage."))
    else:
        out.append(_c("C1", "C", "About / Contact pages", "recommended", "fail",
                      "No About or Contact link found.",
                      "Add About and Contact pages linked from the homepage."))

    if not readable:
        out.append(_c("C2", "C", "Organization schema (logo + sameAs)", "recommended", "skip",
                      "Homepage HTML unavailable."))
    elif home.has_organization and home.org_logo and home.org_sameas > 0:
        out.append(_c("C2", "C", "Organization schema (logo + sameAs)", "recommended", "pass",
                      "Organization schema with logo and sameAs."))
    elif home.has_organization:
        out.append(_c("C2", "C", "Organization schema (logo + sameAs)", "recommended", "warn",
                      "Organization schema present but missing logo and/or sameAs.", ORG_JSONLD))
    else:
        out.append(_c("C2", "C", "Organization schema (logo + sameAs)", "recommended", "fail",
                      "No Organization schema found.", ORG_JSONLD))

    if not readable:
        out.append(_c("D1", "D", "Visible dates", "nice_to_have", "skip",
                      "Homepage HTML unavailable."))
    elif home.has_dates:
        out.append(_c("D1", "D", "Visible dates", "nice_to_have", "pass",
                      "Publication/update dates present."))
    else:
        out.append(_c("D1", "D", "Visible dates", "nice_to_have", "fail",
                      "No visible publication/update dates.",
                      "Expose datePublished/dateModified (JSON-LD) or <time> elements."))

    if not readable:
        out.append(_c("D2", "D", "RSS/Atom feed", "nice_to_have", "skip",
                      "Homepage HTML unavailable."))
    elif home.has_feed:
        out.append(_c("D2", "D", "RSS/Atom feed", "nice_to_have", "pass",
                      "RSS/Atom feed linked."))
    else:
        out.append(_c("D2", "D", "RSS/Atom feed", "nice_to_have", "fail",
                      "No RSS/Atom feed linked.",
                      "Publish an RSS/Atom feed and link it via <link rel=alternate>."))

    if artifacts.security.status == 200:
        out.append(_c("D3", "D", ".well-known/security.txt", "nice_to_have", "pass",
                      "/.well-known/security.txt present."))
    else:
        out.append(_c("D3", "D", ".well-known/security.txt", "nice_to_have", "fail",
                      "No /.well-known/security.txt.",
                      "Add a /.well-known/security.txt contact file."))

    return out


def build_checks(
    artifacts: SiteArtifacts,
    robots: RobotsAnalysis,
    home: HtmlAnalysis,
    page: HtmlAnalysis,
    engine: Optional[str],
) -> list[CheckResult]:
    readable = artifacts.homepage.status == 200 and artifacts.homepage.text is not None
    checks = [
        _check_a1(artifacts),
        _check_a2(artifacts),
        _check_a3(robots, engine),
        _check_a3b(robots, engine),
        _check_a4(artifacts, robots),
        _check_a5(artifacts, page),
    ]
    checks.extend(_content_checks(artifacts, home, readable))
    return checks


def run_audit(
    target: str,
    *,
    engine: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> AuditResult:
    artifacts = gather(target, client=client, timeout=timeout)
    robots = analyze_robots(artifacts.robots.text, artifacts.robots.status)
    home_text = artifacts.homepage.text if artifacts.homepage.status == 200 else None
    home = analyze_html(home_text)
    tp = artifacts.target_page
    if tp is not None and tp.status == 200 and tp.text is not None:
        page = analyze_html(tp.text)
    else:
        page = home
    checks = build_checks(artifacts, robots, home, page, engine)
    return AuditResult(
        target=artifacts.target,
        domain=artifacts.domain,
        engine=engine,
        checked_at=artifacts.checked_at,
        checks=checks,
    )


__all__ = [
    "ROBOTS_ALLOW",
    "ORG_JSONLD",
    "LLMS_MIN",
    "build_checks",
    "run_audit",
]
