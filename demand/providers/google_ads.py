from __future__ import annotations

from datetime import date
from urllib.parse import quote_plus

from demand import config
from demand.providers.base import Provider, ProviderError, http_json, to_int
from demand.schema import DemandStat, RelatedPhrase

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://googleads.googleapis.com"
DEFAULT_VERSION = "v22"

HOWTO = """Google Ads Keyword Planner API (free, worldwide demand).
  1. Google Ads account -> Tools -> API Center -> request a developer token
     (Basic access is usually approved within 1-2 days; 15 000 ops/day).
  2. Google Cloud project -> OAuth client (Desktop) -> get a refresh token
     (https://developers.google.com/google-ads/api/docs/oauth/playground).
  3. .env:
       GOOGLE_ADS_DEVELOPER_TOKEN=...
       GOOGLE_ADS_CLIENT_ID=...       GOOGLE_ADS_CLIENT_SECRET=...
       GOOGLE_ADS_REFRESH_TOKEN=...   GOOGLE_ADS_CUSTOMER_ID=1234567890
       # optional: GOOGLE_ADS_LOGIN_CUSTOMER_ID (MCC), GOOGLE_ADS_API_VERSION
  Note: an account with no recent ad spend gets bucketed ranges from Google
  rather than exact averages — the bucket midpoint is reported, and `scope`
  says so."""


class GoogleAdsProvider(Provider):
    """Google Ads Keyword Planner — avg monthly searches, any country/language."""

    name = "google_ads"
    env_vars = (
        "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID",
    )
    howto = HOWTO
    daily_limit = 15000

    def __init__(self, conn=None, ttl_days: int = 7) -> None:
        super().__init__(conn=conn, ttl_days=ttl_days)
        self._access_token: str | None = None

    def credentials(self) -> tuple[bool, list[str]]:
        missing = [name for name in self.env_vars if not config.env(name)]
        return (not missing), missing

    def supports(self, geo: str, language: str) -> tuple[bool, str]:
        geo = (geo or "ww").lower()
        if geo != "ww" and config.google_geo_target(geo) is None:
            return False, f"no geoTargetConstant mapped for geo={geo} (add it to demand/config.py)"
        if config.google_language(language or "en") is None:
            return False, f"no languageConstant mapped for language={language}"
        return True, ""

    # --- transport ------------------------------------------------------
    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        payload = http_json(
            "POST", TOKEN_URL, params={
                "client_id": config.env("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": config.env("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": config.env("GOOGLE_ADS_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            },
        )
        token = payload.get("access_token")
        if not token:
            raise ProviderError(f"no access_token in OAuth response: {payload}")
        self._access_token = str(token)
        return self._access_token

    def _ideas(self, phrase: str, geo: str, language: str, n_related: int) -> dict:
        customer = config.env("GOOGLE_ADS_CUSTOMER_ID").replace("-", "")
        version = config.env("GOOGLE_ADS_API_VERSION", DEFAULT_VERSION)
        url = f"{API_BASE}/{version}/customers/{customer}:generateKeywordIdeas"
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "developer-token": config.env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        }
        login = config.env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", "")
        if login:
            headers["login-customer-id"] = login
        body: dict = {
            "keywordSeed": {"keywords": [phrase]},
            "language": f"languageConstants/{config.google_language(language or 'en')}",
            "keywordPlanNetwork": "GOOGLE_SEARCH",
            "includeAdultKeywords": False,
            "pageSize": max(1, min((n_related or 0) + 20, 1000)),
        }
        target = config.google_geo_target(geo)
        if target is not None:
            body["geoTargetConstants"] = [f"geoTargetConstants/{target}"]
        return http_json("POST", url, headers=headers, json_body=body)

    # --- contract -------------------------------------------------------
    def lookup(self, phrase: str, geo: str, language: str = "en", *, n_related: int = 0) -> DemandStat:
        geo = (geo or "ww").lower()
        language = language or "en"
        cache_key = f"ideas|{phrase}|{geo}|{language}|{n_related}"
        payload = self._cache_get(cache_key)
        cached = payload is not None
        if not cached:
            try:
                payload = self._ideas(phrase, geo, language, n_related)
            except ProviderError as exc:
                return DemandStat(
                    phrase=phrase, status="error", provider=self.name, geo=geo,
                    language=language, reason=str(exc),
                )
            self._quota_bump()
            self._cache_put(cache_key, payload)
        self.last_from_cache = cached

        wanted = phrase.strip().lower()
        volume: int | None = None
        related: list[RelatedPhrase] = []
        for item in payload.get("results", []):
            text = str(item.get("text", "")).strip()
            metrics = item.get("keywordIdeaMetrics") or {}
            avg = to_int(metrics.get("avgMonthlySearches"))
            if text.lower() == wanted and volume is None:
                volume = avg if avg is not None else 0
                continue
            if text and len(related) < n_related:
                related.append(RelatedPhrase(phrase=text, volume=avg))

        source_url = (
            "https://ads.google.com/aw/keywordplanner/home?ocid=&q=" + quote_plus(phrase)
        )
        stamp = date.today().isoformat()
        geo_name = geo.upper() if geo != "ww" else "worldwide"
        if volume is None:
            return DemandStat(
                phrase=phrase, status="zero", provider=self.name, geo=geo, language=language,
                volume=0, metric="avg_monthly_searches", period="12-month average",
                scope=(
                    f"google ads keyword planner: '{phrase}' — not returned as a keyword idea "
                    f"({geo_name}, {language}, checked {stamp})"
                ),
                source_url=source_url, related=related, cached=cached,
                reason="Keyword Planner returned no metrics row for this exact phrase",
            )
        status = "zero" if volume == 0 else "ok"
        searches = f"{volume:,}".replace(",", " ")
        scope = (
            f"google ads keyword planner: '{phrase}' — {searches} avg monthly searches, "
            f"{geo_name}, {language}, 12-month average (pulled {stamp})"
        )
        return DemandStat(
            phrase=phrase, status=status, provider=self.name, geo=geo, language=language,
            volume=volume, metric="avg_monthly_searches", period="12-month average",
            scope=scope, source_url=source_url, related=related, cached=cached,
            reason=None if status == "ok" else "Keyword Planner reports no measurable volume",
        )

    def expand(self, seed: str, geo: str, language: str = "en", *, n: int = 30) -> list[RelatedPhrase]:
        return self.lookup(seed, geo, language, n_related=n).related


__all__ = ["GoogleAdsProvider", "DEFAULT_VERSION"]
