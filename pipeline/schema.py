from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, model_validator

Lens = Literal["general", "branded", "comparative"]

Rank = Annotated[int, Field(gt=0)]


class Link(BaseModel):

    rank: Rank
    url: str
    domain: str


class QueryCapture(BaseModel):

    query: str
    lens: Lens
    engine: str
    captured_at: datetime
    answer_text_md: Optional[str] = None
    screenshot_path: Optional[str] = None
    overview_present: bool
    sources: list[Link] = []
    citations: list[Link] = []
    target_source_ranks: list[Rank] = []
    target_citation_ranks: list[Rank] = []
    brand_in_answer_text: bool
    sentiment: Optional[str] = None
    prior_context: bool = False
    prior_context_evidence: Optional[str] = None

    @model_validator(mode="after")
    def _citations_subset_of_sources(self) -> "QueryCapture":
        source_domains = {normalize_domain(link.domain) for link in self.sources}
        cited_domains = {normalize_domain(link.domain) for link in self.citations}
        extra = cited_domains - source_domains
        if extra:
            raise ValueError(
                "citations must be a subset of sources (the model can only cite "
                f"what it retrieved); cited domain(s) absent from sources: "
                f"{sorted(extra)}"
            )
        if self.target_citation_ranks and not self.target_source_ranks:
            raise ValueError(
                "target_citation_ranks non-empty requires non-empty "
                "target_source_ranks (a cited target is also a source)"
            )
        for field, ranks, links in (
            ("target_source_ranks", self.target_source_ranks, self.sources),
            ("target_citation_ranks", self.target_citation_ranks, self.citations),
        ):
            over = [r for r in ranks if r > len(links)]
            if over:
                raise ValueError(
                    f"{field} points past the end of the array it indexes: "
                    f"{sorted(over)} with only {len(links)} entries"
                )
        return self

    @model_validator(mode="after")
    def _force_prior_context_from_answer(self) -> "QueryCapture":
        detected, evidence = detect_prior_context(self.answer_text_md)
        if detected:
            self.prior_context = True
            if not (self.prior_context_evidence and self.prior_context_evidence.strip()):
                self.prior_context_evidence = evidence
        if self.prior_context_evidence is not None:
            self.prior_context_evidence = _trim_evidence(self.prior_context_evidence)
        return self


_EVIDENCE_MAX = 300

_PRIOR_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"учитывая,\s+что\s+вы",
        r"как\s+вы\s+спрашивали",
        r"как\s+вы\s+интересовались",
        r"вы\s+интересовались",
        r"ранее\s+вы",
        r"в\s+прошлый\s+раз",
        r"в\s+предыдущем",
        r"как\s+я\s+уже",
        r"мы\s+обсуждали",
        r"мы\s+уже\s+говорили",
        r"as\s+you\s+asked",
        r"you\s+asked\s+earlier",
        r"you\s+mentioned\s+earlier",
        r"based\s+on\s+our\s+previous",
        r"as\s+we\s+discussed",
        r"earlier\s+you",
    )
)

_SENTENCE_SPLIT = re.compile(r"[.!?]+|\n+")


def _trim_evidence(text: str | None) -> str | None:
    if text is None:
        return None
    trimmed = text.strip()
    if not trimmed:
        return None
    if len(trimmed) > _EVIDENCE_MAX:
        trimmed = trimmed[:_EVIDENCE_MAX].rstrip()
    return trimmed or None


def detect_prior_context(text: str | None) -> tuple[bool, str | None]:
    """Whether answer prose refers to an earlier turn, plus the matching sentence.

    Scans the answer, not the query. No match returns `(False, None)`. A match
    returns the sentence (split on `.` `!` `?` or newline) that contains the
    phrase, trimmed to 300 characters. A caller-set `prior_context=True` is
    never cleared by `QueryCapture`.
    """
    if not text or not str(text).strip():
        return False, None
    for piece in _SENTENCE_SPLIT.split(str(text)):
        sentence = piece.strip()
        if not sentence:
            continue
        if any(pattern.search(sentence) for pattern in _PRIOR_CONTEXT_PATTERNS):
            return True, _trim_evidence(sentence)
    return False, None


