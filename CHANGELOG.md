# Changelog

All notable user-facing changes to open-geo. Versions track the Claude Code plugin version in
[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- A comparison section in the README explaining what open-geo, a hosted monitoring service and a
  DIY API/scraping script are each built for, and an "At a glance" fact table.
- An expanded FAQ covering what GEO is, which engines are supported, whether capture uses the API
  or the real UI, audit versus continuous monitoring, and URL-prefix targets.
- A project page under `docs/` (GitHub Pages) carrying `SoftwareApplication` and `FAQPage`
  structured data, plus `llms.txt` and a `robots.txt` that explicitly admits AI search crawlers.
- This changelog.

### Changed
- The README opens with a direct definition of what open-geo is and how it measures, in all four
  languages (English, Русский, 中文, العربية).

## [0.3.0] — 2026-07-25

### Added
- **Repeat runs** — `--repeat R` captures the same question set R times as R ordinary runs sharing
  one group. The dashboard reads a group as one measurement: metrics are aggregated across repeats
  and every KPI card shows a **min–max spread** instead of a run-over-run delta, so an unstable
  number is visible as unstable.
- **Weekly trend rollup** — a "By run / By week" toggle on the trend chart (ISO weeks).
- **Combined multi-engine PDF** — `report.generate --engines all` (and the dashboard's Download PDF
  in compare mode) exports one document: an engines side-by-side table, then a chapter per engine.
  Engines are never blended into a single cross-engine score.
- **Cross-engine comparison panel** — an "All engines — compare" option showing every captured
  engine of a brand side by side, with click-through into a single engine.

### Changed
- KPI cards now follow the selected lens instead of always showing the blended `all` row, and carry
  a general/branded/comparative distribution bar, because the three query types have different
  expected appearance rates and the blended average misleads on its own.

## [0.2.0] — 2026-07-24

### Added
- **Brand mention rate**, a seventh metric: the share of grounded answers whose text names the
  brand, linked or not. It sits *beside* the funnel rather than inside it — a mention without a
  link is invisible to the link funnel — so the funnel inequality is unchanged.
- A results-table outcome filter, including an actionable gap list of queries where the engine
  answered but the brand is absent entirely.

### Changed
- Metric labels are engine-neutral ("Answer coverage" rather than "AI Overview coverage"), since
  the tracker covers engines beyond Google.

## [0.1.6] — 2026-07-10

### Added
- **GEO-audit gate** — a fast, deterministic (non-LLM) pre-run check of whether an AI engine can
  read the target domain at all. Hard blockers (HTTPS/reachability, homepage 200, `robots.txt` not
  blocking the engine's *search* crawler, content present in raw HTML) stop the run unless
  `--force` is passed; everything else (structured data, semantic HTML, meta, `llms.txt`, entity
  and trust signals, freshness) is advisory and ships with a concrete fix.
- **DeepSeek** capture playbook (live-validated) and a **Perplexity** playbook (awaiting its first
  live validation run).

## [0.1.4] — 2026-07-08

### Fixed
- Corrected the Claude-in-Chrome MCP tool names used by the worker agent manifests, and propagated
  the namespace fix through the skill and the engine playbooks.

## [0.1.3] — 2026-07-08

### Fixed
- Worker agent manifests referenced browser tools by the wrong names, so plugin-installed capture
  workers could not drive Chrome.

## [0.1.2] — 2026-07-04

### Fixed
- Documentation drift against the pipeline contract, and the per-lens sentiment contract edges
  (a read-only dashboard on an older database now reports "no summaries" instead of failing).

## [0.1.1] — 2026-07-03

### Fixed
- Plugin installation now actually works: worker agents are declared explicitly in the manifest
  (they are not discovered from a directory), and the skill guards against running outside a repo
  clone.

## [0.1.0] — 2026-07-03

First public release.

### Added
- The `/open-geo` command: capture a question set through an AI engine in a real, logged-in
  browser, score it, and emit a dashboard and/or a PDF.
- Capture playbooks for Google AI Overview, ChatGPT, Claude, Gemini and Yandex Alice / Нейро.
- Seven metrics over a nested funnel (answers → sources → citations), a per-lens qualitative
  sentiment read, and a top-domains leaderboard.
- **Question harvesting** — optional grounded recon sub-agents that assemble a `query,lens` CSV
  from observable signal, with a skeptic pass and a review gate.
- Targets as a domain **or a URL prefix**, so a single repo or docs section can be measured.
- A four-language dashboard and PDF (English, Русский, 中文, العربية, RTL-aware).

[Unreleased]: https://github.com/Pupok462/open-geo/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Pupok462/open-geo/compare/v0.1.0...v0.3.0
[0.1.0]: https://github.com/Pupok462/open-geo/releases/tag/v0.1.0
