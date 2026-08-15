# Capture Playbook — ChatGPT (web search)

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
> brittle CSS/XPath; ChatGPT's DOM and class names drift constantly.
>
> **This is an "always-answering" assistant — the gate is different from Google.**
> ChatGPT almost always replies, so "did it reply" is meaningless as a denominator.
> The meaningful gate here is **"did it run a web search and render a grounded,
> sourced answer"** — see step 2 (`overview_present` reinterpreted as
> *grounded-answer present*, per `pipeline/INTERFACES.md` §4 Scope note and
> `engines/README.md`).

---

## Inputs you are given (per invocation)

- `query` — the exact string to send to ChatGPT. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `Example` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `example.com` or `https://www.example.com` (you will
  normalize it; see step 5).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`chatgpt_search`** (it matches this file's basename,
`engines/chatgpt_search.md`). Do **not** substitute `chatgpt`, `chatgpt_ai`, `openai`
or any other string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Locale knobs (target market ≠ UI language).** Unlike Google there are **no
> `hl`/`gl` URL params**. ChatGPT's answer language/market follows the **account &
> UI language** of the logged-in session (and, secondarily, the language you write
> the query in). Use the session **as configured for the market being tracked** and
> **read the page in whatever language it actually renders** — the labels below are
> shown in English with the **Russian** strings this session actually uses marked
> `RU:`. Do not assume English UI. The dashboard/report UI language (`--lang`) is a
> separate, downstream choice and does not affect capture.

---

## Procedure

> ### Tooling — how to actually read the answer (read this first)
> **Labels vary by locale; the structures are universal.** The **structures** — a
> streamed **answer block**, **inline citation chips**, and a **Sources panel** behind a
> "Sources" button — are the same in every locale. **Lead with the rendered text in the
> page's actual language.** English labels (with the Russian string this session uses,
> marked `RU:`):
> - web-search toggle / "search the web" chip **"Search"** (RU: "Поиск") and the
>   home-screen shortcut **"Search the web" / "Find something"** (RU: "Найди что-то")
> - **temporary chat** toggle **"Temporary chat"** (RU: "Временный чат") — top bar
> - end-of-answer **"Sources"** button → opens the sources panel (RU: "Источники")
> - **model selector** (RU: "Селектор модели")
>
> **Verified live against a real logged-in session (2026-06-22):**
> - **`get_page_text` WORKS for ChatGPT** — it returns the **full answer prose, any
>   table, and the inline citation labels** (each chip shows a source name + an optional
>   **"+N"** counter), in reading order. **This is the opposite of the Google playbook**
>   (where `get_page_text` drops the AI block). **Use `get_page_text` as your primary read**
>   for `answer_text_md`, for detecting whether the answer is grounded, and for the ordered
>   list of inline citation chips. A **screenshot** is a useful visual confirm but is not
>   required to read the prose.
> - ⚠️ **The end-of-answer "Sources" / "Источники" panel is GONE (re-verified live 2026-08-12).**
>   Earlier builds put the full retrieved set behind a "Sources" button; that button no longer
>   renders. Probed directly on a settled grounded answer: **zero** elements anywhere in the
>   document whose text is `Источники|Sources|Цитаты|Citations`, and the only button inside
>   `main` was the model selector. **Do not hunt for it.** Its replacement is the `+N` hover
>   carousel below — the same mechanic already documented for Perplexity.
> - **Inline citation chips expose real `href`s** in `read_page(filter="interactive")` (e.g. a
>   chip link `https://www.reddit.com/r/...?utm_source=chatgpt.com`) — but `read_page` only
>   surfaces the chips currently near the viewport, so for the **complete ordered list of chips**
>   lean on `get_page_text` and read each chip's `href` in place when it is in view.
> - **A chip carrying `+N` is a GROUP of N+1 sources, and the extra members are visible ONLY on
>   hover** — hovering opens a small carousel popup with a `k/K` counter and prev/next arrows.
>   The named (primary) source is what the chip shows; the rest are behind the arrows.
> - ⚠️ **Chip labels MUTATE while the carousel is cycled** (a chip that read `Refine AI +2`
>   pristine read `Baarely Refine AI` after cycling). **A label is not a stable key — only `href`
>   is.** Never resolve a chip by its label.
> - **URLs are DIRECT publisher URLs** (no Google-style `/url?q=` redirect wrappers), with
>   a harmless **`?utm_source=chatgpt.com`** appended. `normalize_domain` strips the query
>   string and `www.`, so no unwrapping is needed — store the URL as-is.
> - **NEVER click a citation chip or a source card.** A chip/card is a **link that opens
>   the source site in a NEW TAB** (verified). Worse than Google: that new tab can be
>   **un-closable** via the browser tools (a "this site is blocked" guard), so a stray
>   click both navigates away *and* litters a tab you cannot clean up. **Every URL you need
>   is already on the ChatGPT page — read its `href` from the tree in place.** If a chip
>   click accidentally opens a tab, switch back to your ChatGPT tab and carry on reading in
>   place; do **not** visit, read, or "study" the source site.
> - **Budget: ~10–25 tool calls with ZERO navigation away from ChatGPT** — the lower end when the
>   answer carries only single chips, the upper end when several `+N` groups must be expanded
>   (each group costs a hover plus one read per member). The older "~6–12" figure predates the
>   Sources panel being removed and is no longer reachable.

