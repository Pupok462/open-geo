# A/B: scripted fast path vs playbook baseline — real end-to-end captures

Six `capture-worker` runs, 2026-08-12. Same query (`best AI search visibility tracking tools`),
same lens (`general`), same target (`otterly.ai` / brand `Otterly`), one worker at a time on one
browser. Arm A followed the playbook with `javascript_tool` **forbidden**; arm B used the scripted
fast path and was bound by the verification contract in `engines/FAST_PATH.md`.

`tool_uses`, `duration_ms` and `subagent_tokens` are **harness telemetry**, not self-reports. The
browser-call columns are the workers' own counts.

## Per-run

| engine | arm | tool_uses | browser MCP calls | browser actions | duration | subagent tokens | n_sources | n_citations |
|---|---|---|---|---|---|---|---|---|
| `claude_search` | baseline | 22 | 17 | 37 | 4 m 32 s | 125 576 | 7 | 6 |
| `claude_search` | **fast** | **18** | **9** | **23** | **3 m 53 s** | **104 628** | 7 | 5 |
| `deepseek` | baseline | 19 | 14 | 29 | 3 m 33 s | 116 595 | 12 | 11 |
| `deepseek` | **fast** | 20 | **7** | **17** | 4 m 20 s | **112 861** | 12 | 25 |
| `perplexity` | baseline | 59 | 54 | 171 | 13 m 01 s | 222 088 | 10 | 36 |
| `perplexity` | **fast** | **51** | **45** | **124** | **12 m 33 s** | **171 873** | 10 | 37 |

## Deltas

| metric | baseline | fast path | delta |
|---|---|---|---|
| tool_uses (sum) | 100 | 89 | **−11.0 %** |
| browser MCP calls (sum) | 85 | 61 | **−28.2 %** |
| browser actions (sum) | 237 | 164 | **−30.8 %** |
| subagent tokens (sum) | 464 259 | 389 362 | **−16.1 %** |
| wall clock (sum) | 21 m 06 s | 20 m 46 s | **−1.5 %** |

Per engine, tool_uses: `claude_search` −18.2 %, `perplexity` −13.6 %, `deepseek` **+5.3 %**
(the one arm that got worse; its wall clock was also +22.3 %). n=1 per cell — a single slow answer
moves these numbers more than the method does.

## Fidelity

**`sources` matched exactly in all three pairs** — 7/7, 12/12, 10/10, same URLs, same order, across
independently generated answers. That is the result that matters: the fast path did not lose or
invent a source in any run, and both `perplexity` workers reported that their independent read
**agreed** with the script output.

`citations` counts are **not comparable** between arms (6 vs 5, 11 vs 25, 36 vs 37): each run
produced a *different answer* with a different number of inline chips. Engine non-determinism, not
extraction fidelity.

## The honest headline: the fast path does not fix the expensive engine

Perplexity cost 59 tool calls at baseline and still cost 51 with the fast path. The expense there is
**citations**, not sources: 22 visible chips expanded into 36 citations, and `+N` group members are
never in the DOM, so the hover carousel is unavoidable. The scripted read removes source *discovery*
cost and leaves the dominant cost untouched. Skipping the carousel is not an option — the baseline
worker measured that it would have undercounted citations by **14 of 36 (39 %)** and dropped
`useomnia.com` and `seo.com` entirely, since neither appears as a single chip anywhere.

## Correction — a claim from the 2026-08-12 audit did NOT reproduce

The audit reported, for `perplexity`, **40 of 40 sources from one JS call on the Answer tab before
any click**. The fast-path worker could not reproduce it: on the settled Answer tab the DOM held
**11 anchors — the single, non-group inline chips only**, not the retrieved set. It obtained the
complete 10-source set by switching to the **Links tab (one click)**, where the script and
`get_page_text` agreed exactly.

Most likely mechanism: during the audit the right-hand **sources rail was already expanded**
(that probe ran on an answer whose panel read "Источники 40"), so those 40 anchors were in the DOM
because the *panel* was rendered — not because the answer body carries them.

**Corrected claim: on Perplexity the source set costs one click (Links tab) plus one read — not
zero clicks.** Still far cheaper than scrolling the virtualized panel, but the "0 clicks" figure was
wrong and is withdrawn. `engines/FAST_PATH.md` and `bench/ENGINE_AUDIT.md` carry the correction.

## Two new traps found by the workers

- **Stale popover nodes read as live.** A naive "find the `k/K` counter" probe returned `1/3` for a
  popover that was already invisible on screen (confirmed against a screenshot). Filtering by
  visibility fixed it. Same failure shape as the three-runs-three-answers result in
  `bench/notes/chatgpt_search__ai_visibility_2026.md`: confident, well-formed, wrong.
- **Fixed coordinates go stale mid-run.** The carousel Next arrow moves between positions, and one
  run had the viewport height change (745 → 689) underneath it. Click the arrow **by ref**, re-read
  the rect per step, never by remembered coordinate.
