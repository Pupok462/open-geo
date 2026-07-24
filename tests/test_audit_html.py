from __future__ import annotations

import pytest

from audit.html import (
    JS_CRITICAL_WORDS,
    JS_EMPTY_ROOT_WORDS,
    JS_SPA_WORDS,
    HtmlAnalysis,
    analyze_html,
)

_LONG_BODY = " ".join(["Example builds trustworthy geo tooling for cited brands today."] * 30)

RICH_HOMEPAGE = (
    '<!doctype html><html lang="en"><head>'
    "<title>Example — Homepage</title>"
    '<meta name="description" content="Example is a demo brand.">'
    '<link rel="canonical" href="https://example.com/">'
    '<meta property="og:title" content="Example">'
    '<meta name="robots" content="index, follow">'
    '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Organization","name":"Example",'
    '"logo":"https://example.com/logo.png",'
    '"sameAs":["https://linkedin.com/company/example","https://en.wikipedia.org/wiki/Example"],'
    '"datePublished":"2026-01-01"}'
    "</script>"
    "</head><body><main>"
    "<h1>Welcome to Example</h1><h2>What we do</h2>"
    "<p>" + _LONG_BODY + "</p>"
    '<time datetime="2026-01-01">January 2026</time>'
    '<a href="/about">About</a><a href="/contact">Contact</a>'
    "</main></body></html>"
)

SPA_SHELL = (
    '<html><body><div id="root"></div>'
    '<script src="/_next/static/x.js"></script></body></html>'
)

HEAD_ONLY = "<html><head><title>T</title></head></html>"

FILLED_ROOT = "<html><body><div id=\"root\">" + ("content " * 20) + "</div></body></html>"

RULE2_PAGE = (
    '<html><body><div id="root">tiny</div><h1>Heading</h1><p>'
    + " ".join(["word"] * 60)
    + "</p></body></html>"
)

RULE3_PAGE = "<html><body><h1>Short heading only here</h1></body></html>"

ARTICLE_ONLY = "<html><body><article><h1>Post</h1><p>hello world text body</p></article></body></html>"

MIXED_LINKS = (
    '<html><body><a href="/pricing">Pricing</a>'
    '<a href="/company">About Us</a>'
    '<a href="/reach">Contact Us</a></body></html>'
)

ATOM_FEED = (
    '<html><head><link rel="alternate" type="application/atom+xml" href="/atom.xml">'
    "</head><body><p>x</p></body></html>"
)

TIME_ONLY = '<html><body><time datetime="2026-02-02">Feb</time><p>hi</p></body></html>'

NOSCRIPT_LONG = "<html><body><noscript>Please enable JavaScript to continue browsing here</noscript><p>x</p></body></html>"

NOSCRIPT_SHORT = "<html><body><noscript>hi</noscript><p>x</p></body></html>"

JSONLD_MIXED = (
    '<html><body>'
    '<script type="application/ld+json">{ this is broken</script>'
    '<script type="application/ld+json">'
    '{"@graph":[{"name":"NoType"},{"@type":"WebSite"},'
    '{"@type":["Article","BlogPosting"],"dateModified":"2026"}]}</script>'
    '<script type="application/ld+json">{"@type":"Organization","sameAs":"https://x.example/only"}</script>'
    "</body></html>"
)

TWO_ORGS = (
    '<html><body><script type="application/ld+json">'
    '[{"@type":"Organization","name":"First","logo":"a.png","sameAs":["x"]},'
    '{"@type":"Organization","name":"Second","logo":"b.png","sameAs":["y","z"]}]'
    "</script></body></html>"
)

ORG_NO_LOGO_NO_SAMEAS = (
    '<html><body><script type="application/ld+json">'
    '{"@type":"Organization","name":"Bare"}</script></body></html>'
)

GRAPH_DICT = (
    '<html><body><script type="application/ld+json">'
    '{"@graph":{"@type":"Organization","logo":"g.png","sameAs":["a"]}}'
    "</script></body></html>"
)

TYPE_LIST_MIXED = (
    '<html><body><script type="application/ld+json">'
    '{"@type":["Thing", 42]}</script></body></html>'
)

JSONLD_STRING = (
    '<html><body><script type="application/ld+json">"justastring"</script></body></html>'
)


