# Gotchas

Read before capture/finalization or when resuming a suspicious run. Add a new entry
only after an agent error is observed or reproduced; keep the failure, correction,
and a test/playbook pointer. Replay evidence is in `validation.md`.

| Failure | Correction | Evidence |
|---|---|---|
| Caller-relative CSV disappears after changing into the runtime | Resolve input **and** output paths before changing CWD | Skill replay: caller/runtime split |
| CSV has 4 rows but only 3 unique pairs; finalize invents a failed query | Use `pending.n_total`, then DB key/count reconciliation | Skill replay: duplicated row; `tests/test_run_cli.py` |
| Ingest appears successful but a later run has no captures | Fix one absolute `--db` for every command; re-query that DB before recapturing | Isolated replay; `run.md` |
| Exit 0 is taken as “all rows accepted” | Inspect ingest `errors`; `ok`/`skipped` contain input indices | `tests/test_ingest.py` |
| A fixed temp filename supplies another run's stale chunk | One invocation directory, separate worker files; verify engine and exact assigned keys before ingest | Previous worker contract used globally repeated chunk indices |
| All GitHub sources are counted as the target repository | Keep URL-prefix target intact and use `target_ranks`; domain leaderboard is not a target-match counter | Skill replay: two github.com links, one target match |
| Resending a corrected existing key is assumed to replace it | Ingest skips existing keys; use a fresh run or explicitly authorized correction | `tests/test_ingest.py` |
| Partial capture is marked done or missing rows become no-overview answers | Reconcile keys first; leave resumable work running or abandon as failed | `tests/test_run_cli.py`; skill forward-test |
| Paused artifact says `n_queries=0,n_ok=1` for a 3-question set | Save expected/stored counts with `update_run_counts` without finalizing; return pending keys separately | Independent forward-test; `run.md` pause command |
| A malformed CSV is silently trimmed to “make it run” | Validate with `read_question_keys` before DB creation; surface the offending row | `tests/test_run_cli.py` |
| `FAST_PATH.md` appears in an engine picker | It is a shared extraction guide, not a capture engine | `engines/FAST_PATH.md` |
| Page text/DOM extraction misses an AI block or source group | Check rendered evidence; an empty extraction is not proof of no answer/citations | `engines/google.md`, `engines/FAST_PATH.md` |
| An answer refers to an earlier chat | Keep `prior_context` and evidence; report contamination separately from visibility | `tests/test_schema.py`; engine clean-context instructions |
| Google playbook mixed older click instructions with a later verified hover correction | Hover `+N`; click only panel expanders. A per-query object is accumulated into the worker's returned array | Independent text review; `engines/google.md`, existing 2026-08-26 evidence |

Capture defaults to one worker: shared account limits apply even across separate
tabs. If a challenge/rate limit appears, preserve saved work and stop that capture.
Do not change account/model/region halfway through a run to hide the failure.
