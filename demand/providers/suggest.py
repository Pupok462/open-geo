from __future__ import annotations

import string
from datetime import date
from urllib.parse import quote_plus

from demand.providers.base import Provider, ProviderError, http_json
from demand.schema import DemandStat, RelatedPhrase, SuggestHit

# Public autocomplete endpoints. No key, no account, every locale — this is the
# floor the harvest can always stand on: it proves a phrasing is real (people
# type it), even where no volume API is configured.
ENGINES: dict[str, str] = {
    "google": "https://suggestqueries.google.com/complete/search",
    "yandex": "https://suggest.yandex.ru/suggest-ff.cgi",
    "bing": "https://api.bing.com/osjson.aspx",
    "duckduckgo": "https://duckduckgo.com/ac/",
}

_UA = {"User-Agent": "Mozilla/5.0 (compatible; open-geo/demand; +https://github.com/Pupok462/open-geo)"}

HOWTO = """Search autocomplete (free, no credentials, every locale).
  Nothing to configure. Gives real phrasings and proves a query exists;
  it does NOT give volume — pair it with wordstat / google_ads / bing."""


def _params(engine: str, query: str, geo: str, language: str) -> dict:
    lang = (language or "en").split("-")[0]
    if engine == "google":
        return {"client": "firefox", "q": query, "hl": lang, "gl": (geo or "us")}
    if engine == "yandex":
        return {"part": query, "v": "4", "uil": lang, "n": "10"}
    if engine == "bing":
        return {"query": query}
    return {"q": query, "type": "list"}


def _parse(payload) -> list[str]:
    """Autocomplete endpoints answer in two shapes: opensearch pairs, or dicts."""
    if isinstance(payload, list):
        if len(payload) >= 2 and isinstance(payload[1], list):
            return [str(item).strip() for item in payload[1] if str(item).strip()]
        out = []
        for item in payload:
            if isinstance(item, dict):
                text = str(item.get("phrase") or item.get("text") or "").strip()
                if text:
                    out.append(text)
            elif isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(payload, dict):
        for key in ("suggestions", "results", "d"):
            value = payload.get(key)
            if isinstance(value, list):
                return _parse(value)
    return []


class SuggestProvider(Provider):
    """Search autocomplete across Google / Yandex / Bing / DuckDuckGo."""

    name = "suggest"
    env_vars = ()
    howto = HOWTO
    daily_limit = None

    def __init__(self, conn=None, ttl_days: int = 7, engines: tuple[str, ...] | None = None) -> None:
        super().__init__(conn=conn, ttl_days=ttl_days)
        self.engines = tuple(engines or ("google", "yandex", "bing", "duckduckgo"))

    def credentials(self) -> tuple[bool, list[str]]:
        return True, []

    def supports(self, geo: str, language: str) -> tuple[bool, str]:
        return True, ""

    def _suggest(self, engine: str, query: str, geo: str, language: str) -> list[str]:
        cache_key = f"{engine}|{query}|{geo}|{language}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            payload = http_json(
                "GET", ENGINES[engine], params=_params(engine, query, geo, language),
                headers=_UA, retries=1,
            )
        except ProviderError:
            return []
        hits = _parse(payload)
        self._quota_bump()
        self._cache_put(cache_key, hits)
        return hits

    def hits(self, seed: str, geo: str, language: str) -> list[SuggestHit]:
        out: list[SuggestHit] = []
        for engine in self.engines:
            for phrase in self._suggest(engine, seed, geo, language):
                out.append(SuggestHit(
                    phrase=phrase, engine=engine, seed=seed,
                    source_url=f"{ENGINES[engine]}?{'q' if engine != 'yandex' else 'part'}={quote_plus(seed)}",
                ))
        return out

    def lookup(self, phrase: str, geo: str, language: str = "en", *, n_related: int = 0) -> DemandStat:
        geo = (geo or "ww").lower()
        hits = self.hits(phrase, geo, language)
        stamp = date.today().isoformat()
        wanted = phrase.strip().lower()
        exact = [h for h in hits if h.phrase.strip().lower() == wanted]
        related = [RelatedPhrase(phrase=h.phrase) for h in hits[:n_related] if h.phrase.strip().lower() != wanted]
        if not hits:
            return DemandStat(
                phrase=phrase, status="zero", provider=self.name, geo=geo, language=language,
                metric="suggest_presence", scope=(
                    f"suggest ({'/'.join(self.engines)}): no completion for '{phrase}' "
                    f"in {geo}/{language} (checked {stamp})"
                ),
                reason="no autocomplete engine completes this phrase",
            )
        engines = sorted({h.engine for h in (exact or hits)})
        kind = "exact autocomplete entry" if exact else "live prefix with completions"
        return DemandStat(
            phrase=phrase, status="ok", provider=self.name, geo=geo, language=language,
            volume=None, metric="suggest_presence", period=None,
            scope=(
                f"suggest ({'+'.join(engines)}): '{phrase}' — {kind}, {geo}/{language} "
                f"(checked {stamp}); presence only, no volume"
            ),
            source_url=hits[0].source_url, related=related,
            reason=None if exact else "phrase completes but is not itself a suggestion",
        )

    def expand(self, seed: str, geo: str, language: str = "en", *, n: int = 30, deep: bool = False) -> list[RelatedPhrase]:
        seen: dict[str, None] = {}
        queries = [seed]
        if deep:
            # The classic alphabet sweep: "<seed> a" ... "<seed> z" surfaces the
            # long tail autocomplete hides behind the first ten rows.
            queries += [f"{seed} {ch}" for ch in string.ascii_lowercase]
        for query in queries:
            for hit in self.hits(query, geo, language):
                key = hit.phrase.strip().lower()
                if key and key not in seen:
                    seen[key] = None
                if len(seen) >= n:
                    break
            if len(seen) >= n:
                break
        return [RelatedPhrase(phrase=phrase) for phrase in list(seen)[:n]]


__all__ = ["SuggestProvider", "ENGINES"]
