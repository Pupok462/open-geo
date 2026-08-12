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
> **Validation status.** **Live-validated 2026-08-08** (the `engines/README.md`
> step-6 gate): 4 queries, all grounded, no CAPTCHA / rate limit / login wall.
>
> The original draft of this playbook was authored from Perplexity's public UI and
> assumed a **numbered** sources strip with inline **`[N]`** pills. **That surface
> does not exist.** The live UI has *unnumbered* source cards and inline chips
> labelled with a *shortened domain*, some of which are **`+N` groups** whose extra
> members are reachable only through a hover carousel. Every section below has been
> corrected against the live page; the numbering model is gone. Session context for
> the validation run: free account, Russian UI, English queries returning English
> answers (answer language follows the **query**, not the UI).
>
> Keep reading **semantically**: the landmark strings below are hints, and if a
> label or layout differs again, the rendered content and the §1 contract win, not
> the exact strings here.

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
> **Sources panel of source cards and/or inline domain-labelled citation chips**
> (per ROADMAP Feature 3 + `engines/README.md` step 3, and the §4 Scope note in
> `pipeline/INTERFACES.md`). Concretely:
>
> - **Grounded** (≥1 source card and/or ≥1 inline citation chip is present) →
>   **`overview_present = true`**. This is the **common case** for Perplexity — it
>   searches by default. All four validation queries were grounded.
> - **Ungrounded** (a bare prose answer with **no** source cards and **no** citation
>   chips) → **`overview_present = false`**, even though prose rendered. This is
>   **rare** on Perplexity (e.g. a non-web focus, a refusal, or an error state), but
>   it is a valid "not visible in search" data point, **not an error.** A model that
>   merely TYPES source names into its prose without any source card / citation chip
>   is **still ungrounded** — that text is model output, not a real citation.
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
> streamed **answer prose block**, an **unnumbered set of source cards** reachable
> from a Sources panel, and **inline citation chips labelled with a shortened
> domain** anchored to sentences — are the same in every locale. **There is no
> numbering anywhere in this UI: do not look for `[N]`.** English labels (match on
> **meaning**, not the exact string; the live session may render another language —
> the strings in parentheses are what a Russian session actually rendered):
> - composer input **"Ask anything"** / **"Ask a follow-up"**
> - the **Sources panel** — a card at the top-right of the answer showing a bare
>   count (RU: **"Источники 10"**), plus an end-of-answer button **"N sources"**
>   (RU: **"N источников"**). Both toggle the same list of **unnumbered** source
>   cards (favicon + shortened domain label + title + snippet).
> - the **answer-mode tabs** above the answer (RU: **"Ответ" / "Ссылки" /
>   "Изображения"**). The **"Links"** tab (RU: **"Ссылки"**, header "Результаты
>   поиска для: `<query>`") lists the SAME retrieved set in the SAME order **with
>   full URLs visible** — this is the cheapest reliable read of `sources`. Its
>   trailing **"Show more"** (RU: **"Показать больше"**) button loads EXTRA search
>   results beyond this answer's set — **do NOT click it**, it would inflate `sources`.
> - **inline citation chips** — small pills after statements in the prose, labelled
>   with a **shortened domain** (`business.adobe`, `zapier`, `oneglanse`), **NOT**
>   numbers. A chip may carry a **"+N" badge**, meaning that sentence is backed by
>   **N+1 sources**; the extra members are visible only via the hover carousel
>   (step 4).
> - the **Incognito** toggle in the **TOP BAR** (hat-and-glasses icon; tooltip:
>   anonymous sessions, not saved to history, deleted after 24 h) — **not** in the
>   account menu — and **"New"** (RU: **"Новый"**) in the left sidebar for a fresh
>   thread. Incognito **persists across New Thread**. Note: incognito threads still
>   appear in the sidebar session list during the session; they disappear on the
>   24 h auto-delete, not immediately.
> - the bottom follow-up questions (RU: **"Последующие вопросы"**) — IGNORE these.
>   The top ones are **"Computer"** agent tasks; never click them.
>
> **Read path (confirmed on the 2026-08-08 live-validation run):**
>
> - **`get_page_text` WORKS for Perplexity, and is better than expected** — it is a
>   normal rendered answer (like ChatGPT/Gemini, unlike Google where `get_page_text`
>   drops the AI block). One call returns the **full answer prose**, **all inline
>   chip labels AND their `+N` badges in reading order**, and — once the Sources
>   panel is expanded — every source card (label + title + snippet) in order. On the
>   **Links** tab it also returns full URLs. **Use `get_page_text` as your primary
>   read.** A **screenshot** is a useful visual confirm but is not required to read
>   the prose.
> - **The retrieved set is your `sources`.** Read it from the **"Links" tab**
>   (RU: "Ссылки") with `get_page_text` — label + full URL + title, in order. **Do
>   NOT scroll the right-hand Sources panel** to enumerate: it is **virtualised in
>   `read_page(interactive)`** (~5 link nodes at a time, and scrolling swaps them
>   out), though it is complete in `get_page_text` once expanded. Rank = display
>   order. Cross-check the count against the "N sources" button.
> - **Inline chips are your `citations`.** Walk them in prose order. A chip with
>   **no** `+N` badge is one link; a chip with **`+N` is N+1 links** and **MUST** be
>   expanded via the hover carousel (step 4). Chip labels are shortened,
>   non-registrable domains and they **mutate as you page the carousel** — never
>   resolve a chip by its label; read the card identity out of the popover.
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
> - **Budget: a correct capture is ~15–50 tool calls with ZERO navigation away from
>   Perplexity.** The floor applies when no chip carries a `+N` badge. Expanding
>   `+N` groups is hover-heavy and dominates the cost: on the validation run one
>   query had **25 chip groups, 12 of which needed expansion, costing ~35 extra tool
>   calls** and taking the citation count from 25 visible to **37 actual**. The only
>   clicks allowed are the Sources/Links expanders and the carousel's Next arrow —
>   all of which stay on the page.

### 1. Open Perplexity, pin a clean grounded session, submit the query
- Use the connected logged-in Chrome. Get tab context (`tabs_context_mcp`) and work
  in **your own tab**; `navigate` to `https://www.perplexity.ai/`. Keep the
  account/locale **as configured for the market being tracked** — do not change the
  account or UI language.
- **Turn on Incognito once, before the first query** (Perplexity's analog of
  ChatGPT's Temporary chat): it is a **toggle in the TOP BAR** (hat-and-glasses
  icon), **not** in the account menu. Once on, the icon shows a highlighted box and
  the setting **persists across New Thread**. It disables personalization/memory,
  giving more neutral, reproducible captures. Note it does **not** immediately hide
  the thread from the sidebar session list — those entries clear on the 24 h
  auto-delete. If Incognito is unavailable, use a plain **New Thread**. Never open,
  read, or reuse the user's existing threads.
- **Pin the default focus/model.** The composer shows a segmented control
  **"Search" | "Computer"** (RU: **"Поиск" | "Computer"**) plus a **"Model"** picker
  (RU: **"Модель"**). Keep **Search** selected and **"Computer" OFF** — Computer is
  an agentic mode with a different retrieval surface. Leave the model on the session
  default. A free account may show a persistent **"free preview of enhanced search
  is enabled"** banner — that is Perplexity's own default, not something you enable;
  record it as session context and do not try to turn it off.
- **Start a fresh thread for THIS query.** Perplexity threads carry follow-up
  context, so each `(query, lens)` must be its **own** thread (`New Thread` /
  navigate to the home composer) — otherwise the previous question bleeds into this
  answer.
- Type the `query` **verbatim** into the composer and **submit with the composer's
  arrow button, NOT Enter** — an autocomplete dropdown appears while typing and
  Enter can select a suggestion, sending the wrong query.
- **Wait until the prose stops changing across two reads ≥5 s apart.** The stop
  control **reverts to the idle arrow BEFORE generation finishes** — it is *not* a
  settle signal; on the validation run the final sentence kept extending across
  three reads after the button had already flipped. Expect 30–50 s for a long
  answer. Read only the settled answer.
- **`get_page_text` can lag behind the rendered page.** It has been seen returning a
  truncated final sentence while the screen already showed the complete one. If the
  text dump looks cut off mid-sentence, **settle against a screenshot**, not against
  the text dump.

### 2. Detect whether a GROUNDED answer rendered → `overview_present` (the gate)
This is the **denominator gate** for all visibility metrics — get it right, and per
the box at the top it means **"a GROUNDED answer rendered"** for Perplexity. Detect
from the settled page: grounding is present iff there is a **Sources panel with ≥1
source card** (the top-right "Sources N" card and/or the answer-footer "N sources"
button, and/or a populated "Links" tab) **and/or** at least one **inline citation
chip** in the prose. **There are no numbers — do not look for `[N]`.** Read
`get_page_text` (chip labels + source titles) and confirm with a screenshot.

> ### ⚠️ A FAILED RENDER IS NOT AN UNGROUNDED ANSWER — do not record a row
> Before you classify anything below, rule out a **technical failure to answer**.
> Observed 2026-08-08: a thread sat on "Рассуждение" / "Reasoning" with an **empty
> answer body and an empty sources panel for ~2.5 minutes**, then the
> `/search/new/<uuid>` URL **302'd back to the home page** and the thread never
> persisted. The underlying cause was the account's search quota, but it first
> appeared as silence, not as a banner.
>
> **That is NOT state (a).** State (a) means Perplexity *answered* without grounding.
> A thread that never produced an answer produced **no data at all**. Logging it as
> `overview_present=false` would push a **silently-wrong zero into the denominator**
> and depress `overview_coverage` for a reason that has nothing to do with
> visibility.
>
> **What to do instead:** do **not** emit a `QueryCapture` for that `(query, lens)`.
> Re-submit the query once to find the real cause (it will usually surface the true
> blocker, e.g. the quota interstitial). If it fails again, **skip the row and report
> it** in your status line as not-captured. The `(run_id, query, lens)` key simply
> stays absent, and a later resume picks it up — that is exactly what the resume
> design is for. Never invent a row to make the chunk look complete.

Three distinct states (all of which presuppose an answer actually rendered):

- **(a) Ungrounded answer (no sources / no chips).** Prose rendered but there are
  **no source cards and no citation chips** anywhere. Rare on Perplexity (all four
  validation queries were grounded), but
  **normal and NOT an error** — a valid "not visible in search" data point. Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path` stays `null`.)
- **(b) Grounded answer, target ABSENT.** Sources/citations rendered, but the target
  domain/brand appears **nowhere** (not in prose, not in any source card or chip).
  Set `overview_present = true`, fill `answer_text_md` + `sources` + `citations` as
  they rendered, but: rank arrays `= []`, `brand_in_answer_text = false`,
  **`sentiment = null`**.
- **(c) Grounded answer, target PRESENT.** As (b), but the target appears in prose
  and/or in links. Fill rank arrays, set `brand_in_answer_text` accordingly, and
  write a non-null `sentiment`.

> **Landmark hint (not a selector):** grounding on Perplexity is the **Sources
> panel** of unnumbered source cards plus the inline **domain-labelled chips**. A
> model-typed source name in the prose with **no** source card / **no** chip is
> **not** grounding → state (a). Beware the opposite trap too: **blue hyperlinks on
> entity names inside the prose** (e.g. a linked product name) are prose formatting,
> **not** citation chips. Do **not** reroll hoping for a "more grounded" answer —
> capture what rendered once (see Guardrails).

### 3. Extract `sources` — the full retrieved set (the Links tab)
- `sources` is the answer's **relied-on / retrieved set** — and it **MUST include
  every domain you cite in step 4** (citations ⊆ sources; see the box after step 4).
  On Perplexity the retrieved set is the **unnumbered source-card list**, surfaced
  either in the Sources panel or, better, on the **Links** tab.
- **Read the complete set from the "Links" tab** (RU: "Ссылки", the third
  answer-mode tab; header "Результаты поиска для: `<query>`"). One `get_page_text`
  call returns the whole ordered set **with full URLs**. On the validation run its
  order matched the Sources panel exactly on all four queries, and its count matched
  the "N sources" button.
- **Do NOT click "Show more"** (RU: "Показать больше") at the bottom of the Links
  tab — that loads **extra web results that are not part of this answer's retrieved
  set** and would inflate `sources`.
- If you instead expand the right-hand **Sources panel**, `get_page_text` returns
  all cards in order but **without URLs**, and `read_page(filter="interactive")` is
  **virtualised** (~5 card links at a time, swapping as you scroll) — so prefer the
  Links tab and do not try to enumerate by scrolling the panel.
- **Never use a chip's or card's visible label as `Link.domain`.** The labels are
  **shortened and non-registrable**: observed `business.adobe` → `adobe.com`,
  `visible.seranking` → `seranking.com`, `duaneforresterdecodes.substack` →
  `substack.com`, `gitblind.noratr` → `noratr.app`, `help.otterly` → `otterly.ai`,
  and bare `geo` → `geo.vote`, `citations` → `citations.io`, `position` →
  `position.digital`. Always compute `normalize_domain(href)` from the real URL.
- **Duplicate domains are allowed** — keep every occurrence (a publisher can back
  several statements / appear as several cards). Do **not** dedupe and do **not**
  reorder.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches array
  position exactly (so `sources[k]` has `rank = k+1`).
- **There is no fixed source count.** The validation run saw 10 / 10 / 10 / 25
  across four queries.
- **Store the URL as rendered** (direct publisher URL incl. any tracking query
  param). No redirect-unwrapping is needed; `normalize_domain` handles the query
  string and `www.`. **Never click a card to "get" a URL** — read its `href` in
  place.
- **Mirror hosts are stored as they render, which can look surprising.** Perplexity
  sometimes cites GitHub through a CDN mirror, e.g.
  `ithub.global.ssl.fastly.net/<owner>/<repo>` — `normalize_domain` correctly yields
  **`fastly.net`**, not `github.com`. That is contract-correct (registrable domain of
  the URL as served) but it means such a citation will **not** match a
  `github.com/...` prefix target and will appear as `fastly.net` in `domain_stats`.
  Do **not** "fix" it by rewriting the URL to github.com — capture what rendered.

### 4. Extract `citations` — the inline domain chips in the prose
- These are the **inline chips** sitting after statements in the answer prose,
  labelled with a **shortened domain** (not a number). In `get_page_text` they
  appear as a label, optionally followed by a separate **`+N`** line. Walk them
  **top-to-bottom**.
- **Tell groups from singles BEFORE hovering — it is free.** In
  `read_page(filter="interactive")`, a **single** chip is a plain **`link` node**
  inside the answer `tabpanel` (its `href` is the citation — just read it). A
  **group** chip is **not a link at all**. So: link ⇒ read the `href` and move on;
  non-link chip ⇒ it is a group, hover it. This avoids hovering every chip.
- **A chip with `+N` is a GROUP of N+1 sources and MUST be expanded.** **Hover** the
  chip (never click it) → a popover opens showing "`1/K`" and "`K sources`" with
  **Previous / Next** arrows, displaying **one source card at a time**. Click
  **Next** K−1 times, recording each member, then match each to the source list from
  step 3. Record **all K links, in carousel order**, at that point in `citations`.
- **Read group members by URL, not by title.** With the popover open,
  `read_page(filter="interactive")` exposes it as `button "Previous"` /
  `button "Next"` **plus a `link` whose `href` is the currently displayed card**. Read
  that `href` at each carousel position. This is far more reliable than matching card
  titles back to the source list.
  > **This is the single most dangerous step in this playbook.** Skipping `+N`
  > expansion silently under-collects citations and is invisible in the output. On
  > the validation run one query went from **25 visible chips to 37 actual citation
  > links**, and the hidden members contributed **two domains that appear nowhere
  > else in that answer** — they would have vanished from `domain_stats` with no
  > error and no warning.
- **Do NOT resolve a chip by its label, and do NOT trust the "Copy" markdown for
  groups.** The label shows only **one** member of the group and **changes as you
  page the carousel** (a chip observed cycling `brightdata` → `github` →
  `oneglanse`). The answer's Copy button yields Markdown with inline `[label](url)`
  citations — handy for `answer_text_md` — but it emits **exactly one link per chip
  group** and **may name a different member than the rendered chip**. **The hover
  carousel is the only complete, authoritative enumeration.**
- **Popover hygiene — moving the mouse away is NOT enough.** A popover overlaps
  neighbouring chips, so hovering the next chip re-opens the *previous* chip's
  popover (reset to `1/K`) whenever the popover box covers the target. Observed on
  every run so far. The **reliable** fix is to **scroll so the OTHER group chip is
  out of the viewport**, then hover the one you want. Confirm by screenshot that the
  popover closed.
  > The "check which chip's label changed" heuristic is a weak fallback, **not** the
  > primary technique: when two group chips sit close together it is itself
  > ambiguous, because either chip's label may be the one that mutated. Scroll first.
- **A "Выполнить задачу" / "run as Computer task" banner can overlay the bottom of
  the answer and cover a citation chip.** Scroll to shift the chip clear. **Never
  click the banner** — it launches the agentic Computer mode.
- **Blue hyperlinks on entity names inside the prose** (e.g. a linked product or
  repo name) are **prose formatting, not citation markers** — they usually point at
  the same URL as the adjacent chip. **Count chips only**, or you will double-count.
- Record one `Link` per chip occurrence (and one per group member), **in prose
  order**. **Duplicates allowed** — if the same source is cited at two places, list
  it twice. Same `Link` shape and same URL handling as step 3. `rank` is 1-based by
  position **within `citations`** (independent of `sources` ranks).

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is the answer's **relied-on / retrieved set**; `citations`
> are the inline chips marking which source backs a given sentence. The model can
> only cite what it retrieved, and on Perplexity every chip (and every member of a
> `+N` group) resolves to a card in the same retrieved set — so **every cited domain
> is also a source by construction.** Still verify: **any domain in `citations` MUST
> also appear in `sources`**, and a non-empty `target_citation_ranks` therefore
> implies a non-empty `target_source_ranks`. (The `QueryCapture` validator rejects a
> citation domain absent from sources.) If a chip somehow resolves to a domain not in
> `sources`, add it to `sources` so the invariant holds.

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
  named with no link (`true`), or cited via a chip but never named in prose
  (`false`). Judge the prose only.
- **Beware the query echo.** If the brand name appears only because the answer
  restates the question ("The **X** you're looking for is most likely…"), that is
  still `true` for this field — but it is **not** visibility. Say so plainly in
  `sentiment` rather than letting the flag imply the brand was recognised.

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

> ### ⚠️ ORCHESTRATOR: do NOT fan out parallel workers on Perplexity
> **A free Perplexity account has a hard search quota, and every concurrent worker
> spends the SAME account's quota.** Measured 2026-08-08: three workers running six
> queries each hit the interstitial *"Вы исчерпали лимит бесплатных поисковых
> запросов — Ваш доступ восстановится через несколько часов"* ("you've used up your
> free search limit; access restores in a few hours") after roughly **3 queries per
> worker**. Parallelism did not buy throughput — it **drained the shared quota ~3×
> faster** and left the run partial for hours.
>
> One account is a **shared stateful resource**. The correct shape here is **ONE
> worker running the queries in sequence** (`--n-worker 1` for this engine),
> regardless of what `--n-worker` is set to globally. Budget the set against the
> account's remaining quota before starting, and prefer splitting a large question
> set **across days** over splitting it across workers. A Pro account raises the cap
> but does not change the "one account, one worker" rule.
>
> This does not apply to engines without a per-account search quota — it is a
> Perplexity-specific (and free-tier-specific) constraint.

- **Login wall / rate-limit / anti-bot.** If Perplexity shows a **login/signup
  wall**, a **usage-cap** notice (e.g. a Pro-only / "you've reached your limit"
  interstitial), a Cloudflare / "verify you are human" challenge, or any
  interstitial: **STOP**. Do **not** attempt to solve it, log in, switch accounts,
  or retry in a loop. Leave the challenge **visible in the browser** and **surface
  it to the human** ("limit/CAPTCHA on `<query>` — please resolve it in the open
  Chrome window, then tell me to continue"). Resume only after the human clears it.
  Other workers keep going.
- **NEVER click a source card or a citation chip.** They open the source site in a
  new tab that may be **un-closable** via the browser tools. Read every URL's `href`
  in place, and expand chip groups by **hovering**, never clicking. The only clicks
  you make on the answer are the **Sources / Links expanders** and the **carousel's
  Next arrow**, all of which stay on the Perplexity page. If a source link opens by
  accident, switch back to your Perplexity tab and continue — never read the source
  site.
- **A knowledge/entity card may render ABOVE the answer** (favicon + domain + title
  + snippet). It is a link but **not a citation and not part of `answer_text_md`** —
  exclude it from `citations`. It normally also appears in the retrieved set, where
  it counts as a normal source.
- **Reading the clipboard.** The answer's Copy button yields Markdown with inline
  `[label](url)` citations — a handy shortcut for `answer_text_md`. If you paste it
  into the follow-up composer to read it, **clear the composer afterwards and never
  press Enter.** Remember it is incomplete on `+N` groups (step 4).
- **Do NOT switch focus/model, and IGNORE follow-ups.** Stay on the default Search
  focus with **"Computer" OFF** and the default model. Do **not** click the
  follow-up questions at the bottom (the top ones launch **Computer** agent tasks),
  and do **not** ask a follow-up in the same thread — one thread, one
  `(query, lens)`.
- **Selectors drift — read semantically.** Everything above (the Sources panel, the
  Links tab, the domain chips and their `+N` carousels, Incognito, New Thread,
  follow-ups) is a **landmark hint**. Identify blocks by **meaning and rendered
  text**, not fixed CSS/XPath. **Labels are locale-dependent** — match on intent.
  The 2026-08-08 validation run already invalidated one whole landmark model (the
  numbered strip); assume it can happen again.
- **Determinism caveat.** The same query can return a different answer (or a
  different source set) on repeat — Perplexity is non-deterministic. An Incognito
  thread reduces personalization, but **capture what rendered right now.** Do not
  regenerate hoping for a "better" answer; one honest capture per invocation. The
  UTC `captured_at` timestamps exactly what you saw.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false`
  is a **valid, expected** (if rare) result — it feeds the grounded-answer rate.
  Never fabricate sources, citations, or sentiment to "fill in" a capture, and never
  promote a model-typed source name into real `sources`/`citations` — only real
  source cards and citation chips count.
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

A grounded answer rendered. The Links tab listed four source cards — several review sites
plus the target twice (positions 2 and 4). The prose carried two citation chips: a plain
`g2` chip, and an `example +1` chip whose hover carousel showed **2 sources**
(`example.com/product/team-plan`, then `reddit.com/...`) — so that one chip contributes
**two** entries to `citations`, in carousel order. The prose also named "Example".
Resulting single object:

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "perplexity",
  "captured_at": "2026-07-08T20:15:30Z",
  "answer_text_md": "For a small team, the best tool is the one your team will actually keep updated. Review roundups converge on a short list. **Example** is frequently recommended for its clean task board and simple workflows...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.reddit.com/r/SaaS/comments/abc123/best_pm_software/", "domain": "reddit.com" },
    { "rank": 4, "url": "https://example.com/blog/how-to-choose", "domain": "example.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.reddit.com/r/SaaS/comments/abc123/best_pm_software/", "domain": "reddit.com" }
  ],
  "target_source_ranks": [2, 4],
  "target_citation_ranks": [2],
  "brand_in_answer_text": true,
  "sentiment": "recommended among suitable options, named with a direct link to the product"
}
```

> Contrast the other two states for the **same** query shape:
> - **State (b), grounded but no target:** `overview_present: true`, `sources`/`citations`
>   filled with whatever rendered, but `target_source_ranks: []`, `target_citation_ranks: []`,
>   `brand_in_answer_text: false`, `sentiment: null`.
> - **State (a), ungrounded (no source cards / no citation chips):** `overview_present: false`,
>   `answer_text_md: null`, `sources: []`, `citations: []`, both rank arrays `[]`,
>   `brand_in_answer_text: false`, `sentiment: null` (`screenshot_path` stays `null`). A
>   model-typed source name in the prose does **not** change this — without real source
>   cards / citation chips it is ungrounded.
>
> Note how the `+1` chip makes `citations` **longer** than the number of visible chips
> (3 entries from 2 chips). If your `citations` array is never longer than your chip
> count, you have almost certainly skipped carousel expansion — re-read step 4.
