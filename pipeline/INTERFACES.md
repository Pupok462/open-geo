# open-geo — Pipeline Interfaces (the contract for all downstream agents)

> This is the **single source of truth** that every other agent (capture,
> ingest, aggregate, report, dashboard, skill) builds against. The shapes here
> are authoritative. Code identifiers are guaranteed English; user-facing
> docs/reports/UI are **English by default and localized via the i18n layer**
> (`--lang`, `i18n/<code>.json`) — but THIS file is English so all agents read
> it identically.
>
> **All of the following are implemented:** `pipeline/schema.py`,
> `pipeline/db.py`, the `python -m pipeline.ingest` and
> `python -m pipeline.aggregate` CLIs, the PDF report (`report.generate`), and
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
| `engine` | string | yes | Engine id, snake_case — the orchestrator's `<engine>` argument **copied through verbatim** (it equals the capture playbook basename, e.g. `google` ↔ `engines/google.md`); do not hardcode a different value. **Open string by design** — this is the multi-engine extension point: one `engines/<engine>.md` playbook per engine, and supporting more (ChatGPT, Gemini, Claude, Perplexity, Yandex, DeepSeek, …) is a backlog item (ROADMAP Feature 3). |
| `captured_at` | string (ISO-8601 datetime) | yes | When the answer was captured. Parsed by pydantic into `datetime`. Use UTC, e.g. `"2026-06-18T20:15:30Z"`. |
| `answer_text_md` | string \| null | no (default `null`) | The answer prose as Markdown. `null` if no overview / not captured. |
| `screenshot_path` | string \| null | no (default `null`) | **v1: always `null`.** A *transient* screenshot may be taken to read the overview, but screenshots are **not persisted**, so nothing is stored here (column kept for forward-compat). |
| `overview_present` | bool | yes | Did an AI Overview actually render for this query? This is the **denominator gate** for visibility metrics. |
| `sources` | array of `Link` | no (default `[]`) | The **relied-on / retrieved set** — every link the model drew on, in display order, **duplicate domains allowed**. This **includes every cited domain**: fold any inline-cited link into `sources` (the visible Google "sources panel" is only a *partial* view of the retrieval set, so a domain cited in the prose but missing from the panel is still a source). |
| `citations` | array of `Link` | no (default `[]`) | Links **attached / cited** in the answer prose, in order, duplicates allowed. Citations are a **subset of `sources`** (the model can only cite what it retrieved) — every domain here MUST also appear in `sources`. |
| `target_source_ranks` | array of int | no (default `[]`) | **ALL** 1-based positions of the target domain within `sources`. `[]` if the target never appears in sources. |
| `target_citation_ranks` | array of int | no (default `[]`) | Same, but for `citations`. |
| `brand_in_answer_text` | bool | yes | Was the brand **NAME** mentioned in the prose, independent of any link? |
| `sentiment` | string \| null | no (default `null`) | Short **qualitative** text describing how the answer treats the target domain (e.g. `"recommended as top pick"`, `"mentioned neutrally among 5 options"`). **`null` if the domain/brand did not appear at all.** This is free text, NOT a number. |

`Link` object:

| field | type | meaning |
|---|---|---|
| `rank` | int | 1-based position in its ordered list (`sources` or `citations`). |
| `url` | string | The full URL. |
| `domain` | string | Registrable domain, **lowercased, no `www`**. Produce it with `pipeline.schema.normalize_domain(url)`. |

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
  existing table** (`ALTER TABLE … ADD COLUMN`; currently `metrics.relative_citation`).
  Safe to call on every startup: it both initializes a fresh DB and forward-migrates an
  older one in place (existing rows read `NULL` for a newly added column until re-aggregated).
- Arrays / nested objects are stored as **JSON strings** in `*_json` columns.

### Tables

**`brands`**

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT | brand name |
| `domain` | TEXT | normalized registrable domain |
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
| `computed_at` | TEXT | ISO-8601 |

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
| `is_brand` | INTEGER | 0/1 — `1` for the run's own brand domain (so the UI can highlight the brand's row in the leaderboard) |
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

### DB helpers provided by `pipeline/db.py`

- `get_conn(db_path="data/aeo.db") -> sqlite3.Connection`
- `init_db(conn) -> None`
- `get_or_create_brand(conn, name, domain) -> int` (normalizes `domain`)
- `create_run(conn, brand_id, engine) -> int` (status `'running'`)
- `update_run_counts(conn, run_id, n_queries=?, n_ok=?, n_failed=?, status=?) -> None`
- `upsert_lens_sentiment(conn, run_id, lens, summary) -> None` (replaces the row for that `run_id`+`lens`; `summary=None` clears it)
- `get_lens_sentiments(conn, run_id) -> dict[str, str]` (lens → summary; returns `{}` if the `lens_sentiment` table is absent)
- `get_domain_stats(conn, run_id, lens="all") -> list[dict]` (the leaderboard rows for one run+lens, ordered by `appearances_sources` desc; returns `[]` if the `domain_stats` table is absent)
- `get_captured_keys(conn, run_id) -> set[tuple[str, str]]` (the `(query, lens)` pairs already in `results` for the run — the resume diff source)
- `find_unfinished_run(conn, brand_id, engine) -> int | None` (most recent `status='running'` run for that brand+engine — the crashed run to resume, or `None`)

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