def test_thresholds_are_module_constants():
    assert JS_SPA_WORDS == 200
    assert JS_EMPTY_ROOT_WORDS == 100
    assert JS_CRITICAL_WORDS == 50


def test_rich_homepage_full_fields():
    a = analyze_html(RICH_HOMEPAGE)
    assert isinstance(a, HtmlAnalysis)
    assert a.raw_word_count >= JS_SPA_WORDS
    assert a.js_dependent is False
    assert a.framework is None
    assert a.empty_root_markers == []
    assert a.heading_count == 2
    assert a.h1_count == 1
    assert a.has_main_or_article is True
    assert a.heading_order_ok is True
    assert a.title == "Example — Homepage"
    assert a.meta_description == "Example is a demo brand."
    assert a.canonical == "https://example.com/"
    assert a.lang == "en"
    assert a.noindex is False
    assert a.og_present is True
    assert a.jsonld_blocks == 1
    assert a.jsonld_invalid == 0
    assert a.jsonld_types == ["Organization"]
    assert a.has_organization is True
    assert a.org_logo is True
    assert a.org_sameas == 2
    assert a.has_about_link is True
    assert a.has_contact_link is True
    assert a.has_dates is True
    assert a.has_feed is True
    assert a.has_noscript is False


def test_spa_shell_is_js_dependent():
    a = analyze_html(SPA_SHELL)
    assert a.js_dependent is True
    assert a.framework == "Next"
    assert a.empty_root_markers == ["div#root"]
    assert a.raw_word_count == 0
    assert a.heading_count == 0
    assert a.h1_count == 0
    assert a.has_main_or_article is False
    assert a.heading_order_ok is True
    assert a.title is None
    assert a.meta_description is None
    assert a.canonical is None
    assert a.lang is None
    assert a.noindex is False
    assert a.og_present is False
    assert a.jsonld_blocks == 0
    assert a.jsonld_types == []
    assert a.has_organization is False
    assert a.org_logo is False
    assert a.org_sameas == 0
    assert a.has_about_link is False
    assert a.has_contact_link is False
    assert a.has_dates is False
    assert a.has_feed is False


@pytest.mark.parametrize("value", [None, "", "   ", "\n\t "])
def test_empty_input_is_all_empty_but_js_dependent(value):
    a = analyze_html(value)
    assert a.js_dependent is True
    assert a.framework is None
    assert a.raw_word_count == 0
    assert a.heading_count == 0
    assert a.empty_root_markers == []
    assert a.has_noscript is False
    assert a.h1_count == 0
    assert a.has_main_or_article is False
    assert a.heading_order_ok is True
    assert a.title is None
    assert a.meta_description is None
    assert a.canonical is None
    assert a.lang is None
    assert a.noindex is False
    assert a.og_present is False
    assert a.jsonld_types == []
    assert a.jsonld_blocks == 0
    assert a.jsonld_invalid == 0
    assert a.has_organization is False
    assert a.org_logo is False
    assert a.org_sameas == 0
    assert a.has_about_link is False
    assert a.has_contact_link is False
    assert a.has_dates is False
    assert a.has_feed is False


def test_head_only_no_body_content():
    a = analyze_html(HEAD_ONLY)
    assert a.title == "T"
    assert a.lang is None
    assert a.raw_word_count == 0
    assert a.has_main_or_article is False
    assert a.js_dependent is True
    assert a.canonical is None
    assert a.og_present is False


def test_filled_root_not_a_marker():
    a = analyze_html(FILLED_ROOT)
    assert a.empty_root_markers == []
    assert a.framework is None


@pytest.mark.parametrize(
    "html,expected",
    [
        (SPA_SHELL, "Next"),
        ('<script src="/__next/x.js"></script>', "Next"),
        ('<div id="__nuxt"></div><link href="/_nuxt/app.js">', "Nuxt"),
        ('<div id="root"></div><script>ReactDOM.createRoot(el)</script>', "React"),
        ('<div ng-version="17.0.0"></div>', "Angular"),
        ('<div id="app"></div>', "Vue"),
        ('<div id="gatsby-focus-wrapper"></div>', "Gatsby"),
        ('<div class="astro-island"></div>', "Astro"),
        ('<link href="/_astro/index.css">', "Astro"),
        ("<div>react is a library</div>", None),
        ('<div class="plain">hello world content</div>', None),
    ],
)
def test_framework_detection(html, expected):
    assert analyze_html(html).framework == expected


