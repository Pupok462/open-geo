# open-geo — Dashboard

FastAPI backend (read-only over `data/aeo.db`) + Vite/React/TypeScript/Tailwind/Recharts
frontend. Shows AI-visibility metrics per brand/engine with retrospective charts,
read-time deltas, lens breakdown, a **top-domains (competitor) leaderboard**, a per-query
results table, and a PDF export. The
brand/engine selectors are **data-driven** — the engine list is whatever has runs in the DB
(`/api/engines`), so as capture expands beyond Google AI Overview (ROADMAP Feature 3) new
engines surface automatically with no dashboard change (the Google-flavored metric *labels*
in `i18n/` are the one thing Feature 3 may revisit). The
React UI has light & dark themes (toggle, system-aware), a **language switcher** (EN/RU/ZH/AR,
extensible — driven by `i18n/`, see below), and per-metric `(i)` tooltips carrying the
§4 definitions; it lives in `web/src/redesign/` as a self-contained, dependency-free
design system (semantic CSS-variable tokens, inline SVG icons).

## Layout

```
dashboard/
  api.py            FastAPI app (package: dashboard.api:app)
  seed_fixture.py   seeds a throwaway data/_fixture_dash.db for self-test
  web/              Vite + React + TS + Tailwind 4 + Recharts frontend
  README.md         this file
```

> **`dashboard/seed_fixture.py` vs `pipeline/seed_demo.py`** — `seed_fixture.py` is the
> **dashboard self-test fixture**: it writes a **separate throwaway DB**
> (`data/_fixture_dash.db`, never `data/aeo.db`) seeded multi-brand and with a
> still-running-run edge case, just to exercise the UI. `pipeline/seed_demo.py` is the
> **canonical demo** that seeds the real working `data/aeo.db`. Use `seed_demo` to see a
> realistic dashboard/report; use `seed_fixture` only for dashboard self-testing.

## Backend

Read-only JSON API. DB path comes from env `OPEN_GEO_DB` (default `data/aeo.db`).
All paths resolve relative to the repo root, so launch from anywhere.

Run (from the repo root `open-geo/`). **Local port 8000 is often already busy on this
machine** — prefer a free port such as `8077` and point the frontend at it with
`VITE_API_BASE` (see below); the API serves permissive CORS, so a cross-origin base works
without the dev proxy:

```bash
# Pick a free port (8000 is the frontend dev-proxy default but is often taken — use 8077):
OPEN_GEO_DB=data/aeo.db .venv/bin/python -m uvicorn dashboard.api:app \
    --host 127.0.0.1 --port 8077
```

Then start the frontend with `VITE_API_BASE=http://127.0.0.1:8077 npm run dev` (see the
Frontend section). Only when you stay on `--port 8000` does the bare `npm run dev` proxy
line up without `VITE_API_BASE`.

> **Launching from outside the repo root / in a background shell** (e.g. an orchestrator
> that backgrounds the servers and does **not** inherit the repo-root CWD): use absolute
> paths and `--app-dir`, since a relative `.venv/bin/python` fails with exit 127. The form
> that works from any CWD (`<REPO>` = absolute repo root):
> ```bash
> OPEN_GEO_DB=<REPO>/data/aeo.db <REPO>/.venv/bin/python -m uvicorn dashboard.api:app \
>     --host 127.0.0.1 --port 8077 --app-dir <REPO>
> # frontend — no `cd`:
> VITE_API_BASE=http://127.0.0.1:8077 npm --prefix <REPO>/dashboard/web run dev
> ```

### Endpoints

| method | path | purpose |
|---|---|---|
| GET  | `/api/health` | liveness + which DB is wired in |
| GET  | `/api/brands` | `[{id, name, domain}]` |
| GET  | `/api/engines?brand_id=` | distinct engines for a brand |
| GET  | `/api/runs?brand_id=&engine=` | runs newest-first |
| GET  | `/api/metrics?brand_id=&engine=&period=today\|all&lens=` | metrics + read-time deltas + per-lens `sentiment_summary` |
| GET  | `/api/timeseries?brand_id=&engine=&lens=` | per-run points over time (retrospective) |
| GET  | `/api/competitors?brand_id=&engine=&period=today\|all&lens=&sort=sources\|citations&limit=15` | top-domains leaderboard from `domain_stats` |
| GET  | `/api/results?run_id=&lens=` | per-query rows (JSON cols decoded, incl. sentiment) |
| GET  | `/api/i18n` | the `i18n/locales.json` registry — `[{code, name}]`, drives the language switcher |
| GET  | `/api/i18n/{code}` | that locale's string dict (`i18n/<code>.json`); falls back to `en` for an unknown code |
| POST | `/api/report?brand_id=&engine=&period=today\|all&lang=en\|ru\|zh\|ar` | runs `report.generate` (with `--lang`), streams the PDF |

`period` semantics for `/api/metrics`:
- `today` → snapshot of the latest **completed** run; each rate metric carries a
  `*_delta` vs the previous completed run (INTERFACES §4.1, matched per lens).
- `all` → whole-period view aggregated across **all** completed runs (the §4 ratios
  recomputed from summed numerators/denominators); no per-run delta in this mode.

