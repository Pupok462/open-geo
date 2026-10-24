# Skill validation

Read when changing the skill, worker persistence, or CLI instructions. These checks
validate orchestration, not current engine UI compatibility or live brand visibility.

## Evidence behind this revision (2026-10-25)

Before rewriting, a separate agent executed 16 real pipeline CLI calls on synthetic
captures in an isolated database. Input: caller-relative CSV with 3 unique pairs
and one duplicate; target `github.com/Pupok462/open-geo`; captures for a target
citation, a different repository on the same domain, and no overview.

- The caller-relative CSV failed after CWD changed. Making input/output paths
  absolute before switching roots fixed it.
- Literal full-CSV finalization produced `n_queries=4,n_ok=3,n_failed=1` although
  pending was empty. Using `pending.n_total=3` fixed it.
- Resume found 1 captured / 2 missing. Re-ingesting the first chunk skipped exactly
  one row; ingesting the rest left no pending keys. Final artifact: done, 3/3, 0 failed.
- Aggregate: answer coverage 2/3, target source/citation/mention visibility 1/2,
  best positions 1, relative citation 1. The no-overview lens had null visibility.
  Domain leaderboard counted 2 github.com source appearances, only 1 target match.

These observations motivated `./runtime.md`, `./run.md`, and the matching gotchas.
The existing contracts/tests supply the remaining capture and presentation rules;
they are not new claims of live-provider validation.

The independent forward-test then completed a resumed run (3/3, done) and paused
another after one capture (running, 2 pending, resumable). It exposed
`run.n_queries=0` in the paused export because ingest updates only `n_ok`.
The pause command in `./run.md` now persists expected counts without a terminal
status; a regression test executes that exact command and checks resume again.
The same independent agent retested that command: expected=3, stored=1, failed=0,
status=running, resume=true with 2 pending. Captures and metric values were unchanged.
Its text review also found conflicting Google `+N` click/hover and object/array
instructions. Those now follow the playbook's existing dated hover evidence and
the worker's chunk-array contract; no new live UI verification is claimed.

## Reusable checks

1. Run `tests/test_skill_workflow.py`: isolated CLI replay, duplicate-row resume,
   idempotent ingest, URL-prefix distinction, null denominators, paused and failed partial exports.
2. Run `tests/test_agent_tools.py`: native worker pointers and browser bindings on
   Claude, Codex, Cursor, Gemini, and Grok.
3. Validate canonical and generated skill frontmatter/references; keep `description`
   at most 1024 characters and SKILL.md under 500 lines / 5000 tokens. Measure with
   the host's tokenizer when available, not a word-count estimate.
4. Give a separate agent the updated skill and raw test inputs, without an expected
   answer. Have it actually resume/export an isolated run, then independently check
   the returned artifact. Include one partial or malformed-input case.
5. Run the repository's Python coverage gate. For a packaged release also run the
   frontend build/tests and plugin manifest validation. Use the CI's Node 22 runtime;
   the local Node 26 alpha caused unavailable `localStorage` in the test environment.

When the engine capture procedure changes, add a real browser probe for that engine;
an offline replay cannot establish login, source-panel behavior, or current UI fidelity.
