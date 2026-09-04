from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus

from demand import config
from demand.providers.base import Provider, ProviderError, http_json, to_int
from demand.schema import DemandStat, RelatedPhrase

CLOUD_BASE = "https://searchapi.api.cloud.yandex.net/v2/wordstat"
LEGACY_BASE = "https://api.wordstat.yandex.net/v1"

HOWTO = """Yandex Wordstat API (free, RU/CIS demand).
  Cloud form (current):
    1. https://aistudio.yandex.ru -> create a folder + service account,
       give it the `search-api.webSearch.user` role, issue an API key.
    2. .env: WORDSTAT_API_KEY=<api key>
       WORDSTAT_FOLDER_ID is optional — only if the key is not already bound to a folder.
  Legacy form (beta OAuth token, api.wordstat.yandex.net):
    .env: WORDSTAT_OAUTH_TOKEN=<token>  (folder id not needed)
  Limits: ~10 req/s, 1000 req/day."""


class WordstatProvider(Provider):
    """Yandex Wordstat — impressions/month for a phrase, plus real related phrases.

    The number is Wordstat's broad-match "shows per month" over the last 30 days:
    the same figure a human reads in the web UI, fetched over the API instead of
    a logged-in browser.
    """

    name = "wordstat"
    env_vars = ("WORDSTAT_API_KEY", "or WORDSTAT_OAUTH_TOKEN")
    howto = HOWTO
    daily_limit = 1000

    # Wordstat is a Yandex-search ruler: meaningful where Yandex has real share.
    STRONG_GEOS = {"ru", "by", "kz", "uz", "am", "ge", "az", "kg", "md", "tj", "tm", "ww"}

    def credentials(self) -> tuple[bool, list[str]]:
        if config.env("WORDSTAT_OAUTH_TOKEN"):
            return True, []
        key = config.env("WORDSTAT_API_KEY")
        if not key:
            return False, ["WORDSTAT_API_KEY"]
        return True, []

    def supports(self, geo: str, language: str) -> tuple[bool, str]:
        geo = (geo or "ww").lower()
        lang = (language or "").split("-")[0].lower()
        if geo in self.STRONG_GEOS or lang == "ru":
            return True, ""
        return False, (
            f"wordstat measures Yandex search; geo={geo}/lang={lang} is outside its "
            "meaningful range — use google_ads or bing"
        )

    # --- transport ------------------------------------------------------
    def _endpoint(self, method: str) -> tuple[str, dict, dict]:
        """(url, headers, extra body fields) for the configured auth form."""
        oauth = config.env("WORDSTAT_OAUTH_TOKEN")
        if oauth:
            base = config.env("WORDSTAT_BASE_URL", LEGACY_BASE)
            return f"{base}/{method}", {"Authorization": f"Bearer {oauth}"}, {}
        base = config.env("WORDSTAT_BASE_URL", CLOUD_BASE)
        key = config.env("WORDSTAT_API_KEY")
        extra: dict = {}
        folder = config.env("WORDSTAT_FOLDER_ID")
        # SA keys already belong to a folder; sending a *different* folderId
        # is a 403. Only attach when explicitly set and needed.
        if folder:
            extra["folderId"] = folder
        return f"{base}/{method}", {"Authorization": f"Api-Key {key}"}, extra

    def _top_requests(self, phrase: str, geo: str, n_related: int) -> dict:
        url, headers, extra = self._endpoint("topRequests")
        body: dict = {"phrase": phrase, "numPhrases": max(1, min(n_related or 1, 2000))}
        body.update(extra)
        region = config.yandex_region(geo)
        if region is not None:
            # Cloud Wordstat types regions as string codes ("225"), not ints.
            body["regions"] = [str(region)]
        return http_json("POST", url, headers=headers, json_body=body)

    # --- contract -------------------------------------------------------
    def lookup(self, phrase: str, geo: str, language: str = "ru", *, n_related: int = 0) -> DemandStat:
        geo = (geo or "ru").lower()
        cache_key = f"top|{phrase}|{geo}|{n_related}"
        payload = self._cache_get(cache_key)
        cached = payload is not None
        if not cached:
            if self.quota_exhausted():
                return DemandStat(
                    phrase=phrase, status="error", provider=self.name, geo=geo,
                    language=language, reason=(
                        f"wordstat daily quota exhausted ({self.daily_limit}/day); "
                        "retry tomorrow or read from cache"
                    ),
                )
            try:
                payload = self._top_requests(phrase, geo, n_related)
            except ProviderError as exc:
                return DemandStat(
                    phrase=phrase, status="error", provider=self.name, geo=geo,
                    language=language, reason=str(exc),
                )
            self._quota_bump()
            self._cache_put(cache_key, payload)
        self.last_from_cache = cached

        volume = to_int(payload.get("totalCount"))
        results = payload.get("results") or payload.get("topRequests") or []
        related = [
            RelatedPhrase(phrase=str(item.get("phrase", "")).strip(), volume=to_int(item.get("count")))
            for item in results[:n_related]
            if str(item.get("phrase", "")).strip()
        ]
        region_name = "Россия" if geo == "ru" else (geo.upper() if geo != "ww" else "все регионы")
        source_url = f"https://wordstat.yandex.ru/?words={quote_plus(phrase)}"
        stamp = date.today().isoformat()
        if volume is None:
            return DemandStat(
                phrase=phrase, status="error", provider=self.name, geo=geo,
                language=language, source_url=source_url, related=related, cached=cached,
                reason="wordstat answered without a totalCount field",
            )
        status = "zero" if volume == 0 else "ok"
        shows = f"{volume:,}".replace(",", " ")
        scope = (
            f"wordstat api: «{phrase}» — {shows} показов/мес, {region_name}, "
            f"за последние 30 дней (снято {stamp})"
        )
        return DemandStat(
            phrase=phrase, status=status, provider=self.name, geo=geo, language=language,
            volume=volume, metric="impressions_per_month", period="last 30 days",
            scope=scope, source_url=source_url, related=related, cached=cached,
            reason=None if status == "ok" else "wordstat reports no measurable demand",
        )

    def expand(self, seed: str, geo: str, language: str = "ru", *, n: int = 30) -> list[RelatedPhrase]:
        stat = self.lookup(seed, geo, language, n_related=n)
        return stat.related


__all__ = ["WordstatProvider", "CLOUD_BASE", "LEGACY_BASE"]
