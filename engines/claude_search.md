# Capture Playbook — Claude (claude.ai with Web search)

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
> brittle CSS/XPath; claude.ai's DOM and class names drift constantly.
>
> **This is an "always-answering" assistant — the gate is different from Google.**
> claude.ai almost always replies, so "did it reply" is meaningless as a denominator.
> The meaningful gate here is **"did Claude run a web search and render a grounded,
> sourced answer"** — see step 2 (`overview_present` reinterpreted as
> *grounded-answer present*, per `pipeline/INTERFACES.md` §4 Scope note and
> `engines/README.md`).

---

## Inputs you are given (per invocation)

- `query` — the exact string to type into the claude.ai composer. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `Example` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `example.com` or `https://www.example.com` (you will
  normalize it; see step 5).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`claude_search`** (it matches this file's basename,
`engines/claude_search.md`). Do **not** substitute `claude`, `claude_ai`, or any other
string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Locale knobs (target market ≠ UI language).** claude.ai has **no `hl`/`gl` URL
> parameters** — Claude's **answer language / market follows the ACCOUNT** (its language
> preference, region, and any custom instructions), not the URL. The English query in the
> worked example below returned a **Russian** answer because the account preference was
> Russian. So: the **TARGET MARKET = whatever the logged-in claude.ai account is configured
> for** — keep that account fixed for the whole run, and read the answer in **whatever
> language Claude actually replied in**. This is **separate** from the dashboard/report UI
> language (`--lang`). Do **not** try to force a market via the URL; there is no such knob.

> **Model & mode (pin a default, keep it fixed).** The composer shows a **model picker**
> (e.g. `Opus 4.8 High`). The answer and its sources depend on the model — **do not change
> it between queries in a run.** Use the account's **default model** and leave it as-is for
> every capture. The `QueryCapture` contract intentionally carries **no model field** (v1
> keeps the contract stable — ROADMAP Feature 3), so you do not record the model in the
> object; just keep it constant. **Web search MUST be ON and "Research" mode MUST be OFF**
> (see step 1) — those are the knobs that define this surface.

---

## Procedure

