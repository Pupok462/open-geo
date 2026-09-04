from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from demand import cache, providers
from demand.schema import DemandStat


def lookup_phrases(
    phrases: list[str],
    geo: str,
    language: str,
    *,
    provider: str = "auto",
    n_related: int = 0,
    ttl_days: int = 7,
    with_suggest: bool = True,
    db_path: str = cache.DEFAULT_DB,
    conn=None,
) -> dict:
    """Demand for a batch of phrases in ONE locale.

    Falls forward through the configured volume providers, then — only when no
    volume ruler answered — records the autocomplete presence signal so the
    candidate still carries evidence, explicitly marked as presence-without-volume.
    """
    own_conn = conn is None
    conn = conn or cache.get_conn(db_path)
    try:
        usable, skipped = providers.resolve(
            geo, language, provider=provider, conn=conn, ttl_days=ttl_days
        )
        floor = providers.suggest_provider(conn=conn, ttl_days=ttl_days) if with_suggest else None

        results: list[DemandStat] = []
        for phrase in phrases:
            phrase = phrase.strip()
            if not phrase:
                continue
            stat: Optional[DemandStat] = None
            attempts: list[str] = []
            for instance in usable:
                candidate = instance.lookup(phrase, geo, language, n_related=n_related)
                if candidate.status in ("ok", "zero"):
                    stat = candidate
                    break
                attempts.append(f"{instance.name}: {candidate.reason}")
                stat = stat or candidate
            if stat is None or stat.status not in ("ok", "zero"):
                if floor is not None:
                    presence = floor.lookup(phrase, geo, language, n_related=n_related)
                    presence.reason = "; ".join(
                        filter(None, [
                            "no volume provider answered",
                            *attempts,
                            *[f"{s['provider']}: {s['reason']}" for s in skipped],
                            presence.reason,
                        ])
                    )
                    stat = presence
                elif stat is None:
                    stat = DemandStat(
                        phrase=phrase, status="unavailable", geo=geo, language=language,
                        reason="; ".join(
                            [f"{s['provider']}: {s['reason']}" for s in skipped]
                        ) or "no provider configured",
                        scope="",
                    )
            results.append(stat)

        quota = {
            instance.name: {
                "used_today": instance.quota_used(),
                "daily_limit": instance.daily_limit,
            }
            for instance in usable
        }
        return {
            "geo": geo,
            "language": language,
            "providers_used": [p.name for p in usable],
            "providers_skipped": skipped,
            "quota": quota,
            "results": [r.model_dump() for r in results],
        }
    finally:
        if own_conn:
            conn.close()


def _read_phrases(args: argparse.Namespace) -> list[str]:
    phrases = list(args.phrase or [])
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            phrases += [line.strip() for line in fh if line.strip()]
    if not phrases and not sys.stdin.isatty():
        phrases += [line.strip() for line in sys.stdin if line.strip()]
    return phrases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demand.lookup",
        description="Keyword demand over official APIs (Wordstat / Google Ads / Bing / suggest).",
    )
    parser.add_argument("--phrase", action="append", help="repeatable; or use --file / stdin")
    parser.add_argument("--file", help="file with one phrase per line")
    parser.add_argument("--geo", default="ru", help="ISO-3166 alpha-2 lowercase, or 'ww'")
    parser.add_argument("--lang", dest="language", default="", help="query language, e.g. ru / en")
    parser.add_argument("--provider", default="auto", choices=["auto", *providers.REGISTRY])
    parser.add_argument("--related", type=int, default=0, help="related phrases to return per lookup")
    parser.add_argument("--ttl-days", type=int, default=7, help="cache TTL; 0 disables the cache")
    parser.add_argument("--no-suggest", action="store_true", help="do not fall back to autocomplete presence")
    parser.add_argument("--db", default=cache.DEFAULT_DB)
    args = parser.parse_args(argv)

    phrases = _read_phrases(args)
    if not phrases:
        print("no phrases given (--phrase / --file / stdin)", file=sys.stderr)
        return 2

    language = args.language or ("ru" if args.geo.lower() in providers.RU_LOCALES else "en")
    payload = lookup_phrases(
        phrases, args.geo.lower(), language,
        provider=args.provider, n_related=args.related, ttl_days=args.ttl_days,
        with_suggest=not args.no_suggest, db_path=args.db,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
