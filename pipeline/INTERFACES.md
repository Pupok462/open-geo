# open-geo — Pipeline Interfaces (the contract for all downstream agents)

> This is the **single source of truth** that every other agent (capture,
> ingest, aggregate, report, dashboard, skill) builds against. The shapes here
> are authoritative. Code identifiers are guaranteed English; user-facing
> docs/reports/UI are **English by default and localized via the i18n layer**
> (`--lang`, `i18n/<code>.json`) — but THIS file is English so all agents read
> it identically.
>
> **All of the following are implemented:** `pipeline/schema.py`,
> `pipeline/db.py`, the `python -m pipeline.ingest`,
> `python -m pipeline.aggregate` and `python -m pipeline.lens_sentiment` CLIs,
> the question-harvesting package (`harvest/schema.py` + `python -m harvest.build`, §6),
> the PDF report (`report.generate`), and
> the dashboard (`dashboard/api.py` + `dashboard/web/`).

---

## 1. The capture contract — `QueryCapture` JSON

The **capture agent** drives an engine (e.g. Google AI Overview) for one
`(query, lens)` and emits **one `QueryCapture` JSON object per query**, which it
**returns to the orchestrator** — a capture agent never writes to the database
itself. The **orchestrator** collects the per-query objects into a **JSON array**
and feeds it to the ingest CLI on STDIN — **per worker chunk, as each returns**
(incremental durability, §2.1), not one batch at the very end. Ingest is
**idempotent** on `(run_id, query, lens)`, so retries/resumes never duplicate rows.

Canonical model: `pipeline/schema.py :: QueryCapture` (pydantic v2). Ingest
validates every object against it.

### 1.1 Field-by-field

| field | type | required | meaning |
|---|---|---|---|
| `query` | string | yes | The exact query sent to the engine. |
| `lens` | `"general" \| "branded" \| "comparative"` | yes | Framing of the query. `general` = neutral, no brand named; `branded` = brand explicitly named; `comparative` = brand vs alternatives. |
| `engine` | string | yes | Engine id, snake_case — the orchestrator's `<engine>` argument **copied through verbatim** (it equals the capture playbook basename, e.g. `google` ↔ `engines/google.md`, `chatgpt_search` ↔ `engines/chatgpt_search.md`); do not hardcode a different value. **Open string by design** — this is the multi-engine extension point: one `engines/<engine>.md` playbook per engine. Shipped today: **`google`** (Google AI Overview), **`chatgpt_search`** (ChatGPT web search), **`claude_search`** (Claude web search), **`yandex_neuro`** (Yandex Alice / Нейро), **`gemini`** (Google Gemini) and **`deepseek`** (DeepSeek web search); **`perplexity`** (Perplexity, `engines/perplexity.md`, grounded-answer gate, live-validated 2026-08-08); more remain a backlog item (ROADMAP Feature 3). |
| `captured_at` | string (ISO-8601 datetime) | yes | When the answer was captured. Parsed by pydantic into `datetime`. Use UTC, e.g. `"2026-06-18T20:15:30Z"`. |
| `answer_text_md` | string \| null | no (default `null`) | The answer prose as Markdown. `null` if no overview / not captured. |
| `screenshot_path` | string \| null | no (default `null`) | **v1: always `null`.** A *transient* screenshot may be taken to read the overview, but screenshots are **not persisted**, so nothing is stored here (column kept for forward-compat). |
| `overview_present` | bool | yes | Did an AI Overview actually render for this query? This is the **denominator gate** for visibility metrics. |
| `sources` | array of `Link` | no (default `[]`) | The **relied-on / retrieved set** — every link the model drew on, in display order, **duplicate domains allowed**. This **includes every cited domain**: fold any inline-cited link into `sources` (the visible Google "sources panel" is only a *partial* view of the retrieval set, so a domain cited in the prose but missing from the panel is still a source). |
| `citations` | array of `Link` | no (default `[]`) | Links **attached / cited** in the answer prose, in order, duplicates allowed. Citations are a **subset of `sources`** (the model can only cite what it retrieved) — every domain here MUST also appear in `sources`. |
| `target_source_ranks` | array of int | no (default `[]`) | **ALL** 1-based positions of links **matching the target** (domain or URL prefix) within `sources`, as produced by `pipeline.schema.target_ranks`. `[]` if the target never appears in sources. |
| `target_citation_ranks` | array of int | no (default `[]`) | Same, but for `citations`, via `pipeline.schema.target_ranks`. |
| `brand_in_answer_text` | bool | yes | Was the brand **NAME** mentioned in the prose, independent of any link? |
| `sentiment` | string \| null | no (default `null`) | Short **qualitative** text describing how the answer treats the target domain (e.g. `"recommended as top pick"`, `"mentioned neutrally among 5 options"`). **`null` if the domain/brand did not appear at all.** This is free text, NOT a number. |

`Link` object:

| field | type | meaning |
|---|---|---|
| `rank` | int | 1-based position in its ordered list (`sources` or `citations`). |
| `url` | string | The full URL. |
| `domain` | string | Registrable domain, **lowercased, no `www`**. Produce it with `pipeline.schema.normalize_domain(url)`. `Link.url` SHOULD be the direct publisher URL (unwrap redirect wrappers where possible); when `url` is a redirect wrapper, target matching by URL prefix falls back to domain-only. |

### 1.2 Rules the capture agent MUST follow

- `rank` is **1-based** and matches array position (first link = rank 1).
- `target_source_ranks` / `target_citation_ranks` list **every** position of the
  target domain (a domain can legitimately appear more than once). Order them
  ascending.
- **Every domain in `citations` MUST also appear in `sources`** (fold inline-cited
  links into `sources` — citations ⊆ sources, because the model can only cite what
  it retrieved; the visible sources panel is just a partial view). Consequently a
  non-empty `target_citation_ranks` ⟹ a non-empty `target_source_ranks` for the
  same query.
- When `overview_present` is `false`: `sources`, `citations` and both rank
  arrays should be `[]`, `answer_text_md` is typically `null`, `sentiment` is
  `null`, `brand_in_answer_text` is `false`.
- `sentiment` is `null` **iff** the target did not appear (neither in prose nor
  in links). If it appeared anywhere, write one short qualitative phrase.
- Determine `domain` (and the target domain you match against) via
  `normalize_domain` so matching is consistent across the pipeline.
