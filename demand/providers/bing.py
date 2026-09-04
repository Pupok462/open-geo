from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus

from demand import config
from demand.providers.base import Provider, ProviderError, http_json, to_int
from demand.schema import DemandStat, RelatedPhrase

API_BASE = "https://ssl.bing.com/webmaster/api.svc/json"

HOWTO = """Bing Webmaster keyword research API (free, worldwide, no ad account).
  1. https://www.bing.com/webmasters -> add & verify any site you own.
  2. Settings -> API access -> API key.
  3. .env: BING_WEBMASTER_API_KEY=...
  Returns weekly impression counts per country+language; open-geo sums the last
  4 weeks and says so in `scope`."""


class BingProvider(Provider):
    """Bing Webmaster Tools — weekly impressions for a phrase, per country/language.

    The cheapest worldwide ruler: a free API key on any verified site, no ad
    spend. Bing's absolute numbers are smaller than Google's; they are used as a
    demand *signal* (does anyone search this, and how does it rank against its
    siblings), never as a Google-volume substitute.
    """

    name = "bing"
    env_vars = ("BING_WEBMASTER_API_KEY",)
    howto = HOWTO
    daily_limit = None

    def credentials(self) -> tuple[bool, list[str]]:
        missing = [name for name in self.env_vars if not config.env(name)]
        return (not missing), missing

    def supports(self, geo: str, language: str) -> tuple[bool, str]:
        return True, ""

    def _call(self, method: str, params: dict) -> dict:
        params = dict(params)
        params["apikey"] = config.env("BING_WEBMASTER_API_KEY")
        return http_json("GET", f"{API_BASE}/{method}", params=params)

    def lookup(self, phrase: str, geo: str, language: str = "en", *, n_related: int = 0) -> DemandStat:
        geo = (geo or "ww").lower()
        country = "us" if geo == "ww" else geo
        locale = config.bing_locale(language, country)
        cache_key = f"stats|{phrase}|{country}|{locale}"
        payload = self._cache_get(cache_key)
        cached = payload is not None
        if not cached:
            try:
                payload = self._call(
                    "GetKeywordStats",
                    {"q": phrase, "country": country, "language": locale},
                )
            except ProviderError as exc:
                return DemandStat(
                    phrase=phrase, status="error", provider=self.name, geo=geo,
                    language=language, reason=str(exc),
                )
            self._quota_bump()
            self._cache_put(cache_key, payload)
        self.last_from_cache = cached

        rows = payload.get("d") if isinstance(payload, dict) else payload
        rows = rows or []
        weekly = [to_int(row.get("Impressions")) for row in rows if isinstance(row, dict)]
        weekly = [w for w in weekly if w is not None]
        source_url = f"https://www.bing.com/webmasters/keywordresearch?q={quote_plus(phrase)}"
        stamp = date.today().isoformat()
        if not weekly:
            return DemandStat(
                phrase=phrase, status="zero", provider=self.name, geo=geo, language=language,
                volume=0, metric="impressions_4w", period="last 4 weeks",
                scope=(
                    f"bing webmaster: '{phrase}' — no impressions reported, "
                    f"{country.upper()}/{locale} (checked {stamp})"
                ),
                source_url=source_url, cached=cached,
                reason="Bing reports no impressions for this phrase in this locale",
            )
        last4 = weekly[-4:]
        volume = sum(last4)
        related: list[RelatedPhrase] = []
        if n_related:
            related = self.expand(phrase, geo, language, n=n_related)
        shows = f"{volume:,}".replace(",", " ")
        scope = (
            f"bing webmaster: '{phrase}' — {shows} impressions over the last "
            f"{len(last4)} weeks, {country.upper()}/{locale} (pulled {stamp})"
        )
        return DemandStat(
            phrase=phrase, status="ok" if volume else "zero", provider=self.name, geo=geo,
            language=language, volume=volume, metric="impressions_4w",
            period=f"last {len(last4)} weeks", scope=scope, source_url=source_url,
            related=related, cached=cached,
        )

    def expand(self, seed: str, geo: str, language: str = "en", *, n: int = 30) -> list[RelatedPhrase]:
        country = "us" if (geo or "ww").lower() == "ww" else geo.lower()
        locale = config.bing_locale(language, country)
        cache_key = f"related|{seed}|{country}|{locale}"
        payload = self._cache_get(cache_key)
        if payload is None:
            try:
                payload = self._call(
                    "GetRelatedKeywords",
                    {"q": seed, "country": country, "language": locale},
                )
            except ProviderError:
                return []
            self._quota_bump()
            self._cache_put(cache_key, payload)
        rows = payload.get("d") if isinstance(payload, dict) else payload
        out: list[RelatedPhrase] = []
        for row in (rows or [])[:n]:
            if not isinstance(row, dict):
                continue
            text = str(row.get("Query", "")).strip()
            if text:
                out.append(RelatedPhrase(phrase=text, volume=to_int(row.get("Impressions"))))
        return out


__all__ = ["BingProvider", "API_BASE"]
