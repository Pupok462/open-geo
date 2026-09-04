from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# What the number actually measures. Never normalize across providers: an
# impression count and an average-monthly-search count are different rulers, and
# collapsing them would invent precision the source never had.
Metric = Literal[
    "impressions_per_month",   # Wordstat: shows/month for the phrase
    "avg_monthly_searches",    # Google Ads Keyword Planner
    "impressions_4w",          # Bing Webmaster keyword stats, last 4 weeks summed
    "suggest_presence",        # suggest APIs: the phrase is a real suggestion, no volume
]

Status = Literal[
    "ok",           # a number (or a presence signal) came back
    "zero",         # the provider answered and the demand is zero / below its floor
    "unavailable",  # no provider is configured or supports this locale
    "error",        # the provider was called and failed (quota, auth, network)
]


class RelatedPhrase(BaseModel):
    phrase: str
    volume: Optional[int] = None


class SuggestHit(BaseModel):
    phrase: str
    engine: str          # google | yandex | bing | duckduckgo
    seed: str
    source_url: str


class DemandStat(BaseModel):
    """One phrase's demand as one provider reported it."""

    phrase: str
    status: Status
    provider: Optional[str] = None
    geo: str
    language: Optional[str] = None
    volume: Optional[int] = None
    metric: Optional[Metric] = None
    period: Optional[str] = None
    # The ready-to-paste `signal` string for a QuestionCandidate: the number WITH
    # its scope, so provenance survives the hand-off to harvest/METHODOLOGY §3.
    scope: str = ""
    source_url: Optional[str] = None
    related: list[RelatedPhrase] = Field(default_factory=list)
    cached: bool = False
    reason: Optional[str] = None   # why, when status is unavailable/error/zero

    @field_validator("phrase")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        stripped = str(v).strip()
        if not stripped:
            raise ValueError("phrase must be a non-empty string")
        return stripped


__all__ = ["DemandStat", "RelatedPhrase", "SuggestHit", "Metric", "Status"]