- **Target matching — domain or URL prefix.** The `--domain` argument (§3.1) accepts
  either a bare registrable domain (`example.com`) **or a URL prefix**
  (`github.com/Pupok462/open-geo`). Canonical form is produced by
  `pipeline.schema.normalize_target` (strips scheme/`//`, userinfo, port, query,
  fragment; lowercases path segments; collapses empty segments). A link matches the
  target when both are canonicalized and: registrable domains are equal **AND** (the
  target has no path segments, OR the target's path segments are a prefix of the
  link's path segments). Concretely:
  - Target without path (`example.com`) → same behavior as before (domain equality).
  - Target with path (`github.com/user/repo`) → `github.com/user/repo/blob/main/README.md`
    matches; `github.com/user-fake/repo` does not; `github.com/user` without path does not.
  - Domain-only `Link` (redirect wrapper or domain-only entry) when target has a path →
    **conservative non-match** (path unavailable; use `pipeline.schema.target_ranks` which
    applies this rule via the `effective` selection: direct URL if `normalize_domain(url) ==
    normalize_domain(domain)`, else domain-only fallback).
  - Subdomains collapse to registrable domain: `forum.ixbt.com` matches target `ixbt.com`.
  - Path comparison is **case-insensitive** (GitHub, Reddit, X are case-insensitive — undercounting
    is worse than rare overcounting).
- `screenshot_path` is **`null`** in v1: a screenshot may be taken to *read* the
  overview (required — `get_page_text` drops the AI block), but it is **not saved**
  as an artifact.

### 1.3 Example `QueryCapture` JSON object

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "google",
  "captured_at": "2026-06-18T20:15:30Z",
  "answer_text_md": "For small teams, tools with a simple task board are often recommended in this range. **Example** offers several suitable plans...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.techradar.com/best/project-management-software", "domain": "techradar.com" },
    { "rank": 4, "url": "https://example.com/blog/how-to-choose", "domain": "example.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://example.com/product/team-plan", "domain": "example.com" }
  ],
  "target_source_ranks": [2, 4],
  "target_citation_ranks": [1],
  "brand_in_answer_text": true,
  "sentiment": "recommended among suitable options, mentioned by name with a direct link to the product"
}
```

A batch fed to ingest is simply: `[ {QueryCapture}, {QueryCapture}, ... ]`.

---

## 2. Database — `data/aeo.db` (SQLite, WAL mode)

- **Location:** `data/aeo.db` (relative to repo root). Opened via
  `pipeline.db.get_conn(db_path="data/aeo.db")`, which sets
  `PRAGMA journal_mode=WAL;` and `PRAGMA foreign_keys=ON;`.
- **Schema creation / forward-migration:** `pipeline.db.init_db(conn)` — idempotent.
  Creates tables (`CREATE TABLE IF NOT EXISTS`) **and adds any column missing from an
  existing table** (`ALTER TABLE … ADD COLUMN`; currently `metrics.relative_citation`,
  `metrics.n_brand_mentions`, `metrics.brand_mention_rate`).
  Safe to call on every startup: it both initializes a fresh DB and forward-migrates an
  older one in place (existing rows read `NULL` for a newly added column until re-aggregated).
- Arrays / nested objects are stored as **JSON strings** in `*_json` columns.

### Tables

**`brands`**

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | brand name |
| `domain` | TEXT | normalized target (registrable domain or URL prefix), produced with `normalize_target` |
| `created_at` | TEXT | ISO-8601 |
| — | | `UNIQUE(name, domain)` |

**`runs`**

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `brand_id` | INTEGER | FK → `brands(id)` |
| `engine` | TEXT | |
| `run_at` | TEXT | ISO-8601 |
| `status` | TEXT | default `'running'` (e.g. `running` → `done`/`failed`) |
| `n_queries` | INTEGER | default 0 |
| `n_ok` | INTEGER | default 0 |
| `n_failed` | INTEGER | default 0 |
| `group_id` | TEXT \| NULL | repeat-run group tag (Feature 5). NULL = a standalone run (default, unchanged behavior). Runs of the **same brand+engine** sharing a `group_id` are **repeats of the same question set** captured deliberately R times; readers aggregate them as one logical measurement (mean + spread) at read-time. Assigned at creation (`--group-id`), never mutated. A DB created before this column **self-heals** on the next `init_db` (`ALTER TABLE … ADD COLUMN`; existing rows read NULL = standalone). |

**`results`** (one row per captured query = one serialized `QueryCapture`)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER | FK → `runs(id)` |
| `query` | TEXT | |
| `lens` | TEXT | |
| `captured_at` | TEXT | |
| `answer_text_md` | TEXT | |
| `screenshot_path` | TEXT | |
| `overview_present` | INTEGER | 0/1 |
| `sources_json` | TEXT | JSON array of `Link` |
| `citations_json` | TEXT | JSON array of `Link` |
| `target_source_ranks_json` | TEXT | JSON array of int |
| `target_citation_ranks_json` | TEXT | JSON array of int |
| `brand_in_answer_text` | INTEGER | 0/1 |
| `sentiment` | TEXT | qualitative text or NULL |

> **Capture identity / idempotency.** `(run_id, query, lens)` is the identity of a
> capture within a run, enforced by `UNIQUE INDEX idx_results_run_query_lens ON
> results(run_id, query, lens)`. Re-ingesting the same `(run_id, query, lens)` is a
> **safe no-op** (`INSERT … ON CONFLICT DO NOTHING`) — this is what makes
> incremental ingest and resume (§2.1) idempotent (no duplicate rows, no metric
> drift). A DB created before this index **self-heals** on the next `init_db`: it
> de-duplicates any pre-existing `(run_id, query, lens)` collisions (keeping the
> lowest `id`) and then creates the unique index — no manual step, no data loss
> beyond the redundant duplicates.

**`metrics`** (one row per lens + one `lens="all"` aggregate row per run)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER | FK → `runs(id)` |
| `brand_id` | INTEGER | |
| `engine` | TEXT | |
| `lens` | TEXT | a specific lens, or `"all"` for the cross-lens aggregate |
| `n_queries` | INTEGER | total queries in scope |
| `n_overviews` | INTEGER | queries with `overview_present=1` |
| `overview_coverage` | REAL \| NULL | see §4 (NULL when `n_queries=0`) |
| `n_in_sources` | INTEGER | queries (among overview-present) with non-empty `target_source_ranks` |
| `visibility_in_sources` | REAL \| NULL | see §4 (NULL when `n_overviews=0`) |
| `n_cited` | INTEGER | queries (among overview-present) with non-empty `target_citation_ranks` |
| `visibility_in_citations` | REAL \| NULL | see §4 (NULL when `n_overviews=0`) |
| `avg_source_position` | REAL \| NULL | see §4 (NULL when `n_in_sources=0`) |
| `avg_citation_position` | REAL \| NULL | see §4 (NULL when `n_cited=0`) |
| `relative_citation` | REAL \| NULL | see §4 (NULL when `n_in_sources=0`) |
| `n_brand_mentions` | INTEGER \| NULL | queries (among overview-present) with `brand_in_answer_text=1`; NULL on rows written before this column existed, until the run is re-aggregated |
| `brand_mention_rate` | REAL \| NULL | see §4 (NULL when `n_overviews=0`, and NULL on pre-migration rows until re-aggregated) |
| `computed_at` | TEXT | ISO-8601 |

> **Schema change / migration (mention axis):** `n_brand_mentions` /
> `brand_mention_rate` aggregate the long-captured `results.brand_in_answer_text`
> (§1) — no capture change, purely a new aggregate readout. A DB created before
> these columns **self-heals** on the next `init_db` (`ALTER TABLE … ADD COLUMN`);
> existing rows read `NULL` until re-aggregated, and every read-time consumer
> (dashboard API, report, `--period all` rollup) MUST treat `NULL` as "no data"
> ("—"), never as `0`.
>
> **Schema change / migration:** `relative_citation` was **RE-ADDED** (reversing
> its earlier removal — it is valid because citations ⊆ sources, so the ratio is
> bounded; see §4). `visibility_in_citations` and `avg_citation_position` remain.
> A DB created before this column **self-heals automatically**: `init_db` adds the
> missing `metrics.relative_citation` via `ALTER TABLE … ADD COLUMN` on the next
> startup — **no manual `DROP`, no data loss** (existing rows read `NULL` until the
> run is re-aggregated; `pipeline.aggregate` re-`DELETE`s + re-`INSERT`s a run's
> rows, so the value populates on the next aggregate).
>
> **Filename note:** `aeo.db` is a **historical filename** (the project is now
> *open-geo* / GEO); it is kept as-is for compatibility and carries no meaning
> beyond "the working SQLite DB".

**`lens_sentiment`** (one row per lens — incl. `lens="all"` — per run; the **orchestrator-written qualitative synthesis**, decoupled from `metrics`)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER | FK → `runs(id)` |
| `lens` | TEXT | a specific lens, or `"all"` for the cross-lens synthesis |
| `summary` | TEXT \| NULL | short **qualitative** synthesis of that lens's per-query `sentiment`s; `NULL` = no data (brand absent across the whole lens) |
| `computed_at` | TEXT | ISO-8601 |
| — | | `UNIQUE(run_id, lens)` |

> **Who writes it:** the **orchestrator** (skill), at finalize, via
> `python -m pipeline.lens_sentiment` (§3.4) — **NOT** `pipeline.aggregate` (which stays
> deterministic math and `DELETE`s+rebuilds `metrics`). This table is intentionally **separate
> from `metrics`** so re-aggregation never clobbers the synthesized prose. It is **qualitative**
> (free text) — consistent with §4's "no numeric sentiment": a per-lens text roll-up, **not** a
> score, index, or share-of-voice.
>
> **New table / migration:** `init_db` creates it (`CREATE TABLE IF NOT EXISTS`). The read-only
> dashboard API does **not** call `init_db`, so against a DB created before this change it MUST
> treat a missing `lens_sentiment` as "no summaries" (catch `no such table`), never error.

**`domain_stats`** (one row per `domain` × lens — incl. `lens="all"` — per run; the **competitor / top-domain leaderboard**, deterministic math written by `aggregate`)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `run_id` | INTEGER | FK → `runs(id)` |
| `brand_id` | INTEGER | denormalized (parity with `metrics`) |
| `engine` | TEXT | denormalized |
| `lens` | TEXT | a specific lens, or `"all"` for the cross-lens scope |
| `domain` | TEXT | normalized registrable domain (`normalize_domain`); **every** domain seen in `sources`/`citations`, not just the brand |
| `is_brand` | INTEGER | 0/1 — `1` when at least one link folded into this row actually matches the run's brand target under `matches_target` (§1.1), i.e. the same URL-prefix semantics the funnel metrics use. For a registrable-domain target (`ectem.ru`) that is every link on the domain; for a URL-prefix target (`github.com/user/repo`) a `github.com` row carrying only strangers' repos stays `is_brand=0`. |
| `appearances_sources` | INTEGER | # of overview-present queries in scope where the domain appears in `sources` (presence, counted once per query) |
| `appearances_citations` | INTEGER | same, for `citations` |
| `sum_min_source_rank` | REAL | Σ over those queries of `min(rank of domain in sources)` — kept so `period=all` rolls up `avg_source_position` by weighted sum |
| `sum_min_citation_rank` | REAL | same, for `citations` |
| `avg_source_position` | REAL \| NULL | `sum_min_source_rank / appearances_sources` (NULL if 0); lower = better |
| `avg_citation_position` | REAL \| NULL | `sum_min_citation_rank / appearances_citations` (NULL if 0); lower = better |
| `computed_at` | TEXT | ISO-8601 |
| — | | `UNIQUE(run_id, lens, domain)` |

> **Who writes it:** `pipeline.aggregate` (§3.3) — this is **deterministic math** over the same
> `results` rows it already reads (just generalized from the brand to **every** domain in
> `sources`/`citations`), so it correctly lives in `aggregate` and is `DELETE`+rebuilt per run
> alongside `metrics`. (Contrast `lens_sentiment`, which is LLM prose and is therefore kept *out*
> of the aggregate path.)
>
> **New table / migration:** `init_db` creates it (`CREATE TABLE IF NOT EXISTS`) — no `ALTER`
> needed. The read-only dashboard API does **not** call `init_db`, so against a DB created before
> this change it MUST treat a missing `domain_stats` as "no leaderboard" (catch `no such table` →
> empty list), never error. Rows populate on the next `aggregate` of each run.

**`audits`** (one row per audit of a domain — the **GEO-Audit Gate** result, Feature 2 / §7; both the history and the TTL cache)

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `target` | TEXT | the audited target as given — `normalize_target` (registrable domain or URL prefix) |
| `domain` | TEXT | registrable domain (`normalize_domain` of the target host) — the report/dashboard join key |
| `engine` | TEXT \| NULL | the engine context the audit ran for (A3 is **engine-aware**, §7); `NULL` = generic |
| `checked_at` | TEXT | ISO-8601 |
| `verdict` | TEXT | `ready` \| `ready_with_warnings` \| `blocked` |
| `score` | INTEGER | 0–100 GEO-readiness readout (§7) |
| `blocked` | INTEGER | 0/1 — `1` iff `verdict='blocked'` |
| `result_json` | TEXT | the full `AuditResult` JSON (§7), incl. every `CheckResult` |

> **Who writes it:** `python -m audit.gate` (§7) — the deterministic gate, **not** any run /
> `aggregate`. Keyed by `domain` (not `run_id`): the audit is about a domain's readiness and runs
> **before** any run exists (SKILL STEP 0). It is **append-only** time-series (like `runs`); the
> most recent row within the TTL doubles as the **cache** (`get_latest_audit` + `audit.cache.is_fresh`).
>
> **New table / migration:** `init_db` creates it (`CREATE TABLE IF NOT EXISTS`) — no `ALTER`
> needed. The read-only dashboard API does **not** call `init_db`, so against a DB created before
> this change it MUST treat a missing `audits` as "no audit" (catch `no such table` → `None`),
> never error.

### DB helpers provided by `pipeline/db.py`

- `get_conn(db_path="data/aeo.db") -> sqlite3.Connection`
- `init_db(conn) -> None`
- `get_or_create_brand(conn, name, domain) -> int` (normalizes `domain`)
- `create_run(conn, brand_id, engine, group_id=None) -> int` (status `'running'`; optional repeat-group tag, §2 `runs.group_id`)
- `update_run_counts(conn, run_id, n_queries=?, n_ok=?, n_failed=?, status=?) -> None`
- `upsert_lens_sentiment(conn, run_id, lens, summary) -> None` (replaces the row for that `run_id`+`lens`; `summary=None` clears it)
- `get_lens_sentiments(conn, run_id) -> dict[str, str]` (lens → summary; rows with a `NULL` `summary` are omitted — a missing key already means "no synthesis"; returns `{}` if the `lens_sentiment` table is absent)
- `get_domain_stats(conn, run_id, lens="all") -> list[dict]` (the leaderboard rows for one run+lens, ordered by `appearances_sources` desc; returns `[]` if the `domain_stats` table is absent)
- `get_captured_keys(conn, run_id) -> set[tuple[str, str]]` (the `(query, lens)` pairs already in `results` for the run — the resume diff source)
- `find_unfinished_run(conn, brand_id, engine) -> int | None` (most recent `status='running'` run for that brand+engine — the crashed run to resume, or `None`)
- `insert_audit(conn, target, domain, engine, checked_at, verdict, score, blocked, result_json) -> int` (appends one `audits` row, §7; returns its id)
- `get_latest_audit(conn, domain, engine=None) -> dict | None` (most recent audit for the registrable `domain`. **`engine` matches strictly**: given an engine, only that engine's row is returned — never another engine's, because A3 is engine-aware and one engine's crawl verdict does not transfer to another. `engine=None` returns the most recent row for the domain whatever its engine. Returns `None` if the `audits` table is absent — read-only-API safe)

### 2.1 Run lifecycle, incremental ingest & resume

A run moves `running → done` (or `failed`); **only the orchestrator finalizes it**
(SKILL STEP 4.2). Capture data is made durable **incrementally**, so a crash
mid-run never loses already-captured work:

- **Incremental ingest** — the orchestrator ingests **each worker's chunk the
  moment it returns**, not one batch at the very end. Every accepted `QueryCapture`
  is committed to `results` immediately; `ingest` keeps `runs.n_ok` at the live
  cumulative `COUNT(results for run)` and leaves `status='running'`.
- **Idempotency** — `(run_id, query, lens)` is unique and inserts are
  `ON CONFLICT DO NOTHING`, so re-sending a chunk (retry / overlap / resume) never
  duplicates rows or inflates metrics.
- **Resume** — a crashed run stays `status='running'` and is located via
  `find_unfinished_run(brand_id, engine)`. The orchestrator reads what is already
  captured (`get_captured_keys(run_id)`) and **re-dispatches only the missing
  `(query, lens)` rows** (CSV minus captured) into the **same** run, then finalizes
  (`status='done'`) once nothing is missing.
- **Repeat-run groups (Feature 5)** — `--repeat R` (SKILL) captures the same
  question set R times as R **ordinary runs** sharing one `runs.group_id` (§2);
  each repeat keeps the full durability/resume story above (it IS a normal run).
  Aggregation over the group is **read-time only** (dashboard API and the PDF
  report, §3.6): per lens, the
  seven §4 metrics are rolled up **weighted** across the group's completed runs
  (same math as the whole-period rollup) and each metric additionally carries its
  **min–max spread across repeats** — a *stability signal, not a precision claim*
  (moat #3: single LLM measurements are noisy; the spread says when a number
  cannot be trusted). Inside a group, previous-run **deltas are suppressed**
  (comparing overlapping noise is exactly what the spread replaces). Nothing is
  stored: no group rows in `metrics`, no composite index. `lens_sentiment` and
  `domain_stats` stay **per-run** (prose and leaderboards are not averaged); the
  dashboard shows them from the group's latest run.

---

## 3. CLI contracts — ingest, aggregate, sentiment, artifact export, report

> **All five CLIs are implemented.** This section is the authoritative contract they
> conform to. The four `pipeline.*` CLIs print a **single JSON object to STDOUT** (so
> callers can parse it); human/log noise goes to STDERR. `report.generate` (§3.6) is a
> renderer, not a JSON CLI: its product is the PDF at `--out` and STDOUT stays empty.
> Each also accepts an optional
> `--db <path>` (default `data/aeo.db`, §2) selecting the SQLite file — used by
> tests/fixtures; it changes no contract shape.

### 3.1 `python -m pipeline.ingest --brand "<name>" --domain <domain-or-url-prefix> --engine <engine> --new-run [--group-id <tag>]`

- Ensures the brand exists (`get_or_create_brand`), creates a new run
  (`create_run`) for that brand+engine.
- Optional `--group-id <tag>` stamps the new run's `runs.group_id` (§2 / §2.1
  repeat-run groups); omitted → NULL (standalone run, default). `--group-id`
  is only valid together with `--new-run`.
- **STDOUT:** `{"run_id": <int>}`

### 3.2 `python -m pipeline.ingest --run-id <N>`  (JSON array of `QueryCapture` on STDIN)

- Reads a JSON **array** of `QueryCapture` objects from STDIN.
- Validates **each** object against `pipeline.schema.QueryCapture`.
- Writes every **valid** row to `results` **idempotently** — `INSERT … ON
  CONFLICT(run_id, query, lens) DO NOTHING`: a row whose `(run_id, query, lens)` is
  already present is **skipped** (no duplicate, no metric drift), not rewritten.
  **Invalid rows do NOT abort the batch** — they are collected into `errors` so the
  **orchestrator** can fix and re-send (re-capturing via the relevant worker).
- Updates **only** `runs.n_ok`, to the live cumulative `COUNT(results for run)`. It
  does **NOT** set `n_queries`, `n_failed`, or `status` — the run stays
  `status='running'` until the **orchestrator** finalizes it (SKILL STEP 4.2 /
  §2.1). This is what lets one run be ingested **incrementally** (chunk by chunk, as
  workers return) and **resumed** after a crash.
- **STDOUT:**
  ```json
  {
    "run_id": N,
    "ok": [0, 1, 3],
    "skipped": [4],
    "errors": [
      { "index": 2, "query": "<query or null>", "field": "<field path>", "msg": "<validation message>" }
    ]
  }
  ```
  - `ok` = indices (0-based, by position in the input array) of rows **newly
    written** by this call.
  - `skipped` = indices of **valid** rows whose `(run_id, query, lens)` was
    **already present** (idempotent no-op — e.g. a retry or a resume overlap).
  - `errors` = one entry per rejected row; `index` is its position in the input
    array, `field`/`msg` come from the pydantic `ValidationError` (first error is
    sufficient). `query` echoes the offending object's `query` if present, else
    `null`.

### 3.3 `python -m pipeline.aggregate --run-id <N>`

- Reads all `results` for run `N`, computes metrics **per lens** plus one
  `lens="all"` aggregate row, writes them to `metrics`, and prints a summary.
- **STDOUT:** a JSON summary, e.g.
  ```json
  {
    "run_id": N,
    "brand_id": 1,
    "engine": "google",
    "metrics": [
      { "lens": "all", "n_queries": 30, "n_overviews": 22, "overview_coverage": 0.733,
        "n_in_sources": 9, "visibility_in_sources": 0.409,
        "n_cited": 7, "visibility_in_citations": 0.318,
        "avg_source_position": 2.4, "avg_citation_position": 1.7,
        "relative_citation": 0.778,
        "n_brand_mentions": 12, "brand_mention_rate": 0.545 },
      { "lens": "general", "...": "..." },
      { "lens": "branded", "...": "..." },
      { "lens": "comparative", "...": "..." }
    ],
    "top_domains": [
      { "domain": "g2.com", "is_brand": 0,
        "appearances_sources": 14, "appearances_citations": 6,
        "sum_min_source_rank": 25.0, "sum_min_citation_rank": 7.0,
        "avg_source_position": 1.786, "avg_citation_position": 1.167 }
    ]
  }
  ```
- A lens row is emitted only for lenses present in the run's results; the `all`
  row is always emitted.
- **`top_domains`** echoes the **`all`-scope top-10 rows of `domain_stats`** (the
  leaderboard, §2/§4.2) as a convenience slice — each entry is one `domain_stats`
  row (same fields as the table). The authoritative, per-lens leaderboard lives in
  the `domain_stats` table; this STDOUT field is just the headline `all` top-10.
- **Also writes `domain_stats` (§2/§4.2).** In the same pass `aggregate` `DELETE`s + rebuilds the
  run's `domain_stats` rows — the per-domain frequency + average-position leaderboard over **every**
  domain in `sources`/`citations`, per lens + `all`. This is deterministic and idempotent on
  re-aggregation, exactly like `metrics`.

### 3.4 `python -m pipeline.lens_sentiment --run-id <N>`  (JSON object `{lens: summary}` on STDIN)

- Reads a JSON **object** mapping `lens` → `summary` from STDIN, e.g.
  `{"all": "...", "general": "...", "branded": "...", "comparative": "..."}`. Keys are a
  subset of `{general, branded, comparative, all}`; `summary` is a string, or `null` to clear.
  Only provided lenses are written. A key **outside** that set is **silently skipped** — it is
  not written and does not appear in `written` (no error; the caller sees the omission by
  diffing `written` against what it sent).
- **Upserts** into `lens_sentiment` (§2) — one row per `run_id`+`lens` (`UNIQUE(run_id, lens)`),
  stamping `computed_at`. This is how the **orchestrator** persists the per-lens **qualitative
  synthesis** it writes at finalize (SKILL STEP 5b); the deterministic `pipeline.aggregate`
  (§3.3) never touches this table.
- **STDOUT:** `{"run_id": N, "written": ["all", "general", ...]}` — lenses written, in input order.
- Unknown `run_id` → message on STDERR, exit 1 (STDOUT carries the JSON only on success).

### 3.5 `python -m pipeline.artifact --run-id <N> [--out <file.json>]`

- Exports one run as a portable, versioned JSON document for agent-to-agent workflow
  composition. The default output is `reports/run-<N>.json`; `--out` may be an absolute path
  in the caller's workspace.
- Reads the already-persisted run only; it does not capture, mutate metrics, start a server,
  or require the dashboard frontend.
- The top-level `schema_version` is **`open-geo.run-artifact.v1`**. The payload contains:
  `run`, `brand`, `metrics` keyed by lens, `lens_sentiment`, decoded per-query `results`,
  `domain_stats` keyed by lens, and the latest matching engine-aware `audit` (or `null`).
- The file write is atomic (`tempfile` in the destination directory + `os.replace`), UTF-8,
  and pretty-printed. Downstream agents consume this file instead of scraping the human
  summary or reading SQLite directly.
- **STDOUT:**
  ```json
  {
    "schema_version": "open-geo.run-artifact.v1",
    "run_id": 42,
    "artifact_path": "/absolute/path/to/run-42.json"
  }
  ```
- Unknown `run_id` → message on STDERR, exit 1, no output artifact.

### 3.6 `python -m report.generate --brand "<name>" --domain <domain-or-url-prefix> (--engine <e> | --engines <a,b|all>) --period today|all --out <file.pdf> [--lang <code>]`

| flag | default | meaning |
|---|---|---|
| `--engine <e>` / `--engines <a,b\|all>` | — (exactly one required) | single-engine report, or the **combined multi-engine** document (`all` = every engine with completed runs for this brand). Engines get a matrix row + a chapter each; they are **never blended** into one number. |
| `--period today\|all` | — (required) | `today` = the latest completed run as a snapshot. `all` = **the whole period rolled up** (see below). |
| `--lang <code>` | `en` | UI-chrome language (`i18n/<code>.json`); unknown codes fall back to English. Captured **data** (queries, sentiment, domains, audit text) keeps its own language. |
| `--out <path>` | — (required) | output PDF. |
| `--db <path>` | `data/aeo.db` | SQLite DB (§2). |

- **`--period all` is a rollup, not "the latest run with a trend chart".** The report folds the
  brand+engine's completed runs with the **same weighted math as the dashboard API**
  (`dashboard/api.py`): ratios recomputed from summed numerators/denominators, `avg_*_position`
  as `Σ sum_min_rank / Σ appearances`, `NULL` treated as "no data" (§2 migration note). The cover
  and section 01 name how many runs were folded; the run-context line still shows the latest run.
  A report and a dashboard opened on the same brand/engine/period MUST show the same numbers.
- **Repeat groups (§2.1).** When the focus run carries a `group_id`, the report reads the group as
  **one measurement** exactly like the dashboard: metrics rolled up across the group's completed
  runs, and each KPI card carries the **min–max spread** instead of a run-over-run delta.
- **Section order is fixed** (numbered `01`…`10` in the document): cover → `01` key metrics →
  `02` breakdown by lens → `03` visibility funnel → `04` trend across runs (`--period all` only:
  by-run chart + ISO-week rollup when the period spans ≥2 weeks) → `05` top domains in answer
  space (§4.2) → `06` sentiment by lens (§3.4) → `07` **results by query** (every row of the run,
  grouped by outcome `cited → in sources, not cited → mentioned, no link → absent → no answer`,
  with per-group counts — the static equivalent of the dashboard's outcome filter) → `08`
  **gaps to close** (the `absent` subset alone) → `09` GEO-readiness audit (§7.4) → `10`
  **how to read this report** (the glossary: one `metrics.<id>.hint` formula per metric plus the
  funnel invariant `cited ⊆ in_sources ⊆ overviews ⊆ queries` — it replaces the dashboard's
  tooltips). `--engines` prepends the engine matrix and repeats `01`…`09` per engine chapter.
- **The PDF is not a subset of the dashboard.** Anything the dashboard shows for a scope has a
  static equivalent here; new report-only strings live under the `report.*` i18n namespace, the
  shared vocabulary is reused from `dashboard.*` / `audit.*` / `metrics.*` so both surfaces say
  the same thing in all four locales.
- **Exit code:** `0` on success; `1` on a resolution failure (unknown brand/domain/engine, no
  completed run); `2` when neither or both of `--engine` / `--engines` are given. Progress and
  the resolved run context go to STDERR.

---

## 4. Metric definitions & formulas

**Denominator for visibility = overview-present queries** (this is the key
modeling choice: you can only be visible where an overview rendered).

Let, within a scope (a specific lens, or `all` = across all lenses of the run):

- `n_queries`   = number of results in scope.
- `n_overviews` = results with `overview_present = 1`.
- `n_in_sources` = results (**among overview-present**) with non-empty
  `target_source_ranks`. ("Target" here means the brand's domain **or URL prefix**
  as accepted by `--domain`; see §1.2 Target matching.)
- `n_cited`     = results (**among overview-present**) with non-empty
  `target_citation_ranks`. Counts each query **once** even if the target (domain or
  URL prefix) is cited multiple times (presence, not occurrences).
- `n_brand_mentions` = results (**among overview-present**) with
  `brand_in_answer_text = 1` — the brand **name** appears in the answer prose,
  independent of any link. This is an **adjacent axis, NOT a funnel stage**: a
  brand can be mentioned without any link (unlinked mention) and linked without a
  name mention, so `n_brand_mentions` has **no subset relation** with
  `n_in_sources` / `n_cited`; the funnel inequality below is unchanged.

The model is a **funnel**. Because capture folds every cited link into `sources`
(citations ⊆ sources — the model can only cite what it retrieved; see §1), the
counts nest within any scope:

```
n_cited  ≤  n_in_sources  ≤  n_overviews  ≤  n_queries
```

Read it as: of all queries, some render an overview; of those, in some the domain
is **retrieved into `sources`** (the relied-on set); of those, in some it is
actually **cited** in the answer prose. The visible Google "sources panel" is only
a *partial* view of the retrieval set, so a domain cited in the prose but absent
from the panel is still recorded as a source — which is exactly why the funnel
holds and `n_cited` can never exceed `n_in_sources`.

> **Scope note (multi-engine).** This metric model — and especially
> `overview_present` as the **denominator gate** — was first specified against
> **Google AI Overview**, where an overview may legitimately not render. The rest
> of the contract is **engine-agnostic** (`engine` is an open id; the funnel and
> the `sources` / `citations` shapes apply to any answer engine). For
> **always-answering** chat assistants a reply alone is meaningless as a
> denominator, so the top-of-funnel gate is **reinterpreted per engine** as "a
> grounded / sourced answer rendered" rather than "an overview rendered". **This
> has landed for `chatgpt_search`, `claude_search`, `yandex_neuro`, `gemini` and
> `deepseek`** (`engines/chatgpt_search.md`, `engines/claude_search.md`,
> `engines/yandex_neuro.md`, `engines/gemini.md`, `engines/deepseek.md`), and a
> playbook has landed for **`perplexity`** too (`engines/perplexity.md`,
> grounded-answer gate, live-validated 2026-08-08):
> there `overview_present` means *the model ran a web search and rendered a sourced
> answer* (it retrieved ≥1 source and surfaced sources / inline citations) — the
> **same field, same funnel shape**
> (`n_cited ≤ n_in_sources ≤ n_overviews ≤ n_queries`), only the top-of-funnel
> reading changes, so the contract field is unchanged. The remaining engines
> are still a **backlog item —
> ROADMAP Feature 3**, each pinning its own gate when its playbook is authored.
> Where an engine's reading differs, the metric labels stay engine-neutral in the
> UI (e.g. "Answer coverage"); the formulas below are unchanged across engines.

| metric | formula | guard |
|---|---|---|
| `overview_coverage` | `n_overviews / n_queries` | `null` if `n_queries = 0` |
| `visibility_in_sources` | `n_in_sources / n_overviews` | `null` if `n_overviews = 0` |
| `visibility_in_citations` | `n_cited / n_overviews` | `null` if `n_overviews = 0` |
| `avg_source_position` | mean over in-sources queries of `min(target_source_ranks)` | `null` if `n_in_sources = 0`; lower = better |
| `avg_citation_position` | mean over cited queries of `min(target_citation_ranks)` | `null` if `n_cited = 0`; lower = better |
| `relative_citation` | `n_cited / n_in_sources` | `null` if `n_in_sources = 0`; ∈ `[0, 1]`; higher = better |
| `brand_mention_rate` | `n_brand_mentions / n_overviews` | `null` if `n_overviews = 0`; higher = better |

Notes:

- Both `avg_*_position` metrics use the **best (smallest)** rank per query
  (`min(...)` of that channel's rank array), then average those across the
  queries where the domain appears **in that channel**. Lower is better.
- **`relative_citation` is RESTORED** (reversing its earlier removal). It is the
  **source→citation conversion** — the last step of the funnel: *of the queries
  where you were retrieved into `sources`, in what share did the model actually
  cite you?* It is valid **precisely because citations ⊆ sources**, so
  `n_cited ≤ n_in_sources` and the ratio is bounded to `[0, 1]`; **higher is
  better**. (The earlier removal assumed citations ⊄ sources, reading the
  partial sources panel as the whole retrieval set — that was a UI-panel
  artifact; capture now folds cited links into `sources`, so the funnel is
  well-defined.)
- **`brand_mention_rate` surfaces the already-captured `brand_in_answer_text`** —
  before it, a brand named in the prose **without any link** was invisible in every
  aggregate (only the per-query results table showed it). It is a plain honest
  share over the same denominator as the visibility metrics (overview-present
  queries), **not** a composite index and **not** share-of-voice. Because it is an
  adjacent axis (see the `n_brand_mentions` definition above), do **not** read it
  as a funnel stage: mentioned ⊅ cited and cited ⊅ mentioned.
- **`sentiment` is QUALITATIVE** (free text, per query in `results.sentiment`).
  It is **NOT** aggregated into any *numeric* metric — there is intentionally **no
  composite index and no share-of-voice index**, and sentiment itself stays non-numeric.
  (**Competitor / top-domain modeling, previously excluded, is now provided** — but as plain
  deterministic frequency + average-position stats, **not** a composite "voice" index; see §4.2.)
  **However**, the **orchestrator** additionally writes a per-lens **qualitative
  synthesis**: one short sentence per lens (and `all`) summarizing that lens's
  per-query `sentiment`s, stored in the `lens_sentiment` table (§2) at finalize via
  `pipeline.lens_sentiment` (§3.4). This stays **text, not a number**, so it does not
  break the "no numeric" rule — it is a readout, not a score. Dashboard and report read
  **both**: the per-query `sentiment` (results table / sentiment section) **and** the
  per-lens `summary` (the dashboard's per-lens sentiment cards + the report's sentiment
  section lead).
  **Synthesis rules (orchestrator).** Summarize ONLY what the per-query `sentiment`
  strings of that lens actually say — never invent ranks, competitors, numbers, or
  praise; ~1 neutral sentence. It is **data, so it follows the language of the captured
  sentiments, not `--lang`**. If the brand appeared in no query of the lens, write `null`
  (the UI then shows a "not mentioned" fallback).

### 4.1 Deltas (computed at read-time, NOT stored)

Deltas are computed by **report/dashboard at read-time**, by comparing a run's
`metrics` to the **previous completed run** of the **same brand + engine**
(i.e. the most recent run with `status='done'` and an earlier `run_at`, matched
per `lens`). Deltas apply to `overview_coverage`, `visibility_in_sources`,
`visibility_in_citations`, `avg_source_position`, `avg_citation_position`,
`relative_citation`, and `brand_mention_rate` (for the two `avg_*_position`
deltas, remember **lower = better**, so a negative delta is an improvement).
**Do not store deltas** in any table — derive them on read.

Two scopes carry **no** run-over-run delta, on both surfaces (dashboard and PDF): a
**repeat group** shows the min–max spread instead (§2.1), and a **whole-period rollup**
(`period=all`, §3.6) is not a single run, so there is nothing to compare it against.

### 4.2 Competitor / top-domain leaderboard (`domain_stats`)

The brand's `avg_source_position` / `avg_citation_position` (§4) generalized from the one target
domain to **every** domain that shows up in the answers. **No new capture** — it reads the
`sources` / `citations` arrays already stored in `results` (each is a full ranked `Link` list, not
just the brand), so it also applies **retroactively** to existing runs on the next `aggregate`.

Scope = one lens, or `all` (across the run's lenses). Within a scope, over **overview-present
queries only** (same gate as §4), for each domain `D`:

| field | formula | meaning |
|---|---|---|
| `appearances_sources` | # queries where `D ∈ sources` (presence, once per query) | **popularity** — the default leaderboard sort key |
| `appearances_citations` | # queries where `D ∈ citations` | |
| `avg_source_position` | mean over those queries of `min(rank of D in sources)` | lower = better |
| `avg_citation_position` | mean over those queries of `min(rank of D in citations)` | lower = better |
| `share_sources` | `appearances_sources / n_overviews` | directly comparable to the brand's `visibility_in_sources` (same denominator) |
| `share_citations` | `appearances_citations / n_overviews` | comparable to `visibility_in_citations` |

`share_*` is **derived on read** (numerator from `domain_stats`, denominator `n_overviews` from
`metrics` for the same scope) — it is **not** stored. The stored `sum_min_*_rank` columns exist so
`period=all` rolls up `avg_*_position` as `Σ sum_min_rank / Σ appearances` across the period's
done runs (the same weighted-mean trick as the brand's `avg_*_position`, §3 dashboard rollup).

This is **honest "who shares the answer space with you"**, not a curated competitor set: every
domain is listed (brand-competitors *and* publishers/aggregators alike), and the brand itself is
one row (`is_brand=1`). Default leaderboard order: `appearances_sources` desc (tie-break
`appearances_citations` desc, then `domain`); the dashboard additionally lets the user re-sort the
columns. No domain is dropped silently other than the explicit top-N cap the caller asks for.

> **URL prefix and the leaderboard.** `domain_stats` aggregates by **registrable domain** (not
> prefix), but `is_brand` is decided per link, with `matches_target` — the same semantics as the
> funnel metrics. With the target `github.com/user/repo`, a `github.com` row built only from other
> people's repos is `is_brand=0`; the row is flagged only once a link under the prefix lands in it.
> Residual coarseness: when both land on the same host, the flagged row's *counts* still include
> the foreign links, because the row is one registrable domain. The funnel metrics in `metrics`
> stay exactly prefix-accurate (`target_source_ranks` / `target_citation_ranks` per §1.1). The two
> views are complementary: funnel = "does your specific page get retrieved/cited?"; leaderboard =
> "what domains share the answer space?"

---

## 5. Quick usage sketch (foundation pieces only)

```python
from pipeline.db import get_conn, init_db, get_or_create_brand, create_run
from pipeline.schema import QueryCapture, normalize_domain

