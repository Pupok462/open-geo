from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel
from selectolax.parser import HTMLParser

JS_SPA_WORDS = 200
JS_EMPTY_ROOT_WORDS = 100
JS_CRITICAL_WORDS = 50

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_EMPTY_ROOT_MARKERS = (
    "div#root",
    "div#app",
    "div#__next",
    "div#__nuxt",
    "div#gatsby-focus-wrapper",
)
_FEED_TYPES = ("application/rss+xml", "application/atom+xml")
_ABOUT_TEXTS = ("about", "about us")
_CONTACT_TEXTS = ("contact", "contact us")
_LD_JSON_TYPE = "application/ld+json"
_STRIP_TAGS = ("script", "style", "noscript")
_FRAMEWORK_SCAN_CHARS = 10_000


class HtmlAnalysis(BaseModel):
    raw_word_count: int
    heading_count: int
    empty_root_markers: list[str]
    framework: Optional[str]
    has_noscript: bool
    js_dependent: bool
    h1_count: int
    has_main_or_article: bool
    heading_order_ok: bool
    title: Optional[str]
    meta_description: Optional[str]
    canonical: Optional[str]
    lang: Optional[str]
    noindex: bool
    og_present: bool
    jsonld_types: list[str]
    jsonld_blocks: int
    jsonld_invalid: int
    has_organization: bool
    org_logo: bool
    org_sameas: int
    has_about_link: bool
    has_contact_link: bool
    has_dates: bool
    has_feed: bool


def _empty_analysis() -> HtmlAnalysis:
    return HtmlAnalysis(
        raw_word_count=0,
        heading_count=0,
        empty_root_markers=[],
        framework=None,
        has_noscript=False,
        js_dependent=True,
        h1_count=0,
        has_main_or_article=False,
        heading_order_ok=True,
        title=None,
        meta_description=None,
        canonical=None,
        lang=None,
        noindex=False,
        og_present=False,
        jsonld_types=[],
        jsonld_blocks=0,
        jsonld_invalid=0,
        has_organization=False,
        org_logo=False,
        org_sameas=0,
        has_about_link=False,
        has_contact_link=False,
        has_dates=False,
        has_feed=False,
    )


def _raw_word_count(html: str) -> int:
    tree = HTMLParser(html)
    for tag in _STRIP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    return len(tree.body.text(separator=" ").split())


def _ordered_headings(tree: HTMLParser) -> list[str]:
    return [node.tag for node in tree.css("*") if node.tag in _HEADING_TAGS]


def _heading_order_ok(levels: list[int]) -> bool:
    for prev, cur in zip(levels, levels[1:]):
        if cur - prev > 1:
            return False
    return True


def _empty_root_markers(tree: HTMLParser) -> list[str]:
    markers: list[str] = []
    for selector in _EMPTY_ROOT_MARKERS:
        node = tree.css_first(selector)
        if node is not None and len(node.text().strip()) < 50:
            markers.append(selector)
    return markers


def _detect_framework(html: str) -> Optional[str]:
    head = html[:_FRAMEWORK_SCAN_CHARS].lower()
    if "/__next/" in head or "_next/static" in head or "__next" in head:
        return "Next"
    if "__nuxt" in head or "_nuxt/" in head:
        return "Nuxt"
    if "react" in head and ('id="root"' in head or "createroot" in head):
        return "React"
    if "ng-version" in head or "ng-app" in head:
        return "Angular"
    if "data-v-" in head or 'id="app"' in head:
        return "Vue"
    if "gatsby" in head:
        return "Gatsby"
    if "astro" in head or "_astro/" in head:
        return "Astro"
    return None


def _js_dependent(word_count: int, heading_count: int, markers: list[str]) -> bool:
    if word_count < JS_SPA_WORDS and heading_count == 0:
        return True
    if markers and word_count < JS_EMPTY_ROOT_WORDS:
        return True
    if word_count < JS_CRITICAL_WORDS:
        return True
    return False


def _text_or_none(node) -> Optional[str]:
    if node is None:
        return None
    return node.text().strip()


def _iter_nodes(value):
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_nodes(item)
        elif isinstance(graph, dict):
            yield from _iter_nodes(graph)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_nodes(item)


def _node_types(node: dict) -> list[str]:
    value = node.get("@type")
    if isinstance(value, list):
        return [t for t in value if isinstance(t, str)]
    if isinstance(value, str):
        return [value]
    return []


