# Deliverables and repeat groups

Read only for `dashboard`, `pdf`, `both`, combined-engine reports, or `--repeat R>1`.
Use the same absolute `DB` as capture/ingest. JSON export is required for every run;
optional presentation failure must not discard that artifact.

## Repeat groups

1. Mint a unique group ID for this invocation (UUID). For each repeat, sequentially:

   ```bash
   .venv/bin/python -m pipeline.ingest --new-run --db "$DB" \
     --brand "$BRAND" --domain "$TARGET" --engine "$ENGINE" --group-id "$GROUP_ID"
   ```

2. Complete capture, reconciliation, finalization, aggregate, sentiment, and JSON
   export for each run using `./run.md`. Use `run-<id>.json` per repeat or append the
   repeat index to a caller-supplied output stem; never overwrite earlier exports.
   The same unique question set is captured afresh for **each** repeat.
3. For recovery, inspect runs of the known group and resume its unfinished repeat
   explicitly. The ordinary resume lookup returns the latest unfinished brand/engine
   run; verify `group_id` before attaching it. Do not recapture completed repeats.
4. Start the dashboard/PDF once after the group finishes. The dashboard groups by
   `group_id` and shows mean and min–max spread. Never describe that spread as a
   confidence interval or blend different engines into one score.

## Dashboard

Inspect existing listeners before starting processes; reuse a healthy dashboard
only if it points to the intended DB. Otherwise choose free API and web ports.
Set `REPO` to the absolute runtime root, `API_PORT`/`WEB_PORT` to those ports.
Run both commands as separate managed background sessions:

```bash
OPEN_GEO_DB="$DB" "$REPO/.venv/bin/python" -m uvicorn dashboard.api:app \
  --host 127.0.0.1 --port "$API_PORT" --app-dir "$REPO"
```

```bash
VITE_API_BASE="http://127.0.0.1:$API_PORT" npm --prefix "$REPO/dashboard/web" run dev -- \
  --host 127.0.0.1 --port "$WEB_PORT" --strictPort
```

Absolute paths avoid dependence on the background session's CWD. `--strictPort`
prevents Vite silently moving to a different port. Record owned process/session IDs.
Verify API health **and brands**, then the frontend before returning its URL:

```bash
curl --fail --silent "http://127.0.0.1:$API_PORT/api/health"
curl --fail --silent "http://127.0.0.1:$API_PORT/api/brands"
curl --fail --silent --output /dev/null "http://127.0.0.1:$WEB_PORT/"
```

Hand over `http://127.0.0.1:<WEB_PORT>/?lang=<lang>`. Brand/engine/period are selected
inside the UI; only `lang` is a query parameter. Leave requested dashboard sessions
running and identify them; stop servers started only for temporary validation.

## PDF

Set `PDF`, `PERIOD` (`today|all`), `LANG` (`en|ru|zh|ar`) from the requested output:

```bash
.venv/bin/python -m report.generate --db "$DB" \
  --brand "$BRAND" --domain "$TARGET" --engine "$ENGINE" \
  --period "$PERIOD" --lang "$LANG" --out "$PDF"
```

`report.generate` reads a brand/engine **period**, not a run ID. `today` is the
run's date when generated that day; `all` includes completed history. Do not label
historical or multi-run report metrics as the exported single run's metrics.
Check that the output file exists and opens before reporting its absolute path.

For a combined-engine document, replace `--engine "$ENGINE"` with `--engines all`
(or an explicit comma-separated list). It compares engines in separate sections.
`both` adds this PDF and the dashboard to the already exported JSON.
