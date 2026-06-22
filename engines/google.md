# Capture Playbook — Google AI Overviews

> **What this is.** A prompt for a Claude Code agent driving a **real, logged-in
> Chrome** via the Claude-in-Chrome browser tools (`mcp__Claude_in_Chrome__*`).
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
> brittle CSS/XPath; Google's DOM and class names drift constantly.

---

## Inputs you are given (per invocation)

- `query` — the exact string to type into Google. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `Example` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `example.com` or `https://www.example.com` (you will
  normalize it; see step 5).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`google`** (it matches this file's basename, `engines/google.md`).
Do **not** substitute `google_ai_overview` or any other string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Locale knobs (target market ≠ UI language).** The search URL's **`hl`**
> (interface language) and **`gl`** (country) set the **TARGET MARKET** — *which
> country/language edition of Google you query* — and should **match the market
> being tracked** (e.g. `hl=en&gl=us` for the US, `hl=ru&gl=ru` for Russia). This
> is **separate** from the dashboard/report UI language (`sentiment` aside, that's
> a downstream choice). The examples below default to an **English market
> (`hl=en&gl=us`)**, but this is **configurable per market** — set `hl`/`gl` to
> whichever market you are tracking, and read the page in **that** locale's
> language.

---

## Procedure

> ### Tooling — how to actually read the overview (read this first)
> **Labels vary by locale; the structures are universal.** Google AI Overview labels
> depend on the search locale (`hl`/`gl`). The **structures** — an **AI-Overview block**,
> **inline citation chips**, a **sources panel**, and **`+N` expanders** — are the same
> in every locale. **Lead with the rendered text in the page's actual language** and
> treat the specific strings below as **examples**. English labels (with one Russian
> example each, marked `RU:`):
> - block header **"AI Overview"** (RU: "Обзор от ИИ" / "AI-обзор")
> - expanders **"Show more"** / **"Show all"** (RU: "Показать ещё" / "Показать все похожие ссылки")
> - sources-panel button **"N sites"** (RU: "N сайтов")
> - inline citation chip **"<Name> (+N), see related links"** (RU: "<Name> (+N), посмотреть ссылки по теме")
> - prose expander **"Expand AI summary"** (RU: "Развернуть краткий пересказ от ИИ")
>
> Match whatever locale the page is actually in — do not assume English strings if you
> queried a non-English market.
>
> **Verified live against a real logged-in session:** `get_page_text` **silently
> drops the AI Overview block** — on a query that visibly rendered an AI Overview ("AI
> Overview"; RU: "Обзор от ИИ"), it returned only the organic results and zero overview
> content. **Do NOT use `get_page_text` for the AI Overview** — neither to detect it nor
> to read its prose; it will make you wrongly set `overview_present=false`. Use a
> **screenshot** to detect the block and read the prose, and
> **`read_page(filter="interactive")`** to collect the source/citation links (it returns
> them as links with real `href`s).
>
> - **Detect + read prose → `computer` (action=screenshot).** A screenshot shows the
>   "✦ AI Overview" header (RU: "✦ Обзор от ИИ"), the prose, the inline citation chips,
>   and the right-side sources panel. Confirm `overview_present` and read `answer_text_md`
>   from it.
> - **Collect sources/citations → `read_page(filter="interactive")`** (plus `find`). It
>   reliably returns the overview's source/citation elements as links with real `href`s —
>   e.g. an inline chip link `"Example (+1), see related links"` (RU example:
>   `"Орма Мебель (+1), посмотреть ссылки по теме"`) href=`https://example.com/…`, and
>   sources-panel cards href=`https://example.com/…`, href=`https://review-site.com/…`.
>   A `"(+N)"` on a chip means **N more sources hide behind it.**
>   **Every URL you need is already on the Google page — just READ its `href` from the
>   tree. You never have to visit a source site to get its link.**
> - **NEVER navigate to a cited/source website.** Visiting source sites is *always*
>   wasteful and trips their own CAPTCHAs (e.g. an agent landed on a review site's "Are
>   you a robot?" block; runs ballooned to 40–65 tool calls / ~12 min). A correct capture
>   is **~6–10 tool calls with ZERO navigation away from Google.** If a click accidentally
>   leaves Google or pops a new tab to a source site, **close that tab / go back
>   immediately** and re-read via `read_page` — never proceed on, read, or "study" a source
>   site. **Collect every URL by reading its `href` in place;** opening a source URL is a
>   last-resort fallback only if a URL genuinely cannot be read in place (it almost never
>   can't).
> - **Click only the `button` form, never the `link` form.** In the interactive tree each
>   item exposes **two** forms: a **`link`** that *navigates to the source site* and a
>   **`button`** that *expands in place*. Click **only `button`s** — the **"N sites"** (RU:
>   "N сайтов") button and a chip's **`button`** form (e.g. ref for `"Example (+3)…"`
>   **button**, not its `link`). **NEVER click the source `link`/card** ("…opens in a new
>   tab"; RU: "Страница откроется в новой вкладке") or a chip's `link` — those open the
>   source site, trip its captcha, and lose your place. For source cards you only ever
>   **read** their `href`; you never click them.
> - **Expand before collecting.** Buttons like **"N sites"** (e.g. "8 sites"; RU: "N
>   сайтов" / "8 сайтов"), **"Show all"** (RU: "Показать все похожие ссылки"), the
>   **`"(+N)"` chip** (its `button` form), and the prose **"Expand AI summary"** (RU:
>   "Развернуть краткий пересказ от ИИ") reveal the full set. Click each via `computer`
>   `left_click` using the element `ref` from `read_page`/`find`, **then re-run
>   `read_page(filter="interactive")`** to gather all revealed links.
> - **The "N sites" (RU: "N сайтов") panel opens IN PLACE (a popover) — scroll it to the
>   bottom.** `read_page` often exposes only the first few source cards at a time. After
>   opening the panel, **scroll the popover down and re-read until no new cards appear**,
>   collecting **all N** cards (the "N sites" label tells you how many to expect). **Do not
>   stop at the first 3–4 visible cards** — that under-captures `sources` and makes real
>   citations look like they aren't in the panel.
> - **URLs are frequently DIRECT** (e.g. `example.com`, `example.com`), not Google redirect
>   wrappers — so unwrapping is often unnecessary, but still unwrap when a link *is*
>   wrapped (see steps 3–4).

### 1. Open Google and submit the query
- Use the connected logged-in Chrome (e.g. `navigate` to
  `https://www.google.com/search?q=<url-encoded query>&hl=en&gl=us`, or open
  `google.com` and type the query into the search box, then submit). Set
  **`hl`/`gl` to the market being tracked** (`hl=en&gl=us` shown as the default;
  configurable per market — see the **Locale knobs** note above).
- Keep the **session's** locale/login as-is. Do **not** open incognito, do
  **not** log out, do **not** change the Google account — AI Overviews depend on
  who is logged in and the locale. The browser is **visible**; the human can see
  it.
- Give the page a moment to settle. AI Overviews often **stream in after** the
  blue links — wait until the overview block stops growing before reading. Then
  read it with the tools from the **Tooling** note above: **a screenshot** for the
  prose and **`read_page(filter="interactive")`** for the links. **Do not use
  `get_page_text` for the overview** — it drops the block.

### 2. Detect whether an AI Overview actually rendered → `overview_present`
This is the **denominator gate** for all visibility metrics — get it right.
**Detect from a screenshot, not `get_page_text`** (which drops the overview and
would falsely yield state (a) / `overview_present=false`). Detect the block by its
**structure in any locale** (boxed answer at the top with inline citation chips and
a sources panel), matching the **page's actual language** — not a fixed string.

Three distinct states:

- **(a) No overview rendered.** There is no AI Overview block at all (only the
  normal organic results / ads / "people also ask"). This is **normal and NOT an
  error.** Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still note state (a): fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path`
    stays `null`.)
- **(b) Overview rendered, target ABSENT.** An AI Overview block is present, but
  the target domain/brand appears **nowhere** (not in prose, not in any source
  or citation link). Set `overview_present = true`, fill `answer_text_md` +
  `sources` + `citations` as they rendered, but: rank arrays `= []`,
  `brand_in_answer_text = false`, **`sentiment = null`**.
- **(c) Overview rendered, target PRESENT.** As (b), but the target appears in
  prose and/or in links. Fill rank arrays, set `brand_in_answer_text`
  accordingly, and write a non-null `sentiment`.

> **Landmark hints (not selectors):** the AI Overview is the boxed answer block,
> usually at the very top, often labelled **"AI Overview"** (RU: "Обзор от ИИ" /
> "AI-обзор"), sometimes behind a **"Show more"** expander (RU: "Показать
> подробнее"), and may carry a "Generative AI is experimental" note (RU:
> "Сгенерировано ИИ"). Labels are locale-dependent — match the page's actual
> language. A **featured snippet** (a plain quoted block from one site) is **NOT**
> an AI Overview — don't count it. If only organic results show, it's state (a) —
> but confirm that from a **screenshot**, since `get_page_text` shows organic
> results even when an overview *is* present.
> If the overview is collapsed behind **"Show more" / "Expand AI summary"** (RU:
> "Показать подробнее" / "Развернуть краткий пересказ от ИИ"), **expand it** (click
> the control's `ref` via `computer` `left_click`) and read the full prose from a
> fresh screenshot.

### 3. Extract `sources` — the full relied-on set (INCLUDING every cited link)
- `sources` is the overview's **relied-on / retrieved set** — and it **MUST
  include every domain you cite in step 4** (citations ⊆ sources; see the box after
  step 4). Most sources live in the overview's **references / sources panel** (often
  a right-side or trailing list, sometimes behind a link/sources icon), which may be
  **collapsed or truncated** — but the panel is only a **partial** view, so any
  inline-cited link that isn't in the panel still belongs in `sources`.
- **EXPAND it fully, then collect via `read_page(filter="interactive")`.** Click
  the expanders — **"N sites"** (e.g. "8 sites"), **"Show all"** / **"Show more"**
  (RU: "N сайтов" / "8 сайтов" / "Показать все похожие ссылки" / "Показать ещё" /
  "Показать все") and any "sources" toggle — by `computer` `left_click` on each
  control's `ref` (from `read_page`/`find`), **then re-run
  `read_page(filter="interactive")`** to gather every revealed link with its real
  `href`. Repeat until no more links appear. Capture the **complete** set. (Do
  **not** read sources from `get_page_text` — it omits the overview.)
- **The "N sites" button opens the panel as an in-place popover — SCROLL it to the
  bottom and collect ALL N cards.** `read_page` typically surfaces only the first
  **3–4** cards at a time, so after opening the panel **scroll the popover down and
  re-read `read_page(filter="interactive")` repeatedly until no new cards appear.**
  The **"N sites"** (RU: "N сайтов") label tells you how many to expect — keep
  going until you have all N. **Do not stop at the first few visible cards:**
  under-capturing here makes genuine citations look like they're missing from the
  panel.
- **Click only the `button` form; never the source `link`/card.** The "N sites"
  (RU: "N сайтов") control is a **`button`** (expands in place) — click that. The
  source **cards themselves are `link`s** ("…opens in a new tab"; RU: "Страница
  откроется в новой вкладке") — you only ever **READ their `href`s**, never click
  them. **Never navigate to a source site** to fetch a URL: every URL is already on
  the Google page. If a click accidentally leaves Google, **go back** and re-read
  via `read_page`.
- Record links in **display order**. **Duplicate domains are allowed** — keep
  every occurrence (the same site can be listed twice). Do **not** dedupe and do
  **not** reorder.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches
  array position exactly.
- Prefer the **real destination URL**. The `href`s from
  `read_page(filter="interactive")` are **frequently DIRECT** (e.g.
  `example.com`, `example.com`) — when so, no unwrapping is needed. But Google
  sometimes wraps links in redirect trackers (`/url?q=…`, `google.com/url…`,
  grounding redirectors); when a link **is** wrapped, unwrap to the underlying
  target (the displayed publisher/host or the decoded `q=` param). If you
  genuinely cannot unwrap, store what you have and still normalize its domain.

### 4. Extract `citations` — the inline attached link chips
- These are the **inline badges/chips** sitting next to individual statements in
  the answer prose — the little source pills, e.g. **"Wikipedia"**, a favicon
  with a **"(+N)"** counter, or **`"Example (+1), see related links"`** (RU example:
  `"Орма Мебель (+1), посмотреть ссылки по теме"`). Spot them in the
  **screenshot**; pull their link `href`s from **`read_page(filter="interactive")`**.
- **A chip hides multiple sources.** A pill carrying **"(+N)"** (e.g.
  `"Example (+1)…"`) stands for **N+1** underlying links (the named one **plus N
  more**). **Click the chip's `button` form via `computer` `left_click` on its
  `ref`** (from `read_page`/`find`), **then re-run
  `read_page(filter="interactive")`** and record **each** revealed link as its
  own `Link`. Never collapse a "(+N)" into one entry.
- **Click the chip's `button`, NOT its `link`.** Each chip exposes both a
  **`button`** (expands its sources in place — click this) and a **`link`** (opens
  the source site — never click this). To read the chip's own href, just **READ**
  it from the tree; clicking the `link` opens the source site and trips its
  captcha. **Never navigate to a cited website** — every URL is already on the
  Google page. If a click accidentally leaves Google, **go back** and re-read via
  `read_page`.
- Order them as they appear in the prose (top-to-bottom, left-to-right within a
  statement). **Duplicates allowed** — if the same link is cited twice, list it
  twice.
- Same `Link` shape and same redirect handling as step 3 (`href`s are often
  already direct; unwrap only when wrapped). `rank` is 1-based by position
  **within `citations`** (independent of `sources` ranks).

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an
> independent channel.** `sources` is the overview's **relied-on / retrieved set**;
> `citations` are the inline chips marking which source(s) back specific sentences.
> The model can only cite what it retrieved, so **every cited domain is also a
> source.** The visible "N sites" (RU: "N сайтов") panel is only a **PARTIAL view**
> of that retrieval set — an inline-cited brand link can be missing from the panel.
> Therefore: **`sources` MUST INCLUDE every cited domain.** Collect the panel
> fully (step 3) **and** the chips (step 4); then if any chip domain is **not**
> already present in `sources`, **add it to `sources`** (fold the cited link in) so
> the invariant holds. Concretely: **any domain in `citations` MUST also appear in
> `target`-eligible `sources`**, and a non-empty `target_citation_ranks` therefore
> implies a non-empty `target_source_ranks`. If a chip domain seems absent from the
> panel, you under-captured it (scroll and re-read, step 3) — but even so, the cited
> domain belongs in `sources`.

### 5. Derive `domain` and match the TARGET
- Compute every `Link.domain` with **`normalize_domain`** semantics
  (`pipeline/schema.py`): strip scheme / userinfo / path / query / fragment /
  port and a leading `www.`, **lowercase**, keep the **registrable domain**
  (last two labels, e.g. `blog.example.com → example.com`; multi-part suffixes like
  `co.uk` preserved → three labels). Apply the **same** function to the given
  target `domain` so matching is consistent.
- A link **matches the target** iff its normalized `domain` **equals** the
  normalized target domain (exact string equality after normalization).

### 6. Compute `target_source_ranks` and `target_citation_ranks`
- `target_source_ranks` = **every** 1-based position in `sources` whose `domain`
  equals the target domain, in **ascending** order. A domain can appear more
  than once → list all (e.g. `[2, 4]`). `[]` if it never appears in `sources`.
- `target_citation_ranks` = the same, computed over `citations`. `[]` if absent.
- These are positions **within each respective list**, not global.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is
  non-empty, then `target_source_ranks` **must** be non-empty too (you cited the
  target, so it is also a source — fold it into `sources` per step 3 if the panel
  didn't list it). A cited target with empty `target_source_ranks` is a capture bug.

### 7. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow
  obvious transliterations / locale variants of the same name) appears **in the
  answer prose**.
- This is about the **name in text**, **independent of any link** — the brand
  can be named with no link (`true`), or linked but never named in prose
  (`false`). Judge the prose only.

### 8. Write `sentiment`
- **One short qualitative phrase**, describing **how the answer treats the target
  domain/brand** — e.g.
  `"recommended as one of the best options, named with a direct link"`,
  `"mentioned neutrally among 5 options"`,
  `"named, but with a caveat about price"`
  (RU example: `"упомянут нейтрально среди 5 вариантов"`).
- Write it in the **tracked market's language** (the `hl` locale you queried) so
  it reads naturally next to the answer prose.
- It is **free text**, **not** a number or label enum. It is **never**
  aggregated into a metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in
  `sources`, not in `citations`). If it appeared **anywhere**, write a non-null
  phrase. (Equivalently: `sentiment` is non-null exactly in state (c).)

### 9. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **do** take screenshots to **detect and read** the overview (required —
  `get_page_text` drops the AI block). But v1 does **not** save them as artifacts.
- Set **`screenshot_path = null`** in your object. Do **not** write any file under
  `data/screenshots/...`.

### 10. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see the
  worked example below) and **return it to the orchestrator** — it collects all objects and
  ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do NOT write to the
  DB.** You may **read** `pipeline/schema.py` to self-validate first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-06-19T20:15:30Z"`); `screenshot_path
  = null`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending; empty arrays
  when `overview_present=false`; `sentiment` null-iff-absent; domains normalized; citations
  ⊆ sources).

---

## Guardrails & caveats

- **reCAPTCHA / "unusual traffic" / "Verify it's you, not a robot"** (RU:
  "необычный трафик" / "Подтвердите, что запросы отправляли вы, а не робот").
  If a CAPTCHA or interstitial
  appears: **STOP**. Do **not** attempt to solve it, do **not** retry in a loop,
  do **not** hammer Google. Leave the challenge **visible in the browser** and
  **surface it to the human** ("CAPTCHA on `<query>` — please solve it in the
  open Chrome window, then tell me to continue"). Resume only after the human
  clears it. Never spawn fresh tabs/queries to "get around" it.
- **Selectors drift — read semantically.** Everything above ("AI Overview"
  label, "Show more", "+2" chips, sources panel) is a **landmark hint**.
  Identify blocks by **meaning and rendered text**, not fixed CSS/XPath. **Labels
  are locale-dependent** (the strings shown are English with one RU example each) —
  if a label is worded differently or in another language, match on intent.
- **Determinism caveat.** The same query can return a different overview (or
  none) on repeat — Google is non-deterministic and personalized. **Capture what
  rendered right now.** Do not retry hoping for a "better" overview; one honest
  capture per invocation. The UTC `captured_at` timestamps exactly what you saw.
- **Absence is data, not failure.** No overview → `overview_present=false` is a
  **valid, expected** result (it feeds `overview_coverage`). Never fabricate an
  overview, sources, citations, or sentiment to "fill in" a capture.
- **Stay in this engine / this query.** One object per `(query, lens)`. Don't
  branch into other queries or engines.

---

## Worked example

**Inputs:** `query = "best project management software for small teams"`, `lens = "general"`,
brand `name = "Example"`, target `domain = "https://www.example.com"` (→ normalizes to
`example.com`). Market: `hl=en&gl=us` (English/US — set `hl`/`gl` to whichever market you
track).

An AI Overview rendered. After expanding the sources panel ("Show all") and the
inline "Example" citation chip, the target domain appeared at **source positions 2
and 4** and **citation position 1**, and the brand name "Example" was in the prose.
Resulting single object:

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "google",
  "captured_at": "2026-06-19T20:15:30Z",
  "answer_text_md": "For small teams, experts often recommend a tool with a clean task board and simple workflows. **Example** offers several plans suited to this...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.techradar.com/project-management-tips", "domain": "techradar.com" },
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
> - **State (b), overview but no target:** `overview_present: true`, `sources`/
>   `citations` filled with whatever rendered, but `target_source_ranks: []`,
>   `target_citation_ranks: []`, `brand_in_answer_text: false`,
>   `sentiment: null`.
> - **State (a), no overview:** `overview_present: false`, `answer_text_md:
>   null`, `sources: []`, `citations: []`, both rank arrays `[]`,
>   `brand_in_answer_text: false`, `sentiment: null` (`screenshot_path` stays `null`).
