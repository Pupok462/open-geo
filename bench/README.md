# `bench/` — frozen-capture extraction benchmark

Measures **one thing only**: given a real engine answer already frozen to disk, how well does a
model turn it into a valid `QueryCapture`? Browser driving is deliberately excluded — the page is a
file, so every candidate sees byte-identical input and the run is reproducible.

## Layout

| path | what |
|---|---|
| `fixtures/<id>/` | the frozen page: `meta.json` + verbatim tool outputs (`get_page_text`, `read_page`, DOM dump) |
| `truth/<id>.json` | hand-verified `QueryCapture` — **kept out of the fixture dir so candidates cannot read it** |
| `notes/<id>.md` | how truth was derived, ambiguities, drift found while capturing |
| `candidates/<model>.json` | one candidate output per model under test |
| `task.md` | the instruction handed to every candidate |
| `score.py` | deterministic scorer |

## Run

```bash
.venv/bin/python -m bench.score --fixture bench/fixtures/<id> --truth bench/truth/<id>.json --candidates bench/candidates
```

Candidates are produced by spawning one sub-agent per model, each pinned with the Agent tool's
`model` override, all given `task.md` and forbidden from reading `truth/` and `notes/`.

## What is scored

No composite index — the same principle as the product's metrics. Two tiers, reported separately:

**Hard gates** (a failure here makes the capture unusable, not merely imprecise): schema validity,
`overview_present`, `brand_in_answer_text`, `sentiment` null-iff-absent, both target rank arrays,
and **fabrication** — any emitted URL not literally present in a fixture artifact.

**Fidelity**: multiset precision/recall/F1 over `sources` and `citations` domains, exact-order match,
`Link.domain` vs `normalize_domain(url)` agreement.

## Results — fixture `chatgpt_search__ai_visibility_2026` (2026-08-12)

Query `best AI search visibility tracking tools`, engine `chatgpt_search`, target `otterly.ai`
(brand named in prose, present in **no** link — see `notes/`).

| model | hard gates | fabricated URLs | sources P/R | citations P/R | exact order |
|---|---|---|---|---|---|
| Sonnet 5 | all pass | 0 | 1.00 / 1.00 | 1.00 / 1.00 | src ✅ cit ✅ |
| Haiku 4.5 | all pass | 0 | 1.00 / 1.00 | 0.88 / 1.00 | src ✅ cit ❌ |
| Opus 5 | all pass | 0 | 1.00 / 0.71 | 1.00 / 1.00 | src ❌ cit ✅ |
| Fable 5 | all pass | 0 | 1.00 / 0.71 | 0.88 / 1.00 | src ❌ cit ❌ |

**Every model passed every hard gate, and precision on `sources` was 1.00 across the board — nobody
invented a link.** All four independently reported that the playbook's "Sources panel" step could not
be executed, rather than papering over it.

The spread is confined to the two ambiguities documented in `notes/`:

- **`sources` recall 0.71 (Opus, Fable)** — both deduped `getrefine.ai` to one entry instead of
  keeping its three occurrences. Defensible given no Sources panel exists to define display order;
  it costs the duplicate-occurrence signal the metrics use.
- **`citations` precision 0.88 (Haiku, Fable)** — both emitted 8 chips, resolving the second label
  inside the merged first anchor to `trylyra.ai`. Also defensible: the fixture shows 8 chip labels
  but 7 anchors.

### What this does and does not license

It says the **assembly step is not model-limited on this fixture** — a cheap model extracts as
faithfully as an expensive one, and the specific failure this project fears (confident fabricated
data) did not occur at any tier. So the capture worker is a reasonable place to spend less, and the
real risk lives upstream in browser driving and UI drift.

It does **not** generalize yet: one fixture, one query, one engine, one run per model. Non-determinism
across repeat runs of the *same* model is unmeasured. Widening this — more fixtures per engine, other
engines, repeat runs for variance — is the next step before any routing decision rests on it.
