# Run control and data handoff

Read before creating/resuming a run or replaying captured data. Commands run from
the resolved runtime root. Set absolute `CSV`, `DB`, `ARTIFACT`, `WORK` paths and
`BRAND`, `TARGET`, `ENGINE` values from the invocation; do not paste placeholders.
`WORK` is created with `mktemp -d`; each worker gets its own file inside it.
`RUN_ID` always comes from parsed JSON, never the newest database row guessed by ID.

## Preflight before a new run

Validate the whole CSV without opening the DB:

```bash
.venv/bin/python - "$CSV" <<'PY'
import json, sys
from pipeline.run import read_question_keys
rows = read_question_keys(sys.argv[1])
unique = list(dict.fromkeys(rows))
print(json.dumps({"rows": len(rows), "n_unique": len(unique),
                  "duplicates": len(rows) - len(unique)}, ensure_ascii=False))
PY
```

Invalid headers, blank queries, unknown lenses, or zero rows stop here. Do not repair
the user's question text by dropping rows. Duplicates retain their first occurrence;
the DB identity is `(run_id,query,lens)`, so they cannot be separate observations.
Also check the engine playbook and live-browser prerequisites before new run creation.
An explicitly requested replay of existing captures needs no browser.

## Find or create

```bash
.venv/bin/python -m pipeline.run --resume-check --db "$DB" \
  --brand "$BRAND" --domain "$TARGET" --engine "$ENGINE" --csv "$CSV"
```

Stdout: `{run_id,resumable,run_at,n_captured,n_missing}`. With an explicit resume
request or fully specified invocation, reuse a non-null `run_id` only when
`resumable=true`; otherwise offer resume versus fresh. A mismatched set gets a new
run; report the unfinished run ID separately. `--resume-check` is not read-only:
it initializes the DB and may create the brand. It is not a CSV preflight validator.

When creating a new run:

```bash
.venv/bin/python -m pipeline.ingest --new-run --db "$DB" \
  --brand "$BRAND" --domain "$TARGET" --engine "$ENGINE"
```

Parse `{run_id}`. Optional `--question-set` is a human label; repeat groups use
`--group-id` as described in `deliverables.md`.

## Pending work and ingest

```bash
.venv/bin/python -m pipeline.run --pending --db "$DB" \
  --run-id "$RUN_ID" --csv "$CSV"
```

Stdout: `{run_id,n_total,n_captured,n_pending,pending:[[query,lens],...]}`.
`n_total` is the unique-pair count, including rows captured before a resume.
Capture only `pending`. If it is empty, skip capture and proceed to reconciliation.

`CHUNK` is the worker's saved UTF-8 JSON **array** of `QueryCapture`, not its status
message. Before ingest, parse every object with `QueryCapture.model_validate`,
check the assigned engine and `(query,lens)`, and recompute both target rank arrays
with `pipeline.schema.target_ranks(links, TARGET)`. Preserve the path in `TARGET`.
See INTERFACES §1 for ordered `Link` fields, source/citation inclusion, and sentiment.

```bash
.venv/bin/python -m pipeline.ingest --db "$DB" --run-id "$RUN_ID" < "$CHUNK"
```

Stdout: `{run_id,ok:[indices],skipped:[indices],errors:[{index,query,field,msg}]}`.
Exit 0 can contain errors. Correct only fields supported by captured evidence;
otherwise recapture the affected pair. Retry once, then preserve the residual
error and pending work rather than looping indefinitely. Ingest each durable
chunk as it arrives, not at the end of the whole run.

`skipped` means an existing key was **not overwritten**. A revised capture with that
key needs a separate fresh run or an explicitly authorized data correction.

## Reconcile and finalize

Re-run `--pending` and independently inspect the stored keys/count:

