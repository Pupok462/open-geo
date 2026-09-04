# Deliverables & repeat runs (STEP 6 detail, STEP 1 repeats)

> Loaded by the open-geo skill only when the run needs a dashboard, a PDF, or `--repeat R > 1`.
> The portable JSON artifact is always produced by the skill itself and does not need this file.

## Repeat-run groups (`--repeat R`, R > 1)

The whole point is R **independent** captures of the same CSV, grouped so readers can see
mean + spread instead of trusting one noisy run (INTERFACES §2.1). Flow:

1. Mint one group tag for the whole invocation — `grp_<YYYYMMDD-HHMM>_<engine>` is fine.
2. For each repeat `i = 1..R` **sequentially**: create its run with
   `python -m pipeline.ingest --brand … --domain … --engine … --new-run --group-id <tag>`,
   then execute STEPS 2–5b for that run exactly as for a single run (full CSV each time —
   do NOT dedupe across repeats; a repeat IS the same question asked again).
3. Resume semantics are **per repeat**: a crashed repeat is found by `find_unfinished_run`
   and finished into its own run; already-`done` repeats of the group are never re-captured.
4. Deliverables (STEP 6) run **once, after the last repeat**. The dashboard detects the
   group automatically (latest run carries the `group_id`) and shows the mean + min–max
   spread; nothing extra to pass.

---

## `--output dashboard` — or as part of `both`

Start the dashboard (FastAPI backend + Vite/React frontend) and print the **local URL**.
The frontend selects brand/engine/period through its own UI controls (read from the API),
so you do **not** scope brand/engine/period via the query string — **only the UI language**:
hand the operator `http://localhost:5173/?lang=<lang>`, which seeds the dashboard's initial
language from the run's `--lang` (the in-browser switcher still overrides it, and the choice
persists in `localStorage`).

```bash
# Run BOTH in the background (they are long-running dev servers).
# Background shells do NOT inherit the repo-root CWD, so use ABSOLUTE paths anchored at
# <REPO> = the repository root (your working directory). Do NOT use a relative
# `.venv/bin/python` or `cd dashboard/web` here — backgrounded, they fail (exit 127 /
# wrong CWD). `--app-dir <REPO>` lets uvicorn import `dashboard.api` regardless of CWD.
#
# 1) API (read-only over data/aeo.db). PICK A FREE PORT — 8000 is often taken:
OPEN_GEO_DB=<REPO>/data/aeo.db <REPO>/.venv/bin/python -m uvicorn dashboard.api:app \
    --host 127.0.0.1 --port <PORT> --app-dir <REPO>

# 2) Web (Vite dev server), pointed at the API's port. Use `npm --prefix` instead of `cd`
#    (run `npm --prefix <REPO>/dashboard/web install` once if node_modules is missing):
VITE_API_BASE=http://127.0.0.1:<PORT> npm --prefix <REPO>/dashboard/web run dev
```

- **Port caveat:** local port **8000 is often already occupied** by another service on
  this machine. Pick a free port for the API (e.g. `8077`) and point the frontend at it via
  `VITE_API_BASE` (CORS is open, so a cross-origin base works without the dev proxy):
  ```bash
  VITE_API_BASE=http://127.0.0.1:<PORT> npm --prefix <REPO>/dashboard/web run dev
  ```
- **Verify before handing off** (a backgrounded server can exit non-zero or the port can
  clash): probe both before printing the URL —
  ```bash
  curl -s http://127.0.0.1:<PORT>/api/health
  curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/
  ```
  so you surface a *working* URL, not a hopeful one.
- After both are up, print the **Vite dev URL** the operator should open —
  `http://localhost:5173/?lang=<lang>` (the frontend's own controls drive brand/engine/period;
  `?lang=<lang>` seeds the UI language from the run's `--lang`, and the switcher still
  overrides). If `dashboard/` cannot be started, say so (in `--lang`) and skip gracefully
  (still finish steps 5 and 7).

## `--output pdf` — or as part of `both`

```bash
.venv/bin/python -m report.generate \
  --brand "<name>" --domain <domain> --engine <engine> \
  --period <period> --lang <lang> \
  --out reports/<brand>_<date>.pdf [--db data/aeo.db]
```

- This is the real, built CLI. It prints progress/status to **stderr**; the **output path**
  (`--out`) is what to surface to the operator. Pass `--lang <lang>` (the run's `--lang`,
  default `en`) so the report renders in that language.
- Use `<date>` = today (`YYYY-MM-DD`). Create `reports/` if missing. **Print the resulting
  file path.** If the command fails, say so (in `--lang`) and skip gracefully.
- **Combined multi-engine document (Feature 7):** when the operator asks for one document
  across every engine the brand has runs on, swap `--engine <engine>` for
  `--engines all` (or an explicit comma list) — one PDF: engines side-by-side table, then
  a chapter per engine. Numbers are never blended across engines.

## `--output both`

The JSON artifact already exists; additionally start the dashboard and generate the PDF.

---
