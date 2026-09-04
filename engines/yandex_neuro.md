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

- `query` — the exact string to put to Alice. Send it **verbatim** (via the URL, not the
  composer — step 1).
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
> ### The React-fiber read is the primary route on this engine
> Everything a capture needs — the **complete sources list** *and* **every citation,
> including the members hidden behind `+N`** — sits in the page's React props and comes
> out of **one `javascript_tool` call with zero clicking** (step 3). Clicking the UI is
> now the **fallback**, not the plan: the **"Источники" button is genuinely unreliable**
> (4 opens in ~10 attempts across run 29; 0 opens in 5 clicks on 2026-08-24 with the pointer
> verified to be over the button — see the live audit at the bottom), while the fiber data is there whether
> or not a panel ever opens. This **replaces** the click-every-chip / open-the-panel
> procedure that steps 3–4 used to prescribe.
>
> **Three tools, three jobs:**
> - **`sources` + `citations` → `javascript_tool` over the React fiber.** One call
>   returns the panel list and the full chip sequence with their source ids (step 3).
> - **Prose, cited domains in order, `+N` counters, "Промо" markers → `get_page_text`.**
>   Unlike Google (where `get_page_text` silently drops the AI block), on Alice the answer
>   **IS** the page's main content, so `get_page_text` returns the **full prose** with each
>   inline chip's **domain text and `+N` counter inline** (e.g. `fluidwave.com +1`), and it
>   clearly marks **"Промо"** ad cards. Use it for `answer_text_md` — **and as the
>   mandatory cross-check on the script's output** (see the verification box in step 4).
> - **Confirm grounding + see anything you must see → `computer` (action=screenshot).**
>   A screenshot shows whether the answer is **grounded** (inline source chips and/or
>   the "Источники" button present) and is the only way to check a computed rect.
> - `read_page(filter="interactive")` still works for **single** chips (they are real `A`
>   elements with direct hrefs) and for the panel when it happens to be open, but it is
>   viewport-limited and virtualized — it is no longer the collection path.
> - **Every URL you need is already on the Alice page — read it from the fiber or from a
>   `href` in place. NEVER navigate to a cited/source website** (it wastes calls and trips
>   the source site's own CAPTCHA). A correct capture is **~5–8 tool calls with ZERO
>   navigation away from `yandex.ru/alice`.** If a click accidentally leaves Alice or opens
>   a new tab to a source/ad site, **close that tab / go back immediately** — never proceed
>   on, read, or "study" a source site.

### 1. Open a FRESH Alice chat and submit the query
- **Start a NEW chat for every query.** Alice is a **chat** — a previous question's
  answer stays in context and would poison the next query.
- **Do NOT type the query. Navigate it in.** Typing is the weakest link on this engine
  (dropped spaces, a server-synced shared draft, `Return` that does not submit). The
  deterministic entry, verified live on 2026-08-24:
  1. `navigate` to `https://yandex.ru/search/?text=<urlencoded query>`
  2. one `javascript_tool` call that reads the **"Алиса AI"** tab's anchor and assigns it:
     ```js
     const a = [...document.querySelectorAll('a')]
       .find(x => /алиса/i.test(x.textContent || ''));
     location.href = a.href; 'go'
     ```
  3. wait, then **confirm the tab settled on `https://yandex.ru/alice/chat/<id>/`.**

  The query arrives **verbatim in a fresh chat**, bypassing the composer entirely.
- **Assign `location.href` — do not click the "Алиса AI" tab by coordinates.** In run 29
  the coordinate click failed twice and once left the worker on the **SERP with an inline
  quick answer**: a *different surface with a different generation*. A capture taken there
  is a wrong measurement that looks perfectly well-formed. Always verify the URL is
  `/alice/chat/<id>/` before reading anything.
- If you ever must fall back to typing: `cmd+a` + `Backspace`, type, **verify the box in a
  screenshot**, then submit with the send **ARROW** — `Return` opens the autocomplete
  suggestion list and leaves the query **unsent** (still true on 2026-08-24).
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

### 3. Extract `sources` and the chip map — ONE `javascript_tool` call over the React fiber
- `sources` is Alice's **relied-on / retrieved set** — the same list the **"Источники"**
  panel renders — and it **MUST include every domain you cite in step 4** (citations ⊆
  sources; see the box after step 4).
- **Read it from the React fiber, not from the panel.** The fiber above the answer block
  carries **`memoizedProps.sources`**: an array of `{ url, title, isRKN }` **in panel
  order**. This *is* the panel — verified against real, opened, screenshotted panels on
  three run-29 queries (same count, same order) and re-verified on 2026-08-24. It is
  present **whether or not the panel ever opens**, which matters because the panel
  frequently does not (see the live audit).
- The same call also returns **every inline chip in prose order** with its **1-based ids**
  into that array, which is what step 4 needs. Run it once, on a **settled** answer:

```js
const K  = el => Object.keys(el).find(k => k.startsWith('__reactFiber$'));
const up = (el, pred, max) => {                    // walk the fiber up from a DOM element
  let f = el[K(el)], d = 0;
  while (f && d < max) { const p = f.memoizedProps; if (p && pred(p)) return p; f = f.return; d++; }
  return null;
};

// 1. the sources array — the «Источники» panel, opened or not
let sources = null;
for (const el of document.querySelectorAll('*')) {
  if (!K(el)) continue;
  const p = up(el, q => Array.isArray(q.sources) && q.sources.length, 6);
  if (p) { sources = p.sources; break; }
}

// 2. every inline chip, in prose order, with its 1-based ids into `sources`
const hasIds = q => Array.isArray(q.sourceIds) || (q.sourceId !== undefined && q.hostname);
const cand   = [...document.querySelectorAll('*')].filter(el => K(el) && up(el, hasIds, 10));
const set    = new Set(cand);
const chips  = cand
  .filter(el => { let p = el.parentElement; while (p) { if (set.has(p)) return false; p = p.parentElement; } return true; })
  .map(el => {
    const p = up(el, hasIds, 10);
    return { ids: (p.sourceIds ? [...p.sourceIds] : [p.sourceId]).sort((a, b) => a - b),
             label: (el.innerText || '').trim() };
  });

JSON.stringify({ sources: sources.map((s, i) => ({ id: i + 1, url: s.url, title: s.title })), chips });
```

- **What the ids mean.**
  - Ids are **1-based positions in `sources`**. `sources[id - 1]` is the link.
  - **`id === 0` means "not a source" — that is the Промо card.** Verified 2026-08-24: the
    promo advertiser's link renders as a footnote-shaped chip carrying `sourceId: 0`, while
    the `sources` array held only the organic entries. **Drop every chip whose id is 0**;
    never look it up in `sources`.
  - A **`+N` group** carries `sourceIds` (plural, shallow in the fiber). A **single chip**
    carries `sourceId` (singular, deeper — next to `url` / `hostname` / `title`) and is also
    a real `A` with a direct href, so it can be spot-checked without the fiber.
  - **Array order is not render order.** The popover renders members **sorted by id
    ascending**; the chip's own label shows the domain of the **first id in array order**.
    Measured: `sourceIds = [6, 3]` rendered `medesk.ru` (3) above `rechka.ai` (6) and was
    labelled `rechka.ai +1`. Sort ascending — that reproduces what a human would read.
- **Two pitfalls in the script itself (both cost a real run):**
  - **Filter by element ancestry, never by value.** A chip's inner icon span inherits the
    same props through the fiber walk, so a naive scan returns every group twice. The
    filter above drops any element that has an already-matched ancestor.
    **Do not "collapse consecutive duplicates" instead** — six adjacent single chips
    pointing at the same source are **six citations** (measured 2026-08-24), and
    consecutive-dedupe reports one.
  - **Do not key on class names.** `FuturisFootnoteGroup` / `FuturisFootnote` are what they
    are called today; the script above keys on React props precisely so it survives the
    rename.
- Build `sources` from the array **in order**: for each entry a `Link`
  `{ "rank": <1-based position>, "url": "<full URL>", "domain": "<normalize_domain(url)>" }`.
  Keep **duplicate domains** — the same site can be listed twice with different pages.
  Do **not** dedupe, do **not** reorder.
- **The array already excludes Промо.** Confirmed at scale: promo cards rendered on 9 of 20
  run-29 queries, and **no promo entry ever appeared in `sources`**. You still exclude promo
  chips by their `id === 0` (previous bullet) and you still keep promo copy out of
  `answer_text_md`.
- ⚠️ **Do NOT filter `yandex.ru` hosts.** Filtering the promo redirect wrapper
  `yabs.yandex.ru` with a rule like `/(^|\.)yandex\.ru$/` **silently deletes real organic
  sources**: run 29 saw **`direct.yandex.ru`** as a genuine source on queries 6 and 8, and
  **`yandex.ru/maps/org/...`** on queries 12 and 20. Exclude promo by **`id === 0` / the
  "Промо" label**, never by host. (A Maps *org card rendered as a UI block* is still not a
  source; a `yandex.ru/maps/org/...` entry **inside the sources array** is.)

> **Fallback when the fiber read comes back empty.** `sources === null` means the fiber
> shape drifted (or the answer is not grounded — check with `get_page_text` first; an empty
> script result is **never** evidence that the answer cited nothing). Only then fall back to
> the UI: try the **"Источники"** button (expect it to fail — see the live audit), and click
> each chip to read its popover. **The popover DOES render real anchors with `href`s** — two
> per card (title + domain label, same href), so consecutive-dedupe them there. If the panel
> never opens, build `sources` = unique cited links in first-appearance order, which keeps
> `citations ⊆ sources` but **drops retrieved-but-uncited sources**: report such a row as a
> flagged undercount, since a panel-only appearance of the target cannot be ruled out.

### 4. Extract `citations` — the inline chips, expanded through the chip map
- The chips from step 3 **are** the citations, already in prose order. For each chip, in
  order, emit **one `Link` per id** — a `+N` chip therefore contributes **N+1** links, its
  hidden members included, with **no clicking at all**. Ids are already sorted ascending,
  which is the order the popover shows.
- `url` = `sources[id - 1].url`; `domain` = `normalize_domain(url)`. `rank` is 1-based by
  position **within `citations`** (independent of `sources` ranks).
- **Skip chips with `id === 0`** (Промо). **Duplicates are kept** — if the same link is
  cited twice, list it twice.
- **Never navigate to a cited website** — every URL comes from the `sources` array.

> **⚠️ Verification is mandatory — the fast path is not a trusted path**
> (`engines/FAST_PATH.md`). Before you use the script's output, read the answer with
> `get_page_text` and check the **chip sequence** it prints inline in the prose against the
> `chips` array: same **count**, same **order**, same **domain labels**, same **`+N`
> counters** (a chip with `ids.length = k` must read `+{k-1}`). Also check
> `max(id) <= sources.length`. Run 29: **20 of 20 queries matched**; the 2026-08-24 re-check
> matched **21 of 21 chips** on one answer, including six identical adjacent `medesk.ru`
> chips and a `[6,3]` group.
> **Agreement → use the script's output. Disagreement → discard it, read with the agent,
> and report the drift.** Never reconcile the two by picking whichever looks nicer.

> **`citations` ⊆ `sources` — citations are a SUBSET of sources, not an independent
> channel.** `sources` is Alice's **relied-on / retrieved set**; `citations` are the inline
> chips marking which source(s) back specific sentences. With the id map this invariant is
> **structural** — every citation is looked up *inside* `sources` — so it can only break if
> you hand-edit one of the two arrays. Concretely: **any domain in `citations` MUST also
> appear in `sources`**, and a non-empty `target_citation_ranks` therefore implies a
> non-empty `target_source_ranks`.

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
- **Exclude promotional/ad links** (Промо-карточки) from `sources`/`citations` before
  matching — these are ads, not organic sources. Identify them by **`id === 0` in the chip
  map** (step 3) or by the **"Промо"** label, **never by host pattern**: a `yandex.ru`
  filter deletes real sources (see the ⚠️ bullet in step 3).
- **A promo card can point at the TARGET domain — exclude it anyway.** Run 29 query 14
  carried a promo card for `lp.zabota.tech`, the target's own domain. It was correctly kept
  out, and `lp.zabota.tech` still counted normally on queries 15 and 17 where it appeared as
  a legitimate organic source. Paid placement is not visibility; counting it inflates the
  brand's own score with its own ad spend.

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
  (= the fiber `sources` array) and the **inline citation chips** are real grounding. (This
  is the main Yandex-specific trap; Google's overview does not interleave ads this way.)
  The array itself already excludes promo, and promo chips carry `id === 0` — exclude by
  **that**, not by host: `direct.yandex.ru` and `yandex.ru/maps/org/...` occur as **genuine**
  organic sources (step 3).
- ⚠️ **Account memory contaminates sequential queries — `--n-worker 1` does not fix it.**
  One worker per account removes *cross-worker* contamination, but Alice also personalises
  from **earlier queries in the same chunk**, even though each query gets a fresh chat. Run
  29, query 11: «Это напрямую связано с вашими запросами про RFM», «это отвечает на ваш
  вопрос про отзывы», «Учитывая ваши прошлые вопросы про автоматизацию в медицинском центре
  и CRM». With the usual `general → branded` ordering, the **branded** answers — the ones
  the whole measurement is about — are the contaminated ones. Countermeasures, in order of
  preference: (1) **shuffle the lens order** so branded queries are not all downstream of
  the general ones; (2) clear the account's Alice history / use a memory-free session
  between queries; (3) if neither is possible, **say so in the worker's status line** so the
  run is read as personalised rather than clean. An answer that references *other queries*
  is evidence of contamination — capture it as it rendered, and flag it.
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

Alice returned a **grounded** answer. The fiber `sources` array held **10 entries**
(= what the "Источники" panel would render; duplicates kept — `robotobzor.ru` appeared
twice), with `ixbt.com` at **source position 3**; `ixbt.com` was also carried by an inline
`+N` chip (`sourceIds` including id `3`), landing at **citation position 3**; and the brand
name "iXBT" was **not** spelled out in the prose (linked only). A "Промо" `ozon.ru` card was
present, carried `sourceId: 0`, and was **excluded**. Resulting single object:

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

---

## Live audit — 2026-08-17 (20-query run, 3 parallel workers, one account)

> Observed independently by all three capture workers on the same run. These are **input-integrity**
> findings: each one can produce a confident, well-formed capture of the **wrong query** — the failure
> mode this project exists to prevent.
>
> ⚠️ **Four claims in this section were corrected by run 29 (2026-08-24)** — they are marked inline
> below. Read the 2026-08-24 audit at the bottom for what replaced them.

### ⚠️ ORCHESTRATOR: prefer `--n-worker 1` on this engine

Not for quota reasons (that is Perplexity) — for **cross-worker contamination on one Yandex account**:

- **The compose draft is server-synced across sessions.** Another worker's query text arrived
  pre-filled in a worker's input box and its own text was appended to it — three separate times.
  Mandatory countermeasure: `cmd+a` + `Backspace`, then **verify the box in a screenshot before
  sending**.
- **Alice personalises from account memory shared by the parallel workers.** One answer opened with
  «вы интересовались превентивной медициной и нутрициологией» — drawn from a *different* worker's
  queries. Parallel chunks on one account are therefore **not independent samples**.
- **Only the window's active tab receives key/mouse input.** With workers competing, `type` silently
  dropped spaces (`example person` → `exampleperson`), `cmd+a` intermittently failed, and one tab
  received no mouse input at all for a stretch.

### Typing is the weak link — two verified workarounds

- **Skip typing entirely:** navigate to `https://yandex.ru/search/?text=<query>` and go to the
  **«Алиса AI»** tab. This submits the exact query verbatim into a fresh chat, bypassing the composer,
  the shared draft, and the space-dropping bug at once. Preferred entry when it is available.
  ⚠️ **Corrected 2026-08-24: do not *click* the tab — assign `location.href` from its anchor.** The
  coordinate click failed twice in run 29 and once landed the worker on the **SERP inline quick
  answer**, a different surface with a different generation (step 1).
- If you do type: type → **verify** → clear → retype. `computer type` drops spaces on the **first**
  typing attempt after page load. A query sent without spaces is a silently-wrong measurement.

### Render lag and the «Источники» button

- **The rendered view lags the tab state.** `get_page_text` kept returning the empty `/alice/` greeting
  while the tab had already navigated to `/alice/chat/<id>/`; screenshots went stale mid-run. Fix:
  read the chat id from tab context and **`navigate` to the chat URL again** (the trick already
  documented for Gemini), sometimes twice. One answer stuck mid-stream completed only after a reload.
- ⚠️ **WITHDRAWN — "the «Источники» button often needs 2–4 clicks" understates it badly.** Run 29
  opened the panel on **4 attempts out of ~10**, and a 2026-08-24 re-check failed **5 times out of 5** —
  clicking both the computed rect centre and the button position read off a screenshot, with
  `elementFromPoint` confirming the pointer sat on `BUTTON.FuturisSourcesButton`. See the 2026-08-24 audit for the
  full list of what does not work. The panel is no longer on the critical path — read the fiber (step 3).
  When it *is* closed, its markup is simply **absent from the DOM**, so "no panel nodes" says nothing
  about the answer. Historical fallback, still valid when the fiber read fails: `sources` = unique cited links in first-appearance order, which keeps
  `citations ⊆ sources` **but drops retrieved-but-uncited sources** — report such rows as a flagged
  undercount, since a **panel-only appearance of the target cannot be ruled out** there (in this run
  the target appeared **only** in the panel on one query, so the risk is real, not theoretical).
- **Do not trust a computed rect blindly**: `querySelectorAll('button')` matching «Источники» returned
  a rect ~215 px left of the visible button in one state. Verify against a screenshot.
- **Bare `element.click()` never opens a chip popover** (same limitation as Gemini). A real
  `computer left_click` works; where clicks were not delivered, a **full synthetic pointer sequence**
  (`pointerover/enter/move` + `mouseover/enter/move` + `pointerdown/mousedown/pointerup/mouseup/click`)
  worked. Press `Escape` to dismiss a popup before locating the next chip — a popup covering the next
  chip's coordinates caused a mis-click that opened a source site.

### Fast path — confirmed, with a correction to step 3

One `javascript_tool` call over the whole DOM returns the **complete** «Источники» panel (14, 21, 15,
22, 13 entries measured) with **no panel scrolling**: the playbook's "scroll the popover until no new
cards appear" is a **`read_page` limitation, not a page one**. Panel anchors separate from body chips
by `getBoundingClientRect().left > ~1050` (CSS px at a 1440 viewport); panel cards render **two anchors
with the same href** (domain label + title) — consecutive-dedupe them. Still a **fast path, not a
trusted path** (`FAST_PATH.md`): every worker cross-checked script output against `get_page_text` chip
order and `+N` counts before using it.

⚠️ **WRONG — "`+N` popup cards carry no `href`" is withdrawn.** Re-checked live on 2026-08-24: the
popover a `+N` chip opens renders **real anchors with real `href`s** — two per card (title + domain
label, same href), matching the sources array exactly. Run 29 read 5 URLs including `zabota.tech/` out
of the `klientiks.ru +4` popover. What genuinely carries no href is the **`SPAN.FuturisFootnoteGroup`
chip itself** (and none of its ancestors) — that is hard limit #3 in `FAST_PATH.md`, and it stands.
The href-diff that returned `[]` was measuring the wrong nodes.

### Промо exclusion — confirmed at scale

Promo cards appeared on **~12 of 20** queries (lantox.ru, profi.ru, miin.ru, genosys.ru, nadpo.ru,
uom-education.online, avdoshenkoschool.com, imin.ru, mizomed.ru, fr-ekolaser.ru, genotek.ru, ddma.me,
edprodpo.com) and were excluded. Their links are **`yabs.yandex.ru` redirect wrappers**.
⚠️ **WRONG — "so filtering `yandex.ru` hosts drops them automatically" is withdrawn and harmful.**
Run 29 found `direct.yandex.ru` as a **genuine organic source** (queries 6, 8) and
`yandex.ru/maps/org/...` likewise (queries 12, 20); a `/(^|\.)yandex\.ru$/` filter deletes them
silently. Exclude promo by **`id === 0` in the chip map / the "Промо" label**, never by host.
Two adjacent traps: a promo advertiser's domain may **also**
appear legitimately inside the panel (`biogotchi.genotek.ru` did) — keep the panel entry; and
**Yandex Maps organisation cards** (universities, clinics) are org cards, **not sources** — exclude them.

---

## Live audit — 2026-08-24 (run 29: «Забота 2.0» / `zabota.tech`, 20 queries, `--n-worker 1`)

> Everything below was measured on the live surface: by the run-29 capture worker across 20 queries,
> and re-verified independently on 2026-08-24 on a fresh answer (query «как выбрать CRM для частной
> клиники», 9 sources, 21 chips) before being written here. Where it contradicts the 2026-08-17 audit,
> that section is marked ⚠️ inline and **this one wins**.

### 1. The «Источники» panel is unreliable — treat it as optional, not as the source of truth

- Run 29: the panel opened on **4 attempts out of ~10**. The 2026-08-24 re-check: **0 opens in 5
  clicks** — at the computed rect centre and at the button position read off a screenshot, with
  `document.elementFromPoint` confirming the pointer was over `BUTTON.FuturisSourcesButton`.
- **Nothing reliably opens it.** Verified not to work: real `computer left_click` on computed
  coordinates, clicks on a `read_page` `ref`, full synthetic pointer sequences
  (`pointerover/enter/move` + `mouseover/enter/move` + `pointerdown/mousedown/pointerup/mouseup/click`),
  `Enter` on the focused button, and calling the React `onClick` prop directly. (The `ref`, `Enter` and
  `onClick` variants are the run-29 worker's; the 2026-08-24 re-check covered real coordinate clicks.)
- **While it is closed, the panel's markup is not in the DOM at all** — so "the DOM has no panel" is
  not evidence about the answer, only about the panel.
- The **chip popovers behave differently and open fine** on a real click (first try in the re-check).
  The unreliability is specific to the «Источники» button.
- The old "2–4 clicks" figure is **withdrawn**. So is the panel-scrolling procedure — that was a
  `read_page` limitation, not a page one.

### 2. React fiber replaces both the panel and every chip click

- The fiber above the answer block carries **`memoizedProps.sources` = `[{ url, title, isRKN }, …]`**,
  and **that array is the «Источники» panel** — verified against panels that did open and were
  screenshotted on run-29 queries 1, 2 and 4 (same count, same order), and again on 2026-08-24.
- Each inline chip carries its ids into that array: a **`+N` group** has **`sourceIds`** (plural,
  ~2 fiber hops up), a **single chip** has **`sourceId`** (singular, ~7 hops up, next to
  `url`/`hostname`/`title`). Ids are **1-based**; **`0` = not a source** and is what the **Промо**
  card's link carries.
- The popover renders group members **sorted by id ascending**, while the chip's label shows the
  **first id in array order** — measured: `sourceIds = [6, 3]` → popover `medesk.ru` (3) then
  `rechka.ai` (6), label `rechka.ai +1`. Sort ascending.
- Net effect: **the complete source list and all citations, `+N` members included, come out of one
  `javascript_tool` call with zero clicks.** The click-through procedure in the old steps 3–4 is gone.
- **Known script trap:** exclude **descendant** elements (a chip's icon span inherits the same props
  through the fiber walk and doubles every group). Do **not** substitute "collapse consecutive
  duplicates" — the 2026-08-24 answer had **six identical adjacent `medesk.ru` chips**, which that
  shortcut would report as one.
- **Verification held:** script chip sequence vs. `get_page_text` chip domains and `+N` counters —
  **20/20 queries** in run 29, **21/21 chips** in the re-check.

### 3. `+N` — both earlier formulations were wrong

- The chip itself is a `SPAN.FuturisFootnoteGroup` with **no href on it or any ancestor** — hard limit
  #3 in [`FAST_PATH.md`](FAST_PATH.md) is correct.
- **But the popover it opens renders real anchors with `href`s** (two per card: title + domain label,
  same href). The 2026-08-17 note "popup cards carry no href" is **withdrawn**. Run 29 read 5 URLs,
  `zabota.tech/` among them, out of the `klientiks.ru +4` popover.
- Neither matters for a normal capture any more: the fiber gives the same URLs without opening
  anything. The popover is the fallback path.

### 4. Query entry: navigate, never type, never click the tab

- `Return` still does not submit the composer.
- Typing is unnecessary: `https://yandex.ru/search/?text=<q>` → assign `location.href` from the
  **«Алиса AI»** tab's anchor → the query lands **verbatim in a fresh chat**, deterministically.
- **Clicking that tab by coordinates is the failure mode**: it failed twice in run 29 and once left the
  worker on the **SERP inline quick answer** — a different surface with a different generation, i.e. a
  well-formed capture of the wrong thing. Confirm the URL is `/alice/chat/<id>/` before reading.

### 5. Domain filtering: never blanket-filter `yandex.ru`

`direct.yandex.ru` appeared as a **real organic source** on queries 6 and 8, and `yandex.ru/maps/org/…`
on queries 12 and 20. The tempting rule `/(^|\.)yandex\.ru$/` — meant to drop the `yabs.yandex.ru`
promo wrappers — **silently deletes those**. Exclude promo by chip `id === 0` / the "Промо" label.

### 6. Промо exclusion works, including against the target's own domain

Promo cards rendered on **9 of 20** queries, and **no promo entry ever appeared in the fiber `sources`
array**. The instructive case: query 14's promo card pointed at **`lp.zabota.tech` — the target's own
domain** — and was correctly excluded, while the same `lp.zabota.tech` counted normally on queries 15
and 17, where it appeared as a legitimate organic source. Paid placement is not visibility.

### 7. ⚠️ `--n-worker 1` does not stop self-contamination

One worker per account fixes *cross-worker* leakage (2026-08-17), **not** contamination between
**consecutive queries of the same chunk**, despite each query getting a fresh chat. Run 29, query 11:
«Это напрямую связано с вашими запросами про RFM», «это отвечает на ваш вопрос про отзывы», «Учитывая
ваши прошлые вопросы про автоматизацию в медицинском центре и CRM».

With the usual `general → branded` ordering this lands specifically on the **branded** answers — the
ones the measurement is about. Recommended: **shuffle lens order** and/or clear Alice history between
queries; when neither is possible, **flag the run as personalised** in the worker's status line.

> **Open item (not implemented):** a per-run warning field in the report — something like
> "answers may be personalised by account memory" — so a reader of the PDF/dashboard sees this without
> reading capture logs. Deliberately not added to `QueryCapture` here; it needs a schema decision.
