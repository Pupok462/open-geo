# Capture Playbook — Yandex Alice (Нейро)

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
> **Surface.** This playbook captures **Yandex's Alice AI assistant** — the
> generative answer reached via the **"Алиса AI"** tab on a Yandex search results
> page, served at **`yandex.ru/alice`** (branded "Алиса AI" / "Нейросеть Алиса").
> It is a **chat assistant**, so unlike Google it **almost always replies** — which
> changes the denominator gate (see step 2). Structurally it is otherwise **very
> close to Google AI Overview**: prose answer + inline citation chips with `+N`
> counters + a sources panel ("Источники") + mostly direct source URLs.
>
> You are an **LLM reading rendered content**. Read the page **semantically** —
> the landmark hints below are *hints*, not selectors. Do **not** depend on
> brittle CSS/XPath; Yandex's DOM and class names drift constantly.

---

## Inputs you are given (per invocation)

- `query` — the exact string to type into Alice. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `iXBT` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `ixbt.com` or `https://www.ixbt.com` (you will
  normalize it; see step 5).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`yandex_neuro`** (it matches this file's basename,
`engines/yandex_neuro.md`). Do **not** substitute `yandex`, `yandex_alice`, `alice`,
or any other string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Locale / market (account-driven, NOT URL params).** Unlike Google's `hl`/`gl`,
> Alice has **no per-URL locale knob** — the market is set by the **logged-in Yandex
> account's region + interface language**. To track a given market, log the browser
> in to a Yandex account configured for that region/language; the answer renders in
> that account's language (Russian / Russia by default). Read the page in **that**
> locale's language. This market choice is **separate** from the dashboard/report UI
> language (`--lang`); `sentiment` follows the market language you queried.

---

## Procedure

