from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, field_validator

from pipeline.schema import Lens

_WS = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\s\?\!\.\,;:…]+$")


class QuestionCandidate(BaseModel):

    query: str
    lens: Lens
    segment: str
    signal: str
    source_url: str
    note: Optional[str] = None

    @field_validator("query", "segment", "signal", "source_url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        stripped = str(v).strip()
        if not stripped:
            raise ValueError("must be a non-empty string")
        return stripped


def normalize_query(query: str) -> str:
    if not query:
        return ""
    text = _WS.sub(" ", str(query).strip()).lower()
    text = _TRAILING_PUNCT.sub("", text)
    return text


def contains_brand(query: str, brand: str) -> bool:
    if not brand:
        return False
    tokens = [t for t in re.split(r"[^\w]+", brand.strip().lower(), flags=re.UNICODE) if t]
    if not tokens:
        return False
    haystack = f" {normalize_query(query)} "
    return all(
        re.search(rf"(?<!\w){re.escape(t)}(?!\w)", haystack, flags=re.UNICODE)
        for t in tokens
    )


__all__ = ["QuestionCandidate", "normalize_query", "contains_brand"]
