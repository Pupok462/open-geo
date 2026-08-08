from __future__ import annotations

import re
from typing import Optional

from protego import Protego
from pydantic import BaseModel

from audit.bots import AI_CRAWLERS


class BotPolicy(BaseModel):
    ua: str
    operator: str
    tier: str
    allowed: bool


class RobotsAnalysis(BaseModel):
    fetched: bool
    present: bool
    malformed: bool
    sitemaps: list[str]
    policies: list[BotPolicy]
    unreadable: bool = False


_SITEMAP_RE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE)


def _all_allowed() -> list[BotPolicy]:
    return [
        BotPolicy(ua=b.ua, operator=b.operator, tier=b.tier, allowed=True)
        for b in AI_CRAWLERS
    ]


def _sitemaps_from_text(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _SITEMAP_RE.match(line)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _sitemaps(rp: Protego, text: str) -> list[str]:
    try:
        return list(rp.sitemaps)
    except Exception:  # noqa: BLE001
        return _sitemaps_from_text(text)


def analyze_robots(text: Optional[str], status: Optional[int]) -> RobotsAnalysis:
    fetched = status == 200
    body = text or ""
    if not fetched or not body.strip():
        return RobotsAnalysis(
            fetched=fetched,
            present=False,
            malformed=False,
            sitemaps=[],
            policies=_all_allowed(),
            unreadable=status is None or status >= 500,
        )
    try:
        rp = Protego.parse(body)
        policies = [
            BotPolicy(
                ua=b.ua,
                operator=b.operator,
                tier=b.tier,
                allowed=rp.can_fetch("/", b.ua),
            )
            for b in AI_CRAWLERS
        ]
        sitemaps = _sitemaps(rp, body)
    except Exception:  # noqa: BLE001
        return RobotsAnalysis(
            fetched=fetched,
            present=True,
            malformed=True,
            sitemaps=[],
            policies=_all_allowed(),
        )
    return RobotsAnalysis(
        fetched=fetched,
        present=True,
        malformed=False,
        sitemaps=sitemaps,
        policies=policies,
    )


__all__ = [
    "BotPolicy",
    "RobotsAnalysis",
    "analyze_robots",
]
