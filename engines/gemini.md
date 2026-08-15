# Capture Playbook — Google Gemini (grounded answers)

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
> brittle CSS/XPath; Gemini's DOM and class names drift constantly.

---

> ## ⚠️ The denominator gate is REINTERPRETED for Gemini — read this first
>
> On **Google AI Overview** (`engines/google.md`) the gate `overview_present`
> means *"an AI Overview block rendered at all"* — it legitimately may not. **Gemini
> is an always-answering chat assistant: it returns prose for essentially every
> query.** So "an answer rendered" is trivially true and useless as a gate.
>
> For Gemini the gate is therefore **"did Gemini produce a GROUNDED, web-sourced
> answer"** — i.e. did it run **Google Search grounding** and attach **citation
> chips** to the answer (per ROADMAP Feature 3 + `engines/README.md` step 3, and
> the §4 Scope note in `pipeline/INTERFACES.md`). Concretely:
>
> - **Grounded** (grounding citation chips present) → **`overview_present = true`**.
> - **Ungrounded** (a pure parametric answer with **no** citation chips) →
>   **`overview_present = false`**, even though prose rendered. **A model that
>   merely TYPES the word "Sources:" followed by publisher names in its prose is
>   STILL ungrounded** — that text is model output, not a real citation. Only the
>   **chips** (the gray pills that open a real source popover) count.
>
> The field name stays `overview_present` and the funnel is unchanged
> (`n_cited ≤ n_in_sources ≤ n_overviews ≤ n_queries`); only the **top-of-funnel
> meaning** shifts from "overview rendered" to "grounded answer rendered". Read
> `overview_coverage` for Gemini as the **grounded-answer rate**.

---

## Inputs you are given (per invocation)

