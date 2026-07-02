from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, model_validator

Lens = Literal["general", "branded", "comparative"]


class Link(BaseModel):

    rank: int
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
    target_source_ranks: list[int] = []
    target_citation_ranks: list[int] = []
    brand_in_answer_text: bool
    sentiment: Optional[str] = None

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
        return self


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


__all__ = ["Lens", "Link", "QueryCapture", "normalize_domain"]