> ### Tooling — how to actually read the answer (read this first)
> **Labels vary by locale; the structures are universal.** The Russian labels below
> are what a default RU account shows; match whatever language the account renders.
> The **structures** — a **prose answer**, **inline citation chips** with `+N`
> counters, a **"Источники" (Sources) panel**, and embedded **ad / product cards** —
> are stable. Russian labels (with an English gloss):
> - new-chat control **"Новый чат"** (the compose / "+" icon, top-left)
> - answer-in-progress hint **"Готовлю ответ, подождите немного…"** ("preparing the answer")
> - sources-panel button **"Источники"** (a row of source favicons + the word), opening
>   **"На основе N источников"** ("based on N sources")
> - inline citation chip **"<domain>"** or **"<domain> +N"** (e.g. `multivarka.pro +1`)
> - ad / promo card label **"Промо"** with a **"Перейти"** ("Go") button (e.g. ozon.ru,
>   market.yandex.ru, advertiser product cards) — **NOT a source; exclude it (see steps 3–4).**
>
> **Three tools, three jobs:**
> - **Read the prose + see which domains are cited → `get_page_text`.** Unlike Google
>   (where `get_page_text` silently drops the AI block), on Alice the answer **IS** the
>   page's main content, so `get_page_text` returns the **full prose** with each inline
>   chip's **domain text and `+N` counter inline** (e.g. `fluidwave.com +1`), and it
>   clearly marks **"Промо"** ad cards. Use it for `answer_text_md`, to enumerate the
>   cited domains in order, and to spot the ads you must exclude. (It does **not** give
>   `href`s or the hidden `+N` domains — use the next tool for those.)
> - **Confirm grounding + read chips/panel visually → `computer` (action=screenshot).**
>   A screenshot shows whether the answer is **grounded** (inline source chips and/or
>   the "Источники" button present), and lets you read chip placement and the panel.
> - **Collect source/citation `href`s → `read_page(filter="interactive")`** (plus `find`).
>   It returns the source/citation elements as links/menuitems with real `href`s — e.g. a
>   single-source chip `link "rg.ru"` href=`https://rg.ru/2025/05/05/…`, and sources-panel
>   `menuitem "multivarka.pro"` href=`https://multivarka.pro/article/…`. **`href`s are
>   frequently DIRECT** (no Yandex redirect wrapper) — unwrap only if one *is* wrapped.
> - **Every URL you need is already on the Alice page — read its `href` from the tree.
>   NEVER navigate to a cited/source website** (it wastes calls and trips the source
>   site's own CAPTCHA). A correct capture is **~6–12 tool calls with ZERO navigation
>   away from `yandex.ru/alice`.** If a click accidentally leaves Alice or opens a new
>   tab to a source/ad site, **close that tab / go back immediately** and re-read via
>   `read_page` — never proceed on, read, or "study" a source site.
> - **Expand before collecting.** Click the **"Источники"** button to open the sources
>   popover, and click each **`+N` chip badge** to reveal its hidden citations — **then
>   re-run `read_page(filter="interactive")`** to gather all revealed links.
> - **The "Источники" panel opens IN PLACE (a popover) — scroll it to the bottom.**
>   `read_page` often exposes only the first few source cards at a time. The header
>   **"На основе N источников"** tells you how many to expect — after opening the panel,
>   **scroll the popover down and re-read until no new cards appear**, collecting **all N**.

### 1. Open a FRESH Alice chat and submit the query
- **Start a NEW chat for every query.** Alice is a **chat** — a previous question's
  answer stays in context and would poison the next query. Per `(query, lens)`, either
  **navigate** to `https://yandex.ru/alice/` (a clean, empty chat) **or** click the
  **"Новый чат"** compose / "+" icon (top-left). Confirm the input box
  (**"Спросите о чём угодно"** — "ask anything") is empty/centered before typing.
- Click the input box and **type the `query` verbatim**. ⚠️ **Submit with the send ARROW, not
  `Return`** (verified live 2026-08-12): pressing Return opened the autocomplete suggestion list and
  left the query **unsent**, exactly as already documented for Perplexity. Confirm the query actually
  went through before you start waiting on an answer that was never asked for.
  (Equivalently you may reach Alice from a Yandex search by clicking the **"Алиса AI"**
  tab, but a fresh `yandex.ru/alice/` chat is the deterministic entry.)
- Keep the **session's** locale/login as-is. Do **not** open incognito, do **not** log
  out, do **not** switch Yandex account, and do **not** change the model/persona
  (ignore "Промптхаб" / "Персонажи") — the answer and its grounding depend on the
  logged-in account and the **default** mode. The browser is **visible**; the human can
  see it.
- Give the answer time to finish. It **streams in** (the hint "Готовлю ответ…" then
  growing prose; a **stop** button shows while generating and returns to the mic/submit
  state when done). **Wait until the prose stops growing AND the "Источники" button has
  appeared** (grounding finishes slightly after the prose). Then read it with the tools
  from the **Tooling** note above.

### 2. Decide `overview_present` → the GROUNDED-ANSWER gate (Alice ≠ Google here)
This is the **denominator gate** for all visibility metrics — get it right. Because
Alice is a chat assistant it **almost always replies**, so "an answer rendered" would be
a useless ~100% gate. For this engine `overview_present` is reinterpreted (per
`pipeline/INTERFACES.md` §4 Scope note, ROADMAP Feature 3) as **"a web-grounded answer
rendered"**: the answer is **backed by web sources** — it has **inline source chips
and/or an "Источники" panel**.

Detect grounding from a **screenshot** + `get_page_text` (look for chips like
`<domain> +N` and the "Источники" button), matching the **account's actual language**.

Three distinct states:

- **(a) Ungrounded answer (no web grounding).** Alice answered purely from its own
  knowledge — **no inline source chips and no "Источники" panel**. This is **normal and
  NOT an error** (it is the analog of Google's "no overview"). Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path` stays `null`.)
- **(b) Grounded, target ABSENT.** A grounded answer (chips and/or "Источники"), but the
  target domain/brand appears **nowhere** (not in prose, not in any source or citation
  link). Set `overview_present = true`, fill `answer_text_md` + `sources` + `citations`
  as they rendered, but: rank arrays `= []`, `brand_in_answer_text = false`,
  **`sentiment = null`**.
- **(c) Grounded, target PRESENT.** As (b), but the target appears in prose and/or in
  links. Fill rank arrays, set `brand_in_answer_text` accordingly, and write a non-null
  `sentiment`.

> **Landmark hint (not a selector):** "grounded" = you can see inline chips
> (`<domain>` / `<domain> +N`) attached to statements **and/or** the **"Источники"**
> button under the answer. A bare reply with neither is state (a). An embedded **"Промо"
> ad card alone is NOT grounding** — promo cards are advertising, not retrieved sources
> (see steps 3–4); if the only "links" are promo cards, it is still state (a).

### 3. Extract `sources` — the full relied-on set (the "Источники" panel)
- `sources` is Alice's **relied-on / retrieved set** — and it **MUST include every
  domain you cite in step 4** (citations ⊆ sources; see the box after step 4). The
  authoritative list is the **"Источники" panel**: click the **"Источники"** button to
  open the **"На основе N источников"** popover.
- **EXPAND + SCROLL the popover, then collect via `read_page(filter="interactive")`.**
  The popover is **scrollable** and `read_page` typically surfaces only the first **3–4**
  source `menuitem`s at a time. The **"На основе N источников"** header says how many to
  expect — **scroll the popover down and re-run `read_page(filter="interactive")`
  repeatedly until no new cards appear**, capturing the **complete** set of N. **Do not
  stop at the first few visible cards** — under-capturing here makes genuine citations
  look like they are missing from the panel.
- **EXCLUDE ad / promo cards.** Embedded **"Промо"** product cards with a **"Перейти"**
  button (e.g. `ozon.ru`, `market.yandex.ru`, advertiser sites) are **advertising, not
  retrieved sources** — they do **not** belong in `sources` (or `citations`). Only count
  entries listed inside the **"Источники"** panel (and inline citation chips, step 4).
- Record links in **display order** (panel order). **Duplicate domains are allowed** —
  keep every occurrence (the same site can be listed twice with different pages, e.g.
  `robotobzor.ru` appearing at two positions). Do **not** dedupe and do **not** reorder.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches array
  position exactly.
- Prefer the **real destination URL**. The `href`s from
  `read_page(filter="interactive")` are **frequently DIRECT** (e.g.
  `https://multivarka.pro/article/…`) — when so, no unwrapping is needed. If a link **is**
  wrapped in a Yandex redirect (`/clck/`, `yandex.ru/…&url=…`, a tracker), unwrap to the
  underlying target. If you genuinely cannot unwrap, store what you have and still
  normalize its domain. **Never navigate to a source site** to fetch a URL — every URL is
  already on the Alice page; read its `href` in place.

### 4. Extract `citations` — the inline attached chips in the prose
- These are the **inline badges/chips** sitting next to statements in the answer — small
  pills carrying a favicon + a domain, e.g. **`rg.ru`**, **`multivarka.pro`**, or a
  **`+N`** form like **`ixbt.com +1`**. `get_page_text` lists them inline with the prose
  (great for **order** and **which domains**); pull their link `href`s from
  **`read_page(filter="interactive")`** / `find`.
- **Two chip forms (mirror Google):**
  - a **single-source chip** is a **`link`** with a direct `href` — read it directly.
  - a **`+N` chip** is a **badge** that **expands on click** into a popover of the **N+1**
    underlying links (the named domain **plus N more**). **Click the `+N` badge via
    `computer` `left_click` on its `ref`** (from `read_page`/`find`), **then re-run
    `read_page(filter="interactive")`** and record **each** revealed link as its own
    `Link`. Never collapse a `+N` into one entry.
- **EXCLUDE ad / promo cards** here too — a "Промо" card's "Перейти" link is advertising,
  not a citation.
- Order them as they appear in the prose (top-to-bottom). **Duplicates allowed** — if the
  same link is cited twice, list it twice.
- Same `Link` shape and same redirect handling as step 3 (`href`s are usually already
  direct; unwrap only when wrapped). `rank` is 1-based by position **within `citations`**
  (independent of `sources` ranks). **Never navigate to a cited website** — read its
  `href` in place; if a click leaves Alice, **go back** and re-read.

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is Alice's **relied-on / retrieved set** (the "Источники" panel);
> `citations` are the inline chips marking which source(s) back specific sentences. The
> model can only cite what it retrieved, so **every cited domain is also a source.**
> Therefore: **`sources` MUST INCLUDE every cited domain.** Collect the panel fully
> (step 3) **and** the chips (step 4); then if any chip domain is **not** already present
> in `sources`, **add it to `sources`** (fold the cited link in) so the invariant holds.
> Concretely: **any domain in `citations` MUST also appear in `sources`**, and a non-empty
> `target_citation_ranks` therefore implies a non-empty `target_source_ranks`. (In
> practice the cited domains all appear in the "Источники" panel — if one seems missing,
> you under-captured the panel; scroll and re-read, step 3.)

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
  over-credit. (Yandex URLs are direct, so redirect wrappers are rare here.)
- **Exclude promotional/ad links** (Промо-карточки — `ozon.ru`, `market.yandex.ru`, etc.)
  from `sources`/`citations` before matching — these are ads, not organic sources.

### 6. Compute `target_source_ranks` and `target_citation_ranks`
- Both arrays are computed **deterministically** by
  `pipeline.schema.target_ranks(links, target)` — the self-validation step
  (capture-worker instructions) overwrites whatever you put in the JSON with the
  authoritative result. You do not need to count by hand.
- `target_source_ranks` = every 1-based position in `sources` that matches the target
  (ascending); `[]` if never. `target_citation_ranks` = the same over `citations`.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is non-empty,
  then `target_source_ranks` **must** be non-empty too (you cited the target, so it is
  also a source — fold it into `sources` per step 3 if the panel didn't list it). A cited
  target with empty `target_source_ranks` is a capture bug.

### 7. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow obvious
  transliterations / locale variants — e.g. a Latin name written in Cyrillic, or vice
  versa) appears **in the answer prose**.
- This is about the **name in text**, **independent of any link** — the brand can be named
  with no link (`true`), or linked but never named in prose (`false`). Judge the prose
  only (exclude ad-card copy).

### 8. Write `sentiment`
- **One short qualitative phrase**, describing **how the answer treats the target
  domain/brand** — e.g.
  `"recommended as one of the top picks, cited directly"`,
  `"mentioned neutrally as one source among several"`,
  `"cited for one fact, not discussed"`
  (RU example: `"процитирован как один из источников, нейтрально"`).
- Write it in the **tracked market's language** (the account locale you queried, Russian
  by default) so it reads naturally next to the answer prose.
- It is **free text**, **not** a number or label enum. It is **never** aggregated into a
  metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in `sources`,
  not in `citations`). If it appeared **anywhere**, write a non-null phrase. (Equivalently:
  `sentiment` is non-null exactly in state (c).)