### 1. Open ChatGPT, pin a clean grounded session, submit the query
- Use the connected logged-in Chrome. Get tab context (`tabs_context_mcp`) and work in
  **your own tab**; `navigate` to `https://chatgpt.com/`. The session must be **logged in**
  (a logged-out wall means stop — see Guardrails). Keep the account/locale **as configured
  for the market being tracked** — do not change the account or UI language.
- **Turn on Temporary chat** (RU: "Временный чат") from the top bar (URL becomes
  `https://chatgpt.com/?temporary-chat=true`). This is the right capture mode: it keeps the
  run out of the user's history, **disables memory/personalization** (more neutral,
  reproducible captures), and does not touch the user's other chats. (A copy may be retained
  ~30 days for safety — that is fine.) Never open, read, or reuse the user's existing chats.
- **Enable web search** so the answer is grounded: click the **"Search the web" / "Find
  something"** chip (RU: "Найди что-то") on the home screen, or toggle the composer's
  **globe → "Search"** (RU: "Поиск"). When search is armed a **"Search" pill** (RU: "Поиск")
  shows in the composer. Pin the **default model** + **Search ON**; do not switch models.
- Type the `query` **verbatim** into the composer and submit. **Wait for streaming to
  finish** — the answer streams in; wait until the **stop** button reverts to the idle
  **send** button and the standard disclaimer footer appears (RU: "ChatGPT может допускать
  ошибки…"). Read only the settled answer.

### 2. Detect whether a GROUNDED answer rendered → `overview_present`
This is the **denominator gate** for all visibility metrics — get it right. **ChatGPT
almost always answers, so a reply alone is NOT the gate.** The gate is **"the model ran a
web search and rendered a sourced answer"**: there is an end-of-answer **"Sources" button**
(RU: "Источники") **and/or** inline citation chips in the prose. Detect from `get_page_text`
(inline chip labels + a trailing "Sources"/"Источники") and confirm with a screenshot.

Three distinct states:

- **(a) Ungrounded answer — no web search / no sources.** ChatGPT answered from its own
  knowledge: **no "Sources" button and no inline citation chips** anywhere. This is a valid
  "not visible in search" data point, **not an error.** Set:
  - `overview_present = false`
  - `sources = []`, `citations = []`
  - `target_source_ranks = []`, `target_citation_ranks = []`
  - `answer_text_md = null`
  - `brand_in_answer_text = false`
  - `sentiment = null`
  - (Still fill `query`/`lens`/`engine`/`captured_at`; `screenshot_path` stays `null`.)
- **(b) Grounded answer, target ABSENT.** Sources/citations rendered, but the target
  domain/brand appears **nowhere** (not in prose, not in any source or citation). Set
  `overview_present = true`, fill `answer_text_md` + `sources` + `citations` as they
  rendered, but: rank arrays `= []`, `brand_in_answer_text = false`, **`sentiment = null`**.
- **(c) Grounded answer, target PRESENT.** As (b), but the target appears in prose and/or
  in links. Fill rank arrays, set `brand_in_answer_text` accordingly, and write a non-null
  `sentiment`.

> **Landmark hints (not selectors):** a grounded answer carries the inline source chips
> (name + optional "+N") and a trailing **"Sources"** control (RU: "Источники"). An answer
> with neither is ungrounded → state (a). Do **not** force a reroll hoping search fires —
> capture what rendered once (see Guardrails).

### 3. Extract `sources` — the full relied-on set (chips + expanded `+N` groups)
- `sources` is the answer's **relied-on / retrieved set** — and it **MUST include every
  domain you cite in step 4** (citations ⊆ sources; see the box after step 4).
- **There is no Sources panel any more** (see the tooling box). The retrieved set is assembled
  from the inline chips: **every chip's primary `href`, plus every hidden member of every `+N`
  group.**
- **Expand each `+N` group by HOVERING the chip** (`computer` → `hover`), never by clicking it.
  A popup opens with a `k/K` counter; step through it with the **next arrow** — the arrow is a
  navigation control inside the popup and is safe to click. **The source card itself is a link —
  never click it.** Read each member's `href` via `read_page(filter="interactive")` while the
  popup is open.
- Record links in **reading order** of the chips, and within a group in **carousel order**.
  **Duplicate domains are allowed** — keep every occurrence (a chip and a group member can be the
  same domain; `getrefine.ai` legitimately appeared three times in the validation capture). Do
  **not** dedupe and do **not** reorder.
- **If a group will not expand, record its primary source and say so in your status line.** An
  undercount you flagged is data; an undercount you hid is a silent error — never invent the
  missing members.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1** and matches array
  position exactly.
- **Store the URL as rendered** (direct publisher URL incl. the `?utm_source=chatgpt.com`
  param). No redirect-unwrapping is needed; `normalize_domain` handles the query string and
  `www.`. **Never click a card to "get" a URL** — read its `href` in place.

### 4. Extract `citations` — the inline attached chips in the prose
- These are the **inline badges/chips** sitting next to statements in the answer prose — a
  favicon + a source name, e.g. **"Reddit"**, **"Spotsaas"**, or
  **"mysoftwarecompare.com (+1)"**. In `get_page_text` they appear inline as the source
  label plus an optional **"+N"** on its own line. Walk them **in reading order**.
- **A chip can hide multiple sources.** A chip carrying **"+N"** stands for the named source
  **plus N more**, reachable only through the hover carousel (step 3). **Do not click the chip**
  (clicking opens the source site in a possibly-unclosable tab) — **hover** it and step through
  with the popup's next arrow.
- **Never resolve a chip by its label** — labels are locale-dependent, truncated, and **mutate as
  the carousel is cycled**. The `href` is the only authoritative identity.
- For `citations`, record **one `Link` per chip occurrence** using that chip's **primary** href.
  The group's extra members belong in `sources` (step 3), not in `citations` — they back the same
  statement but are not separately attached to it.
- Record one `Link` per chip occurrence, **in prose order** (top-to-bottom). **Duplicates
  allowed** — if the same source is cited at two places, list it twice. Same `Link` shape and
  same URL handling as step 3. `rank` is 1-based by position **within `citations`**
  (independent of `sources` ranks).

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is the answer's **relied-on / retrieved set**; `citations` are the
> inline chips marking which source backs a given sentence. The model can only cite what it
> retrieved, so **every cited domain is also a source** (in ChatGPT the Sources panel is the
> *union* of all inline chips, so this holds naturally). Therefore: **`sources` MUST INCLUDE
> every cited domain.** If a chip domain is somehow not already in `sources`, **add it to
> `sources`** so the invariant holds. Concretely: **any domain in `citations` MUST also
> appear in `sources`**, and a non-empty `target_citation_ranks` therefore implies a
> non-empty `target_source_ranks`. (The `QueryCapture` validator enforces this.)

### 5. Derive `domain` and match the TARGET
- Compute every `Link.domain` with **`normalize_domain`** semantics
  (`pipeline/schema.py`): strip scheme / userinfo / path / query / fragment / port and a
  leading `www.`, **lowercase**, keep the **registrable domain** (last two labels, e.g.
  `blog.example.com → example.com`; multi-part suffixes like `co.uk` preserved → three
  labels). The `?utm_source=chatgpt.com` query string is stripped automatically.
- The target is a **domain OR URL-prefix** (e.g. `example.com` or `github.com/Pupok462`).
  A link **matches the target** iff (a) its registrable domain equals the target's
  registrable domain, **and** (b) if the target has a path, the target's path segments are a
  case-insensitive **prefix** of the link URL's path segments. A target with no path keeps
  the old domain-only behaviour. If the target has a path and the link's full URL is
  unavailable (domain-only chip) or is a redirect wrapper
  (`normalize_domain(url) ≠ link.domain`), it is **NOT** a match — never silently
  over-credit. (ChatGPT URLs are direct, so redirect wrappers are rare here.)

### 6. Compute `target_source_ranks` and `target_citation_ranks`
- Both arrays are computed **deterministically** by
  `pipeline.schema.target_ranks(links, target)` — the self-validation step
  (capture-worker instructions) overwrites whatever you put in the JSON with the
  authoritative result. You do not need to count by hand.
- `target_source_ranks` = every 1-based position in `sources` that matches the target
  (ascending); `[]` if never. `target_citation_ranks` = the same over `citations`.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is non-empty, then
  `target_source_ranks` **must** be non-empty too (you cited the target, so it is also a
  source — fold it into `sources` per step 4 if needed). A cited target with empty
  `target_source_ranks` is a capture bug.

### 7. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow obvious
  transliterations / locale variants of the same name) appears **in the answer prose**.