> ### Tooling — how to actually read a Claude answer (read this first)
> Claude's chrome (sidebar, composer, buttons) is in **English** regardless of the answer
> language; the **structures** are what matter and they are stable across locales: a streamed
> **answer message**, a collapsible **research/thinking trace** above it, **web-search steps**
> inside that trace (each `"<search query>" — N results`), an expandable **source-results
> popover** per search step, and **inline citation chips** (small gray pills carrying a
> publisher short-name) sitting next to sentences in the prose.
>
> **`get_page_text` is your friend here (the OPPOSITE of the Google playbook).** On
> claude.ai `get_page_text` reliably returns the **full** answer prose **and** the expanded
> research trace **and** the complete ordered **source list** (each card as `Title` + its
> `domain`) **and** the inline **citation labels** in prose order — all in one read, immune
> to the message virtualization described below. Use it as your **structural backbone**:
> read the prose, the grounded-gate signals, the ordered sources, and the ordered citation
> labels from it. (It gives **domains/labels, not full URLs** — pair it with
> `read_page(filter="interactive")` for the actual `href`s.)
>
> - **Get the href URLs → `read_page(filter="interactive")`.** Both the source-result cards
>   and the inline citation chips appear as **links with real, DIRECT `href`s** (e.g.
>   `href="https://stackpicked.com/…"`, `href="https://www.wrike.com/…"`) — **no Google-style
>   redirect wrappers**, so unwrapping is normally unnecessary.
> - **VIRTUALIZATION GOTCHA — the answer message is virtualized; the search popover is not.**
>   `read_page(filter="interactive")` only returns the inline citation chips **currently near
>   the viewport**, so a **long** answer can hide chips above/below a single read. For a long
>   answer, **scroll Claude's message top→bottom**, re-running `read_page(filter="interactive")`
>   as you go, and accumulate. **For short/medium answers one read (after scrolling to the
>   message top) usually returns all chips at once** — lean on `get_page_text`'s full ordered
>   chip list to know how many to expect, and stop once you have them all (don't grind a
>   scroll loop a short answer doesn't need). **By contrast the source-results popover is a
>   small bounded list fully present in the DOM** — one `read_page(filter="interactive")` with
>   it open returns **all N** source `href`s at once (no scrolling needed there).
> - **Detect + read prose → `get_page_text` (primary), screenshot (confirm).** A screenshot
>   is useful to confirm the answer finished streaming and to eyeball the chips/trace, but
>   `get_page_text` is the authoritative reader for the text.
> - **NEVER navigate to a cited/source website.** Every URL you need is **already on the
>   claude.ai page** — read each `href` in place from the tree. Visiting a source site is
>   always wasteful and can trip its own CAPTCHA. The chips/cards are **`link`s that open the
>   source in a new tab** — you only ever **READ their `href`**, you never click them to
>   navigate. If a click accidentally opens a source tab, **close it immediately**
>   (`tabs_close_mcp`) and re-read in place. A correct capture visits **zero** external sites.
> - **Expand before reading.** Click the collapsed **research-trace header** (the gray
>   one-line summary above the answer, e.g. *"Synthesized …"*, with a `⌄`/`›` affordance) and
>   then each search step's **"N results"** to render the source cards into the DOM **before**
>   `get_page_text` / `read_page` — collapsed, they may not be returned.

### 1. Open claude.ai, ensure Web search is ON, submit the query
- Use the connected logged-in Chrome. `navigate` to **`https://claude.ai/new`** (a fresh
  chat per query keeps captures clean and independent). Dismiss any promo modal
  (e.g. *"Meet Claude Design" → "Not now"*) and any banner overlapping the composer.
- **Ensure Web search is enabled and Research is OFF.** Open the composer's **`+`** menu
  ("Add files, connectors, and more"). On a freshly loaded `claude.ai/new` the **first** click
  on `+` may only surface its tooltip (registered as a hover) — if the menu does not open,
  **click `+` again**. **Web search** must show a checkmark (enabled). Do **not** enable
  **Research** (that is a different, long-form deep-research surface we do not measure). If Web
  search is off, click it once to enable, then re-open to confirm the check. (Web search ON /
  Research OFF persist across queries in a session, but re-verify per query.)
- Keep the **session's** account/login/locale as-is. Do **not** log out, switch account, or
  change the model — Claude's answer and its grounding depend on the account and model. The
  browser is **visible**; the human can see it.
- Click the composer, type the `query` **verbatim**, and submit (Enter). Then **wait for the
  answer to finish streaming** — Claude first runs web searches (the trace shows a spinner),
  then streams prose. Wait until the **"Retry / Copy / good-bad feedback"** action toolbar
  appears under the message (that means it is done) before reading. **Read the footer only on
  the settled answer:** mid-stream it reads *"…double-check **responses**"* and only switches
  to *"…double-check **cited sources**"* once grounding lands — so the *"cited sources"*
  wording is a reliable grounded tell **after** streaming finishes, not during it.

### 2. Detect whether a GROUNDED answer rendered → `overview_present`
This is the **denominator gate** for all visibility metrics — get it right. On claude.ai an
answer **almost always renders**, so (unlike Google's "did an overview appear?") the
meaningful gate is **"did Claude actually GROUND this answer in a web search?"** (ROADMAP
Feature 3 / INTERFACES §4 Scope note). Concretely:

> **`overview_present = true` (GROUNDED) iff** the research trace contains **≥1 web-search
> step that returned results** (a `"<query>" — N results` entry with **N ≥ 1**) **and/or**
> the answer carries **inline citation chips** / the *"double-check cited sources"* footer.
> Expand the trace to confirm. This is the **grounded-answer gate** — the Claude analogue of
> Google's "an AI Overview rendered".

Three distinct states (parallel to Google's a/b/c):

- **(a) UNGROUNDED answer.** Claude answered **from its own knowledge with no web search**
  (no search step in the trace, no citation chips, no "cited sources" footer). This is
  **normal and NOT an error** — it just means the query is **out of the visibility
  denominator** (there is no retrieved/cited surface to be visible in). Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path` stays `null`.)
- **(b) Grounded, target ABSENT.** Claude searched the web (sources retrieved), but the
  target domain/brand appears **nowhere** (not in prose, not in any source card or citation
  chip). Set `overview_present = true`, fill `answer_text_md` + `sources` + `citations` as
  they rendered, but: rank arrays `= []`, `brand_in_answer_text = false`,
  **`sentiment = null`**.
- **(c) Grounded, target PRESENT.** As (b), but the target appears in prose and/or in
  source/citation links. Fill rank arrays, set `brand_in_answer_text` accordingly, and write
  a non-null `sentiment`.

> **Landmark hints (not selectors):** the research trace is the gray collapsible block
> directly above the answer prose; web-search steps inside it read like `"best project
> management software small teams 2026" — 8 results`; the *"Please double-check cited
> sources"* footer link and the inline gray chips are grounding tells. A long answer with
> **no** trace search step and **no** chips is state (a). If the trace is collapsed, **expand
> it** (click its header) before deciding — a collapsed trace can hide the search step.

### 3. Extract `sources` — the retrieved set (the search-result cards)
- `sources` is Claude's **relied-on / retrieved set** = the **search-result cards** shown
  inside the research trace, and it **MUST include every domain you cite in step 4**
  (citations ⊆ sources; see the box after step 4).
- **Expand, then collect.** Click the **research-trace header** to expand it, then click each
  web-search step's **"N results"** to open its **source-results popover**. Then read the
  cards:
  - `get_page_text` lists them in order as `Title` + `domain` (good for order + domains).
  - `read_page(filter="interactive")` returns each card as a **link with its full direct
    `href`** — and the popover is **not virtualized**, so a single read returns **all N** at
    once. Use these `href`s for `Link.url`.
- **Dismissing the "N results" popover:** it does **not** close on `Escape` or a click in
  empty space while its search step stays in view (a stray click may even scroll the popover's
  internal list). Read all its cards first (one `read_page(filter="interactive")` gets them
  all), **then scroll the page so the research-trace step leaves the viewport** to dismiss it.
- If the answer has **multiple** web-search steps, expand **each** and collect **all** their
  cards. Record links in **display order** (search step order, then card order within each).
  **Duplicate domains are allowed** — keep every occurrence (e.g. the same publisher returned
  by two searches, or two different URLs on one domain). Do **not** dedupe and do **not**
  reorder.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches array position
  exactly.
- The `href`s are **DIRECT** (real publisher URLs), so no unwrapping is needed. Store the URL
  as read and normalize its domain.

### 4. Extract `citations` — the inline citation chips
- These are the **small gray pills** sitting next to individual statements in the answer
  prose, each carrying a **publisher short-name** (e.g. **"StackPicked"**, **"Wrike"**).
  Hovering one shows the **source article title** and an external-link arrow; its `href` is
  the **direct** source URL.
- **Read them from `read_page(filter="interactive")`** — each chip is a `link` with a direct
  `href`. The answer message is **virtualized**, so for a **long** answer scroll Claude's
  message top→bottom and re-read as you go, accumulating **every** chip `href`; for a
  **short/medium** answer one read (after scrolling to the message top) usually returns them
  all. Use `get_page_text` to know **how many** chips to expect and **in what prose order** (it
  lists every inline label in order, virtualization-proof) — then make sure your collected
  `href`s match that count and order, scrolling for more **only if** you are short.
- Order them as they appear in the prose (top-to-bottom; left-to-right within a statement).
  **Duplicates allowed** — if the same source is cited next to three different sentences, list
  it three times.
- Same `Link` shape and (no-)unwrapping as step 3. `rank` is 1-based by position **within
  `citations`** (independent of `sources` ranks).
- **Resolve, don't re-fetch.** Every cited chip corresponds to one of the **retrieved source
  cards** from step 3 (Claude cites what it searched). If you are confident of a chip's
  publisher but its `href` scrolled out of view, you may resolve its URL by matching its
  publisher/domain to the same-domain card in `sources` — **never** open the source site to
  get the URL.

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is Claude's **retrieved set** (the search-result cards); `citations`
> are the inline chips marking which retrieved source(s) back specific sentences. The model
> can only cite what it retrieved, so **every cited domain is also a source.** Therefore:
> **`sources` MUST INCLUDE every cited domain.** Collect the search-result cards fully (step
> 3) **and** the chips (step 4); then if any chip domain is **not** already present in
> `sources`, **add it to `sources`** (fold the cited link in) so the invariant holds.
> Concretely: a non-empty `target_citation_ranks` implies a non-empty `target_source_ranks`.
> (In practice the cited domains already appear among the search-result cards, e.g.
> `stackpicked.com` and `wrike.com` in the worked example are both in the 8-card retrieved
> set — but fold-in is the safety net if a chip ever lacks a matching card.)

### 5. Derive `domain` and match the TARGET
- Compute every `Link.domain` with **`normalize_domain`** semantics
  (`pipeline/schema.py`): strip scheme / userinfo / path / query / fragment / port and a
  leading `www.`, **lowercase**, keep the **registrable domain** (last two labels, e.g.
  `blog.example.com → example.com`; multi-part suffixes like `co.uk` preserved → three
  labels).
- The target is a **domain OR URL-prefix** (e.g. `example.com` or `github.com/Pupok462`).
  A link **matches the target** iff (a) its registrable domain equals the target's
  registrable domain, **and** (b) if the target has a path, the target's path segments are a
  case-insensitive **prefix** of the link URL's path segments. A target with no path keeps
  the old domain-only behaviour. If the target has a path and the link's full URL is
  unavailable (domain-only chip) or is a redirect wrapper
  (`normalize_domain(url) ≠ link.domain`), it is **NOT** a match — never silently
  over-credit. (Claude URLs are direct, so redirect wrappers are rare here.)

### 6. Compute `target_source_ranks` and `target_citation_ranks`
- Both arrays are computed **deterministically** by
  `pipeline.schema.target_ranks(links, target)` — the self-validation step
  (capture-worker instructions) overwrites whatever you put in the JSON with the
  authoritative result. You do not need to count by hand.
- `target_source_ranks` = every 1-based position in `sources` that matches the target
  (ascending); `[]` if never. `target_citation_ranks` = the same over `citations`.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is non-empty, then
  `target_source_ranks` **must** be non-empty too (you cited the target, so it is also a
  source — fold it into `sources` per step 4 if a card was missing). A cited target with empty
  `target_source_ranks` is a capture bug.

### 7. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow obvious
  transliterations / locale variants of the same name) appears **in the answer PROSE**.
- This is about the **name in the prose**, **independent of any link or chip** — the brand can
  be **named** in the recommendation text (`true`), or merely **cited as a source publisher**
  via a chip while never discussed in the prose (`false`). Judge the prose only, not the chip
  labels. (Example: an answer whose **sources** include `wrike.com` but whose prose never
  discusses Wrike-the-product → `brand_in_answer_text = false`, even though `wrike.com` is in
  `sources`/`citations`.)

### 8. Write `sentiment`
- **One short qualitative phrase**, describing **how the answer treats the target
  domain/brand** — e.g.
  `"recommended as one of the best options, named in the prose"`,
  `"mentioned neutrally among several alternatives"`,
  `"cited only as a source/review article, not discussed as a product"`
  (RU example: `"процитирован как источник-обзор, как инструмент в ответе не обсуждается"`).
- Write it in the **language Claude actually answered in** (the account's market language) so
  it reads naturally next to the answer prose.
- It is **free text**, **not** a number or label enum. It is **never** aggregated into a
  metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in `sources`, not
  in `citations`). If it appeared **anywhere**, write a non-null phrase. (Equivalently:
  `sentiment` is non-null exactly in state (c).)

### 9. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **may** take screenshots to confirm streaming finished and to eyeball the chips/trace,
  but v1 does **not** save them as artifacts.
- Set **`screenshot_path = null`** in your object. Do **not** write any file under
  `data/screenshots/...`.

### 10. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see the
  worked example below) and **return it to the orchestrator** — it collects all objects and
  ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do NOT write to the
  DB.** You may **read** `pipeline/schema.py` to self-validate first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-06-22T20:15:30Z"`); `screenshot_path
  = null`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending; empty arrays
  when `overview_present=false`; `sentiment` null-iff-absent; domains normalized; citations
  ⊆ sources).

---

## Guardrails & caveats

- **Usage limits / rate limits / bot challenges.** claude.ai enforces per-plan **message
  limits** and may rate-limit rapid sends. If you hit a **usage-limit wall**, a
  **verification / unusual-activity challenge**, or a **CAPTCHA**: **STOP**. Do **not** try to
  solve it, do **not** retry in a loop, do **not** hammer the product. Leave it **visible in
  the browser** and **surface it to the human** ("usage limit / challenge on `<query>` —
  please clear it in the open Chrome window, then tell me to continue"). Resume only after the
  human clears it. This is a **measurement** tool on a dedicated account at low volume, not a
  scraper — respect Anthropic's ToS.
- **Web search must stay ON; Research must stay OFF.** If Web search silently turned off (so
  Claude answers ungrounded), that is a legitimate **state (a)** capture — but if you intended
  a grounded run, re-check the `+` menu. Never switch on **Research** mode: it is a different
  surface and will not produce the chat-answer shape this playbook maps.
- **Selectors drift — read semantically.** Everything above (the `+` menu, the "N results"
  step, the gray chips, the research-trace header) is a **landmark hint**. Identify blocks by
  **meaning and rendered text**, not fixed CSS/XPath. The chrome is English; the **answer**
  may be any language — read the answer in whatever language it is in.
- **Captures are ACCOUNT-PERSONALIZED — claude.ai has no incognito / temporary-chat mode.**
  Unlike ChatGPT's "Temporary chat", claude.ai offers no per-chat incognito toggle, and Claude
  tailors answers to the account's **memory & preferences** (observed live: it referenced
  *"this person's profile"* and chose the account's language). So a capture reflects **this
  account**, not a neutral market. For reproducible **market** measurement, use a **dedicated
  account** with memory/personalization minimized (Settings → disable memory/preferences where
  possible) and keep it **fixed for the whole run**; otherwise treat every capture as
  account-personalized.
- **Determinism caveat.** The same query can return a different answer, different searches, or
  even ground-vs-not on repeat — Claude is non-deterministic and personalized. **Capture what
  rendered right now.** Do not regenerate hoping for a "better" answer; one honest capture per
  invocation. The UTC `captured_at` timestamps exactly what you saw.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false` is a
  **valid, expected** result (it feeds the grounded-answer rate). Never fabricate a search,
  sources, citations, or sentiment to "fill in" a capture.
- **Stay in this engine / this query.** One object per `(query, lens)`. Don't branch into
  other queries, other engines, or follow-up turns in the same chat — start a fresh
  `claude.ai/new` per query.

---

## Worked example

**Inputs:** `query = "best project management software for small teams in 2026"`,
`lens = "general"`, brand `name = "Example"`, target `domain = "https://www.example.com"`
(→ normalizes to `example.com`). Market: the account's language (here Russian — Claude
replied in Russian).