### 9. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **do** take screenshots to **detect grounding and read** the answer, but v1 does
  **not** save them as artifacts. Set **`screenshot_path = null`** in your object. Do
  **not** write any file under `data/screenshots/...`.

### 10. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see the
  worked example below) and **return it to the orchestrator** — it collects all objects and
  ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do NOT write to the
  DB.** You may **read** `pipeline/schema.py` to self-validate first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-06-22T20:15:30Z"`); `screenshot_path
  = null`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending; empty arrays
  when `overview_present=false`; `sentiment` null-iff-absent; domains normalized; citations
  ⊆ sources; ad/promo cards excluded).

---

## Guardrails & caveats

- **Login / anti-bot / "Подтвердите, что вы не робот"** (confirm you are not a robot),
  SMS/captcha walls, or a logged-out state. If a challenge or login wall appears:
  **STOP**. Do **not** attempt to solve it, do **not** retry in a loop, do **not** hammer
  Yandex. Leave the challenge **visible in the browser** and **surface it to the human**
  ("Yandex challenge / not logged in on `<query>` — please resolve it in the open Chrome
  window, then tell me to continue"). Resume only after the human clears it. Never spawn
  fresh tabs/queries to "get around" it.
- **Exclude advertising.** Yandex injects **"Промо"** product/advertiser cards (with a
  **"Перейти"** button) into Alice answers. These are **ads, not retrieved sources** — keep
  them out of `sources`, `citations`, and `answer_text_md`. Only the **"Источники"** panel
  and the **inline citation chips** are real grounding. (This is the main Yandex-specific
  trap; Google's overview does not interleave ads this way.)
- **Selectors drift — read semantically.** Everything above ("Источники", "+N" chips,
  "Промо" cards, "Новый чат") is a **landmark hint**. Identify blocks by **meaning and
  rendered text**, not fixed CSS/XPath. **Labels are locale-dependent** — match on intent
  in the account's language.
- **Determinism caveat.** The same query can return a different answer (or different
  grounding) on repeat — Alice is non-deterministic and personalized. **Capture what
  rendered right now.** Do not regenerate hoping for a "better"/more-grounded answer; one
  honest capture per invocation. The UTC `captured_at` timestamps exactly what you saw.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false` is a
  **valid, expected** result (it feeds `overview_coverage` = the grounded-answer rate).
  Never fabricate grounding, sources, citations, or sentiment to "fill in" a capture.
