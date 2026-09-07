#!/usr/bin/env bash
# Regenerate host adapters from `.agentsmesh`.
# Claude / Codex / Cursor / Gemini: agentsmesh 0.32.
# Grok: scripts/emit_grok_adapters.py (no grok-cli target in that schema).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
npx --yes agentsmesh@0.32.0 generate
python3 "$ROOT/scripts/emit_grok_adapters.py"
