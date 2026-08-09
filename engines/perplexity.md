# Capture Playbook — Perplexity (grounded answers)

> **What this is.** A prompt for a Claude Code agent driving a **real, logged-in
> Chrome** via the Claude-in-Chrome browser tools (`mcp__claude-in-chrome__*`).
> You capture **ONE `(query, lens)`** into **exactly one `QueryCapture` JSON
> object**. The orchestrator runs you once per query and collects the objects
> into a batch array — **you do not emit the array, only your single object.**
>
> **Authoritative contract:** `pipeline/INTERFACES.md` §1 (fields, rules §1.2,
> example §1.3) and `pipeline/schema.py` (`QueryCapture`, `Link`,
> `normalize_domain`). If anything here disagrees with those, **they win.**
> Read them if unsure; do not invent fields.
>
> You are an **LLM reading rendered content**. Read the page **semantically** —
> the landmark hints below are *hints*, not selectors. Do **not** depend on
> brittle CSS/XPath; Perplexity's DOM and class names drift constantly.
>
> **Validation status (be honest).** This playbook was **authored from
> Perplexity's stable public UI** (the numbered-sources + inline-citation surface),
> following the same grounded-answer pattern already proven on `chatgpt_search`,
> `claude_search`, `yandex_neuro` and `gemini`. Its **first live-validation run**
> (the `engines/README.md` step-6 gate) is the acceptance step: on that run,
> **confirm the landmark hints against the real page and read semantically** — if a
> label or layout differs, the rendered content and the §1 contract win, not the
> exact strings here.

---

> ## ⚠️ The denominator gate is REINTERPRETED for Perplexity — read this first
>
> On **Google AI Overview** (`engines/google.md`) the gate `overview_present`
> means *"an AI Overview block rendered at all"* — it legitimately may not.
> **Perplexity is a search-first assistant: in its default Search focus it runs a
> web search and returns a sourced answer for essentially every query.** So "an
> answer rendered" is trivially true and useless as a gate.
>
> For Perplexity the gate is therefore **"did Perplexity produce a GROUNDED,
> web-sourced answer"** — i.e. did it retrieve sources and surface them as the
> **numbered Sources strip and/or inline `[N]` citation pills** (per ROADMAP
> Feature 3 + `engines/README.md` step 3, and the §4 Scope note in
> `pipeline/INTERFACES.md`). Concretely:
>
> - **Grounded** (a numbered Sources strip and/or inline `[N]` citation pills are
>   present) → **`overview_present = true`**. This is the **common case** for
>   Perplexity — it searches by default.
> - **Ungrounded** (a bare prose answer with **no** numbered sources and **no**
>   `[N]` pills) → **`overview_present = false`**, even though prose rendered. This
>   is **rare** on Perplexity (e.g. a non-web focus, a refusal, or an error state),
>   but it is a valid "not visible in search" data point, **not an error.** A model
>   that merely TYPES source names into its prose without the numbered
>   sources/`[N]` pills is **still ungrounded** — that text is model output, not a
>   real citation.
>
> The field name stays `overview_present` and the funnel is unchanged
> (`n_cited ≤ n_in_sources ≤ n_overviews ≤ n_queries`); only the **top-of-funnel
> meaning** shifts from "overview rendered" to "grounded answer rendered". Read
> `overview_coverage` for Perplexity as the **grounded-answer rate**.

---

## Inputs you are given (per invocation)

- `query` — the exact string to send to Perplexity. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `Example` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `example.com` or `https://www.example.com` (you will
  normalize it; see step 6).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`perplexity`** (it matches this file's basename,
`engines/perplexity.md`). Do **not** substitute `perplexity_ai`, `perplexity_search`,
`pplx`, or any other string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Session / locale knobs (target market ≠ UI language).** Perplexity is usable
> logged-out, but use the **connected session as configured for the market being
> tracked** — do not log out or switch account. There are **no `hl`/`gl` URL
> parameters** like Google Search: the answer language/market follows the
> **account & UI language** of the session (and, secondarily, the language you
> write the query in). The live session may render in any language; **lead with the
> rendered text in the page's actual language** and treat the English strings below
> as examples. The dashboard/report UI language (`--lang`) is a separate,
> downstream choice and does not affect capture.
>
> **Model / focus pin.** Perplexity offers a model picker and **focus modes**
> (default **Search** / **Web**, plus **Pro Search**, **Deep Research**, **Labs**,
> **Academic**, **Writing**, **Social**, …). The answer and its sources depend on
> the choice. **Pin the session default — the free default model with the default
> Search/Web focus —** and do **not** switch models or focus mid-run. In
> particular do **not** enable **Pro Search** / **Deep Research** (they change the
> retrieval depth and source set) and do **not** pick a non-web focus like
> **Writing** (which will not ground). If a run ever standardizes on another mode,
> that is an orchestrator-level decision; absent one, capture the default.

