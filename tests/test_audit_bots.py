from __future__ import annotations

import pytest

from audit import bots


def test_lookup_hit_and_miss():
    b = bots.bot("OAI-SearchBot")
    assert b is not None
    assert b.operator == "OpenAI"
    assert b.tier == "search"
    assert bots.bot("NopeBot") is None


def test_every_bot_has_valid_tier():
    for b in bots.AI_CRAWLERS:
        assert b.tier in ("search", "training", "user")
        assert b.ua and b.operator
        assert isinstance(b.respects_robots, bool)


def test_bots_by_tier_partitions_the_registry():
    total = sum(len(bots.bots_by_tier(t)) for t in ("search", "training", "user"))
    assert total == len(bots.AI_CRAWLERS)
    search = {b.ua for b in bots.bots_by_tier("search")}
    assert {"OAI-SearchBot", "Claude-SearchBot", "PerplexityBot", "Googlebot", "Bingbot", "YandexBot"} <= search
    training = {b.ua for b in bots.bots_by_tier("training")}
    assert {"GPTBot", "Google-Extended", "ClaudeBot"} <= training
    assert "GPTBot" not in search


@pytest.mark.parametrize(
    "engine,expected",
    [
        ("google", "Googlebot"),
        ("gemini", "Googlebot"),
        ("chatgpt_search", "OAI-SearchBot"),
        ("claude_search", "Claude-SearchBot"),
        ("yandex_neuro", "YandexBot"),
        ("perplexity", "PerplexityBot"),
    ],
)
def test_gating_ua_known_engines(engine, expected):
    assert bots.gating_ua(engine) == expected


def test_gating_ua_unknown_and_none_default_to_googlebot():
    assert bots.gating_ua("something_else") == bots.DEFAULT_GATING_UA == "Googlebot"
    assert bots.gating_ua(None) == "Googlebot"
    assert bots.gating_ua("") == "Googlebot"


def test_gating_uas_are_search_tier_and_registered():
    for engine, ua in bots.ENGINE_GATING_UA.items():
        b = bots.bot(ua)
        assert b is not None, f"{engine} maps to unknown UA {ua}"
        assert b.tier == "search"


def test_training_bots_are_not_gating_uas():
    gating = set(bots.ENGINE_GATING_UA.values())
    assert "Google-Extended" not in gating
    assert "GPTBot" not in gating
    assert "ClaudeBot" not in gating
