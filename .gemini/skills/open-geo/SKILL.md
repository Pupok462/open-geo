---
name: open-geo
description: Use this skill when measuring or rechecking a brand's visibility in AI answers, citations, source lists, or competitor rankings; when resuming an interrupted GEO run; or when another workflow needs captured answers and a portable measurement artifact. Use it even if the user says only “am I recommended?”, “who gets cited instead?”, or “run these questions”. Capture rendered answers through an available engine playbook, persist validated data, and export JSON; add PDF/dashboard only when requested. Accept a query CSV or a semantic-core handoff. Question research requires the separate opt-in harvest flow; this skill does not audit or edit the target website.
---

# Open GEO

One run = one question set, target, and engine. Return a portable
`open-geo.run-artifact.v1` JSON file, with optional PDF/dashboard.
`pipeline/INTERFACES.md` defines the contracts; `pipeline/schema.py` validates captures.

## Invocation and defaults

```text
/open-geo <questions.csv> <engine> <domain-or-URL-prefix> --brand "<name>"
          [--n-worker N] [--output data|dashboard|pdf|both]
          [--artifact-out <path.json>] [--period today|all]
          [--lang en|ru|zh|ar] [--repeat R]
```

These are skill arguments, not a shell command. Defaults: one worker, `data`,
`reports/run-<id>.json`, `all`, `en`, one capture. `--lang` controls the exported
presentation and user summary, not query language or captured sentiment.
`--repeat R` costs R independent captures; never infer it from “check again”.

## Read only what this run needs

| When | Read |
|---|---|
| Runtime is not resolved, dependencies are missing, or caller paths differ | [runtime.md](./references/runtime.md) |
| Before creating/resuming a run or processing captures | [run.md](./references/run.md) — exact CLI sequence, counts, failure policy |
| Before capture/finalization, or when a result looks suspicious | [gotchas.md](./references/gotchas.md) — observed failures and corrections |
| User requests question research instead of supplying a CSV/core | [harvest.md](./references/harvest.md) — grounded research and review gate |
| PDF, dashboard, combined-engine report, or repeats requested | [deliverables.md](./references/deliverables.md) |
| Explaining a metric or its denominator | [metrics.md](./references/metrics.md) |
| Editing/testing this skill | [validation.md](./references/validation.md) — replay evidence and acceptance checks |

## STEP R — resolve the runtime and paths

Prefer the current repo containing `pipeline/INTERFACES.md`, then caller-supplied
`OPEN_GEO_ROOT`, then a writable installed package, then the managed runtime.
Bootstrap instructions are in `runtime.md`; perform setup rather than asking the user
to launch services. Use the runtime's `.venv/bin/python` from its root.

**Before changing directories**, resolve the input CSV/core and explicit artifact path
against the caller's original directory. Resolve one absolute database path (normally
`data/aeo.db` under that root, or the caller's explicit isolated DB) and pass it to every CLI.

## STEP A — resolve the measurement

Reuse arguments and free-text context. Ask only for missing brand, target, engine,
and question input; concurrency defaults to 1. List engines from actual playbooks
under `engines/`, excluding `README.md` and `FAST_PATH.md`. A missing playbook is a
blocker, not permission to invent capture steps.

Accept a supplied `query,lens` CSV directly. For a `core.json` handoff, read
`questions_csv`, `brand`, `domain`, and `totals.coverage` (INTERFACES §8); keep the
coverage for the final summary. Missing or empty input blocks run creation.

### Host primitives

Ask with the host's question tool (`AskUserQuestion` on Claude), or in conversation.
Spawn with its native agent tool (Claude `Agent`, Grok `spawn_subagent`, equivalent
on other hosts). Read the host-native worker contract at the pointer below.
Without delegation, perform the same capture contract sequentially; do not substitute
an API or headless scrape for the rendered browser surface.

## STEP A.5 — questions, only if requested

Use `harvest.md` only when the user opts into generating/researching questions.
It produces a reviewed CSV and provenance; a supplied CSV/core bypasses this step.
Do not replace the user's questions with a newly invented set.