- **One fresh chat per `(query, lens)`.** Don't reuse a chat across queries (context
  carryover) and don't branch into other queries or engines.

---

## Worked example

**Inputs:** `query = "как выбрать робот-пылесос для квартиры"`, `lens = "general"`,
brand `name = "iXBT"`, target `domain = "https://www.ixbt.com"` (→ normalizes to
`ixbt.com`). Market: default RU account (Russian / Russia).

Alice returned a **grounded** answer. The "Источники" panel listed **10 sources**
(duplicates kept — `robotobzor.ru` appeared twice), with `ixbt.com` at **source position
3**; `ixbt.com` was also an **inline `+N` chip** that expanded to include it, at
**citation position 3**; and the brand name "iXBT" was **not** spelled out in the prose
(linked only). A "Промо" `ozon.ru` card was present and was **excluded**. Resulting single
object:

```json
{
  "query": "как выбрать робот-пылесос для квартиры",
  "lens": "general",
  "engine": "yandex_neuro",
  "captured_at": "2026-06-22T20:15:30Z",
  "answer_text_md": "Выбрать робот-пылесос непросто — я подобрала главные критерии. **Сила всасывания**: для гладких полов часто хватает 1500–2500 Па... **Навигация**: лидар точнее гироскопа...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://multivarka.pro/article/kak-vybrat-robot-pylesos/", "domain": "multivarka.pro" },
    { "rank": 2, "url": "https://rg.ru/2025/05/05/kakoj-robot-pylesos-vybrat.html", "domain": "rg.ru" },
    { "rank": 3, "url": "https://www.ixbt.com/home/kak-vybrat-robot-pylesos-2025.html", "domain": "ixbt.com" },
    { "rank": 4, "url": "https://www.rbt.ru/blog/kak-vybrat-horoshij-robot-pylesos/", "domain": "rbt.ru" },
    { "rank": 5, "url": "https://robotobzor.ru/kak-vybrat-robot-pylesos.html", "domain": "robotobzor.ru" },
    { "rank": 6, "url": "https://robotobzor.ru/luchshie-roboty-pylesosy-2025.html", "domain": "robotobzor.ru" }
  ],
  "citations": [
    { "rank": 1, "url": "https://multivarka.pro/article/kak-vybrat-robot-pylesos/", "domain": "multivarka.pro" },
    { "rank": 2, "url": "https://rg.ru/2025/05/05/kakoj-robot-pylesos-vybrat.html", "domain": "rg.ru" },
    { "rank": 3, "url": "https://www.ixbt.com/home/kak-vybrat-robot-pylesos-2025.html", "domain": "ixbt.com" }
  ],
  "target_source_ranks": [3],
  "target_citation_ranks": [3],
  "brand_in_answer_text": false,
  "sentiment": "процитирован как один из источников по выбору робота-пылесоса, нейтрально"
}
```