def _sameas_count(value) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, list):
        return len(value)
    return 0


def analyze_html(html: Optional[str]) -> HtmlAnalysis:
    if html is None or not html.strip():
        return _empty_analysis()

    tree = HTMLParser(html)

    heading_tags = _ordered_headings(tree)
    heading_levels = [int(tag[1]) for tag in heading_tags]
    heading_count = len(heading_tags)
    h1_count = heading_tags.count("h1")

    word_count = _raw_word_count(html)
    markers = _empty_root_markers(tree)
    framework = _detect_framework(html)

    noscript = tree.css_first("noscript")
    has_noscript = noscript is not None and len(noscript.text().strip()) > 20

    has_main_or_article = (
        tree.css_first("main") is not None or tree.css_first("article") is not None
    )

    title = _text_or_none(tree.css_first("title"))
    lang = tree.root.attributes.get("lang")

    meta_description: Optional[str] = None
    noindex = False
    og_present = False
    for meta in tree.css("meta"):
        attrs = meta.attributes
        name = (attrs.get("name") or "").lower()
        prop = (attrs.get("property") or "").lower()
        content = attrs.get("content") or ""
        if name == "description" and meta_description is None:
            meta_description = attrs.get("content")
        if name == "robots" and "noindex" in content.lower():
            noindex = True
        if prop.startswith("og:"):
            og_present = True

    canonical: Optional[str] = None
    has_feed = False
    for link in tree.css("link"):
        attrs = link.attributes
        rels = (attrs.get("rel") or "").lower().split()
        link_type = (attrs.get("type") or "").lower()
        if "canonical" in rels and canonical is None:
            canonical = attrs.get("href")
        if "alternate" in rels and link_type in _FEED_TYPES:
            has_feed = True

    jsonld_types: list[str] = []
    jsonld_blocks = 0
    jsonld_invalid = 0
    first_org: Optional[dict] = None
    jsonld_has_date = False
    for script in tree.css("script"):
        if (script.attributes.get("type") or "").lower() != _LD_JSON_TYPE:
            continue
        jsonld_blocks += 1
        try:
            parsed = json.loads(script.text())
        except (json.JSONDecodeError, ValueError):
            jsonld_invalid += 1
            continue
        for node in _iter_nodes(parsed):
            types = _node_types(node)
            for t in types:
                if t not in jsonld_types:
                    jsonld_types.append(t)
            if "Organization" in types and first_org is None:
                first_org = node
            if "datePublished" in node or "dateModified" in node:
                jsonld_has_date = True

    has_organization = first_org is not None
    org_logo = has_organization and bool(first_org.get("logo"))
    org_sameas = _sameas_count(first_org.get("sameAs")) if has_organization else 0

    has_about_link = False
    has_contact_link = False
    for anchor in tree.css("a"):
        href = (anchor.attributes.get("href") or "").lower()
        text = anchor.text().strip().lower()
        if "about" in href or text in _ABOUT_TEXTS:
            has_about_link = True
        if "contact" in href or text in _CONTACT_TEXTS:
            has_contact_link = True

    has_dates = jsonld_has_date or tree.css_first("time[datetime]") is not None

    return HtmlAnalysis(
        raw_word_count=word_count,
        heading_count=heading_count,
        empty_root_markers=markers,
        framework=framework,
        has_noscript=has_noscript,
        js_dependent=_js_dependent(word_count, heading_count, markers),
        h1_count=h1_count,
        has_main_or_article=has_main_or_article,
        heading_order_ok=_heading_order_ok(heading_levels),
        title=title,
        meta_description=meta_description,
        canonical=canonical,
        lang=lang,
        noindex=noindex,
        og_present=og_present,
        jsonld_types=jsonld_types,
        jsonld_blocks=jsonld_blocks,
        jsonld_invalid=jsonld_invalid,
        has_organization=has_organization,
        org_logo=org_logo,
        org_sameas=org_sameas,
        has_about_link=has_about_link,
        has_contact_link=has_contact_link,
        has_dates=has_dates,
        has_feed=has_feed,
    )


__all__ = [
    "JS_SPA_WORDS",
    "JS_EMPTY_ROOT_WORDS",
    "JS_CRITICAL_WORDS",
    "HtmlAnalysis",
    "analyze_html",
]
