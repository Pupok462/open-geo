# demand/ — keyword demand over official APIs (no browser)

The deterministic half of question harvesting: **how much is this actually searched?**, answered by
the search platforms' own APIs instead of an agent driving a logged-in Wordstat tab. The agentic
half — which angles a product has, how a person phrases the need to an assistant, which lines
survive a skeptic — stays in `harvest/METHODOLOGY.md`. This package only supplies measured numbers
and real phrasings, each carrying the scope it was measured in.

**Nothing here invents a figure.** When no provider covers a locale, the answer is
`status="unavailable"` with the reason, not a plausible number.

## Providers

| provider | ruler | scope | credentials |
|---|---|---|---|
| `wordstat` | impressions/month (Yandex, last 30 days) | RU/CIS, or any Russian-language slice | free API key (Yandex Cloud / AI Studio) or the legacy beta OAuth token — 1000 calls/day |
| `google_ads` | avg monthly searches (12-month) | worldwide, per country + language | free developer token (Google Ads API Center) + OAuth refresh token |
| `bing` | impressions, last 4 weeks summed | worldwide, per country + language | free API key from Bing Webmaster Tools (verify any site you own) |
| `suggest` | presence only, **no volume** | everywhere, no credentials | none — Google / Yandex / Bing / DuckDuckGo autocomplete |

Routing is locale-aware (`demand/providers/__init__.py :: preference`): a Russian slice asks
Wordstat first, everything else asks Google Ads first, and `suggest` is the floor that always
answers — it proves a phrasing is real even where no volume ruler is configured.

## CLIs

```bash
# What can I measure right now, and what is missing to widen it?
.venv/bin/python -m demand.doctor --geo ru

# Volume for specific phrases (repeatable --phrase, or --file / stdin)
.venv/bin/python -m demand.lookup --geo ru --lang ru \
  --phrase "речевая аналитика" --phrase "контроль качества звонков" --related 10

# Seed -> the real queries around it, volume where a ruler exists
.venv/bin/python -m demand.expand --seed "speech analytics" --geo us --lang en --n 60 [--deep]

# Commit a measured core: validates clusters, mints questions.csv via harvest.build
.venv/bin/python -m demand.core --out core/<brand>/core.json \
  --questions-out <brand>_questions.csv --brand "<Brand>" --domain <domain> \
  < core_in.json
```

Every `DemandStat` carries a **`scope`** string — the number *with* its region, period and pull
date, ready to paste into a `QuestionCandidate.signal`. That is the hand-off: provenance travels
with the figure instead of being re-typed.

## Caching and quotas

Answers are cached in `data/demand_cache.db` (SQLite, 7-day TTL by default) and every live call is
counted per provider per day, because Wordstat allows 1000/day. `--ttl-days 0` forces a fresh pull.

## Contract

`pipeline/INTERFACES.md §8` — `DemandStat`, `SemanticCore`, and the `demand.core` hand-off that
open-geo reads. Schemas: `demand/schema.py`, `demand/core.py`.