Each per-lens row from `/api/metrics` (incl. the `all` row) also carries
**`sentiment_summary`** (`string | null`) — the orchestrator's per-lens **qualitative** roll-up
of that lens's per-query `sentiment`s, read from the `lens_sentiment` table (INTERFACES §2; it is
written at finalize by the `/open-geo` skill via `pipeline.lens_sentiment`, **not** by
`pipeline.aggregate`). `null` means the brand appeared in no query of that lens. It is text, not a
number, and follows the language of the captured sentiments (independent of the UI language). The
web UI surfaces these as a **"Sentiment by lens"** panel above the per-query results table.
Because the API is **read-only and never calls `init_db`**, a DB created before this table existed
degrades gracefully: the endpoint returns rows with `sentiment_summary: null` (catching
`no such table`) instead of erroring.

`/api/competitors` returns the **top-domains leaderboard** (the `domain_stats` table, INTERFACES
§2/§4.2): every domain appearing in `sources`/`citations` for the scope — brand competitors and
publishers alike — with `appearances_sources`/`appearances_citations` (presence over
overview-present queries), `avg_source_position`/`avg_citation_position`, and read-time
`share_sources`/`share_citations` (appearances ÷ that scope's `n_overviews`). `is_brand` flags the
brand's own row. `period=today` reads the latest completed run; `period=all` rolls the period up
across completed runs (avg positions via summed `min`-rank weights). `sort` (default `sources`)
picks the top-`limit` (default 15); the web UI re-sorts those rows client-side on column click. As
with sentiment, the read-only API never calls `init_db`, so a DB predating `domain_stats` returns
an empty `domains: []` (catching `no such table`) instead of erroring. The web UI surfaces this as a
**"Top domains in answer space"** panel (the brand row highlighted with a "you" badge); the PDF
report carries the same as its top-domains section.

The frontend shows the **Trend across runs** chart only in the `all` (whole-period) view; the
`today` (latest-run) view is a pure snapshot — KPI cards with read-time deltas, no trend chart.

`/api/report` invokes the report CLI
(`python -m report.generate --brand --domain --engine --period --lang --out --db`) into a
temp file and returns `application/pdf`. `lang` defaults to `en` and is passed through as
`--lang`. If `report/generate.py` is absent it returns `501` with the exact CLI command, so
the button degrades gracefully.

`/api/i18n` and `/api/i18n/{code}` serve the static locale files from the repo's `i18n/`
dir (resolved relative to the repo root, same as `OPEN_GEO_DB`). `/api/i18n` returns the
`locales.json` registry that drives the switcher; `/api/i18n/{code}` returns one locale's
string dict, falling back to `en` for an unknown code (the frontend also falls back per
key). Adding a language is dropping a JSON file — see `i18n/README.md`.

## Frontend

```bash
cd dashboard/web
npm install
npm run dev      # http://localhost:5173  (proxies /api -> http://127.0.0.1:8000)
```

The header carries a **language switcher** (EN/RU/ZH/AR; and a light/dark theme toggle). It fetches
`GET /api/i18n` for the available locales and `GET /api/i18n/<chosen>` for the active string
dict, looks strings up via `t("namespace.key")`, defaults to `en`, and persists the choice in
`localStorage`. Missing keys fall back to English per key, so a partial translation never
breaks the UI. To add a language, drop a JSON file into `i18n/` and register it in
`i18n/locales.json` (full instructions in `i18n/README.md`) — it appears in the switcher
automatically.

**Initial UI language.** On first load the language is resolved as `?lang=<code>` URL param
→ persisted `localStorage["og-lang"]` → `en`. So `http://localhost:5173/?lang=ru` opens in
Russian without touching the switcher (the switcher still overrides and persists the choice;
an unknown code falls back to English per key). This is how `/open-geo --lang` seeds the
dashboard language.

Production build:

```bash
cd dashboard/web
npm run build    # tsc -b && vite build  ->  dist/
npm run preview  # serve the built dist/
```

Point the UI at a non-default API origin (skips the dev proxy; relies on CORS):

```bash
VITE_API_BASE=http://127.0.0.1:8077 npm run dev
# or bake it into a build:
VITE_API_BASE=http://127.0.0.1:8077 npm run build
```

## Self-test (reproduce)

```bash
# 1. Seed a throwaway fixture DB (never touches data/aeo.db):
.venv/bin/python -m dashboard.seed_fixture          # -> data/_fixture_dash.db

# 2. Start the API against the fixture on a test port:
OPEN_GEO_DB=data/_fixture_dash.db .venv/bin/python -m uvicorn dashboard.api:app \
    --host 127.0.0.1 --port 8077

# 3. Probe it (the fixture seeds engine `google` — the same id as a live run):
curl -s 'http://127.0.0.1:8077/api/brands'
curl -s 'http://127.0.0.1:8077/api/metrics?brand_id=1&engine=google&period=today'
curl -s 'http://127.0.0.1:8077/api/i18n'

# 4. Build the frontend:
cd dashboard/web && npm install && npm run build
```

The fixture seeds two brands (e.g. Example / Globex), each with three completed runs of
increasing visibility plus one still-running run, across all three lenses — enough to
exercise deltas, the retrospective chart, lens breakdown, and the results table.
