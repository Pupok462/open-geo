from __future__ import annotations

import argparse
import json
from datetime import date

from demand import cache, providers
from demand.schema import Metric

_METRIC_BY_PROVIDER: dict[str, Metric] = {
    "wordstat": "impressions_per_month",
    "google_ads": "avg_monthly_searches",
    "bing": "impressions_4w",
    "suggest": "suggest_presence",
}

_UNIT = {
    "impressions_per_month": "показов/мес",
    "avg_monthly_searches": "avg monthly searches",
    "impressions_4w": "impressions / 4 weeks",
}


def _scope(provider: str, phrase: str, volume: int | None, geo: str, language: str) -> str:
    stamp = date.today().isoformat()
    where = "worldwide" if geo == "ww" else geo.upper()
    if volume is None:
        return f"{provider}: '{phrase}' — real phrasing, {where}/{language} (checked {stamp}); no volume"
    metric = _METRIC_BY_PROVIDER.get(provider, "avg_monthly_searches")
    unit = _UNIT.get(metric, "")
    shown = f"{volume:,}".replace(",", " ")
    return f"{provider}: '{phrase}' — {shown} {unit}, {where}/{language} (pulled {stamp})"


def expand_seed(
    seed: str,
    geo: str,
    language: str,
    *,
    provider: str = "auto",
    n: int = 60,
    deep: bool = False,
    with_suggest: bool = True,
    min_volume: int = 0,
    ttl_days: int = 7,
    db_path: str = cache.DEFAULT_DB,
    conn=None,
) -> dict:
    """One seed phrase -> the real phrasings around it, with volume where a ruler exists."""
    own_conn = conn is None
    conn = conn or cache.get_conn(db_path)
    try:
        usable, skipped = providers.resolve(
            geo, language, provider=provider, conn=conn, ttl_days=ttl_days
        )
        merged: dict[str, dict] = {}

        for instance in usable:
            for item in instance.expand(seed, geo, language, n=n):
                key = item.phrase.strip().lower()
                if not key or key in merged:
                    continue
                merged[key] = {
                    "phrase": item.phrase.strip(),
                    "volume": item.volume,
                    "provider": instance.name,
                    "metric": _METRIC_BY_PROVIDER.get(instance.name),
                    "scope": _scope(instance.name, item.phrase.strip(), item.volume, geo, language),
                }

        if with_suggest:
            floor = providers.suggest_provider(conn=conn, ttl_days=ttl_days)
            for item in floor.expand(seed, geo, language, n=n, deep=deep):
                key = item.phrase.strip().lower()
                if not key or key in merged:
                    continue
                merged[key] = {
                    "phrase": item.phrase.strip(),
                    "volume": None,
                    "provider": "suggest",
                    "metric": "suggest_presence",
                    "scope": _scope("suggest", item.phrase.strip(), None, geo, language),
                }

        phrases = list(merged.values())
        if min_volume:
            phrases = [p for p in phrases if p["volume"] is None or p["volume"] >= min_volume]
        phrases.sort(key=lambda p: (p["volume"] is None, -(p["volume"] or 0), p["phrase"]))
        return {
            "seed": seed,
            "geo": geo,
            "language": language,
            "providers_used": [p.name for p in usable] + (["suggest"] if with_suggest else []),
            "providers_skipped": skipped,
            "count": len(phrases[:n]),
            "phrases": phrases[:n],
        }
    finally:
        if own_conn:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demand.expand",
        description="Expand a seed phrase into the real queries around it, with volume where available.",
    )
    parser.add_argument("--seed", action="append", required=True, help="repeatable")
    parser.add_argument("--geo", default="ru")
    parser.add_argument("--lang", dest="language", default="")
    parser.add_argument("--provider", default="auto", choices=["auto", *providers.REGISTRY])
    parser.add_argument("--n", type=int, default=60, help="max phrases per seed")
    parser.add_argument("--deep", action="store_true", help="alphabet sweep on autocomplete (slower, wider tail)")
    parser.add_argument("--no-suggest", action="store_true")
    parser.add_argument("--min-volume", type=int, default=0)
    parser.add_argument("--ttl-days", type=int, default=7)
    parser.add_argument("--db", default=cache.DEFAULT_DB)
    args = parser.parse_args(argv)

    language = args.language or ("ru" if args.geo.lower() in providers.RU_LOCALES else "en")
    conn = cache.get_conn(args.db)
    try:
        payload = {
            "geo": args.geo.lower(),
            "language": language,
            "seeds": [
                expand_seed(
                    seed, args.geo.lower(), language, provider=args.provider, n=args.n,
                    deep=args.deep, with_suggest=not args.no_suggest,
                    min_volume=args.min_volume, ttl_days=args.ttl_days, conn=conn,
                )
                for seed in args.seed
            ],
        }
    finally:
        conn.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
