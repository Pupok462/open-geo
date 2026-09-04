---
name: semantic-core
description: Build a measured semantic core for a brand through official keyword APIs (Yandex Wordstat for RU, Google Ads Keyword Planner / Bing Webmaster worldwide, autocomplete everywhere), commit it as core.json plus a questions.csv, and hand that straight to an open-geo visibility run. Use when the user wants demand research, a semantic core, keyword volume, or "collect the questions and then measure visibility" — no browser and no manual keyword tool.
---

# semantic-core — measured demand core, then the run

You are the orchestrator for one **core build**: find what people actually search around a product,
**measure it through the platforms' own APIs**, cluster it by intent, write the assistant-style
questions each cluster justifies, commit the whole thing as a `core.json` + `questions.csv`, and hand
that to an **open-geo** visibility run.

Two halves, deliberately separated:

- **Deterministic** — the numbers. `demand/` asks Wordstat / Google Ads / Bing / autocomplete and
  returns each figure *with its scope* (region, period, pull date). No browser, no logged-in session,
  no hand-typed volume. Contract: `pipeline/INTERFACES.md §8`, guide: `demand/README.md`.
- **Agentic** — the judgement. Which angles the product has, how a person phrases the need to an
  assistant, which lines survive a skeptic. Authority: `harvest/METHODOLOGY.md` (§3 demand gate,
  §4 lens invariants, §5 segments).

> Run Python from the open-geo runtime root with its venv (`.venv/bin/python`). Code and intermediate
> JSON are English; the summary you print follows `--lang`.

---

## INVOCATION

```
/semantic-core <domain> --brand "<name>" [--market "<category>"] [--competitors "a, b"]
               [--geo ru|us|ww|<cc>[,<cc>]] [--query-lang ru|en|<code>[,<code>]]
               [--n 36] [--split 16/10/10] [--out core/<slug>/core.json]
               [--run <engine>] [--n-worker N] [--output data|dashboard|pdf|both]
               [--lang en|ru|zh|ar] [--no-run]
```

| arg / flag | required | default | meaning |
|---|---|---|---|
| `<domain>` | yes | — | The product's site. Also the target of the follow-on run. |
| `--brand "<name>"` | yes | — | Human brand name; enforces the lens/brand invariants at commit time. |
| `--market` | no | inferred | Category in the user's words. Inferred from the homepage when absent — always echo the inference for confirmation. |
| `--competitors` | no | — | Seed list; workers extend it. |
| `--geo` | no | `ru` | ISO-3166 alpha-2 lowercase, or `ww` for worldwide. Comma-separated for several markets — each is measured on its own ruler. |
| `--query-lang` | no | follows geo | The language **people search in** — independent of `--lang` (the deliverable language). A distinct language is a distinct slice with its own CSV. |
| `--n` | no | `36` | Target questions across all slices. |
| `--split` | no | derived | `general/branded/comparative`, general-tilted (for 36: `16/10/10`). |
| `--out` | no | `core/<brand-slug>/core.json` | Where the core artifact lands. The CSV goes beside it as `<brand-slug>_questions.csv`. |
| `--run <engine>` | no | ask | Engine for the follow-on open-geo run (`google`, `chatgpt_search`, `yandex_neuro`, …). |
| `--n-worker` | no | ask | Capture concurrency for that run. |
| `--no-run` | no | off | Build and commit the core, stop before the run. |

Missing required values go to **STEP 1** (wizard), never to a guess.

---

## STEP 1 — RESOLVE PARAMETERS

1. Take everything from the invocation. If `<domain>` or `--brand` is missing, ask for them
   (`AskUserQuestion`), one compact question per unknown.
2. Fetch the homepage (`WebFetch`) to infer **market/category** and obvious competitors. Echo the
   inference in one line and let the user correct it — a wrong category poisons every seed.
3. Ask only for what is still unknown: geo(s), query language(s), count, split, and — unless
   `--no-run` — the engine and worker count for the follow-on run.

## STEP 2 — CAPABILITY CHECK (what can actually be measured)

For each geo:

```bash
.venv/bin/python -m demand.doctor --geo <cc>
```

Report the verdict in one line per geo:

- **volume available** — proceed; the core will rest on numbers.
- **presence only** — no volume ruler is configured for that locale. Say **exactly** which
  credential is missing and what it unlocks (the doctor prints the steps), then ask whether to
  (a) proceed presence-only — a core grounded in real autocomplete phrasings but without volume,
  every line marked as such, or (b) pause while the user obtains the key. Never silently downgrade,
  and never fabricate a number to fill the gap.

Carry the verdict into every worker brief: it decides which gate the workers are working under
(METHODOLOGY §3).

## STEP 3 — SEEDS AND SEGMENTS