- `query` — the exact string to type into Gemini. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `Example` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `example.com` or `https://www.example.com` (you will
  normalize it; see step 6).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`gemini`** (it matches this file's basename, `engines/gemini.md`).
Do **not** substitute `gemini_ai_mode`, `google_gemini`, or any other string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Session / locale knobs (target market ≠ UI language).** Gemini requires a
> **logged-in Google account** — there is **no anonymous mode**, and **no `hl`/`gl`
> URL parameters** like Google Search. The answer locale follows the **Google
> account's language/region** (set in Gemini/Google account settings), so the
> *target market is selected by which account/region you are logged into*, not by
> the URL. Use the connected session **as-is**; do **not** log out or switch
> account. The live session may render in any language (it was verified in
> **Russian** — RU label examples are given below); **lead with the rendered text
> in the page's actual language** and treat the English strings as examples.
>
> **Model pin.** The mode picker (top of the composer / `RU: "Выбор режима, сейчас
> используется Flash"`) selects the model. **Pin the session default — `Flash` —**
> and do **not** switch models mid-run (the answer and its grounding depend on the
> model). If a run ever standardizes on another mode, that is an orchestrator-level
> decision; absent one, leave it on the default and capture what that produces.

---

## Procedure

> ### Tooling — how to actually read a Gemini answer (read this first)
> **Labels vary by locale; the structures are universal.** The structures — an
> **answer prose block**, inline **grounding citation chips**, each chip's **source
> popover**, and **"Ещё N" / "Показать все"** expanders — are the same in every
> locale. English labels (with the verified Russian equivalent each, marked `RU:`):
> - composer input **"Ask Gemini"** (RU: "Спросить Gemini"; aria "Введите запрос для Gemini")
> - mode picker **"…currently using Flash"** (RU: "Выбор режима, сейчас используется Flash")
> - streaming indicator **"Stop generating response"** (RU: "Остановить генерацию ответа")
> - grounding chip button **"View source details. A side panel will open."**
>   (RU: "Посмотреть сведения об источниках. Откроется боковая панель.") — bundled form
>   names the domains: (RU: "…для цитат с сайтов Investing.com, CRN Asia и TNW…")
> - chip counter **"+N more"** (RU: "Ещё N") · popover expander **"Show all"** (RU: "Показать все")
> - response footer **good / bad / regenerate / copy / more** (RU: "Хороший ответ / Плохой
>   ответ / Повторить / Копировать / Показать другие варианты")
>
> Match whatever locale the page is actually in — do not assume English strings.
>
> **Verified live against a real logged-in session — three load-bearing facts:**
>
> - **`get_page_text` WORKS for Gemini** (unlike Google, where it drops the AI
>   block). It returns the **full answer prose** — use it for `answer_text_md`. After
>   the answer has settled (see the reload note), it **also lists each grounding
>   chip inline at its anchor** as the chip's **primary domain + "Ещё N"** counter
>   (e.g. `Investing.com` / `Ещё 3`, `www.docomo.ne.jp`, `The Next Web`). That makes
>   `get_page_text` a cheap way to (a) read the prose, (b) **detect grounding**, and
>   (c) enumerate the chips' primary domains and how many are hidden behind `+N`.
> - **RELOAD the conversation to reach the final grounded state.** Under browser
>   automation the answer frequently gets **stuck in the "generating" state** (the
>   **"Stop generating"** button persists; RU: "Остановить генерацию ответа") even
>   after the visible prose is complete — and in that state the **citation chips and
>   the response footer are NOT rendered yet**, so `read_page` shows no sources and
>   you would wrongly set `overview_present=false`. **Fix:** once the prose stops
>   growing, **navigate to the conversation's own URL again** (`gemini.google.com/app/<id>`)
>   to force a clean settled render — the chips and footer then appear. **Always
>   reload once before reading sources/citations.** **It can take TWO reloads:** the
>   first reload sometimes lands on a transient **blank** conversation (empty content +
>   a generic composer placeholder; `get_page_text` returns "No text content found") —
>   if so, **reload the same URL again** until the prose + chips render.
> - **Chips are BUTTONS, not links — the real URLs live in the popover.** A chip
>   exposes no inline `href`; it is a **button** ("View source details… side panel
>   opens"). **Click the chip** → a **popover of source cards** opens (favicon +
>   publisher + article title + snippet), and **`read_page(filter="interactive")`**
>   then exposes those cards as **links with real, DIRECT `href`s** (e.g.
>   `https://www.investing.com/news/…`, `https://www.docomo.ne.jp/english/…`). URLs
>   are direct publisher URLs (no Google redirect wrappers) carrying a `#:~:text=`
>   highlight fragment that `normalize_domain` strips cleanly. A **"Ещё N"** chip
>   bundles **N+1** sources (named one + N more); the popover lists them and
>   **"Показать все"** (Show all) reveals the rest.
> - **NEVER navigate to a cited/source website.** Every URL you need is already on
>   the Gemini page (in the chip popovers). Visiting source sites is wasteful and
>   trips their own CAPTCHAs. A correct capture is **read in place, ZERO navigation
>   away from Gemini**. If a click accidentally opens a source site or a new tab,
>   **close it / go back immediately** and re-read via `read_page`.
> - **Click only the chip `button` (and "Показать все"); never a source card's
>   `link`.** The card links ("…opens in a new tab") are there only so you can
>   **READ their `href`** — never click them.

### 1. Open Gemini and submit the query
- Use the connected logged-in Chrome: `navigate` to `https://gemini.google.com/app`,
  click the composer (**"Ask Gemini"** / RU: "Спросить Gemini"), type the `query`
  verbatim, and submit. **Submit by clicking the send button** (the round arrow at the
  right of the composer) — pressing Return alone is unreliable right after navigation.
- **After navigating to `/app`, click the composer by its on-screen location** (from a
  screenshot), **not** a pre-navigation element `ref` — a stale ref from before the
  navigation silently swallows the typed text. Screenshot → click the visible composer
  → type → click send.
- Keep the **session's** account/locale as-is. Do **not** open incognito (Gemini needs
  login), do **not** log out, do **not** change the account or model. The browser is
  **visible**; the human can see it.

### 2. Let the answer settle, then RELOAD the conversation (required)
- After submit, Gemini streams the prose. **Wait until the prose stops growing**
  (poll a screenshot or `get_page_text` until two reads match), then **reload the
  conversation's URL** (`navigate` to the current `gemini.google.com/app/<id>`). This
  forces the final settled render so the **grounding chips and response footer
  appear** (see the Tooling reload note — without this you under-detect grounding).
- Then read with the tools above: **`get_page_text`** for the prose + chip
  enumeration, **`read_page(filter="interactive")`** for the chip buttons, and a
  **screenshot** if you need to see chip placement visually.

### 3. Detect grounded vs ungrounded → `overview_present` (the gate)
This is the **denominator gate** for all visibility metrics — get it right, and per
the box at the top it means **"a GROUNDED answer rendered"** for Gemini. Detect from
the settled page (after the reload): grounding is present iff there are **grounding
citation chips** — i.e. `read_page(filter="interactive")` lists one or more chip
**buttons** *"View source details… side panel will open"* (RU: "Посмотреть сведения об
источниках…"), and/or `get_page_text` shows chip domain tokens (a bare publisher
domain + "Ещё N") interspersed in the prose.

Three distinct states:

- **(a) Ungrounded answer (no grounding).** Prose rendered but there are **no
  citation chips** (no source buttons in the interactive tree, no chip domain tokens
  in `get_page_text`). This is **normal and NOT an error** — Gemini answered from
  parametric memory. **A prose line that merely says "Sources: X, Y" with no chips is
  still state (a).** Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path` stays `null`.)
- **(b) Grounded, target ABSENT.** Citation chips are present, but the target
  domain/brand appears **nowhere** (not in prose, not in any chip's source links).
  Set `overview_present = true`, fill `answer_text_md` + `sources` + `citations` as
  they rendered, but: rank arrays `= []`, `brand_in_answer_text = false`,
  **`sentiment = null`**.
- **(c) Grounded, target PRESENT.** As (b), but the target appears in prose and/or in
  a chip's source links. Fill rank arrays, set `brand_in_answer_text` accordingly, and
  write a non-null `sentiment`.

> **Landmark hint (not a selector):** a grounding chip is a small gray pill sitting
> inside or right after a sentence, showing a publisher name/domain and sometimes a
> **"Ещё N"** (+N) counter; clicking it opens a **source popover**. A model
> **"double-check"** affordance or a model-typed "Sources:" line is **not** a chip —
> only the pill that opens a real source popover counts as grounding.

### 4. Extract `sources` — the full grounded retrieval set (INCLUDING every cited link)
- `sources` is Gemini's **relied-on / retrieved set** for this answer — and it **MUST
  include every domain you cite in step 5** (citations ⊆ sources; see the box after
  step 5). In Gemini the retrieved set is surfaced **through the citation chips**:
  every grounded source hangs off a chip's popover.
- **Collect by expanding every chip.** For **each** grounding chip button (from
  `read_page(filter="interactive")`): **click it** (use the element `ref`), let the
  **source popover** open, then re-run **`read_page(filter="interactive")`** to read
  the popover's card **links and their real `href`s**. If the chip shows **"Ещё N"**
  (+N) or the popover shows **"Показать все"** (Show all), **click "Показать все"** to
  reveal the full list before reading, so you capture **all N+1** cards, not just the
  named one. Dismiss the popover (press `Escape` or click elsewhere) before the next
  chip.
- **Union across chips, in display order.** Walk the chips **top-to-bottom** through
  the answer and append each chip's revealed card links. **Duplicate domains are
  allowed** — keep every occurrence; do **not** dedupe and do **not** reorder. (The
  same publisher can back several statements.)
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches array
  position exactly.
- **URLs are DIRECT** (real publisher URLs with a `#:~:text=` highlight fragment) —
  `normalize_domain` strips the fragment/path/`www`, so no manual unwrapping is
  needed. Store the full `url` as read; compute `domain` with `normalize_domain`.
- **Never click a source card's `link` and never navigate to a source site** — read
  the `href` in place. If a click leaves Gemini, **go back** and re-read.

> **Gemini note — sources ≈ citations (intentional).** Gemini surfaces its retrieved
> set **only through inline citation chips** (there is no separate "retrieved but
> uncited" panel like Google's sources panel). So in the common case `sources` is the
> **union of all chip links** and `citations` is **those same links grouped by
> statement** — they largely coincide, which is faithful to Gemini's UI (if a domain
> is a source, it is cited). That makes `relative_citation` tend toward `1.0` for
> Gemini — expected, not a bug. (If a conversation's consolidated side panel /
> "Показать все" view ever lists extra related sources **not** attached to any single
> statement, include those in `sources` only.)

### 5. Extract `citations` — the inline grounding chips
- These are the **inline chips attached to specific statements** in the answer prose —
  the gray pills (e.g. `"Investing.com Ещё 3"`, `"www.docomo.ne.jp"`, `"The Next
  Web"`). Spot them in `get_page_text` (domain token + "Ещё N" at the anchor) and in
  the **screenshot**; pull their links from the **popover** via
  `read_page(filter="interactive")` after clicking the chip (step 4).
- **A chip hides multiple sources.** A chip carrying **"Ещё N"** (+N) stands for
  **N+1** links (the named one **plus N more**). Expand it (**"Показать все"**) and
  record **each** revealed link as its own `Link`. Never collapse a "Ещё N" into one
  entry.
- Order them as the chips appear in the prose (top-to-bottom; left-to-right within a
  statement). **Duplicates allowed** — if the same link backs two statements, list it
  twice. `rank` is 1-based by position **within `citations`** (independent of
  `sources` ranks).
- Same `Link` shape and the same direct-URL handling as step 4.

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is the relied-on/retrieved set; `citations` are the inline
> chips marking which source(s) back specific sentences. The model can only cite what
> it retrieved, so **every cited domain is also a source.** Because in Gemini you
> built both from the same chip popovers (step 4), this holds by construction — but
> still verify: **any domain in `citations` MUST also appear in `sources`**, and a
> non-empty `target_citation_ranks` therefore implies a non-empty
> `target_source_ranks`. (The `QueryCapture` validator rejects a citation domain
> absent from sources.)

### 6. Derive `domain` and match the TARGET
- Compute every `Link.domain` with **`normalize_domain`** semantics
  (`pipeline/schema.py`): strip scheme / userinfo / path / query / fragment / port and
  a leading `www.`, **lowercase**, keep the **registrable domain** (last two labels,
  e.g. `blog.example.com → example.com`; multi-part suffixes like `co.uk`, `ne.jp`
  preserved → three labels).
- The target is a **domain OR URL-prefix** (e.g. `anthropic.com` or
  `github.com/Pupok462`). A link **matches the target** iff (a) its registrable domain
  equals the target's registrable domain, **and** (b) if the target has a path, the
  target's path segments are a case-insensitive **prefix** of the link URL's path
  segments. A target with no path keeps the old domain-only behaviour. If the target has
  a path and the link's full URL is unavailable (domain-only chip) or is a redirect
  wrapper (`normalize_domain(url) ≠ link.domain`), it is **NOT** a match — never
  silently over-credit.
- **A brand-adjacent label or URL path on a DIFFERENT domain is NOT a match.**
  A mention of the brand name in a link's display label or in its URL path does NOT cause
  a match unless the link's registrable domain matches the target's. This applies when the
  target itself has no path (domain-only behaviour) AND when the target has a path (path
  prefix is checked only on the target's own domain, not others'). Verified examples for
  target `anthropic.com`: a "Claude Console" chip resolves to
  `platform.claude.com → claude.com` (**not** a match); a card at
  `lorka.ai/ai-models/anthropic` is `lorka.ai` (**not** a match); only chips whose card
  URL is on `www.anthropic.com → anthropic.com` match. Always read the `href` and run
  `normalize_domain` on it — never match on the chip's display name.

### 7. Compute `target_source_ranks` and `target_citation_ranks`
- Both arrays are computed **deterministically** by
  `pipeline.schema.target_ranks(links, target)` — the self-validation step
  (capture-worker instructions) overwrites whatever you put in the JSON with the
  authoritative result. You do not need to count by hand.
- `target_source_ranks` = every 1-based position in `sources` that matches the target
  (ascending); `[]` if never. `target_citation_ranks` = the same over `citations`.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is
  non-empty, `target_source_ranks` **must** be non-empty too. A cited target with
  empty `target_source_ranks` is a capture bug — fix it by folding the cited link into
  `sources` (step 4).

### 8. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow obvious
  transliterations / locale variants of the same name) appears **in the answer prose**.
