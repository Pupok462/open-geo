# Fixture notes — `chatgpt_search__ai_visibility_2026`

## Why this fixture

It exercises every hard edge of the `QueryCapture` contract at once:

- **Grounded answer, target present in prose but absent from every link.** `Otterly` is named in
  the shortlist table and gets its own "best inexpensive starting point" pick, yet `otterly.ai`
  appears in no source and no citation. The correct capture is therefore
  `brand_in_answer_text = true`, **both rank arrays empty**, and **`sentiment` non-null** (the rule
  is `sentiment` is null *iff* the target appeared **nowhere** — prose counts).
  Two natural model errors are visible here: filling rank arrays because the brand "is mentioned",
  and nulling `sentiment` because there is no link.
- **Duplicate domains in order.** `getrefine.ai` legitimately occupies ranks 1, 2 and 4 — dedup or
  reorder is wrong.
- **Only one URL is reachable through `read_page`.** The remaining six live in the DOM dump. A model
  that emits URLs present in neither artifact is fabricating.

## How ground truth was derived

Strictly from the three pristine artifacts in this directory — nothing else. `citations` = the seven
`<a href>` chip occurrences in `03_dom_links.json`, in reading order, each taken at its primary
(named) href, per `engines/chatgpt_search.md` step 4. `sources` = the same set, because this build of
ChatGPT renders **no Sources panel** (see drift finding below), so the retrieved set is not otherwise
observable; `citations ⊆ sources` holds trivially.

**Known ambiguity.** Anchor `i=0` is a single `<a>` whose inner text carries **two** chip labels
(`Refine AI +2` / `Lyra +2`) but exposes one href. A capture that emits 8 citations, inserting
`trylyra.ai` at rank 2, is a defensible reading. The scorer therefore leads with **multiset F1 over
domains** and reports exact-sequence match separately, so this ambiguity shows up without dominating
the result.

## Drift finding (not part of the benchmark — a real bug in the playbook)

`engines/chatgpt_search.md` step 3 instructs the worker to open an end-of-answer **"Sources" /
"Источники" panel** and read the complete retrieved set from it. **That panel does not exist in this
build.** Probed directly: zero elements anywhere in the document whose text is
`Источники|Sources|Цитаты|Citations`, and the only button inside `main` is `Размышление`.

What replaced it: a `+N` badge on a chip opens a **hover carousel** (`1/3`, prev/next arrows) — the
same mechanic already documented for Perplexity. Consequences for the playbook:

1. `sources` can no longer be captured as written; following the playbook literally makes a worker
   hunt for a control that isn't there.
2. Group members are reachable **only** by cycling the carousel, so any capture that reads chips
   alone **undercounts** the retrieved set.
3. Chip labels **mutate while the carousel is cycled** (the first chip read `Refine AI +2` pristine
   and `Baarely Refine AI` after cycling) — labels are not a stable key, only `href` is.

## In-page extractor: three runs, three answers

A DOM-walking extractor was prototyped live against this same settled page — hover each chip,
enumerate its carousel, collect hrefs. It ran three times on **the same answer**:

| run | result |
|---|---|
| 1 | groups enumerated coherently: `{getrefine.ai, trylyra.ai, baarely.com}` per group, `techradar.com`, `arxiv.org`, `reddit.com` present |
| 2 | `reddit.com` **silently dropped**; first chip collapsed to a single member |
| 3 | all seven chips reported the *same* 3-member group; `techradar.com`, `arxiv.org`, `reddit.com` **all gone** |

Cause: cycling a carousel rewrites the chip's own label and leaves popup nodes in the DOM, so
chip↔group association and the `+N` test both decay as the pass proceeds. The failure mode matters
more than the cause: every run returned **well-formed, confident, plausible JSON**, and runs 2 and 3
were wrong. Nothing in the output distinguished them from run 1.

That is the exact failure class this project treats as existential (moat #3), and it is the argument
for the verification layer: a scripted extractor may be the fast path, but it may not be the
*trusted* path until an independent agent read agrees with it on a canary set.
