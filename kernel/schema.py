"""SEO semantic kernel: questions, not keyword strings.

A formulation is what a person typed. A question is the need those
formulations share. The kernel is the questions a brand can honestly answer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

Band = Literal["high", "mid", "low", "micro", "unknown"]
Intent = Literal["informational", "commercial", "transactional", "comparative", "navigational"]
Rel = Literal["S1", "S2", "S3", "S4"]
Status = Literal["inbox", "accepted", "rejected", "deferred"]
Insert = Literal["own_page", "h2_of_parent", "comparison", "offsite_review", "skip"]
Gate = Literal["human", "auto"]


class Formulation(BaseModel):
    text: str
    volume: Optional[int] = None
    provider: str = "suggest"
    scope: str = ""
    source_url: Optional[str] = None


class Question(BaseModel):
    id: str
    canonical: str
    formulations: list[Formulation] = Field(default_factory=list)
    intent: Intent = "informational"
    band: Band = "unknown"
    rel: Rel = "S3"
    insert: Insert = "own_page"
    parent_id: Optional[str] = None
    status: Status = "inbox"
    volume: Optional[int] = None
    why: str = ""
    round: int = 1


class BrandProfile(BaseModel):
    url: str
    domain: str
    brand: str
    title: Optional[str] = None
    h1: Optional[str] = None
    description: Optional[str] = None
    seeds: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)


class Kernel(BaseModel):
    """One brand's growing kernel. Iterative: inbox is the current batch."""

    slug: str
    brand: str
    domain: str
    url: str
    geo: str = "ru"
    language: str = "ru"
    gate: Gate = "human"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    round: int = 0
    volume_available: bool = False
    doctor_verdict: str = ""
    profile: Optional[BrandProfile] = None
    questions: list[Question] = Field(default_factory=list)
    rejected_memory: list[str] = Field(default_factory=list)

    def by_status(self, status: Status) -> list[Question]:
        return [q for q in self.questions if q.status == status]

    def known_texts(self) -> set[str]:
        out: set[str] = set(self.rejected_memory)
        for q in self.questions:
            out.add(q.canonical.lower())
            for f in q.formulations:
                out.add(f.text.lower())
        return out
