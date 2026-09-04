# Question harvesting (STEP A.5, GENERATE path)

> Loaded by the open-geo skill only when the operator chose to generate a question set.
> Process authority: `harvest/METHODOLOGY.md`. Contract: `pipeline/INTERFACES.md §6`.

Run this **after STEP A and STEP 0**, **before STEP 1**. Goal: end up with a real `<questions.csv>` on disk.
It is the operator entry point for **question harvesting** (Feature 1) — the process authority is
`harvest/METHODOLOGY.md`, the contract is `pipeline/INTERFACES.md §6`. Harvesting is **agentic**
(recon sub-agents under the methodology), not an algorithm, and it is **opt-in**.

1. **FAST PATH / bring-your-own — a real CSV is already resolved.** If STEP A resolved
   `<questions.csv>` to a path that **exists and has data rows**, this step is a **no-op** — use that
   file and go straight to STEP 1. (A user's own hand-made `query,lens` CSV is a first-class input;
   loops/headless always take this path.)

   **Hand-off from a core build.** If you were handed a `core.json` instead (INTERFACES §8 — written
   by `demand.core`, typically by the `semantic-core` skill), read `questions_csv`, `brand` and
   `domain` out of it and take this same fast path. The CSV it points at is an ordinary
   `query,lens` file; nothing downstream distinguishes it. Mention the core's `totals.coverage` in
   the run summary so the operator knows how much of the set rests on measured volume.

2. **GENERATE PATH — the user chose "Generate a set" (or no CSV is resolved).** Harvest one:

   a. **Collect harvest inputs** (reuse what STEP A already has — brand, domain, `--lang`). Ask only
      for what is missing, via `AskUserQuestion`:
      - **market / category** (free text) and **known competitors** (free text seed; recon extends).
      - **how many** questions — presets `20 / 36 / 60` (+ custom). Default split is a deliberate
        **`general`-tilt** derived from the count (for ~36: `16 / 10 / 10`); offer to override the
        general/branded/comparative split.
      - **language(s) of the queries** — default to `--lang`, but note the **query language is the
        language people really ask in**, independent of the deliverable `--lang`; a distinct-language
        slice goes to its own file (`<name>_<code>.csv`). Do **not** machine-translate for coverage.

   b. **Plan the segments** from the inputs (METHODOLOGY §5) — the "different angles" on the product
      (demand primary/secondary, supply if two-sided, category/discovery, branded-reputation,
      comparative-rivals, regional slice). A two-sided product adds a supply segment; a single-sided
      one may not. Keep the plan to the segments the product actually has.

   c. **Phase A — fan-out grounded recon.** Spawn **one `harvest-worker` sub-agent per segment**
      (Task tool), **in parallel**. Its full contract lives in `../../../../.codex/agents/harvest-worker.toml` —
      do not restate it. Give each a self-contained brief:
      - the **full text of `harvest/METHODOLOGY.md`** (authoritative process + iron reality rule);
      - the **product context** (brand, domain, market, competitors);
      - its **one segment** + dominant lens(es), its **worker index** (for its unique temp file
        `/tmp/open_geo_harvest_<idx>.json`), the target **15–25 candidates**, and the language(s);
      - the **demand gate** (METHODOLOGY §3, INTERFACES §8): every candidate is asked about
        through the `demand/` APIs — its `signal` carries the provider's `scope` string verbatim, or
        an explicit stated reason why no ruler applies to that line. Run
        `.venv/bin/python -m demand.doctor --geo <cc>` yourself first and pass the verdict down, so
        workers know whether the locale yields volume or presence only;
      - authority pointers: `pipeline/INTERFACES.md §6` and `harvest/schema.py :: QuestionCandidate`.
      > A harvest worker **grounds every candidate in an observable signal, returns a
      > `QuestionCandidate` JSON pool, and cleans up its own browser tabs** — it never writes
      > `questions.csv`, never touches `data/aeo.db`, never balances or trims (that is your Phase B).

   d. **Phase B — synthesize (you, the orchestrator).** Merge all pools; **dedup by meaning** (not
      just text); drop anything without a real signal or violating its lens (METHODOLOGY §3/§4) —
      including a line that came back without a demand-provider `scope` in its `signal` or a stated
      reason why the gate does not apply;
      **balance** to the target split with the `general`-tilt, maximizing intent diversity within
      each lens; split any non-primary-language slice into its own list.

   e. **Phase C — adversarial skeptic.** Spawn **1–2 `harvest-skeptic` sub-agents** (Task tool;
      contract in `../../../../.codex/agents/harvest-skeptic.toml`) with the thesis + the final `{query, lens}`
      list. They return **KEEP/CUT verdicts**. Apply the cuts, backfill each with the next-strongest
      distinct Phase-A candidate, until every shipped line survives.

   f. **Commit to CSV** via the build CLI (INTERFACES §6.2). Write your final candidate array (each a
      `QuestionCandidate` with `query,lens,segment,signal,source_url`) to a UTF-8 temp file, then:
      ```bash
      .venv/bin/python -m harvest.build --out <name>_questions.csv --brand "<name>" \
        < /tmp/open_geo_harvest_final.json
      ```
      Read stdout `{"out","written","by_lens","dropped_dups","errors"}`. **`errors` must be empty** —
      fix any flagged row (usually a mislabeled lens: general-with-brand or branded-without-brand) and
      re-run until `errors: []`. For a separate-language slice, call `harvest.build` again with its own
      `--out <name>_<code>.csv`.

   g. **Write `<name>_rationale.md`** — per segment: who we catch, on which observable signals (from
      the workers' `signal`/`source_url`), why this lens; plus the competitors that surfaced. This is
      the provenance the CSV omits (see `gonka_questions_rationale.md` for the shape). Keep it in the
      language of the audit's stakeholders.

   h. **REVIEW GATE (human-in-the-loop).** Show a short summary — total, `by_lens`, and the full query
      list — and ask (`AskUserQuestion`): **Apply** (use this CSV for the run), **Edit** (you open
      `<name>_questions.csv`, the user tweaks rows / you adjust per their notes, then re-run
      `harvest.build` to re-validate — `errors: []` before proceeding), or **Discard** (fall back to
      bring-your-own: re-offer file selection / a path). On **Apply/Edit**, set `<questions.csv>` to
      the written path and proceed to STEP 0. This gate is deliberate — never skip straight to capture
      on a generated set without the operator seeing it (moat #3, trust).

> **Boundary.** Harvesting only produces the CSV; nothing downstream changes. The capture contract
> (§1), the run, ingest/aggregate are untouched — STEP 1 onward treats a harvested CSV exactly like a
> hand-made one.

---
