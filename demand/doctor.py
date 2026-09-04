from __future__ import annotations

import argparse
import json

from demand import cache, config, providers


def diagnose(geo: str = "ru", language: str = "", db_path: str = cache.DEFAULT_DB) -> dict:
    """What can actually be measured right now, and what is missing to widen it."""
    config.load_env()
    language = language or ("ru" if geo.lower() in providers.RU_LOCALES else "en")
    conn = cache.get_conn(db_path)
    try:
        rows = []
        for name in providers.REGISTRY:
            instance = providers.build(name, conn=conn)
            configured, missing = instance.credentials()
            supported, why = instance.supports(geo, language)
            rows.append({
                "provider": name,
                "configured": configured,
                "missing_env": missing,
                "supports_locale": supported,
                "locale_note": why,
                "used_today": instance.quota_used(),
                "daily_limit": instance.daily_limit,
                "howto": instance.howto,
            })
        usable = [r["provider"] for r in rows if r["configured"] and r["supports_locale"]]
        volume_capable = [p for p in usable if p != "suggest"]
        return {
            "geo": geo,
            "language": language,
            "preference": list(providers.preference(geo, language)),
            "usable": usable,
            "volume_capable": volume_capable,
            "verdict": (
                "volume available" if volume_capable
                else "presence only — no volume provider configured for this locale"
            ),
            "providers": rows,
        }
    finally:
        conn.close()


def render(report: dict) -> str:
    lines = [
        f"demand doctor — geo={report['geo']} lang={report['language']}",
        f"verdict: {report['verdict']}",
        "",
    ]
    for row in report["providers"]:
        mark = "ok " if row["configured"] else "-- "
        limit = f"{row['used_today']}/{row['daily_limit']}" if row["daily_limit"] else str(row["used_today"])
        lines.append(f"[{mark}] {row['provider']:<11} used today: {limit}")
        if not row["configured"]:
            lines.append(f"       missing: {', '.join(row['missing_env'])}")
            for text in row["howto"].splitlines():
                lines.append(f"       {text}")
        elif not row["supports_locale"]:
            lines.append(f"       skipped here: {row['locale_note']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demand.doctor",
        description="Which demand providers are configured, what they cover, what is missing.",
    )
    parser.add_argument("--geo", default="ru")
    parser.add_argument("--lang", dest="language", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--db", default=cache.DEFAULT_DB)
    args = parser.parse_args(argv)

    report = diagnose(args.geo.lower(), args.language, db_path=args.db)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
