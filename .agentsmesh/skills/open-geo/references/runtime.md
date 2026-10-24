# Runtime resolution

Read when starting outside the repository, installing missing dependencies, or
resolving paths from another workflow. Capture/ingest commands are in `run.md`.

1. Save caller CWD. Make CSV/core input and explicit artifact output absolute against
   that directory **before** changing CWD. Resolve a `core.json`'s `questions_csv`
   using its producer's path contract, not by guessing a different CSV in the runtime.
2. Choose the first root containing `pipeline/INTERFACES.md`: current CWD,
   valid caller `OPEN_GEO_ROOT`, writable plugin/package root (Claude:
   `CLAUDE_PLUGIN_ROOT`), managed `${OPEN_GEO_HOME:-$HOME/.local/share/open-geo}/runtime`.
3. If the managed runtime is absent, create its parent and clone:

   ```bash
   git clone https://github.com/Pupok462/open-geo "$RUNTIME"
   ```

   Here `RUNTIME` is the resolved absolute managed path. Do not overwrite or reset
   an existing checkout. A root without the contract is not a usable runtime.
4. From that root, install only what the requested output requires:

   ```bash
   bash scripts/setup.sh --minimal
   ```

   Run this if `.venv/bin/python` is absent or its required imports fail:

   ```bash
   .venv/bin/python -c 'import pipeline.schema, pipeline.db, pydantic'
   ```

   For `dashboard`/`both`, use `bash scripts/setup.sh` if frontend dependencies
   are absent. `data` and `pdf` need no frontend installation. Do not execute the
   setup script's suggested `pipeline.seed_demo --reset`; that replaces real data.
5. Resolve `DB` once to the absolute caller-selected database, or
   `data/aeo.db` under the runtime root. Every CLI uses `--db "$DB"`; the dashboard uses the same
   path through `OPEN_GEO_DB`. Merely exporting to a caller directory does not move
   the runtime database there.

If setup fails, preserve the command/error and stop before run creation. A browser
connection/login requirement is separate from Python installation; follow the
engine playbook rather than substituting API data.