```bash
.venv/bin/python - "$DB" "$RUN_ID" "$CSV" <<'PY'
import json, sqlite3, sys
from pathlib import Path
from pipeline.run import read_question_keys
db, run_id, csv_path = sys.argv[1:]
wanted = set(read_question_keys(csv_path))
with sqlite3.connect(Path(db).as_uri() + "?mode=ro", uri=True) as conn:
    rows = conn.execute("SELECT query,lens FROM results WHERE run_id=?", (int(run_id),)).fetchall()
stored = set(rows)
print(json.dumps({"expected": len(wanted), "stored": len(rows),
                  "missing": sorted(wanted - stored), "extra": sorted(stored - wanted)}))
PY
```

`done` requires missing/extra both empty, `len(results)=n_total`, and no unresolved
ingest errors. Use `TOTAL=pending.n_total`, `STORED=COUNT(results)`:

```bash
.venv/bin/python -m pipeline.run --finalize --db "$DB" --run-id "$RUN_ID" \
  --n-queries "$TOTAL" --n-ok "$STORED" --status done
```

This CLI trusts the supplied counts; it does not enforce those invariants for you.
`n_failed` defaults to `TOTAL-STORED`. No-overview captures count as stored, not failed.
For a temporary blocker/explicit pause, leave `running` and return the ID and
pending count so `--resume-check` can find it. If abandoning or unable to recover,
use the same finalize command with `--status failed` and actual counts.
Do not create placeholder no-answer captures for missing queries.

### Pause without losing expected counts

After reconciliation, set `TOTAL` and `STORED` as above. Ingest updates `n_ok` only;
without this step a paused artifact can say `n_queries=0` despite saved results.
The finalize CLI accepts only terminal statuses, so use the existing DB helper:

```bash
.venv/bin/python - "$DB" "$RUN_ID" "$TOTAL" "$STORED" <<'PY'
import json, sys
from pipeline.db import get_conn, update_run_counts
db, run_id, total, stored = sys.argv[1:]
run_id, total, stored = int(run_id), int(total), int(stored)
conn = get_conn(db)
try:
    assert conn.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0] == "running"
    update_run_counts(conn, run_id, n_queries=total, n_ok=stored, n_failed=0)
finally:
    conn.close()
print(json.dumps({"run_id": run_id, "status": "running", "n_queries": total,
                  "n_ok": stored, "n_pending": total - stored}))
PY
```

`n_failed=0` here means the missing rows are pending, not terminal failures.
Return the pending list separately: artifact v1 has no `pending` field. If exporting
a diagnostic artifact, aggregate and summarize only the stored captures below.

## Aggregate and qualitative summaries

```bash
.venv/bin/python -m pipeline.aggregate --db "$DB" --run-id "$RUN_ID"
.venv/bin/python -m pipeline.run --sentiments --db "$DB" --run-id "$RUN_ID"
```

Save aggregate stdout `{run_id,brand_id,engine,metrics:[{lens,...}],top_domains}`.
The second command returns `[{lens,query,sentiment},...]`. Synthesize one short,
evidence-supported sentence per represented lens and `all`; all-null notes yield
null. Keep the notes' language, independent of `--lang`.
Write `SUMMARIES` as a UTF-8 JSON **object**, e.g. `{"general":null,"all":null}`:

```bash
.venv/bin/python -m pipeline.lens_sentiment --db "$DB" \
  --run-id "$RUN_ID" < "$SUMMARIES"
```

Check `{run_id,written:[lenses]}` against the intended lenses; unknown keys are
silently ignored. Re-aggregate leaves these summaries intact.

## Export and verify

```bash
.venv/bin/python -m pipeline.artifact --db "$DB" \
  --run-id "$RUN_ID" --out "$ARTIFACT"
```

Stdout: `{schema_version,run_id,artifact_path}`. Open `artifact_path` and verify
`schema_version=open-geo.run-artifact.v1`, `run.id/status/n_queries/n_ok/n_failed`,
`brand.target`, `len(results)`, `metrics`, `lens_sentiment`, `domain_stats`.
Only `done` runs feed completed-history rollups. A partial diagnostic export may
still be produced; state its missing count and that aggregate denominators cover
**stored captures**, not the full CSV. Export success alone does not prove completion.
