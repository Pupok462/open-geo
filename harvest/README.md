# harvest/ — question harvesting (Feature 1)

Builds the `<questions.csv>` an open-geo run consumes. **Agentic, not an algorithm** — recon
sub-agents gather real, signal-backed user queries under a natural-language methodology, mirroring
the capture side, instead of an embeddings/keyword-tool pipeline. The one deterministic half is the
**demand measurement** (`demand/`, INTERFACES §8): volume comes from the platforms' own APIs, with
its scope, so a signal is re-pullable instead of read off a browser tab. Opt-in: a user's own
hand-made CSV is equally valid.

## Pieces
- `METHODOLOGY.md` — **authority** for the process (the harvest counterpart of `engines/<engine>.md`):
  the iron reality rule, lens invariants, segment taxonomy, the three phases, balance.
- `schema.py` — `QuestionCandidate` (pydantic v2) + `normalize_query` / `contains_brand`.
- `../demand/` — the measured half: `demand.doctor` / `demand.lookup` / `demand.expand` supply the
  volume behind a candidate's `signal`; `demand.core` commits a whole measured core through this
  same `harvest.build` path (INTERFACES §8).
- `build.py` — `python -m harvest.build --out <csv> [--brand "<name>"]`: reads a JSON array of
  `QuestionCandidate` on STDIN, validates, dedups, guards the lens/brand invariants, writes the
  `query,lens` CSV, prints a JSON summary. Contract: `pipeline/INTERFACES.md §6`.

## Who runs what
- Orchestrator (`.claude/skills/open-geo/SKILL.md`, **STEP A.5**): plans segments, fans out Phase-A
  recon, synthesizes (Phase B), runs the skeptic (Phase C), calls `harvest.build`, writes
  `questions.csv` + `<name>_rationale.md`, then the review gate (apply / edit / discard).
- `.claude/agents/harvest-worker.md` — one grounded recon worker per segment (Phase A); returns a
  `QuestionCandidate` pool, never writes the CSV or the DB.
- `.claude/agents/harvest-skeptic.md` — adversarial KEEP/CUT review (Phase C); returns verdicts only.

## Provenance
`questions.csv` carries only `query,lens` (the run's contract). The per-candidate `signal` /
`source_url` / `segment` live in the sibling `<name>_rationale.md` (see `gonka_questions_rationale.md`
for a hand-built example), so the set is explainable and visibly grounded, not invented.