- This is about the **name in text**, **independent of any chip** — the brand can be
  named with no chip (`true`), or cited via a chip but never named in prose (`false`).
  Judge the prose only.

### 9. Write `sentiment`
- **One short qualitative phrase** describing **how the answer treats the target
  domain/brand** — e.g. `"recommended as one of the best options, cited with a direct
  link"`, `"mentioned neutrally among 5 options"`, `"named, but with a caveat about
  price"` (RU example: `"упомянут нейтрально среди 5 вариантов"`).
- Write it in the **rendered answer's language** (the account locale) so it reads
  naturally next to the prose.
- It is **free text**, **not** a number or label enum, and is **never** aggregated into
  a metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in
  `sources`, not in `citations`). If it appeared **anywhere**, write a non-null phrase.
  (Equivalently: `sentiment` is non-null exactly in state (c).)

### 10. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **do** take screenshots to detect/read the answer and chips, but v1 does **not**
  save them as artifacts. Set **`screenshot_path = null`**. Do **not** write any file
  under `data/screenshots/...`.

### 11. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see the
  worked example below) and **return it to the orchestrator** — it collects all objects and
  ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do NOT write to the
  DB.** You may **read** `pipeline/schema.py` to self-validate first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-06-22T20:15:30Z"`); `screenshot_path
  = null`; `engine = "gemini"`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending; empty arrays
  when `overview_present=false`; `sentiment` null-iff-absent; domains normalized; citations
  ⊆ sources).

---

## Guardrails & caveats

- **reCAPTCHA / "unusual traffic" / "verify it's you"** (RU: "необычный трафик" /
  "Подтвердите, что это вы"). If a CAPTCHA or interstitial appears: **STOP**. Do
  **not** attempt to solve it, do **not** retry in a loop, do **not** hammer Gemini.
  Leave the challenge **visible in the browser** and **surface it to the human**
  ("CAPTCHA on `<query>` — please solve it in the open Chrome window, then tell me to
  continue"). Resume only after the human clears it. Never spawn fresh tabs/queries to
  "get around" it.
- **Login wall.** If Gemini shows a sign-in screen instead of the composer, **stop and
  surface it** — the session is logged out. Do **not** attempt to log in or enter
  credentials yourself.
- **Selectors drift — read semantically.** Everything above (chip pills, "Ещё N",
  "Показать все", the source popover, the "Stop generating" indicator) is a **landmark
  hint**. Identify blocks by **meaning and rendered text**, not fixed CSS/XPath.
  **Labels are locale-dependent** (English with a verified RU example each) — match on
  intent.
- **Determinism caveat.** The same query can return a different answer — and may
  **ground one time and not the next**. **Capture what rendered right now.** Do not
  retry hoping for a "better" or grounded answer; one honest capture per invocation.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false` is
  a **valid, expected** result (it feeds the grounded-answer rate). Never fabricate
  grounding, sources, citations, or sentiment to "fill in" a capture. **Never promote a
  model-typed "Sources:" prose line into real `sources`/`citations`** — only chips count.