- This is about the **name in text**, **independent of any link** — the brand can be named
  with no link (`true`), or linked but never named in prose (`false`). Judge the prose only.

### 8. Write `sentiment`
- **One short qualitative phrase**, describing **how the answer treats the target
  domain/brand** — e.g.
  `"recommended as a top pick for small teams, linked directly"`,
  `"mentioned neutrally among 6 options"`,
  `"named, but with a caveat about setup complexity"`
  (RU example: `"упомянут нейтрально среди 6 вариантов"`).
- Write it in the **tracked market's language** (the language the answer rendered in) so it
  reads naturally next to the answer prose.
- It is **free text**, **not** a number or label enum. It is **never** aggregated into a
  metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in `sources`,
  not in `citations`). If it appeared **anywhere**, write a non-null phrase. (Equivalently:
  `sentiment` is non-null exactly in state (c).)

### 9. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **may** take screenshots to visually confirm the answer, but v1 does **not** save them
  as artifacts (and unlike Google, `get_page_text` already reads the answer, so a screenshot
  is optional). Set **`screenshot_path = null`** in your object. Do **not** write any file
  under `data/screenshots/...`.

### 10. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see the
  worked example below) and **return it to the orchestrator** — it collects all objects and
  ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do NOT write to the
  DB.** You may **read** `pipeline/schema.py` to self-validate first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-06-22T20:15:30Z"`);
  `screenshot_path = null`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending; empty arrays
  when `overview_present=false`; `sentiment` null-iff-absent; domains normalized; citations
  ⊆ sources).