conn = get_conn("data/aeo.db")
init_db(conn)
brand_id = get_or_create_brand(conn, "Example", "https://www.example.com")  # -> stores "example.com"
run_id = create_run(conn, brand_id, "google")

cap = QueryCapture.model_validate_json(some_json_string)  # raises ValidationError on bad input
```

---

## 6. The question-harvest contract — `QuestionCandidate` JSON → `questions.csv` (Feature 1)

**Question harvesting** produces the `<questions.csv>` that the run consumes (§3). It is
**agentic, not a deterministic algorithm**: a written methodology (`harvest/METHODOLOGY.md`,
the harvest counterpart of `engines/<engine>.md`) executed by **recon sub-agents** that ground
every candidate query in an **observable demand signal**, then a synthesis + adversarial-skeptic
pass. This mirrors the capture side (sub-agents + natural-language playbook) rather than the old
Wordstat/embeddings pipeline. It is a **subsystem beside the main command**, invoked from the
skill's question-sourcing step (SKILL STEP A.5); the capture contract (§1) is **unchanged** — the
harvest's only hand-off to the run is the CSV.

### 6.1 What a recon worker emits — `QuestionCandidate` JSON

A **harvest worker** covers ONE segment/angle, drives the browser to gather grounded candidates,
and **returns a JSON array of `QuestionCandidate` to the orchestrator** — a harvest worker never
writes files a run reads and never touches `data/aeo.db` (same boundary as capture-worker). Model:
`harvest/schema.py :: QuestionCandidate` (pydantic v2).

| field | type | required | meaning |
|---|---|---|---|
| `query` | string | yes | The query **as a real person would type it to an assistant** (natural, conversational — not keyword-stuffed). |
| `lens` | `"general" \| "branded" \| "comparative"` | yes | Same `Lens` vocabulary as §1. `general` = no brand named; `branded` = brand named; `comparative` = brand vs alternatives (or a niche "X vs Y" the brand should intrude on). |
| `segment` | string | yes | The audience/angle this candidate came from (e.g. `demand-inference`, `supply-side`, `branded-reputation`, `comparative-direct`) — free text, used for balance + the rationale. |
| `signal` | string | yes | The **observable evidence** this is really searched (e.g. `"google autocomplete: 'cheapest gpu cloud for'"`, `"r/LocalLLaMA thread title"`, `"People-also-ask"`). The reality guardrail — no signal ⟹ the candidate is dropped. |
| `source_url` | string | yes | A URL backing `signal` (where the pattern was observed). |
| `note` | string \| null | no (default `null`) | Optional short intent note. |

### 6.2 What the orchestrator does with them — `python -m harvest.build`

The orchestrator collects all workers' candidate arrays, **dedups by meaning** and **balances to
the target lens split** (agentic reasoning — this is the synthesis phase, not code), runs the
**skeptic** pass (KEEP/CUT), then commits the final set to CSV via the build CLI:

`python -m harvest.build --out <questions.csv> [--brand "<name>"]`
— reads a JSON **array** of `QuestionCandidate` on STDIN. (A distinct **query
language** is handled by calling `harvest.build` again with its own `--out
<name>_<code>.csv`, not a flag — the CSV language follows the candidates, SKILL
STEP A.5.)

- Validates each object against `QuestionCandidate`; **invalid rows do not abort the batch** —
  they go to `errors` (index/query/field/msg), exactly like `pipeline.ingest` (§3.2).
- **Exact/normalized dedup** — drops later candidates whose `normalize_query(query)` (lowercase,
  whitespace-collapsed, trailing-punctuation-stripped) is already present. (Meaning-level dedup is
  the orchestrator's job upstream; this is the deterministic safety net.)
- **Lens/brand guard** (when `--brand` is given, deterministic mirror of the methodology's
  invariants): a `general` candidate whose text contains the brand token, or a `branded` candidate
  whose text does **not**, is rejected into `errors` (`field="lens"`) so the orchestrator fixes the
  lens rather than shipping a mislabeled row. Brand matching (`contains_brand`) is **Unicode-aware
  and whole-word**: every whitespace-separated brand token must appear as a whole word (each token
  present for a multi-word brand), case-insensitively — so non-Latin brands (e.g. «Аскона») match
  their own script and a mere substring (`асконаленд`) does not.
- Writes the surviving rows to `--out` as a **valid `query,lens` CSV** (header `query,lens`, RFC-4180
  quoting) — **the exact input contract the run reads in SKILL STEP 2 / §3**. `segment`/`signal`/
  `source_url` are **not** in the CSV; provenance lives in the sibling `<name>_rationale.md` the
  orchestrator writes (like `gonka_questions_rationale.md`).
- **STDOUT:**
  ```json
  {
    "out": "questions.csv",
    "written": 36,
    "by_lens": { "general": 16, "branded": 10, "comparative": 10 },
    "dropped_dups": 4,
    "errors": [ { "index": 7, "query": "<q or null>", "field": "lens", "msg": "..." } ]
  }
  ```

### 6.3 Boundaries (unchanged contracts)

- The harvested CSV is a **normal `<questions.csv>`** — a user's own hand-made CSV is equally valid,
  so harvesting is **opt-in** (SKILL STEP A.5 offers own-CSV vs generate). Nothing downstream of the
  CSV changes.
- Harvest workers, like capture workers, **return JSON and clean up their own browser tabs**; the
  orchestrator owns synthesis, the skeptic pass, `harvest.build`, and writing `questions.csv` +
  `<name>_rationale.md`. See `harvest/METHODOLOGY.md` (authority for the process) and
  `.claude/agents/harvest-worker.md` / `.claude/agents/harvest-skeptic.md`.

---

## 7. The audit-gate contract — `AuditResult` JSON + `python -m audit.gate` (Feature 2)

The **Domain GEO-Audit Gate** is a fast, **deterministic (non-LLM)** readiness audit of a
domain that runs **before** a capture run (SKILL STEP 0), so the operator does not spend
capture tokens on a domain an AI engine cannot read. It grades every check by **severity** and
**hard-stops only on real blockers**; everything else is advisory. It is a **subsystem beside
the main command** (like harvest, §6): the capture contract (§1) is untouched. The **check
semantics, the AI-crawler matrix, the SSR heuristic, the score/verdict rules and the module
signatures are authoritative in `audit/CHECKS.md`**; this section is the **data shapes + CLI +
storage contract**.

### 7.1 `AuditResult` / `CheckResult` JSON

Canonical models: `audit/schema.py :: AuditResult` / `CheckResult` (pydantic v2). `score`,
`verdict`, `passed` and `blockers` are **computed** (derived from `checks`, not stored inputs);
they appear in `model_dump()` / STDOUT but are recomputed on read.

**`CheckResult`**

| field | type | meaning |
|---|---|---|
| `id` | string | check id, e.g. `A1`, `A3`, `A3b`, `B1` (see `CHECKS.md §3`). |
| `category` | `"A" \| "B" \| "C" \| "D"` | crawl-access / machine-readability / entity-trust / freshness. |
| `title` | string | short human title. |
| `severity` | `"blocker" \| "recommended" \| "nice_to_have"` | 🔴 / 🟡 / ⚪. **Only `blocker` can hard-stop.** |
| `status` | `"pass" \| "warn" \| "fail" \| "skip"` | `skip` = not applicable / not evaluable (excluded from `score`). |
| `detail` | string | what was found. |
| `remediation` | string \| null | concrete "how to fix" (a robots allow-block, a JSON-LD snippet, …); `null` on pass. |

**`AuditResult`**

| field | type | meaning |
|---|---|---|
| `target` | string | the audited target, `normalize_target` (registrable domain or URL prefix). |
| `domain` | string | registrable domain (`normalize_domain` of the target host) — the storage / report join key. |
| `engine` | string \| null | the engine the audit ran for; makes **A3 engine-aware** (`audit.bots.gating_ua`). `null` = generic (`Googlebot`). An engine with **no published search-bot UA** (`audit.bots.is_engine_mapped` false, e.g. `deepseek`) makes A3 `skip`, never `fail` — see §7.2. |
| `checked_at` | string (ISO-8601) | when the audit ran. |
| `checks` | array of `CheckResult` | every check evaluated. |
| `blockers` | array of string | *(computed)* ids of `blocker` checks that `fail`. |
| `verdict` | `"ready" \| "ready_with_warnings" \| "blocked"` | *(computed)* `blocked` iff `blockers` non-empty; else `ready_with_warnings` if any `warn`/`fail`; else `ready`. |
| `passed` | bool | *(computed)* `verdict != "blocked"`. |
| `score` | int | *(computed)* 0–100 weighted readiness readout (`CHECKS.md §1`). A **readout beside** the verdict, never the verdict itself. |

### 7.2 `python -m audit.gate --domain <domain-or-url-prefix> [flags]`

| flag | default | meaning |
|---|---|---|
| `--domain <d>` | — (required) | target: registrable domain (`example.com`) or URL prefix (`github.com/user/repo`). |
| `--engine <e>` | *(none)* | engine context → **A3 blocker is that engine's search bot** (`google`→`Googlebot`, `chatgpt_search`→`OAI-SearchBot`, …; `CHECKS.md §2`). Omitted → generic (`Googlebot`). An engine **absent from `ENGINE_GATING_UA`** (no published search-bot UA — `deepseek` today) does **not** silently fall back to `Googlebot` for grading: A3 returns `skip` (excluded from `score`, never a blocker) and A3b reports every blocked search bot instead. |
| `--no-cache` | off | force a fresh audit even if a recent one exists. |
| `--max-age <s>` | `86400` | cache TTL: reuse the latest stored audit for this `domain` if newer than this. |
| `--db <path>` | `data/aeo.db` | SQLite DB (the `audits` table doubles as history + cache). |
| `--no-db` | off | do not read or write the DB (pure stdout, e.g. throwaway/CI). |
| `--timeout <s>` | `10` | per-request HTTP timeout. |

- **STDOUT:** a single `AuditResult` JSON object (with the computed fields). Human-readable
  summary (blockers, advisory list, score, verdict) goes to **STDERR**.
- **Exit code:** `0` on any **completed** audit — the `verdict` is **data**, read it from the
  JSON (an unreachable domain is a normal `blocked` result via `A1`, not an error). `1` only on
  an operational failure (bad args / unexpected exception).
- **Persistence:** unless `--no-db`, appends one row to `audits` (§2) via `insert_audit`. Unless
  `--no-cache`, a stored audit for the same registrable `domain` newer than `--max-age` is
  **returned as-is** (no re-fetch).

### 7.3 Gate policy & where it runs (SKILL STEP 0)

- The orchestrator runs the gate **first**, right after `<domain>` is resolved (STEP A) and
  **before** question harvesting (STEP A.5) and the run (STEP 1) — no point harvesting/capturing
  against an unreadable domain.
- **`verdict == "blocked"` ⟹ hard-stop** before any run is created, printing the remediation
  (blockers + how to fix) in `--lang`, **unless** the operator passed **`--force`** (then it
  warns loudly and continues). `ready` / `ready_with_warnings` ⟹ continue; the advisory problems
  are surfaced (skill summary + the PDF section + the dashboard panel).
- The blocker set is **category A only** (can an AI engine physically read you): `A1`
  HTTPS/reachability, `A2` homepage 200, `A3` the engine's search bot not blocked in
  `robots.txt`, `A5` content in raw HTML (not JS-only). All of B/C/D is advisory. Authority for
  the exact criteria and remediation: `audit/CHECKS.md`.
- A blocker whose **premise is unknown does not block**: when the engine has no published
  search-bot UA, A3 grades nothing rather than grading the wrong bot. A false hard-stop on a
  readable site costs more trust than a missed warning (same principle as A5 warning on
  thin-but-server-rendered HTML).
- The friendly human write-up is the **skill's** job (it is already an LLM), not the gate's — the
  gate stays deterministic and only emits structured JSON (same division as `lens_sentiment`
  prose vs `aggregate` math).

### 7.4 Where it surfaces (read side)

The latest audit for a brand's registrable domain (`get_latest_audit`, §2) is read at report /
dashboard time and rendered as **an audit section in the PDF** (§3.6, section `09`) and **an
audit panel in the dashboard** — both carry verdict + score + the per-check table with severity
and remediation. In the PDF the checks are **grouped by category A/B/C/D** (blockers first,
advisory after), each row carries a **"How to fix"** column with the check's `remediation`, and
the section states the blocker list and the audit's `checked_at` date, so the report prints the
treatment and not only the diagnosis. Like the
funnel metrics, the audit is **data** — its check titles/remediation are English canon and the
UI chrome around it is localized via the i18n layer (`--lang`).
