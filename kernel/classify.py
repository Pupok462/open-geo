"""Pure classifiers for the kernel algebra. No I/O, no network."""

from __future__ import annotations

import re

from kernel.schema import Band, Insert, Intent, Question, Rel

STOP = {
    "а", "и", "в", "во", "на", "по", "за", "из", "от", "до", "для", "про", "при",
    "как", "что", "это", "или", "ли", "же", "бы", "не", "ни", "к", "ко", "о",
    "об", "обо", "с", "со", "у", "the", "a", "an", "of", "to", "for", "in",
    "on", "vs", "versus",
}

_COMPARATIVE = (
    " vs ", "versus", "альтернатив", "сравн", "лучше чем", "против ",
    " или ", " vs.", "vs.",
)
_TRANSACTIONAL = (
    "купить", "цена", "тариф", "стоимость", "заказать", "подписк", "купить",
    "buy ", "price", "pricing", "order", "discount", "скидк",
)
_COMMERCIAL = (
    "отзыв", "обзор", "рейтинг", "лучш", "review", "best ", "топ ",
    "стоит ли", "какой выбрать", "какую выбрать",
)
_NAV = (
    "вход", "login", "скачать", "download", "install", "установ",
    "официальный сайт", "личный кабинет", "github.com", "docs.",
)


def normalize(text: str) -> str:
    t = (text or "").lower().replace("ё", "е")
    t = re.sub(r"[«»\"'`„“”]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zа-я0-9]+", normalize(text)) if w not in STOP]


def token_set(text: str) -> frozenset[str]:
    return frozenset(tokens(text))


def band(volume: int | None) -> Band:
    if volume is None:
        return "unknown"
    if volume >= 5000:
        return "high"
    if volume >= 500:
        return "mid"
    if volume >= 10:
        return "low"
    return "micro"


def intent(text: str) -> Intent:
    n = f" {normalize(text)} "
    if any(m in n for m in _NAV):
        return "navigational"
    if any(m in n for m in _COMPARATIVE):
        return "comparative"
    if any(m in n for m in _TRANSACTIONAL):
        return "transactional"
    if any(m in n for m in _COMMERCIAL):
        return "commercial"
    return "informational"


def rel(text: str, brand: str, category_tokens: set[str]) -> Rel:
    phrase = token_set(text)
    brand_toks = token_set(brand)
    if intent(text) == "navigational":
        return "S4"
    if brand_toks and brand_toks <= phrase:
        return "S1"
    if brand_toks and phrase & brand_toks:
        return "S1"
    if category_tokens and phrase & category_tokens:
        return "S2"
    if len(phrase) <= 2:
        return "S3"
    return "S3"


def insert_for(q: Question) -> Insert:
    if q.rel in {"S3", "S4"}:
        return "skip"
    if q.intent == "navigational":
        return "skip"
    if q.intent == "comparative":
        return "comparison"
    if q.parent_id and q.band in {"low", "micro", "unknown"}:
        return "h2_of_parent"
    if q.intent in {"commercial", "transactional"}:
        return "own_page"
    return "own_page"


def why(q: Question) -> str:
    parts = [f"rel={q.rel}", f"intent={q.intent}", f"band={q.band}"]
    if q.parent_id:
        parts.append(f"child of {q.parent_id}")
    if q.volume is None:
        parts.append("volume unknown (phrasing is real)")
    else:
        parts.append(f"volume={q.volume}")
    return "; ".join(parts)


def auto_accept(q: Question) -> bool:
    """Default autonomous policy: НЧ/СЧ that the brand can answer. Not head terms."""
    if q.rel not in {"S1", "S2"}:
        return False
    if q.intent == "navigational":
        return False
    if q.band == "high":
        return False
    if q.insert == "skip":
        return False
    if q.band == "unknown" and q.rel != "S1":
        return False
    return True