---

## Procedure

> ### Tooling — how to actually read a Perplexity answer (read this first)
> **Labels vary by locale; the structures are universal.** The structures — a
> streamed **answer prose block**, a **numbered Sources strip** of source cards at
> the top of the answer (with a **"View N sources" / "Show more" / "+N"** expander),
> and **inline `[N]` citation pills** anchored to sentences — are the same in every
> locale. English labels (match on **meaning**, not the exact string; your live
> session may render another language):
> - composer input **"Ask anything"** / **"Ask a follow-up"**
> - the **Sources** header / tab above or beside the answer, with the source cards
> - the **"View N sources"** / **"Show more"** / **"+N"** expander that reveals the
>   full retrieved set
> - inline citation pills — small numbered chips **`[1]` `[2]` `[3]`** placed after
>   statements in the prose (each maps to the correspondingly numbered source card)
> - the incognito / **Incognito thread** control (account menu) and the
>   **"New Thread"** control
> - the bottom **"Related"** follow-up questions (IGNORE these — not sources)
>
> **Expected read path (author's intent — confirm on the first live run):**
>
> - **`get_page_text` should WORK for Perplexity** — it is a normal rendered answer
>   (like ChatGPT/Gemini, unlike Google where `get_page_text` drops the AI block).
>   It returns the **full answer prose** and the **inline `[N]` markers** in reading
>   order, plus the source-card titles/domains. **Use `get_page_text` as your
>   primary read** for `answer_text_md`, for detecting whether the answer is
>   grounded, and for the ordered list of inline `[N]` citations. A **screenshot**
>   is a useful visual confirm but is not required to read the prose.
> - **The numbered Sources strip is your `sources`.** Perplexity presents the
>   retrieved set as **numbered source cards** (favicon + title + publisher domain),
>   `[1] … [N]`. **Expand it** ("View N sources" / "Show more" / "+N") so you see
>   the **complete** list, then read each card's **real `href`** via
>   **`read_page(filter="interactive")`**. Strip/card display order = your `sources`
>   rank order (rank 1 = source card 1 = citation index `[1]`).
> - **Inline `[N]` pills are your `citations`.** Each `[N]` in the prose points into
>   the numbered source list. Walk them **in prose order**; resolve each `[N]` to the
>   URL of source card `N`.
> - **URLs are DIRECT publisher URLs** (no Google-style `/url?q=` redirect
>   wrappers). Any tracking query string (e.g. `?utm_source=...`) is harmless —
>   `normalize_domain` strips the query string and `www.`, so **store the URL
>   as-is**; no unwrapping needed.
> - **NEVER click a source card or a citation pill.** A card/pill is a **link that
>   opens the source site in a NEW TAB** — that both navigates away and can litter a
>   tab the browser tools may not be able to close (a "this site is blocked" guard,
>   as on ChatGPT). **Every URL you need is already on the Perplexity page — read
>   its `href` from the interactive tree in place.** If a click accidentally opens a
>   tab, switch back to your Perplexity tab and carry on reading in place; do **not**
>   visit, read, or "study" the source site.
> - **A correct capture is ~6–12 tool calls with ZERO navigation away from
>   Perplexity** (bar the one expander click on the Sources strip, which stays on
>   the page).

### 1. Open Perplexity, pin a clean grounded session, submit the query
- Use the connected logged-in Chrome. Get tab context (`tabs_context_mcp`) and work
  in **your own tab**; `navigate` to `https://www.perplexity.ai/`. Keep the
  account/locale **as configured for the market being tracked** — do not change the
  account or UI language.
- **Prefer an Incognito thread** (Perplexity's analog of ChatGPT's Temporary chat):
  it keeps the run out of the user's thread history and disables
  personalization/memory, giving more neutral, reproducible captures. If Incognito
  is unavailable, use a plain **New Thread**. Never open, read, or reuse the user's
  existing threads.
- **Pin the default focus/model.** Leave the focus on the default **Search / Web**
  (do **not** enable Pro Search / Deep Research / Labs / Academic / Writing). Leave
  the model on the session default.
- **Start a fresh thread for THIS query.** Perplexity threads carry follow-up
  context, so each `(query, lens)` must be its **own** thread (`New Thread` /
  navigate to the home composer) — otherwise the previous question bleeds into this
  answer.
- Type the `query` **verbatim** into the composer and submit. **Wait for streaming
  to finish** — the answer streams in; wait until it settles (the stop control
  reverts to idle and the Sources strip + `[N]` pills are rendered). Read only the
  settled answer.

### 2. Detect whether a GROUNDED answer rendered → `overview_present` (the gate)
This is the **denominator gate** for all visibility metrics — get it right, and per
the box at the top it means **"a GROUNDED answer rendered"** for Perplexity. Detect
from the settled page: grounding is present iff there is a **numbered Sources strip**
(one or more source cards) **and/or** inline **`[N]` citation pills** in the prose.
Read `get_page_text` (inline `[N]` markers + source titles) and confirm with a
screenshot.

Three distinct states:

- **(a) Ungrounded answer (no sources / no `[N]`).** Prose rendered but there are
  **no numbered source cards and no `[N]` pills** anywhere. Rare on Perplexity, but
  **normal and NOT an error** — a valid "not visible in search" data point. Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path` stays `null`.)
- **(b) Grounded answer, target ABSENT.** Sources/citations rendered, but the target
  domain/brand appears **nowhere** (not in prose, not in any source card or `[N]`).
  Set `overview_present = true`, fill `answer_text_md` + `sources` + `citations` as
  they rendered, but: rank arrays `= []`, `brand_in_answer_text = false`,
  **`sentiment = null`**.
- **(c) Grounded answer, target PRESENT.** As (b), but the target appears in prose
  and/or in links. Fill rank arrays, set `brand_in_answer_text` accordingly, and
  write a non-null `sentiment`.

> **Landmark hint (not a selector):** grounding on Perplexity is the **numbered
> Sources strip** of source cards plus the inline **`[N]`** pills. A model-typed
> source name in the prose with **no** numbered card / **no** `[N]` pill is **not**
> grounding → state (a). Do **not** reroll hoping for a "more grounded" answer —
> capture what rendered once (see Guardrails).

### 3. Extract `sources` — the full retrieved set (the numbered Sources strip)
- `sources` is the answer's **relied-on / retrieved set** — and it **MUST include
  every domain you cite in step 4** (citations ⊆ sources; see the box after step 4).
  On Perplexity the retrieved set is the **numbered Sources strip** of source cards.
- **Expand the strip to the complete set.** `find` the **"View N sources" / "Show
  more" / "+N"** expander and `left_click` it (it is a real **button/expander** on
  the page, not a source link) so the full card list is visible. If the list
  scrolls, scroll it and re-read until no new cards appear.
- **Collect via `read_page(filter="interactive")`.** Each card is a link with a real
  `href`. Record links in the **strip's display order** (card 1 → card N), which is
  the same numbering the inline `[N]` pills reference.
- **Duplicate domains are allowed** — keep every occurrence (a publisher can back
  several statements / appear as several cards). Do **not** dedupe and do **not**
  reorder.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches array
  position exactly (so `sources[k]` has `rank = k+1`, corresponding to citation
  index `[k+1]`).
- **Store the URL as rendered** (direct publisher URL incl. any tracking query
  param). No redirect-unwrapping is needed; `normalize_domain` handles the query
  string and `www.`. **Never click a card to "get" a URL** — read its `href` in
  place.

### 4. Extract `citations` — the inline `[N]` pills in the prose
- These are the **inline numbered pills** (`[1]`, `[2]`, …) sitting next to
  statements in the answer prose. In `get_page_text` they appear inline as `[N]`
  markers in reading order. Walk them **top-to-bottom**.
- **Resolve each `[N]` to a URL via the Sources strip.** `[N]` indexes the numbered
  source cards from step 3, so `[N]` → the URL of `sources`-card `N`. Read that URL
  from the strip (which you already have in the interactive tree) — **do not click
  the pill** (clicking opens the source site in a possibly-unclosable tab).
- Record one `Link` per pill occurrence, **in prose order**. **Duplicates allowed** —
  if the same `[N]` is cited at two places, list it twice; if a sentence carries
  `[2][5]`, record both in left-to-right order. Same `Link` shape and same URL
  handling as step 3. `rank` is 1-based by position **within `citations`**
  (independent of `sources` ranks).

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is the answer's **relied-on / retrieved set**; `citations`
> are the inline `[N]` pills marking which source backs a given sentence. The model
> can only cite what it retrieved, and on Perplexity each `[N]` **is** an index into
> the numbered Sources strip — so **every cited domain is also a source by
> construction.** Still verify: **any domain in `citations` MUST also appear in
> `sources`**, and a non-empty `target_citation_ranks` therefore implies a non-empty
> `target_source_ranks`. (The `QueryCapture` validator rejects a citation domain
> absent from sources.) If a pill somehow resolves to a domain not in `sources`, add
> it to `sources` so the invariant holds.

### 5. Derive `domain` and match the TARGET
- Compute every `Link.domain` with **`normalize_domain`** semantics
  (`pipeline/schema.py`): strip scheme / userinfo / path / query / fragment / port
  and a leading `www.`, **lowercase**, keep the **registrable domain** (last two
  labels, e.g. `blog.example.com → example.com`; multi-part suffixes like `co.uk`
  preserved → three labels). Any tracking query string is stripped automatically.
- The target is a **domain OR URL-prefix** (e.g. `example.com` or
  `github.com/Pupok462`). A link **matches the target** iff (a) its registrable
  domain equals the target's registrable domain, **and** (b) if the target has a
  path, the target's path segments are a case-insensitive **prefix** of the link
  URL's path segments. A target with no path keeps the old domain-only behaviour. If
  the target has a path and the link's full URL is unavailable or is a redirect
  wrapper (`normalize_domain(url) ≠ link.domain`), it is **NOT** a match — never
  silently over-credit. (Perplexity URLs are direct, so redirect wrappers are rare
  here.)
- **A brand-adjacent label or URL path on a DIFFERENT domain is NOT a match.** A
  mention of the brand name in a card's display title or in a URL path does NOT
  cause a match unless the link's **registrable domain** matches the target's.
  Always read the `href` and run `normalize_domain` on it — never match on a card's
  display name.

### 6. Compute `target_source_ranks` and `target_citation_ranks`
- Both arrays are computed **deterministically** by
  `pipeline.schema.target_ranks(links, target)` — the self-validation step
  (capture-worker instructions) overwrites whatever you put in the JSON with the
  authoritative result. You do not need to count by hand.
- `target_source_ranks` = every 1-based position in `sources` that matches the
  target (ascending); `[]` if never. `target_citation_ranks` = the same over
  `citations`.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is
  non-empty, `target_source_ranks` **must** be non-empty too. A cited target with
  empty `target_source_ranks` is a capture bug — fix it by folding the cited link
  into `sources` (step 3).

### 7. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow obvious
  transliterations / locale variants of the same name) appears **in the answer
  prose**.
- This is about the **name in text**, **independent of any link** — the brand can be
  named with no link (`true`), or cited via a `[N]` pill but never named in prose
  (`false`). Judge the prose only.

### 8. Write `sentiment`
- **One short qualitative phrase** describing **how the answer treats the target
  domain/brand** — e.g. `"recommended as a top pick for small teams, cited with a
  direct link"`, `"mentioned neutrally among 6 options"`, `"named, but with a caveat
  about setup complexity"` (RU example: `"упомянут нейтрально среди 6 вариантов"`).
- Write it in the **tracked market's language** (the language the answer rendered
  in) so it reads naturally next to the answer prose.