1. **Root phrases** (5–12): the job the product does, in the words of the market — not the brand's
   marketing words. Derive from the homepage, the category, and competitor positioning.
2. **Segments** (METHODOLOGY §5), derived from the product, not a fixed list: demand-primary,
   demand-secondary, category/discovery, branded-reputation, comparative-rivals, plus supply-side
   for a two-sided product and a per-language slice where a real audience exists.
3. Sanity-check the roots before fanning out — one cheap call each:
   ```bash
   .venv/bin/python -m demand.lookup --geo <cc> --lang <code> --phrase "<root>" --related 10
   ```
   A root with zero demand is a wrong root: fix it here, not in five workers at once.

## STEP 4 — FAN OUT (one `core-worker` per segment, in parallel)

Spawn one `core-worker` sub-agent per segment (Agent tool), all in one message so they run concurrently. Its contract lives in
`../../agents/core-worker.md` — do not restate it. Each brief carries: the product context, its one
segment + dominant lens, the geo/language and the **doctor verdict**, its worker index, the seeds
relevant to it, and its target (2–4 clusters, 6–15 measured phrases, 4–10 questions).

> A core-worker measures through `demand/`, phrases the questions, and returns a `CoreCluster` JSON
> array. It never writes the core, the CSV, or the DB, and never opens a browser.

## STEP 5 — SYNTHESIZE (you)

Merge every worker's clusters and:

- **drop unmeasured clusters** — no phrase with a `provider` + `scope` means no evidence; do not
  rescue it by writing a number yourself;
- **dedup by meaning** across segments (not just by string), keeping the strongest evidence;
- **balance to `--split`** with the general-tilt, maximizing intent diversity inside each lens —
  the GEO opening lives in `general`, where people do not yet know the brand;
- **split by language**: each query language becomes its own slice and its own CSV;
- keep every cluster's phrases attached — the anchor phrase's `scope` becomes the `signal` of every
  question that cluster ships.

## STEP 6 — SKEPTIC PASS

Spawn 1–2 `harvest-skeptic` sub-agents (contract in `../../agents/harvest-skeptic.md`) with the
thesis and the final `{query, lens}` list. Apply the cuts, backfill each from the next-strongest
candidate in the same cluster, and re-run until every shipped line survives. The skeptic cuts
unmeasured lines and lines that overstate a presence-only signal — both are failures of this step,
not of the worker.

## STEP 7 — COMMIT THE CORE

Write the synthesized `SemanticCore` object (INTERFACES §8.3) to a UTF-8 temp file, then:

```bash
.venv/bin/python -m demand.core \
  --out core/<slug>/core.json \
  --questions-out core/<slug>/<slug>_questions.csv \
  --brand "<name>" --domain <domain> --rationale core/<slug>/<slug>_rationale.md \
  < /tmp/open_geo_core_final.json
```

Read stdout `{core, questions_csv, clusters, written, by_lens, coverage, errors}`. **`errors` must be
empty** — the usual causes are a mislabeled lens (general naming the brand, branded not naming it)
and an unmeasured cluster. Fix and re-run until `errors: []`. For a second query language, call it
again with its own `--out` / `--questions-out`.

Then write `<slug>_rationale.md` yourself: per cluster — who we catch, on which measured signals
(quote the `scope` strings), why this lens, which competitors surfaced. This is the provenance the
CSV omits.

## STEP 8 — REVIEW GATE (human-in-the-loop)

Show: total questions, `by_lens`, `coverage` (how many phrases rest on volume vs presence), the
strongest and weakest clusters by measured volume, and the full query list. Ask (`AskUserQuestion`):
**Apply** / **Edit** (adjust rows, re-run STEP 7 until `errors: []`) / **Discard**. Never go straight
to capture on a freshly generated set without the operator seeing it.

## STEP 9 — HAND OFF TO THE RUN

Unless `--no-run`, invoke the **open-geo** skill with the committed artifacts:

```
/open-geo <questions_csv> <engine> <domain> --brand "<name>" --n-worker <N> \
          [--output …] [--lang …]
```

`core.json` is the carrier: it records `questions_csv`, `brand`, `domain` and `totals.coverage`, so
the run reads one file and cannot mismatch the set it measures. open-geo takes its STEP A.5 fast
path — a committed core and a hand-made CSV are indistinguishable downstream.

Finish with a short summary in `--lang`: where `core.json` and the CSV are, questions by lens,
coverage (volume vs presence), which providers answered, and the run that was started (or the exact
command to start it later).

## Boundaries

- Numbers come from `demand/`; judgement comes from you and the workers. Neither substitutes for the
  other.
- **Never invent a volume**, and never present a presence-only signal as measured demand.
- The commit path is `demand.core` → `harvest.build`: same CSV invariants as every other question set
  in this project. Nothing downstream of the CSV changes.