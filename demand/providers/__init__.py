from __future__ import annotations

from demand.providers.base import Provider, ProviderError
from demand.providers.bing import BingProvider
from demand.providers.google_ads import GoogleAdsProvider
from demand.providers.suggest import SuggestProvider
from demand.providers.wordstat import WordstatProvider

REGISTRY: dict[str, type[Provider]] = {
    "wordstat": WordstatProvider,
    "google_ads": GoogleAdsProvider,
    "bing": BingProvider,
    "suggest": SuggestProvider,
}

# Volume rulers, in the order they are preferred per locale. `suggest` is not
# here: it carries no volume and is appended separately as the presence floor.
RU_FIRST = ("wordstat", "google_ads", "bing")
WW_FIRST = ("google_ads", "bing", "wordstat")

RU_LOCALES = {"ru", "by", "kz", "uz", "am", "ge", "az", "kg", "md", "tj", "tm"}


def preference(geo: str, language: str) -> tuple[str, ...]:
    """Which volume providers make sense for this locale, best first."""
    geo = (geo or "ww").lower()
    lang = (language or "").split("-")[0].lower()
    if geo in RU_LOCALES or lang == "ru":
        return RU_FIRST
    return WW_FIRST


def build(name: str, conn=None, ttl_days: int = 7) -> Provider:
    cls = REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(REGISTRY)}")
    return cls(conn=conn, ttl_days=ttl_days)


def resolve(
    geo: str,
    language: str,
    *,
    provider: str = "auto",
    conn=None,
    ttl_days: int = 7,
) -> tuple[list[Provider], list[dict]]:
    """(usable providers best-first, why each rejected one was skipped).

    A provider is usable only when its credentials exist AND it covers the
    locale. Nothing is silently substituted: the skipped list is reported so the
    caller can say *why* a number is missing instead of inventing one.
    """
    if provider and provider != "auto":
        names: tuple[str, ...] = (provider,)
    else:
        names = preference(geo, language)

    usable: list[Provider] = []
    skipped: list[dict] = []
    for name in names:
        instance = build(name, conn=conn, ttl_days=ttl_days)
        configured, missing = instance.credentials()
        if not configured:
            skipped.append({
                "provider": name, "reason": "not configured",
                "missing_env": missing, "fix": "python -m demand.doctor",
            })
            continue
        supported, why = instance.supports(geo, language)
        if not supported:
            skipped.append({"provider": name, "reason": why, "missing_env": []})
            continue
        usable.append(instance)
    return usable, skipped


def suggest_provider(conn=None, ttl_days: int = 7) -> SuggestProvider:
    return SuggestProvider(conn=conn, ttl_days=ttl_days)


__all__ = [
    "Provider", "ProviderError", "REGISTRY", "resolve", "build", "preference",
    "suggest_provider", "WordstatProvider", "GoogleAdsProvider", "BingProvider",
    "SuggestProvider",
]