---

## Guardrails & caveats

- **Login wall / rate-limit / anti-bot.** If ChatGPT shows a **login/signup wall**, a
  **"you've reached your limit" / usage-cap** notice (RU: "вы достигли лимита"), a
  Cloudflare/"verify you are human" challenge, or any interstitial: **STOP**. Do **not**
  attempt to solve it, log in, switch accounts, or retry in a loop. Leave the challenge
  **visible in the browser** and **surface it to the human** ("limit/CAPTCHA on `<query>` —
  please resolve it in the open Chrome window, then tell me to continue"). Resume only after
  the human clears it. Other workers keep going.
- **NEVER click a citation chip or source card.** They open the source site in a new tab
  that may be **un-closable** via the browser tools. Read every URL's `href` in place. If one
  opens by accident, switch back to your ChatGPT tab and continue — never read the source
  site.
- **Selectors drift — read semantically.** Everything above ("Sources"/"Источники" button,
  "Search"/"Поиск" pill, "+N" chips) is a **landmark hint**. Identify blocks by **meaning and
  rendered text**, not fixed CSS/XPath. **Labels are locale-dependent** — match on intent.
- **Determinism caveat.** The same query can return a different answer (or decide not to
  search) on repeat — ChatGPT is non-deterministic and may personalize. Temporary chat
  reduces this, but **capture what rendered right now.** Do not regenerate hoping for a
  "better" or "grounded" answer; one honest capture per invocation. The UTC `captured_at`
  timestamps exactly what you saw.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false` is a
  **valid, expected** result (it feeds the grounded-answer coverage metric). Never fabricate
  sources, citations, or sentiment to "fill in" a capture.
- **Stay in this engine / this query.** One object per `(query, lens)`. Don't branch into
  other queries, models, or engines. Don't touch the user's existing chats.

---

## Worked example

**Inputs:** `query = "best project management software for small teams"`, `lens = "general"`,
brand `name = "Example"`, target `domain = "https://www.example.com"` (→ normalizes to
`example.com`). Session: logged-in, Temporary chat, Search ON.

A grounded answer rendered. The Sources panel listed several review sites plus the target
twice; the prose cited the target inline once and named "Example". Resulting single object:

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "chatgpt_search",
  "captured_at": "2026-06-22T20:15:30Z",
  "answer_text_md": "For a small team, the best tool is the one your team will actually keep updated. **Example** is frequently recommended for its clean task board and simple workflows...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.spotsaas.com/blog/best-project-management-software/?utm_source=chatgpt.com", "domain": "spotsaas.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan?utm_source=chatgpt.com", "domain": "example.com" },
    { "rank": 3, "url": "https://www.reddit.com/r/SaaS/comments/abc123/best_pm_software/?utm_source=chatgpt.com", "domain": "reddit.com" },
    { "rank": 4, "url": "https://example.com/blog/how-to-choose?utm_source=chatgpt.com", "domain": "example.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://example.com/product/team-plan?utm_source=chatgpt.com", "domain": "example.com" }
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
> - **State (a), ungrounded (no web search / no sources):** `overview_present: false`,
>   `answer_text_md: null`, `sources: []`, `citations: []`, both rank arrays `[]`,
>   `brand_in_answer_text: false`, `sentiment: null` (`screenshot_path` stays `null`).