## STEP 1 — validate, then create or resume

Follow `run.md`: validate CSV **before** writing a run, retain file order, count
unique `(query,lens)` pairs. Reject malformed rows rather than silently dropping them.
Check for a compatible unfinished run; an explicit resume request or fully specified
invocation resumes it automatically. If the set differs, create a separate run and
identify the unfinished one. Capture only the `--pending` rows.

For `--repeat R > 1`, read `deliverables.md` before creating runs; repeats share a
group, but never share captured rows.

## STEPS 2–3 — capture pending rows

Read the **whole** `engines/<engine>.md` and the host-native
`../../agents/capture-worker.md`. Probe the host's visible-browser connection
and playbook-required clean context before creating a new run. A missing connection,
login wall, or unsupported clean context blocks live capture.

Default to sequential capture. If concurrency is requested and the host/browser
supports isolation, split pending rows into `min(N, pending count)` ordered chunks.
One worker owns each chunk and its tabs; account limits still apply across workers.
Give each worker:

- Full engine playbook, exact `(query,lens)` rows, target including its path, brand,
  engine, and pointers to INTERFACES §1 and `pipeline/schema.py`.
- A unique absolute output path inside this invocation's temporary directory
  (`mktemp -d`), plus chunk index. Never reuse a global `/tmp/open_geo_cap_1.json`.

Workers persist a validated array after **each query**, then return its path, JSON,
and captured/missing keys. They never receive the DB/run ID or ingest commands.
The orchestrator owns writes and exports. On hosts without workers, keep that same
separation of capture and ingest in the sequential execution.

Hard capture constraints:

- Read source/citation URLs in place; never visit the cited sites. Close only tabs
  opened for this capture, including on failure.
- Preserve `overview_present`, source order, and citation/source inclusion. Compute
  ranks with `target_ranks`; a shared domain alone does not match a URL-prefix target.
- Preserve `prior_context` and its evidence; a contaminated answer is flagged data,
  not a clean measurement. Screenshots are transient (`screenshot_path=null`).
- On CAPTCHA or rate limit, stop the affected capture and preserve completed work;
  do not solve challenges or keep increasing concurrency.

## STEP 4 — persist and reconcile

Follow the commands in `run.md`. Validate each returned file's engine and keys
against its assignment, then ingest incrementally. Read `errors` even on exit 0.
`skipped` is a duplicate, not a corrected overwrite. Verify stored keys/counts after
ingest; do not equate worker success with durable storage.

Finalize `done` only when every unique CSV pair is stored with no extra keys.
Missing captures are not `overview_present=false` answers. Preserve a paused run
as `running` with its ID and pending count for resume; finalize an abandoned or
unrecoverable run `failed`. Never silently label a partial run as complete.

## STEPS 5–5b — metrics and sentiment

Aggregate with `pipeline.aggregate` and save its JSON stdout. It computes metrics
and domain statistics, but **does not synthesize sentiment**.
Read per-query sentiments via `pipeline.run --sentiments`; write one neutral sentence
for each represented lens plus `all`, using only those notes and their language.
All-null notes mean a null summary. Persist the `{lens: summary}` object with
`pipeline.lens_sentiment`; verify the returned `written` lenses.

## STEP 6 — export

Export JSON with `pipeline.artifact` using the same DB; open the file and check
schema version, run ID/status, target, result counts, metrics, and lens summaries.
The default `data` output ends here. Start presentation services or generate a PDF
only for the requested output, following `deliverables.md`.

## STEP 7 — return the result

Use the `all` row from aggregate stdout: answer coverage, target visibility in
sources/citations, average best source/citation ranks, source→citation conversion,
and brand mention rate. `null` means no data, never zero. Explain denominators when
needed via `metrics.md`; brand mention is independent of linked presence.

Report captured/expected counts, status, unresolved blockers and prior-context
flags alongside metrics. For partial exports, metrics describe captured rows only.
Include core demand coverage if supplied, then the absolute artifact path and any
verified PDF path/dashboard URL. Do not claim a fixture replay is a live GEO result.