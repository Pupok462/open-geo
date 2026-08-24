# Scripted fast path — what a single `javascript_tool` call can and cannot replace

> Measured live on 2026-08-12, one canary query per engine, one browser, sequential.
> Raw probe results and per-engine detail: [`bench/ENGINE_AUDIT.md`](../bench/ENGINE_AUDIT.md).
> **Updated 2026-08-24** for `yandex_neuro` (20-query run 29 + an independent live re-check):
> the React-props section below, and qualification #3 in the hard limits.

Capture stays what it always was: a real logged-in browser reading the rendered answer. What changes
here is only **how the links are lifted off a page that is already open and settled** — the agent
still drives, the script only reads.

## The finding that drives this

`read_page(filter="interactive")` is **viewport-limited and virtualized**. The DOM usually is not.
Several playbooks documented multi-step panel-opening and scrolling procedures that exist purely to
work around `read_page`, not around the page. A single `javascript_tool` call reads the whole DOM at
once and skips all of it:

| engine | sources obtainable in **one** JS call | what the playbook prescribes instead |
|---|---|---|
| `perplexity` | **10 of 10 after ONE click** (switch to the Links tab, then read) — see the correction below | scroll the virtualized panel (~15–50 calls) |
| `claude_search` | **6 of 6** — unchanged across every scroll position | expand research trace → click "N results" → read popup → scroll body |
| `deepseek` | **11 of 12** with zero clicks; **12 of 12** after one click | click the counter → scroll the right panel → read numbered cards |
| `yandex_neuro` | **everything** — full sources list *and* all citations incl. hidden `+N` members, via **React props** (see below) | *(the panel → popup → scroll procedure was removed from the playbook on 2026-08-24)* |
| `google` | possible, **but** see the query-string block below | screenshot-driven read (`get_page_text` drops the AI block — confirmed) |
| `gemini` | **0** — chips are buttons, URLs absent until a popup opens | 24 chips × real click ≈ 48+ calls |
| `chatgpt_search` | primary hrefs only; `+N` members need the hover carousel | see `chatgpt_search.md` |

## Hard limits found by probing (do not assume these away)

1. **JS output containing query strings gets blocked — and NOT only on Google.** A probe returning
   `a.href` came back `[BLOCKED: Cookie/query string data]` on Google, and a capture worker hit the
   same block on **DeepSeek** (2026-08-12). Treat it as a property of the tool, not of one engine:
   **always return `origin + pathname` and never raw `href`.** Harmless in practice — `normalize_domain`
   drops the query string and URL-prefix matching only needs the path — but it does mean a stored
   `Link.url` captured this way is query-stripped, which is fine for matching and slightly lossy for
   provenance. If a full URL is genuinely needed, read it with `read_page` instead.
2. **Synthetic clicks do not work on Gemini.** `HTMLElement.click()` on nine chips opened nothing;
   a real `computer` `left_click` on the same chip opened the popup immediately. Gemini has **no**
   scripted fast path for URLs.
3. **`+N` group *chips* never carry their members** (`perplexity`, `yandex_neuro`, `chatgpt_search`).
   Verified on Perplexity: five `+N` chips were `SPAN`s with no href, while single chips resolved to a
   real URL; same split on Yandex. The chip element and its ancestors are href-free — that part stands.
   **Two qualifications added 2026-08-24 on `yandex_neuro`:** the **popover** a `+N` chip opens *does*
   render real anchors with `href`s (two per card — title + domain label, same href), and the members
   are reachable **without opening anything at all** from React props. "Not in the chip" is not the same
   claim as "not in the DOM" and not the same claim as "not reachable" — check which one you need.
4. **A raw anchor count is not a source count.** Google's AI Overview block held 78 anchors for what
   is roughly a dozen sources — the same article rendered twice, plus `support.google.com` helper
   links and video-carousel items. Per-engine filtering is required; there is no generic rule.

## The DOM is not the only channel — React props (added 2026-08-24, `yandex_neuro`)

A DOM walk reads what the framework chose to render. On a React surface the **data behind** the render
is often still attached to the element, under a `__reactFiber$…` key, and that data can contain what
the UI only shows after a click. On Yandex Alice this is decisive:

- `memoizedProps.sources` on the fiber above the answer block **is** the «Источники» panel —
  `[{url, title, isRKN}, …]`, present whether or not the panel ever opens (and on that engine it often
  will not open at all, whatever you click).
- Each citation chip carries **1-based ids into that array** (`sourceIds` on a `+N` group, `sourceId`
  on a single chip; `0` marks the promo card, which is not a source), so every citation — hidden group
  members included — resolves with **zero clicks**.

Worth probing on any React-rendered engine before designing a click procedure. Two traps found while
implementing it: a chip's child elements **inherit the same props** through the fiber walk, so filter
by DOM ancestry (never by "consecutive duplicates" — six identical adjacent chips are six citations);
and props survive class renames, so key on the props, not on class names. Full detail:
[`engines/yandex_neuro.md`](yandex_neuro.md) § Live audit 2026-08-24.

The verification contract below applies unchanged — this is still a fast path, not a trusted path.

## Correction — the Perplexity "0 clicks" figure is withdrawn

The first audit reported 40 of 40 sources from one JS call **on the Answer tab before any click**. A
real capture worker could not reproduce it: the settled Answer tab held only **11 anchors — the
single, non-group chips** — and the complete set came from the **Links tab (one click)**. The 40
almost certainly appeared because the right-hand sources rail was already expanded during the probe,
so the *panel* put them in the DOM.

Read that as the general lesson for this whole document: **a structural probe measures the page state
it happened to run against.** Numbers here are lower bounds on cost, and any of them can fail to
reproduce on a differently-rendered answer. That is precisely why the contract below is not optional.
Full A/B evidence: [`bench/FASTPATH_AB.md`](../bench/FASTPATH_AB.md).

## What the fast path does NOT buy

Measured end-to-end on Perplexity: baseline **59** tool calls, fast path **51**. The dominant cost is
`citations`, not sources — 22 visible chips expanded to 36 citations, and `+N` members are never in
the DOM, so the hover carousel stays. Skipping it is not an option: the baseline run measured that
doing so undercounts citations by **14 of 36 (39 %)** and loses two domains that appear nowhere as
single chips. Expect the fast path to cut source-discovery cost and leave carousel-heavy engines
roughly as expensive as before.

## The verification contract — non-negotiable

The scripted path is a **fast path, not a trusted path**. Established empirically: a DOM-walking
extractor run three times against one settled ChatGPT answer returned three different results, all
well-formed and confident, two of them wrong
(`bench/notes/chatgpt_search__ai_visibility_2026.md`). Silently-wrong numbers are the one failure
this project cannot ship.

Therefore, whenever a capture uses the scripted path:

- The agent **independently reads the answer** and checks the script's output against what it sees —
  at minimum the source count and a couple of spot domains.
- **Agreement → use the script's output.** **Disagreement → discard it, read with the agent, and
  report the drift.** Never reconcile the two by picking whichever looks nicer.
- **An empty script result is never evidence of absence.** "The script returned nothing" and "the
  answer cited nothing" are different claims; only an agent read can distinguish them.
- Anything the script could not reach (an unexpanded `+N` group, a panel that would not open) is
  named in the worker's status line. A flagged undercount is data; a hidden one is a defect.
