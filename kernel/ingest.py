"""URL → brand profile and seed phrases. Deterministic HTML parse, no LLM."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser

from kernel.classify import normalize, tokens
from kernel.schema import BrandProfile
from pipeline.schema import normalize_domain

_UA = "open-geo-kernel/0.1 (+https://github.com/Pupok462/open-geo)"


def fetch_html(url: str, *, timeout: float = 12.0) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    with httpx.Client(follow_redirects=True, headers={"User-Agent": _UA}, timeout=timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def profile_from_html(url: str, html: str, brand: str | None = None) -> BrandProfile:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    tree = HTMLParser(html or "")
    for tag in ("script", "style", "noscript"):
        for node in tree.css(tag):
            node.decompose()

    title = _text(tree.css_first("title"))
    h1 = _text(tree.css_first("h1"))
    description = None
    site_name = None
    for meta in tree.css("meta"):
        name = (meta.attributes.get("name") or meta.attributes.get("property") or "").lower()
        content = (meta.attributes.get("content") or "").strip()
        if not content:
            continue
        if name in {"description", "og:description"} and not description:
            description = content
        if name == "og:site_name":
            site_name = content

    headings = [_text(n) for n in tree.css("h2")]
    headings = [h for h in headings if h][:8]

    domain = normalize_domain(url)
    inferred = (brand or site_name or _domain_label(domain)).strip()
    seeds = _seeds(inferred, title, h1, description, headings)
    claims = [h for h in headings if h][:6]
    return BrandProfile(
        url=url,
        domain=domain,
        brand=inferred,
        title=title,
        h1=h1,
        description=description,
        seeds=seeds,
        claims=claims,
    )


def profile_from_url(url: str, brand: str | None = None) -> BrandProfile:
    html = fetch_html(url)
    return profile_from_html(url, html, brand=brand)


def category_tokens(profile: BrandProfile) -> set[str]:
    bag: list[str] = []
    for piece in (profile.title, profile.h1, profile.description, *profile.seeds, *profile.claims):
        if piece:
            bag.extend(tokens(piece))
    brand = set(tokens(profile.brand))
    return {t for t in bag if t not in brand and len(t) > 2}


def _text(node) -> str | None:
    if node is None:
        return None
    value = " ".join((node.text(separator=" ") or "").split()).strip()
    return value or None


def _domain_label(domain: str) -> str:
    host = domain.split(":")[0]
    parts = [p for p in host.split(".") if p not in {"www", "com", "ru", "io", "ai", "org", "net"}]
    return parts[0] if parts else host


def _seeds(brand: str, title: str | None, h1: str | None, description: str | None, headings: list[str]) -> list[str]:
    raw: list[str] = []
    for piece in (brand, title, h1):
        if piece:
            for chunk in re_split(piece):
                raw.append(chunk)
    for h in headings:
        raw.append(h)
    if description:
        raw.append(description.split(".")[0])

    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        key = normalize(item)
        if not key or key in seen or len(key) < 3:
            continue
        seen.add(key)
        out.append(item.strip())
        if len(out) >= 12:
            break
    if brand and normalize(brand) not in seen:
        out.insert(0, brand)
    return out


def re_split(text: str) -> list[str]:
    parts = []
    for chunk in text.replace("|", "—").replace("–", "—").split("—"):
        piece = chunk.strip(" -·•")
        if piece:
            parts.append(piece)
    return parts or [text]