A grounded answer rendered: the research trace showed one web-search step
`"best project management software small teams 2026" — 8 results`, the answer prose discussed
several tools with inline citation chips, and the *"double-check cited sources"* footer was
present. After expanding the trace + the "8 results" popover (→ `sources`) and reading the
inline chips top-to-bottom (→ `citations`), the target domain `example.com` appeared at
**source positions 2 and 4** and **citation position 1**, and the brand name "Example" was in
the prose. Resulting single object:

```json
{
  "query": "best project management software for small teams in 2026",
  "lens": "general",
  "engine": "claude_search",
  "captured_at": "2026-06-22T20:21:30Z",
  "answer_text_md": "По обзорам начала 2026 года для маленьких команд стабильно выделяются одни и те же платформы. **Example** чаще всего называют лучшим балансом мощности и простоты...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://project-management.com/best-project-management-software-for-small-teams/", "domain": "project-management.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.paymoapp.com/blog/project-management-software/", "domain": "paymoapp.com" },
    { "rank": 4, "url": "https://example.com/blog/how-to-choose", "domain": "example.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://example.com/product/team-plan", "domain": "example.com" }
  ],
  "target_source_ranks": [2, 4],
  "target_citation_ranks": [1],
  "brand_in_answer_text": true,
  "sentiment": "рекомендован среди подходящих вариантов, назван в тексте со ссылкой на продукт"
}
```

