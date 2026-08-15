# Capture Playbook — DeepSeek (web search / "Умный поиск")

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
> **Surface.** This playbook captures **DeepSeek's chat assistant with web search**
> — the answer produced at **`chat.deepseek.com`** with the **"Умный поиск" (Smart
> search / web search) toggle ON**. It is a **chat assistant**, so unlike Google it
> **almost always replies** — which changes the denominator gate (see step 2).
> Structurally it is a **Perplexity/Bing-style** engine: a **numbered retrieved
> set** (the "Результаты поиска" panel, sources `1..N`) plus **numbered inline
> `[N]` citation badges** in the prose that point back into that set. Mostly
> **direct** publisher URLs.
>
> You are an **LLM reading rendered content**. Read the page **semantically** —
> the landmark hints below are *hints*, not selectors. Do **not** depend on
> brittle CSS/XPath; DeepSeek's DOM and class names drift constantly.

---

> ## ⚠️ The denominator gate is REINTERPRETED for DeepSeek — read this first
>
> On **Google AI Overview** (`engines/google.md`) the gate `overview_present`
> means *"an AI Overview block rendered at all"* — it legitimately may not.
> **DeepSeek is an always-answering chat assistant: it returns prose for
> essentially every query.** So "an answer rendered" is trivially true and useless
> as a gate.
>
> For DeepSeek the gate is therefore **"did DeepSeek produce a GROUNDED,
> web-sourced answer"** — i.e. did **"Умный поиск"** actually run a web search and
> back the answer with sources (per ROADMAP Feature 3 + `engines/README.md` step 3,
> and the §4 Scope note in `pipeline/INTERFACES.md`). Concretely:
>
> - **Grounded** — the answer carries the **"Прочитано N веб-страниц"** ("Read N
>   web pages") header and/or **inline `[N]` citation badges** and/or the
>   **"Результаты поиска"** (Search results) panel → **`overview_present = true`**.
> - **Ungrounded** — DeepSeek answered from its own parametric knowledge with
>   **no** read-pages header, **no** `[N]` badges, and **no** search-results panel
>   → **`overview_present = false`**, even though prose rendered. (This can happen
>   even with "Умный поиск" armed — the model may decide not to search.)
>
> The field name stays `overview_present` and the funnel is unchanged
> (`n_cited ≤ n_in_sources ≤ n_overviews ≤ n_queries`); only the **top-of-funnel
> meaning** shifts from "overview rendered" to "grounded answer rendered". Read
> `overview_coverage` for DeepSeek as the **grounded-answer rate**.

---

## Inputs you are given (per invocation)

- `query` — the exact string to type into DeepSeek. Send it verbatim.
- `lens` — one of `general` | `branded` | `comparative` (already decided
  upstream; copy it through, do not re-classify).
- **target brand `name`** — e.g. `Example` (for `brand_in_answer_text`).
- **target `domain`** — e.g. `example.com` or `https://www.example.com` (you will
  normalize it; see step 5).

`engine` — the engine id the orchestrator passes you, **copied through verbatim**. For
this playbook that is **`deepseek`** (it matches this file's basename,
`engines/deepseek.md`). Do **not** substitute `deepseek_search`, `deep_seek`,
`deepseek_chat`, or any other string.

> You **return** your finished `QueryCapture` object to the orchestrator — you do **not**
> ingest it, **not** create runs, **not** write to the DB, and **not** start any server (so
> you are not given a `run_id` or DB path). The orchestrator owns all of that.

> **Session / locale knobs (target market ≠ UI language).** DeepSeek requires a
> **logged-in account**, and there are **no `hl`/`gl` URL parameters** like Google
> Search. The answer language/market follows the **account & UI language** of the
> logged-in session (and, secondarily, the language you write the query in). Use the
> session **as configured for the market being tracked** and **read the page in
> whatever language it actually renders** — the labels below are shown in English
> with the **Russian** strings this session actually uses marked `RU:`. Do not
> assume English UI. The dashboard/report UI language (`--lang`) is a separate,
> downstream choice and does not affect capture.
>
> **Model / mode pins.** DeepSeek's top mode picker (RU: **"Быстрый" / "Эксперт" /
> "Распознавание"** = Fast / Expert / Recognition) and the two composer toggles
> (**"Глубокое мышление"** = DeepThink and **"Умный поиск"** = web search) all
> affect the answer. **Pin: mode = the session default "Быстрый" (Fast)**, **DeepThink
> OFF**, **"Умный поиск" (web search) ON** — do **not** switch to Эксперт/
> Распознавание and do **not** enable DeepThink mid-run (they change the answer and
> its grounding). If a run ever standardizes on another mode that is an
> orchestrator-level decision; absent one, use these pins and capture what they
> produce.

