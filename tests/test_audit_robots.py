from __future__ import annotations

import pytest

from audit import robots
from audit.bots import AI_CRAWLERS
from audit.robots import BotPolicy, RobotsAnalysis, analyze_robots


def _policy(a, ua):
    return next(p for p in a.policies if p.ua == ua)


def _uas(a):
    return [p.ua for p in a.policies]


ALLOW_ALL = "User-agent: *\nAllow: /"
BLOCK_ALL = "User-agent: *\nDisallow: /"


@pytest.mark.parametrize("status", [404, 500, 403, None])
def test_absent_when_not_200_everything_allowed(status):
    a = analyze_robots("<html>not found</html>", status)
    assert isinstance(a, RobotsAnalysis)
    assert a.fetched is False
    assert a.present is False
    assert a.malformed is False
    assert a.sitemaps == []
    assert all(p.allowed for p in a.policies)
    assert len(a.policies) == len(AI_CRAWLERS)


def test_absent_none_text_and_none_status():
    a = analyze_robots(None, None)
    assert a.fetched is False
    assert a.present is False
    assert all(p.allowed for p in a.policies)


@pytest.mark.parametrize("body", ["", "   ", "\n\t\n"])
def test_present_false_on_empty_body_but_fetched_true(body):
    a = analyze_robots(body, 200)
    assert a.fetched is True
    assert a.present is False
    assert a.malformed is False
    assert a.sitemaps == []
    assert all(p.allowed for p in a.policies)
    assert len(a.policies) == len(AI_CRAWLERS)


def test_present_false_when_text_none_status_200():
    a = analyze_robots(None, 200)
    assert a.fetched is True
    assert a.present is False
    assert all(p.allowed for p in a.policies)


def test_allow_all_explicit():
    a = analyze_robots(ALLOW_ALL, 200)
    assert a.fetched is True
    assert a.present is True
    assert a.malformed is False
    assert all(p.allowed for p in a.policies)


def test_block_all_blocks_every_bot():
    a = analyze_robots(BLOCK_ALL, 200)
    assert a.present is True
    assert a.malformed is False
    assert all(p.allowed is False for p in a.policies)


@pytest.mark.parametrize("blocked_ua", ["GPTBot", "OAI-SearchBot", "ClaudeBot"])
def test_block_one_specific_bot(blocked_ua):
    a = analyze_robots(f"User-agent: {blocked_ua}\nDisallow: /", 200)
    assert a.present is True
    assert _policy(a, blocked_ua).allowed is False
    for p in a.policies:
        if p.ua != blocked_ua:
            assert p.allowed is True


def test_block_search_bot_vs_training_bot():
    a = analyze_robots("User-agent: Googlebot\nDisallow: /", 200)
    google = _policy(a, "Googlebot")
    gptbot = _policy(a, "GPTBot")
    assert google.tier == "search"
    assert google.allowed is False
    assert gptbot.tier == "training"
    assert gptbot.allowed is True


def test_policies_mirror_bots_registry_order_and_fields():
    a = analyze_robots(ALLOW_ALL, 200)
    assert _uas(a) == [b.ua for b in AI_CRAWLERS]
    for b in AI_CRAWLERS:
        p = _policy(a, b.ua)
        assert p.operator == b.operator
        assert p.tier == b.tier
        assert isinstance(p, BotPolicy)


def test_single_sitemap_extracted():
    body = "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml"
    a = analyze_robots(body, 200)
    assert a.present is True
    assert a.sitemaps == ["https://example.com/sitemap.xml"]


def test_multiple_sitemaps_extracted():
    body = (
        "User-agent: *\nDisallow: /private\n"
        "Sitemap: https://example.com/a.xml\n"
        "Sitemap: https://example.com/b.xml"
    )
    a = analyze_robots(body, 200)
    assert a.sitemaps == ["https://example.com/a.xml", "https://example.com/b.xml"]
    assert _policy(a, "Googlebot").allowed is True


def test_garbage_body_still_returns_usable_analysis():
    a = analyze_robots(">>> not robots \x00\x01 %%% random", 200)
    assert isinstance(a, RobotsAnalysis)
    assert a.present is True
    assert a.malformed is False
    assert a.sitemaps == []
    assert all(p.allowed for p in a.policies)
    assert len(a.policies) == len(AI_CRAWLERS)


class _RaisingProtego:
    @staticmethod
    def parse(text):
        raise ValueError("boom")


def test_malformed_when_parse_raises(monkeypatch):
    monkeypatch.setattr(robots, "Protego", _RaisingProtego)
    a = analyze_robots("User-agent: *\nDisallow: /\nSitemap: https://x/y.xml", 200)
    assert a.fetched is True
    assert a.present is True
    assert a.malformed is True
    assert a.sitemaps == []
    assert all(p.allowed for p in a.policies)
    assert len(a.policies) == len(AI_CRAWLERS)


class _BoomSitemaps:
    def can_fetch(self, path, ua):
        return True

    @property
    def sitemaps(self):
        raise RuntimeError("no sitemaps attr behaves")


def test_sitemaps_fallback_parses_lines_when_protego_raises():
    body = (
        "User-agent: *\n"
        "Sitemap: https://a.com/1.xml\n"
        "sitemap:   https://a.com/2.xml\n"
        "Sitemap: https://a.com/1.xml\n"
        "Disallow: /nope"
    )
    got = robots._sitemaps(_BoomSitemaps(), body)
    assert got == ["https://a.com/1.xml", "https://a.com/2.xml"]


def test_sitemaps_from_text_ignores_non_sitemap_lines():
    assert robots._sitemaps_from_text("User-agent: *\nDisallow: /") == []