> Contrast the other two states for the **same** query shape:
> - **State (b), grounded but no target:** `overview_present: true`, `sources`/`citations`
>   filled with whatever rendered, but `target_source_ranks: []`, `target_citation_ranks: []`,
>   `brand_in_answer_text: false`, `sentiment: null`.
> - **State (a), ungrounded (no web search):** `overview_present: false`, `answer_text_md:
>   null`, `sources: []`, `citations: []`, both rank arrays `[]`, `brand_in_answer_text:
>   false`, `sentiment: null` (`screenshot_path` stays `null`).

---

## Live audit — 2026-08-12 (scripted fast path)

> Measured by direct probe on a live answer, not inferred. Contract for using any of this:
> [`engines/FAST_PATH.md`](FAST_PATH.md). Raw results: [`bench/ENGINE_AUDIT.md`](../bench/ENGINE_AUDIT.md).
> The scripted read is a **fast path, not a trusted path** — the agent must independently confirm the
> count and spot-check domains; on disagreement discard the script output, read with the agent, and
> report the drift. An empty script result is never evidence that the answer cited nothing.

- **Sources set in one JS call: 6 of 6.** A single `javascript_tool` read returned every external
  link on the answer; scrolling the answer container top-to-bottom in three steps changed nothing
  (13 anchors at every position, accumulated set stayed at 6).
- ⚠️ **The virtualization warning in this playbook is about `read_page`, not the DOM.**
  `read_page(filter="interactive")` is viewport-limited; `javascript_tool` sees the whole DOM. The
  documented expand-trace → click "N results" → read-popup → scroll sequence exists to work around
  `read_page` and is unnecessary when the scripted read is used.
- The research-trace card rendered as documented (`… · 6 results`), and its count matched the 6
  distinct domains exactly.
