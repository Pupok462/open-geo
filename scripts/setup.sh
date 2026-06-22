#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# open-geo dev setup — idempotent.
#   1. create .venv (python3 -m venv)
#   2. upgrade pip, install requirements.txt
#   3. npm install for the dashboard frontend
# Re-running is safe: venv reuse, pip/npm are no-ops when already satisfied.
# Paths are derived from this script's location so it works from any CWD and
# tolerates spaces in the path (everything is quoted).
# ---------------------------------------------------------------------------

# Repo root = parent of the directory holding this script, resolved absolutely.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VENV="${ROOT}/.venv"
PY_BIN="${VENV}/bin/python"
PIP_BIN="${VENV}/bin/pip"
WEB_DIR="${ROOT}/dashboard/web"

echo "==> open-geo setup"
echo "    repo root: ${ROOT}"

# --- 1. Python virtualenv ---------------------------------------------------
if [ ! -x "${PY_BIN}" ]; then
  echo "==> Creating virtualenv at ${VENV}"
  python3 -m venv "${VENV}"
else
  echo "==> Reusing existing virtualenv at ${VENV}"
fi

# --- 2. Python dependencies -------------------------------------------------
echo "==> Upgrading pip"
"${PY_BIN}" -m pip install -U pip

echo "==> Installing Python dependencies (requirements.txt)"
"${PIP_BIN}" install -r "${ROOT}/requirements.txt"

# --- 3. Dashboard frontend --------------------------------------------------
if command -v npm >/dev/null 2>&1; then
  echo "==> Installing dashboard frontend deps (npm install)"
  ( cd "${WEB_DIR}" && npm install )
else
  echo "!!  npm not found on PATH — skipping dashboard frontend install."
  echo "!!  Install Node.js (https://nodejs.org), then run:"
  echo "!!      cd \"${WEB_DIR}\" && npm install"
fi

# --- Next steps -------------------------------------------------------------
cat <<EOF

==> Setup complete.

Next steps:

  1. Seed demo data into the local SQLite DB:
       "${PY_BIN}" -m pipeline.seed_demo --reset

  2. Run the dashboard (two terminals):
       # API (read-only) — port 8000 is often taken, 8077 is a safe alt:
       OPEN_GEO_DB="${ROOT}/data/aeo.db" "${PY_BIN}" -m uvicorn dashboard.api:app \\
           --host 127.0.0.1 --port 8077
       # Frontend (point it at the API via VITE_API_BASE):
       cd "${WEB_DIR}" && VITE_API_BASE=http://127.0.0.1:8077 npm run dev
       # then open http://localhost:5173

  3. Browser prerequisite for live capture (running /open-geo):
       The capture step is NOT headless. It drives a VISIBLE, LOGGED-IN Chrome
       via the Claude-in-Chrome MCP. Before a real run, ensure:
         - the Claude-in-Chrome browser extension is installed and connected, and
         - Chrome is open and logged in to the target engine (e.g. Google).

  4. Run a visibility tracking pass (inside Claude Code):
       /open-geo examples/questions.csv google example.com \\
           --brand "Example" --n-worker 3 --output both
       (Generated PDFs land in reports/ ; the local DB is data/aeo.db.)

EOF