@pytest.mark.parametrize(
    "html,h1,count,order_ok",
    [
        ("<h1>a</h1><h2>b</h2><h3>c</h3>", 1, 3, True),
        ("<h1>a</h1><h3>b</h3>", 1, 2, False),
        ("<h1>a</h1><h1>b</h1>", 2, 2, True),
        ("<h2>a</h2>", 0, 1, True),
        ("<p>no headings at all here</p>", 0, 0, True),
        ("<h3>a</h3><h1>b</h1>", 1, 2, True),
        ("<section><h1>a</h1><h2>b</h2></section><h4>c</h4>", 1, 3, False),
    ],
)
def test_heading_structure(html, h1, count, order_ok):
    a = analyze_html(html)
    assert a.h1_count == h1
    assert a.heading_count == count
    assert a.heading_order_ok is order_ok


def test_js_dependent_rule2_empty_root_midrange():
    a = analyze_html(RULE2_PAGE)
    assert a.empty_root_markers == ["div#root"]
    assert a.heading_count == 1
    assert JS_CRITICAL_WORDS <= a.raw_word_count < JS_EMPTY_ROOT_WORDS
    assert a.js_dependent is True


def test_js_dependent_rule3_critical_words():
    a = analyze_html(RULE3_PAGE)
    assert a.empty_root_markers == []
    assert a.heading_count == 1
    assert a.raw_word_count < JS_CRITICAL_WORDS
    assert a.js_dependent is True


def test_article_counts_as_main():
    a = analyze_html(ARTICLE_ONLY)
    assert a.has_main_or_article is True


@pytest.mark.parametrize(
    "content,expected",
    [
        ("noindex, nofollow", True),
        ("NOINDEX", True),
        ("index, follow", False),
    ],
)
def test_noindex_meta(content, expected):
    html = f'<html><head><meta name="robots" content="{content}"></head><body><p>x</p></body></html>'
    assert analyze_html(html).noindex is expected


def test_link_text_matches_about_and_contact():
    a = analyze_html(MIXED_LINKS)
    assert a.has_about_link is True
    assert a.has_contact_link is True


def test_atom_feed_detected():
    a = analyze_html(ATOM_FEED)
    assert a.has_feed is True


def test_dates_from_time_element_only():
    a = analyze_html(TIME_ONLY)
    assert a.has_dates is True


def test_noscript_long_and_short():
    assert analyze_html(NOSCRIPT_LONG).has_noscript is True
    assert analyze_html(NOSCRIPT_SHORT).has_noscript is False


def test_jsonld_mixed_invalid_graph_and_type_list():
    a = analyze_html(JSONLD_MIXED)
    assert a.jsonld_blocks == 3
    assert a.jsonld_invalid == 1
    assert a.jsonld_types == ["WebSite", "Article", "BlogPosting", "Organization"]
    assert a.has_organization is True
    assert a.org_logo is False
    assert a.org_sameas == 1
    assert a.has_dates is True


def test_jsonld_two_orgs_uses_first():
    a = analyze_html(TWO_ORGS)
    assert a.jsonld_types == ["Organization"]
    assert a.has_organization is True
    assert a.org_logo is True
    assert a.org_sameas == 1


def test_jsonld_org_without_logo_or_sameas():
    a = analyze_html(ORG_NO_LOGO_NO_SAMEAS)
    assert a.has_organization is True
    assert a.org_logo is False
    assert a.org_sameas == 0


def test_jsonld_graph_as_dict():
    a = analyze_html(GRAPH_DICT)
    assert a.has_organization is True
    assert a.org_logo is True
    assert a.org_sameas == 1


def test_jsonld_type_list_filters_non_strings():
    a = analyze_html(TYPE_LIST_MIXED)
    assert a.jsonld_types == ["Thing"]
    assert a.jsonld_blocks == 1
    assert a.jsonld_invalid == 0


def test_jsonld_bare_string_value():
    a = analyze_html(JSONLD_STRING)
    assert a.jsonld_blocks == 1
    assert a.jsonld_invalid == 0
    assert a.jsonld_types == []
    assert a.has_organization is False
