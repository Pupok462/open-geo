from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# --- .env ------------------------------------------------------------------
# Credentials live in a gitignored `.env` at the repo root (see `.env.example`).
# No python-dotenv dependency: the file is a flat KEY=VALUE list.

_ENV_LOADED = False


def load_env(path: str = ".env") -> dict[str, str]:
    """Read `.env` into os.environ (without overriding a real env var)."""
    global _ENV_LOADED
    loaded: dict[str, str] = {}
    file = Path(path)
    if not file.is_file():
        _ENV_LOADED = True
        return loaded
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    _ENV_LOADED = True
    return loaded


def env(name: str, default: str = "") -> str:
    if not _ENV_LOADED:
        load_env()
    return os.environ.get(name, default).strip()


# --- geo / language mapping -------------------------------------------------
# `geo` is an ISO-3166 alpha-2 code, lowercase, or "ww" for worldwide.

# Yandex region ids (wordstat `regions`). "ww" ⟹ no filter (all regions).
YANDEX_REGIONS: dict[str, int] = {
    "ru": 225, "ua": 187, "by": 149, "kz": 159, "uz": 171, "az": 167,
    "am": 168, "ge": 169, "kg": 207, "md": 208, "tj": 209, "tm": 170,
    "il": 181, "tr": 983, "de": 96, "us": 84,
}

# Google Ads geoTargetConstants (country level).
GOOGLE_GEO_TARGETS: dict[str, int] = {
    "us": 2840, "gb": 2826, "de": 2276, "fr": 2250, "es": 2724, "it": 2380,
    "nl": 2528, "pl": 2616, "pt": 2620, "se": 2752, "ch": 2756, "at": 2040,
    "ca": 2124, "au": 2036, "nz": 2554, "ie": 2372, "br": 2076, "mx": 2484,
    "ar": 2032, "in": 2356, "id": 2360, "sg": 2702, "my": 2458, "ph": 2608,
    "jp": 2392, "kr": 2410, "cn": 2156, "tw": 2158, "hk": 2344, "th": 2764,
    "vn": 2704, "tr": 2792, "ae": 2784, "sa": 2682, "eg": 2818, "il": 2376,
    "za": 2710, "ng": 2566, "ke": 2404, "ru": 2643, "ua": 2804, "kz": 2398,
    "by": 2112, "uz": 2860, "am": 2051, "ge": 2268, "az": 2031, "rs": 2688,
    "ro": 2642, "cz": 2203, "gr": 2300, "no": 2578, "dk": 2208, "fi": 2246,
    "be": 2056, "cl": 2152, "co": 2170, "pe": 2604,
}

# Google Ads languageConstants.
GOOGLE_LANGUAGES: dict[str, int] = {
    "en": 1000, "de": 1001, "fr": 1002, "es": 1003, "it": 1004, "ja": 1005,
    "da": 1009, "nl": 1010, "fi": 1011, "ko": 1012, "nb": 1013, "pt": 1014,
    "sv": 1015, "zh": 1017, "ar": 1019, "bg": 1020, "cs": 1021, "el": 1022,
    "hi": 1023, "hu": 1024, "id": 1025, "is": 1026, "he": 1027, "lv": 1028,
    "lt": 1029, "pl": 1030, "ru": 1031, "ro": 1032, "sk": 1033, "sl": 1034,
    "sr": 1035, "uk": 1036, "tr": 1037, "ca": 1038, "hr": 1039, "vi": 1040,
    "ur": 1041, "tl": 1042, "et": 1043, "th": 1044,
}

# Bing needs an IETF tag; this is the default tag per country when the caller
# gives only a language code.
BING_DEFAULT_LOCALE: dict[str, str] = {
    "en": "en-US", "ru": "ru-RU", "de": "de-DE", "fr": "fr-FR", "es": "es-ES",
    "it": "it-IT", "pt": "pt-BR", "nl": "nl-NL", "pl": "pl-PL", "tr": "tr-TR",
    "ar": "ar-SA", "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR", "uk": "uk-UA",
    "he": "he-IL", "sv": "sv-SE", "cs": "cs-CZ", "id": "id-ID", "hi": "hi-IN",
}


def yandex_region(geo: str) -> Optional[int]:
    return YANDEX_REGIONS.get((geo or "").lower())


def google_geo_target(geo: str) -> Optional[int]:
    return GOOGLE_GEO_TARGETS.get((geo or "").lower())


def google_language(language: str) -> Optional[int]:
    return GOOGLE_LANGUAGES.get((language or "").split("-")[0].lower())


def bing_locale(language: str, geo: str) -> str:
    """IETF tag Bing wants: the query language spoken in the queried country.

    A caller-supplied full tag wins. Otherwise language+country beats the
    language's "home" market — English demand in the UK is en-GB, not en-US.
    """
    if "-" in (language or ""):
        return language
    lang = (language or "en").split("-")[0].lower()
    country = (geo or "").lower()
    if country and country not in ("ww", "zz"):
        return f"{lang}-{country.upper()}"
    return BING_DEFAULT_LOCALE.get(lang, f"{lang}-US")


__all__ = [
    "load_env", "env", "yandex_region", "google_geo_target", "google_language",
    "bing_locale", "YANDEX_REGIONS", "GOOGLE_GEO_TARGETS", "GOOGLE_LANGUAGES",
]