- **Stay in this engine / this query.** One object per `(query, lens)`. Don't branch
  into other queries or engines, and don't switch the model picker.

---

## Worked example

**Inputs:** `query = "best project management software for small teams"`, `lens = "general"`,
brand `name = "Example"`, target `domain = "https://www.example.com"` (→ normalizes to
`example.com`). Session: a logged-in Google account (locale follows the account; no `hl`/`gl`).
Model: the session default (`Flash`).

Gemini produced a **grounded** answer (citation chips present). After reloading the
conversation to settle it, expanding the chips and their **"Показать все"** popovers, the
target domain appeared at **source positions 2 and 4** and **citation position 1**, and the
brand name "Example" was in the prose. Resulting single object:

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "gemini",
  "captured_at": "2026-06-22T20:15:30Z",
  "answer_text_md": "For small teams in 2026, the best fit depends on your workflow. **Example** is frequently recommended for its clean task board and simple plans...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.techradar.com/best/project-management-software", "domain": "techradar.com" },
    { "rank": 4, "url": "https://example.com/blog/how-to-choose", "domain": "example.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 2, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" }
  ],
  "target_source_ranks": [2, 4],
  "target_citation_ranks": [1],
  "brand_in_answer_text": true,
  "sentiment": "recommended among suitable options, cited with a direct link to the product"
}
```

> Contrast the other two states for the **same** query shape:
> - **State (b), grounded but no target:** `overview_present: true`, `sources`/`citations`
>   filled with whatever the chips rendered, but `target_source_ranks: []`,
>   `target_citation_ranks: []`, `brand_in_answer_text: false`, `sentiment: null`.
> - **State (a), ungrounded (no chips):** `overview_present: false`, `answer_text_md: null`,
>   `sources: []`, `citations: []`, both rank arrays `[]`, `brand_in_answer_text: false`,
>   `sentiment: null` (`screenshot_path` stays `null`). A model-typed "Sources:" line in the
>   prose does **not** change this — without chips it is ungrounded.

---

## Live audit — 2026-08-12 (scripted fast path)

> Measured by direct probe on a live answer, not inferred. Contract for using any of this:
> [`engines/FAST_PATH.md`](FAST_PATH.md). Raw results: [`bench/ENGINE_AUDIT.md`](../bench/ENGINE_AUDIT.md).
> The scripted read is a **fast path, not a trusted path** — the agent must independently confirm the
> count and spot-check domains; on disagreement discard the script output, read with the agent, and
> report the drift. An empty script result is never evidence that the answer cited nothing.

- **Sources set in one JS call: 0.** Gemini has **no** scripted fast path — chips are buttons and
  the URLs are absent from the DOM until a popup opens.
- ⚠️ **Synthetic clicks do not work here.** `HTMLElement.click()` dispatched at all nine
  domain-labelled chips opened **nothing** (0 popups, 0 URLs); a real `computer` `left_click` on the
  same kind of chip opened the popup instantly and yielded its 2 URLs. Budget accordingly: 24 chips
  × (click + read) is the real cost of a full capture.
- **Confirmed with numbers — the reload step is mandatory:** before reloading the chat the answer had
  settled but exposed **3 buttons and 0 grounding chips**; after **one** `navigate` to the same chat
  URL it exposed **27 buttons and 24 chips**. One reload sufficed on this run.
- Chip labels are **not** domains (`KIME`, `LLM Pulse`, `Searchable` sit alongside `nightwatch.io`),
  so there is no label-only shortcut around the clicking.
