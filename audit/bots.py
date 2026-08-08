from __future__ import annotations

from typing import Literal, Optional

Tier = Literal["search", "training", "user"]

TRAINING: Tier = "training"
SEARCH: Tier = "search"
USER: Tier = "user"


class Bot:
    __slots__ = ("ua", "operator", "tier", "respects_robots", "engine")

    def __init__(
        self,
        ua: str,
        operator: str,
        tier: Tier,
        respects_robots: bool,
        engine: Optional[str] = None,
    ) -> None:
        self.ua = ua
        self.operator = operator
        self.tier = tier
        self.respects_robots = respects_robots
        self.engine = engine


AI_CRAWLERS: list[Bot] = [
    Bot("OAI-SearchBot", "OpenAI", SEARCH, True, engine="chatgpt_search"),
    Bot("ChatGPT-User", "OpenAI", USER, True, engine="chatgpt_search"),
    Bot("GPTBot", "OpenAI", TRAINING, True),
    Bot("Claude-SearchBot", "Anthropic", SEARCH, True, engine="claude_search"),
    Bot("Claude-User", "Anthropic", USER, True, engine="claude_search"),
    Bot("ClaudeBot", "Anthropic", TRAINING, True),
    Bot("PerplexityBot", "Perplexity", SEARCH, True, engine="perplexity"),
    Bot("Perplexity-User", "Perplexity", USER, False, engine="perplexity"),
    Bot("Googlebot", "Google", SEARCH, True, engine="google"),
    Bot("Google-Extended", "Google", TRAINING, True),
    Bot("Bingbot", "Microsoft", SEARCH, True),
    Bot("YandexBot", "Yandex", SEARCH, True, engine="yandex_neuro"),
    Bot("Applebot-Extended", "Apple", TRAINING, True),
    Bot("CCBot", "Common Crawl", TRAINING, True),
    Bot("Amazonbot", "Amazon", TRAINING, True),
    Bot("Meta-ExternalAgent", "Meta", TRAINING, True),
    Bot("Bytespider", "ByteDance", TRAINING, False),
    Bot("DuckAssistBot", "DuckDuckGo", USER, True),
    Bot("MistralAI-User", "Mistral", USER, True),
]

_BY_UA: dict[str, Bot] = {bot.ua: bot for bot in AI_CRAWLERS}

ENGINE_GATING_UA: dict[str, str] = {
    "google": "Googlebot",
    "gemini": "Googlebot",
    "chatgpt_search": "OAI-SearchBot",
    "claude_search": "Claude-SearchBot",
    "yandex_neuro": "YandexBot",
    "perplexity": "PerplexityBot",
}

DEFAULT_GATING_UA = "Googlebot"


def bot(ua: str) -> Optional[Bot]:
    return _BY_UA.get(ua)


def bots_by_tier(tier: Tier) -> list[Bot]:
    return [b for b in AI_CRAWLERS if b.tier == tier]


def is_engine_mapped(engine: Optional[str]) -> bool:
    return engine is None or engine in ENGINE_GATING_UA


def gating_ua(engine: Optional[str]) -> str:
    if engine and engine in ENGINE_GATING_UA:
        return ENGINE_GATING_UA[engine]
    return DEFAULT_GATING_UA


__all__ = [
    "Tier",
    "TRAINING",
    "SEARCH",
    "USER",
    "Bot",
    "AI_CRAWLERS",
    "ENGINE_GATING_UA",
    "DEFAULT_GATING_UA",
    "bot",
    "bots_by_tier",
    "gating_ua",
    "is_engine_mapped",
]