---

## Procedure

> ### Tooling — how to actually read a DeepSeek answer (read this first)
> **Labels vary by locale; the structures are universal.** The structures — a
> **prose answer** (often with a markdown **table**), **inline `[N]` citation
> badges**, a **"Прочитано N веб-страниц"** read-pages header, and the
> **"Результаты поиска"** sources panel — are the same in every locale. English
> labels (with the verified Russian string each, marked `RU:`):
> - composer input **"Message DeepSeek"** (RU: "Сообщение для DeepSeek")
> - new-chat control **"New chat"** (RU: "Новый чат", top-left "+")
> - web-search toggle **"Smart search"** (RU: "Умный поиск") · DeepThink toggle
>   **"Deep thinking"** (RU: "Глубокое мышление")
> - read-pages header **"Read N web pages"** (RU: "Прочитано N веб-страниц") + a favicon row
> - sources side-panel title **"Search results"** (RU: "Результаты поиска")
> - answer footer **"AI-generated, for reference only"** (RU: "Сгенерировано ИИ, только для справки")
>
> Match whatever locale the page is actually in — do not assume English strings.
>
> **Verified live against a real logged-in session (2026-07-08):**
>
> - **`get_page_text` WORKS for DeepSeek** (unlike Google, where it drops the AI
>   block). It returns the **full answer prose + any markdown table + the inline
>   citation numbers at their anchor** (a badge renders inline as its number, e.g.
>   `…тренды-2`, `…X50-6`; a multi-cite renders as adjacent numbers, e.g. `-2 -3`
>   for `[2][3]`), and it prints the **"Прочитано N веб-страниц"** header. **Use
>   `get_page_text` as your primary read** for `answer_text_md`, for **detecting
>   grounding**, and for the **ordered list of inline `[N]` citations**.
> - **`sources` = the "Результаты поиска" (Search results) panel.** Click the
>   **"Прочитано N веб-страниц"** header to open a **right-side panel** listing the
>   retrieved set as **numbered cards `1..N`** (number top-right, favicon +
>   publisher + date + title + snippet). Read the cards' real `href`s via
>   **`read_page(filter="interactive")`**. The panel is **scrollable** and
>   `read_page` surfaces only the cards near the top at first — **scroll the panel
>   down and re-read until all N cards' links are collected** (the header's N tells
>   you how many to expect).
> - **The inline `[N]` badge IS a direct link, and its number IS the source
>   index.** A badge `[N]` in the prose is an `<a href="…">` to the **same
>   publisher URL as source #N** in the panel (verified: the `[10]` badge's href
>   equalled panel source #10). `read_page(filter="interactive")` exposes a badge's
>   `href` **only when it is near the viewport**, so for the **complete ordered
>   list** of citations lean on `get_page_text` (the numbers, in order) and resolve
>   each number to its URL via the **sources panel** (source #N).
> - **URLs are DIRECT publisher URLs** (no Google-style `/url?q=` redirect
>   wrappers), sometimes carrying tracking params (`?utm_*`, a Cloudflare token).
>   `normalize_domain` strips the query string / fragment / path and `www.`, so no
>   unwrapping is needed — store the URL as read.
> - **NEVER click an `[N]` badge or a source card.** Both are **links that open the
>   source site in a NEW TAB** (a stray click both navigates away and can litter a
>   tab you must then clean up). **Every URL you need is already on the DeepSeek
>   page — read its `href` from the tree in place.** If a click accidentally opens a
>   tab, switch back to your DeepSeek tab and carry on reading in place; do **not**
>   visit, read, or "study" the source site.
> - **A correct capture is ~6–12 tool calls with ZERO navigation away from
>   DeepSeek.**

### 1. Open a FRESH chat, pin the grounded config, submit the query
- Use the connected logged-in Chrome. Get tab context (`tabs_context_mcp`) and work
  in **your own tab**; `navigate` to `https://chat.deepseek.com/`. The session must
  be **logged in** (a `/sign_in` redirect means stop — see Guardrails). Keep the
  account/locale **as configured for the market being tracked** — do not change the
  account or UI language.
- **Start a NEW chat for every query.** DeepSeek is a **chat** — a previous
  question's answer stays in context and would poison the next query, and it has
  **no "temporary chat" mode**. Per `(query, lens)` either `navigate` to
  `https://chat.deepseek.com/` fresh **or** click **"Новый чат"** (the "+" top-left)
  and confirm the composer (**"Сообщение для DeepSeek"**) is empty before typing.
- **Pin the grounded config:** mode **"Быстрый" (Fast)**, **"Умный поиск" (web
  search) ON** (its pill is highlighted when armed), **"Глубокое мышление"
  (DeepThink) OFF**. Do not switch models/modes.
- Type the `query` **verbatim** into the composer and submit (press Return, or click
  the send button). **Wait for streaming to finish** — DeepSeek shows a brief search
  phase then streams the answer; wait until the **stop** button reverts to the idle
  **send** button and the **"Сгенерировано ИИ, только для справки"** footer appears.
  Read only the settled answer.

### 2. Detect whether a GROUNDED answer rendered → `overview_present`
This is the **denominator gate** for all visibility metrics — get it right, and per
the box at the top it means **"a GROUNDED answer rendered"** for DeepSeek. **DeepSeek
almost always answers, so a reply alone is NOT the gate.** The gate is **"the model
ran a web search and backed the answer with sources"**: the answer carries the
**"Прочитано N веб-страниц"** header and/or **inline `[N]` badges** and/or the
**"Результаты поиска"** panel. Detect from `get_page_text` (the read-pages header +
inline numbers) and confirm with a screenshot.

Three distinct states:

- **(a) Ungrounded answer — no web search / no sources.** DeepSeek answered from its
  own knowledge: **no "Прочитано N веб-страниц" header, no `[N]` badges, no search
  panel** anywhere. This is a valid "not visible in search" data point, **not an
  error.** Set:
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
- **(c) Grounded answer, target PRESENT.** As (b), but the target appears in prose
  and/or in links. Fill rank arrays, set `brand_in_answer_text` accordingly, and
  write a non-null `sentiment`.

> **Landmark hint (not a selector):** "grounded" = you can see the **"Прочитано N
> веб-страниц"** header (a favicon row + the words), and/or inline **`[N]`** badges
> attached to statements, and/or the **"Результаты поиска"** panel. A bare reply
> with none of these is state (a). Do **not** force a reroll hoping search fires —
> capture what rendered once (see Guardrails).

### 3. Extract `sources` — the full retrieved set (the "Результаты поиска" panel)
- `sources` is DeepSeek's **relied-on / retrieved set** — and it **MUST include every
  domain you cite in step 4** (citations ⊆ sources; see the box after step 4). The
  authoritative list is the **"Результаты поиска" panel**: click the **"Прочитано N
  веб-страниц"** header to open it. The cards are **numbered `1..N`** — that number
  is the citation index used inline (step 4).
- **SCROLL the panel, then collect via `read_page(filter="interactive")`.** The panel
  is **scrollable** and `read_page` typically surfaces only the first few cards at a
  time. The header's **N** says how many to expect — **scroll the panel down and
  re-run `read_page(filter="interactive")` until no new cards appear**, capturing the
  **complete** set of N in **panel (numeric) order**.
- Record links in **panel order** (source #1 → rank 1, …). **Duplicate domains are
  allowed** — keep every occurrence (e.g. the same publisher can legitimately appear
  at several numbers). Do **not** dedupe and do **not** reorder.
- For each, build a `Link`: `{ "rank": <1-based position>, "url": "<full URL>",
  "domain": "<normalize_domain(url)>" }`. `rank` starts at **1**, matches array
  position exactly, and equals the panel's source number.
- **Store the URL as rendered** (direct publisher URL, incl. any `?utm_*` / token
  query). No redirect-unwrapping is needed; `normalize_domain` handles the query
  string, fragment and `www.`. **Never click a card to "get" a URL** — read its
  `href` in place.

### 4. Extract `citations` — the inline `[N]` badges in the prose
- These are the **inline numbered badges** sitting next to statements in the answer
  prose/table — small pills carrying a number, e.g. **`[3]`**, **`[10]`**, or a
  run of them for a multi-cite (**`[2][3]`**). In `get_page_text` they appear inline
  as the bare number at the anchor (walk them **in reading order**).
- **Resolve each badge to a URL by its number.** Badge `[N]` links to the **same URL
  as source #N** in the "Результаты поиска" panel (step 3). Do **not** click the
  badge to expand it (clicking opens the source site in a new tab). Instead map the
  number to the panel entry you already collected. (`read_page(filter="interactive")`
  also exposes a badge's direct `href` when it is near the viewport — useful as a
  cross-check, but the panel is the complete source of URLs.)
- Record one `Link` per badge **occurrence**, **in prose order** (top-to-bottom;
  left-to-right within a statement). **Duplicates allowed** — if `[3]` is cited at two
  places, list it twice; a multi-cite `[2][3]` is two `Link`s. Same `Link` shape and
  same URL handling as step 3. `rank` is 1-based by position **within `citations`**
  (independent of the source number and of `sources` ranks).

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is the answer's **retrieved set** (the "Результаты поиска"
> panel, `1..N`); `citations` are the inline `[N]` badges marking which source backs
> a given sentence. Because **a badge's number IS a source index**, every cited link
> is a source **by construction** — collect the panel fully (step 3) and every cited
> number resolves into it. Still verify: **any domain in `citations` MUST also appear
> in `sources`**, and a non-empty `target_citation_ranks` therefore implies a
> non-empty `target_source_ranks`. If a cited number seems to have no matching panel
> card, you **under-captured the panel** — scroll and re-read (step 3). (The
> `QueryCapture` validator rejects a citation domain absent from sources.)

### 5. Derive `domain` and match the TARGET
- Compute every `Link.domain` with **`normalize_domain`** semantics
  (`pipeline/schema.py`): strip scheme / userinfo / path / query / fragment / port and
  a leading `www.`, **lowercase**, keep the **registrable domain** (last two labels,
  e.g. `blog.example.com → example.com`; multi-part suffixes like `co.uk` preserved →
  three labels). Query strings such as `?utm_source=…` are stripped automatically.
- The target is a **domain OR URL-prefix** (e.g. `example.com` or `github.com/Pupok462`).
  A link **matches the target** iff (a) its registrable domain equals the target's
  registrable domain, **and** (b) if the target has a path, the target's path segments
  are a case-insensitive **prefix** of the link URL's path segments. A target with no
  path keeps the old domain-only behaviour. If the target has a path and the link's
  full URL is unavailable (domain-only entry) or is a redirect wrapper
  (`normalize_domain(url) ≠ link.domain`), it is **NOT** a match — never silently
  over-credit. (DeepSeek URLs are direct, so redirect wrappers are rare here.)

### 6. Compute `target_source_ranks` and `target_citation_ranks`
- Both arrays are computed **deterministically** by
  `pipeline.schema.target_ranks(links, target)` — the self-validation step
  (capture-worker instructions) overwrites whatever you put in the JSON with the
  authoritative result. You do not need to count by hand.
- `target_source_ranks` = every 1-based position in `sources` that matches the target
  (ascending); `[]` if never. `target_citation_ranks` = the same over `citations`.
- **Consistency check (citations ⊆ sources):** if `target_citation_ranks` is non-empty,
  then `target_source_ranks` **must** be non-empty too (you cited the target, so it is
  also a source). A cited target with empty `target_source_ranks` is a capture bug —
  you missed the target's card in the panel; re-read it (step 3).

### 7. Set `brand_in_answer_text`
- `true` iff the **brand NAME** (the given `name`, case-insensitive; allow obvious
  transliterations / locale variants of the same name) appears **in the answer prose**.
- This is about the **name in text**, **independent of any link** — the brand can be
  named with no link (`true`), or linked but never named in prose (`false`). Judge the
  prose only.

### 8. Write `sentiment`
- **One short qualitative phrase**, describing **how the answer treats the target
  domain/brand** — e.g.
  `"recommended as a top pick, cited directly"`,
  `"mentioned neutrally among 6 options"`,
  `"cited for one fact, not discussed"`
  (RU example: `"процитирован как один из источников, нейтрально"`).
- Write it in the **tracked market's language** (the language the answer rendered in)
  so it reads naturally next to the answer prose.
- It is **free text**, **not** a number or label enum. It is **never** aggregated into
  a metric — report/dashboard read it verbatim per query.
- **`sentiment = null` IFF the target appeared nowhere** (not in prose, not in
  `sources`, not in `citations`). If it appeared **anywhere**, write a non-null phrase.
  (Equivalently: `sentiment` is non-null exactly in state (c).)

### 9. Screenshots are transient — do **not** persist; set `screenshot_path = null`
- You **may** take screenshots to visually confirm grounding, but v1 does **not** save
  them as artifacts (and `get_page_text` already reads the answer, so a screenshot is
  optional). Set **`screenshot_path = null`** in your object. Do **not** write any file
  under `data/screenshots/...`.

### 10. RETURN exactly ONE `QueryCapture` JSON object to the orchestrator
- Produce **a single JSON object** matching `pipeline/INTERFACES.md` §1 in shape (see the
  worked example below) and **return it to the orchestrator** — it collects all objects and
  ingests them. **Do NOT run `pipeline.ingest`, do NOT create runs, do NOT write to the
  DB.** You may **read** `pipeline/schema.py` to self-validate first.
- `captured_at` = **now in UTC, ISO-8601** (e.g. `"2026-07-08T20:15:30Z"`);
  `screenshot_path = null`; `engine = "deepseek"`.
- Double-check the §1.2 invariants before returning (ranks 1-based & ascending; empty
  arrays when `overview_present=false`; `sentiment` null-iff-absent; domains normalized;
  citations ⊆ sources).

---

## Guardrails & caveats

- **Login wall / rate-limit / anti-bot.** If DeepSeek redirects to **`/sign_in`**,
  shows a **"server busy" / usage-cap** notice, a Cloudflare/"verify you are human"
  challenge, or any interstitial: **STOP**. Do **not** attempt to solve it, log in,
  switch accounts, or retry in a loop. Leave the challenge **visible in the browser**
  and **surface it to the human** ("login/CAPTCHA on `<query>` — please resolve it in
  the open Chrome window, then tell me to continue"). Resume only after the human
  clears it. Other workers keep going.
- **NEVER click an `[N]` badge or a source card.** Both open the source site in a new
  tab. Read every URL's `href` in place (from the "Результаты поиска" panel and the
  interactive tree). If one opens by accident, switch back to your DeepSeek tab and
  continue — never read the source site.
- **Selectors drift — read semantically.** Everything above ("Прочитано N
  веб-страниц", "Результаты поиска", "Умный поиск", `[N]` badges) is a **landmark
  hint**. Identify blocks by **meaning and rendered text**, not fixed CSS/XPath.
  **Labels are locale-dependent** — match on intent.
- **Pin the mode/toggles; one fresh chat per `(query, lens)`.** Keep mode "Быстрый",
  "Умный поиск" ON, "Глубокое мышление" OFF, and start a **new** chat each time —
  don't reuse a chat (context carryover) and don't switch to Эксперт/Распознавание or
  enable DeepThink.
- **Determinism caveat.** The same query can return a different answer (or decide not
  to search) on repeat — DeepSeek is non-deterministic and may personalize. **Capture
  what rendered right now.** Do not regenerate hoping for a "better" or "grounded"
  answer; one honest capture per invocation. The UTC `captured_at` timestamps exactly
  what you saw.
- **Absence is data, not failure.** An ungrounded answer → `overview_present=false` is
  a **valid, expected** result (it feeds the grounded-answer coverage metric). Never
  fabricate sources, citations, or sentiment to "fill in" a capture.
- **Stay in this engine / this query.** One object per `(query, lens)`. Don't branch
  into other queries, models, or engines. Don't touch the user's existing chats.

---

## Worked example

**Inputs:** `query = "best project management software for small teams"`, `lens = "general"`,
brand `name = "Example"`, target `domain = "https://www.example.com"` (→ normalizes to
`example.com`). Session: logged-in, mode "Быстрый", "Умный поиск" ON.

A grounded answer rendered: a **"Прочитано 6 веб-страниц"** header opened a
"Результаты поиска" panel of 6 numbered sources (the target appeared at **#2 and #5**),
and the prose cited the target inline as **`[2]`** and named "Example". Resulting single
object:

```json
{
  "query": "best project management software for small teams",
  "lens": "general",
  "engine": "deepseek",
  "captured_at": "2026-07-08T20:15:30Z",
  "answer_text_md": "For a small team, the best tool is the one your team will actually keep updated. **Example** is frequently recommended for its clean task board and simple workflows [2]...",
  "screenshot_path": null,
  "overview_present": true,
  "sources": [
    { "rank": 1, "url": "https://www.g2.com/categories/project-management", "domain": "g2.com" },
    { "rank": 2, "url": "https://example.com/product/team-plan", "domain": "example.com" },
    { "rank": 3, "url": "https://www.techradar.com/best/project-management-software", "domain": "techradar.com" },
    { "rank": 4, "url": "https://www.reddit.com/r/SaaS/comments/abc123/best_pm_software/", "domain": "reddit.com" },
    { "rank": 5, "url": "https://example.com/blog/how-to-choose", "domain": "example.com" },
    { "rank": 6, "url": "https://zapier.com/blog/best-project-management-software/", "domain": "zapier.com" }
  ],
  "citations": [
    { "rank": 1, "url": "https://example.com/product/team-plan", "domain": "example.com" }
  ],
  "target_source_ranks": [2, 5],
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

---

## Live audit — 2026-08-12 (scripted fast path)

> Measured by direct probe on a live answer, not inferred. Contract for using any of this:
> [`engines/FAST_PATH.md`](FAST_PATH.md). Raw results: [`bench/ENGINE_AUDIT.md`](../bench/ENGINE_AUDIT.md).
> The scripted read is a **fast path, not a trusted path** — the agent must independently confirm the
> count and spot-check domains; on disagreement discard the script output, read with the agent, and
> report the drift. An empty script result is never evidence that the answer cited nothing.

- **Sources set in one JS call: 11 of 12 with zero clicks; 12 of 12 after one click** on the sources
  counter. Cheapest engine of the seven — two tool calls for the complete set, against this
  playbook's click → scroll-panel → read-cards loop.
- **Confirmed:** all three pinned controls are still there and still named as documented —
  `Быстрый` mode, `Умный поиск` ON, `Глубокое мышление` OFF.
- **Minor drift:** this playbook says the counter reads `Прочитано N веб-страниц` at the top of the
  answer. Live it rendered as **`12 веб-страниц` at the bottom**. Match on meaning (a count of web
  pages read), not on the exact string or position.
- 17 numbered `[N]` badges, and the counter's own "12" matched the 12 distinct URLs.