---

## 3. CLI contracts — `pipeline.ingest` and `pipeline.aggregate`

> **Both CLIs are implemented.** This section is the authoritative contract they
> conform to. All CLIs print a **single JSON object to STDOUT** (so callers can
> parse it); human/log noise goes to STDERR.

### 3.1 `python -m pipeline.ingest --brand "<name>" --domain <domain> --engine <engine> --new-run`

- Ensures the brand exists (`get_or_create_brand`), creates a new run
  (`create_run`) for that brand+engine.
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
        "relative_citation": 0.778 },
      { "lens": "general", "...": "..." },
      { "lens": "branded", "...": "..." },
      { "lens": "comparative", "...": "..." }
    ]
  }
  ```
- A lens row is emitted only for lenses present in the run's results; the `all`
  row is always emitted.
- **Also writes `domain_stats` (§2/§4.2).** In the same pass `aggregate` `DELETE`s + rebuilds the
  run's `domain_stats` rows — the per-domain frequency + average-position leaderboard over **every**
  domain in `sources`/`citations`, per lens + `all`. This is deterministic and idempotent on
  re-aggregation, exactly like `metrics`.

### 3.4 `python -m pipeline.lens_sentiment --run-id <N>`  (JSON object `{lens: summary}` on STDIN)

- Reads a JSON **object** mapping `lens` → `summary` from STDIN, e.g.
  `{"all": "...", "general": "...", "branded": "...", "comparative": "..."}`. Keys are a
  subset of `{general, branded, comparative, all}`; `summary` is a string, or `null` to clear.
  Only provided lenses are written.
- **Upserts** into `lens_sentiment` (§2) — one row per `run_id`+`lens` (`UNIQUE(run_id, lens)`),
  stamping `computed_at`. This is how the **orchestrator** persists the per-lens **qualitative
  synthesis** it writes at finalize (SKILL STEP 5b); the deterministic `pipeline.aggregate`
  (§3.3) never touches this table.
- **STDOUT:** `{"run_id": N, "written": ["all", "general", ...]}` — lenses written, in input order.
- Unknown `run_id` → message on STDERR, exit 1 (STDOUT carries the JSON only on success).

---

## 4. Metric definitions & formulas

**Denominator for visibility = overview-present queries** (this is the key
modeling choice: you can only be visible where an overview rendered).

Let, within a scope (a specific lens, or `all` = across all lenses of the run):

- `n_queries`   = number of results in scope.
- `n_overviews` = results with `overview_present = 1`.
- `n_in_sources` = results (**among overview-present**) with non-empty
  `target_source_ranks`.
- `n_cited`     = results (**among overview-present**) with non-empty
  `target_citation_ranks`. Counts each query **once** even if the domain is
  cited multiple times (presence, not occurrences).

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
> `overview_present` as the **denominator gate** — is specified against **Google
> AI Overview**, where an overview may legitimately not render. The rest of the
> contract is **engine-agnostic** (`engine` is an open id; the funnel and the
> `sources` / `citations` shapes apply to any answer engine). Extending capture to
> other engines (ChatGPT, Gemini, Claude, Perplexity, Yandex, DeepSeek, …) is a
> **backlog item — ROADMAP Feature 3**. For always-answering chat assistants the
> top-of-funnel gate is expected to be **reinterpreted** (e.g. "a grounded /
> sourced answer rendered" rather than "an overview rendered"); until that lands,
> the definitions below describe the Google surface.

| metric | formula | guard |
|---|---|---|
| `overview_coverage` | `n_overviews / n_queries` | `null` if `n_queries = 0` |
| `visibility_in_sources` | `n_in_sources / n_overviews` | `null` if `n_overviews = 0` |
| `visibility_in_citations` | `n_cited / n_overviews` | `null` if `n_overviews = 0` |
| `avg_source_position` | mean over in-sources queries of `min(target_source_ranks)` | `null` if `n_in_sources = 0`; lower = better |
| `avg_citation_position` | mean over cited queries of `min(target_citation_ranks)` | `null` if `n_cited = 0`; lower = better |
| `relative_citation` | `n_cited / n_in_sources` | `null` if `n_in_sources = 0`; ∈ `[0, 1]`; higher = better |

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
`visibility_in_citations`, `avg_source_position`, `avg_citation_position`, and
`relative_citation` (for the two `avg_*_position` deltas, remember **lower =
better**, so a negative delta is an improvement). **Do not store deltas** in any
table — derive them on read.

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
