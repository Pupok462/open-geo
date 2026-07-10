# audit/ — Domain GEO-Audit Gate (Feature 2)

A fast, **deterministic (non-LLM)** readiness audit of a domain, run **before** a capture run
so the operator does not spend capture tokens on a domain an AI engine cannot read. It grades
every check by severity and gates on the real blockers only.

**Two questions, one severity split:**
- **Can an AI engine read you at all?** → **category-A blockers** (🔴): HTTPS/reachability,
  homepage 200, `robots.txt` not blocking the engine's *search* bot, content in raw HTML (not
  JS-only). A blocker fail **hard-stops** the run (overridable with `--force`).
- **Are you optimized to be cited?** → everything else, **advisory** (🟡/⚪): structured data,
  semantic HTML, meta, `llms.txt`, entity/trust, freshness. Reported with a fix, run continues.

## Pieces
- `CHECKS.md` — **authority**: the full checklist + severity, the AI-crawler tier matrix, the
  engine→search-UA mapping, the SSR heuristic, the score/verdict rules, remediation snippets,
  and the frozen module signatures. Contract shapes: `pipeline/INTERFACES.md §7`.
- `schema.py` — `CheckResult` / `AuditResult` (pydantic v2) with computed `score` / `verdict` /
  `passed` / `blockers`.
- `bots.py` — the curated AI-crawler matrix (tier: search/training/user) + `ENGINE_GATING_UA`.
- `fetch.py` — `httpx` fetch of homepage + `robots.txt` + `sitemap.xml` + `llms.txt` +
  `/.well-known` (offline-testable via `httpx.MockTransport`).
- `robots.py` — `protego` robots parse + per-bot allow/deny.
- `html.py` — `selectolax` analysis: SSR heuristic, semantic HTML, meta, JSON-LD.
- `cache.py` — TTL freshness over the `audits` DB table.
- `checks.py` — maps the analyses to the `CHECKS.md` checklist.
- `gate.py` — `python -m audit.gate --domain <d> [--engine <e>] [--no-cache] [--force?]`:
  runs the audit, persists it (`audits` table), prints one `AuditResult` JSON on STDOUT.

## Boundary
The gate is **deterministic Python** — no LLM, no browser, no headless. The friendly
human-language write-up of the remediation is the **skill's** job (SKILL STEP 0), exactly as
`lens_sentiment` prose is the orchestrator's job, not `aggregate`'s. The gate only fetches
public files and prints structured JSON.

## Cite trust (moat #3)
`robots.txt` training-bot blocks are **not** citation blocks — the gate distinguishes
`search` / `training` / `user` bots and only hard-blocks on the engine's *search* bot, so it
never cries wolf (e.g. blocking `Google-Extended` does **not** cost you AI-Overview
eligibility; `Googlebot` governs that). See `CHECKS.md §2`.