> Contrast the other two states for the **same** query shape:
> - **State (b), grounded but no target:** `overview_present: true`, `sources`/
>   `citations` filled with whatever rendered, but `target_source_ranks: []`,
>   `target_citation_ranks: []`, `brand_in_answer_text: false`, `sentiment: null`.
> - **State (a), ungrounded answer:** `overview_present: false`, `answer_text_md: null`,
>   `sources: []`, `citations: []`, both rank arrays `[]`, `brand_in_answer_text: false`,
>   `sentiment: null` (`screenshot_path` stays `null`).

---

## Live audit — 2026-08-12 (scripted fast path)

> Measured by direct probe on a live answer, not inferred. Contract for using any of this:
> [`engines/FAST_PATH.md`](FAST_PATH.md). Raw results: [`bench/ENGINE_AUDIT.md`](../bench/ENGINE_AUDIT.md).
> The scripted read is a **fast path, not a trusted path** — the agent must independently confirm the
> count and spot-check domains; on disagreement discard the script output, read with the agent, and
> report the drift. An empty script result is never evidence that the answer cited nothing.

- **Sources set in one JS call: 7 single-chip URLs.** `+N` chips carry no href and still need a click.
- **Confirmed:** the `Источники` panel exists, `Промо` advertising cards exist (keep them out of
  `sources`/`citations` — the Yandex-specific trap is real), and the chip split is exactly as
  documented: a single chip is an `A` with a real href, a `+N` chip is a `SPAN` badge without one.
- ⚠️ **`Return` does not submit** — it opens the autocomplete list and leaves the query unsent. Use
  the send arrow (folded into step 1).