- It is **free text**, **not** a number or label enum, and is **never** aggregated
  into a metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in
  `sources`, not in `citations`). If it appeared **anywhere**, write a non-null
  phrase. (Equivalently: `sentiment` is non-null exactly in state (c).)

### 9. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **may** take screenshots to visually confirm the answer, but v1 does **not**
  save them as artifacts (and `get_page_text` already reads the answer, so a
  screenshot is optional). Set **`screenshot_path = null`** in your object. Do
  **not** write any file under `data/screenshots/...`.

### 10. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see
  the worked example below) and **return it to the orchestrator** — it collects all
  objects and ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do
  NOT write to the DB.** You may **read** `pipeline/schema.py` to self-validate
  first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-07-08T20:15:30Z"`);
  `screenshot_path = null`; `engine = "perplexity"`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending;
  empty arrays when `overview_present=false`; `sentiment` null-iff-absent; domains
  normalized; citations ⊆ sources).

---

## Guardrails & caveats

- **Login wall / rate-limit / anti-bot.** If Perplexity shows a **login/signup
  wall**, a **usage-cap** notice (e.g. a Pro-only / "you've reached your limit"
  interstitial), a Cloudflare / "verify you are human" challenge, or any
  interstitial: **STOP**. Do **not** attempt to solve it, log in, switch accounts,
  or retry in a loop. Leave the challenge **visible in the browser** and **surface
  it to the human** ("limit/CAPTCHA on `<query>` — please resolve it in the open
  Chrome window, then tell me to continue"). Resume only after the human clears it.
  Other workers keep going.
- **NEVER click a source card or a citation pill.** They open the source site in a
  new tab that may be **un-closable** via the browser tools. Read every URL's `href`
  in place. The only click you make on the answer is the **Sources-strip expander**
  ("View N sources" / "Show more"), which stays on the Perplexity page. If a source
  link opens by accident, switch back to your Perplexity tab and continue — never
  read the source site.
- **Do NOT switch focus/model, and IGNORE follow-ups.** Stay on the default
  Search/Web focus and default model. Do **not** click the **"Related"** follow-up
  questions, and do **not** ask a follow-up in the same thread — one thread, one
  `(query, lens)`.
- **Selectors drift — read semantically.** Everything above (the Sources strip, the
  "View N sources" expander, the `[N]` pills, Incognito thread, New Thread, Related)
  is a **landmark hint**. Identify blocks by **meaning and rendered text**, not fixed
  CSS/XPath. **Labels are locale-dependent** — match on intent.
- **Determinism caveat.** The same query can return a different answer (or a
  different source set) on repeat — Perplexity is non-deterministic. An Incognito
  thread reduces personalization, but **capture what rendered right now.** Do not
  regenerate hoping for a "better" answer; one honest capture per invocation. The
  UTC `captured_at` timestamps exactly what you saw.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false`
  is a **valid, expected** (if rare) result — it feeds the grounded-answer rate.
  Never fabricate sources, citations, or sentiment to "fill in" a capture, and never
  promote a model-typed source name into real `sources`/`citations` — only the
  numbered cards / `[N]` pills count.
- **ToS / volume.** Capture is a **measurement** at low volume via visible
  Claude-in-Chrome (not headless, not the API — the API answer is a different
  surface from the consumer UI we measure). Review Perplexity's ToS before any
  volume, use a dedicated account, and keep the rate low.
- **Stay in this engine / this query.** One object per `(query, lens)`. Don't branch
  into other queries, focuses, models, or engines. Don't touch the user's existing
  threads.

---

## Worked example

**Inputs:** `query = "best project management software for small teams"`, `lens = "general"`,
brand `name = "Example"`, target `domain = "https://www.example.com"` (→ normalizes to
`example.com`). Session: logged-in, Incognito thread, default Search/Web focus.

A grounded answer rendered. The numbered Sources strip listed several review sites plus
the target twice (cards 2 and 4); the prose cited source `[2]` inline once and named
"Example". Resulting single object:

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "perplexity",
  "captured_at": "2026-07-08T20:15:30Z",
  "answer_text_md": "For a small team, the best tool is the one your team will actually keep updated. **Example** is frequently recommended for its clean task board and simple workflows[2]...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.reddit.com/r/SaaS/comments/abc123/best_pm_software/", "domain": "reddit.com" },
    { "rank": 4, "url": "https://example.com/blog/how-to-choose", "domain": "example.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://example.com/product/team-plan", "domain": "example.com" }
  ],
  "target_source_ranks": [2, 4],
  "target_citation_ranks": [1],
  "brand_in_answer_text": true,
  "sentiment": "recommended among suitable options, named with a direct link to the product"
}
```

> Contrast the other two states for the **same** query shape:
> - **State (b), grounded but no target:** `overview_present: true`, `sources`/`citations`
>   filled with whatever rendered, but `target_source_ranks: []`, `target_citation_ranks: []`,
>   `brand_in_answer_text: false`, `sentiment: null`.
> - **State (a), ungrounded (no numbered sources / no `[N]` pills):** `overview_present: false`,
>   `answer_text_md: null`, `sources: []`, `citations: []`, both rank arrays `[]`,
>   `brand_in_answer_text: false`, `sentiment: null` (`screenshot_path` stays `null`). A
>   model-typed source name in the prose does **not** change this — without numbered
>   cards / `[N]` pills it is ungrounded.