_MULTI_PART_TLDS: frozenset[str] = frozenset(
    {
        "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk",
        "com.au", "net.au", "org.au", "gov.au", "edu.au", "id.au",
        "co.nz", "net.nz", "org.nz", "govt.nz",
        "com.br", "net.br", "org.br", "gov.br",
        "co.jp", "ne.jp", "or.jp", "go.jp", "ac.jp",
        "co.kr", "or.kr", "go.kr",
        "co.in", "net.in", "org.in", "gov.in",
        "com.cn", "net.cn", "org.cn", "gov.cn",
        "com.tr", "net.tr", "org.tr", "gov.tr", "edu.tr",
        "com.mx", "org.mx", "gob.mx",
        "co.za", "org.za", "gov.za",
        "com.sg", "com.hk", "com.tw", "com.ua", "co.il", "com.ar",
    }
)


def normalize_domain(url_or_host: str) -> str:
    if not url_or_host:
        return ""

    host = str(url_or_host).strip()

    if "://" in host:
        host = host.split("://", 1)[1]
    else:
        if host.startswith("//"):
            host = host[2:]

    for sep in ("/", "?", "#"):
        idx = host.find(sep)
        if idx != -1:
            host = host[:idx]

    if "@" in host:
        host = host.rsplit("@", 1)[1]

    host = host.strip().strip(".").lower()

    if ":" in host:
        host = host.split(":", 1)[0]

    while host.startswith("www."):
        host = host[4:]

    if not host:
        return ""

    labels = host.split(".")
    if len(labels) <= 2:
        return host

    last_two = ".".join(labels[-2:])
    last_three = ".".join(labels[-3:])

    if last_two in _MULTI_PART_TLDS:
        return last_three

    return last_two


def normalize_target(url_or_host: str) -> str:
    raw = str(url_or_host).strip() if url_or_host is not None else ""

    if "://" in raw:
        raw = raw.split("://", 1)[1]
    elif raw.startswith("//"):
        raw = raw[2:]

    for sep in ("?", "#"):
        idx = raw.find(sep)
        if idx != -1:
            raw = raw[:idx]

    slash = raw.find("/")
    if slash == -1:
        host_part = raw
        path_part = ""
    else:
        host_part = raw[:slash]
        path_part = raw[slash + 1:]

    host = normalize_domain(host_part)
    if not host:
        return ""

    segments = [s.lower() for s in path_part.split("/") if s]
    if not segments:
        return host
    return host + "/" + "/".join(segments)


def _split_domain_segs(norm: str) -> tuple[str, list[str]]:
    slash = norm.find("/")
    if slash == -1:
        return norm, []
    return norm[:slash], norm[slash + 1:].split("/")


def matches_target(url_or_host: str, target: str) -> bool:
    norm_target = normalize_target(target)
    if not norm_target:
        return False

    norm_url = normalize_target(url_or_host)
    if not norm_url:
        return False

    target_domain, target_segs = _split_domain_segs(norm_target)
    url_domain, url_segs = _split_domain_segs(norm_url)

    if target_domain != url_domain:
        return False

    if not target_segs:
        return True

    if len(url_segs) < len(target_segs):
        return False

    return url_segs[: len(target_segs)] == target_segs


def target_ranks(links: list[Link], target: str) -> list[int]:
    result: list[int] = []
    for link in links:
        url_norm = normalize_domain(link.url) if link.url else ""
        dom_norm = normalize_domain(link.domain) if link.domain else ""
        if link.url and url_norm == dom_norm:
            effective = link.url
        else:
            effective = link.domain
        if matches_target(effective, target):
            result.append(link.rank)
    return sorted(result)


__all__ = [
    "Lens",
    "Link",
    "QueryCapture",
    "detect_prior_context",
    "normalize_domain",
    "normalize_target",
    "matches_target",
    "target_ranks",
]
