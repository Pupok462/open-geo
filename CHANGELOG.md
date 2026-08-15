# Changelog

All notable user-facing changes to open-geo. Versions track the Claude Code plugin version in
[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.4] — 2026-08-15

A drift-and-measurement pass. Every playbook was re-probed against the live interface on
2026-08-12, and two of the procedures they prescribed turned out to be workarounds for a *tool*
limit rather than for the page.

### Added
- **A scripted fast path for lifting source links off an already-open answer**
  (`engines/FAST_PATH.md`). `read_page` is viewport-limited and virtualized; the DOM usually is
  not, so a single `javascript_tool` call can replace several playbooks' panel-opening and
  scrolling procedures. The document records, per engine, what one call actually yields, and the
  three hard limits found by probing: the tool blocks any returned value containing a query string
  (seen on Google *and* DeepSeek — always return `origin + pathname`), Gemini ignores synthetic
  clicks entirely and therefore has no scripted path at all, and the members of a `+N` citation
  group are never in the DOM on any engine. The capture worker may now use `javascript_tool`,
  bound by a verification contract: the agent independently reads the answer, discards the
  script's output on disagreement and reports the drift, and an empty script result is never
  evidence that the answer cited nothing. The contract is not decorative — a DOM-walking extractor
  run three times against one settled answer returned three different results, all well-formed and
  confident, two of them wrong.
- **A live audit of all seven engines** (`bench/ENGINE_AUDIT.md`), summarised per playbook, and an
  end-to-end A/B of the fast path over six real capture runs (`bench/FASTPATH_AB.md`): 28 % fewer
  browser calls and 16 % fewer worker tokens, with source sets identical in all three engine pairs.
  It also shows what the fast path does *not* buy — on carousel-heavy engines the cost is dominated
  by citations, not sources, so Perplexity barely moves.
- **`bench/` — a frozen-capture extraction benchmark.** Given a real engine answer frozen to disk,
  it scores how faithfully a model turns it into a `QueryCapture`; browser driving is excluded on
  purpose, so every candidate sees byte-identical input. Hard gates (schema validity, the funnel
  flags, both target rank arrays, and fabricated URLs) are reported separately from fidelity
  (multiset precision/recall/F1 over source and citation domains, exact order) — no composite
  index, the same principle as the product's own metrics. On the first fixture all four models
  passed every hard gate and none invented a link.

### Fixed
- **ChatGPT's "Sources" panel no longer exists, and the playbook still told the worker to open
  it.** Re-verified live: nothing matching Sources/Источники/Citations renders anywhere on a
  settled grounded answer. The retrieved set is now assembled from the inline chips plus the hover
  carousel behind each `+N` group; chips are resolved by `href` only, because a chip's label
  *mutates* while the carousel is cycled and is not a stable key; a group that will not expand is
  recorded as its primary source and flagged, never guessed at. The capture budget is restated as
  ~10–25 tool calls — the old ~6–12 predates the panel's removal and is no longer reachable.
- **Yandex Alice: `Return` does not submit the query.** It opens the autocomplete list and leaves
  the query unsent, so a worker could sit waiting on an answer that was never asked for. Submit
  with the send arrow, as already documented for Perplexity.
- **The Perplexity "40 of 40 sources with zero clicks" figure is withdrawn.** A real capture run
  could not reproduce it: the settled Answer tab held only the single, non-group chips, and the
  complete set came from the Links tab after one click. The 40 appeared only because the sources
  rail happened to be expanded during the probe — the general lesson being that a structural probe
  measures the page state it ran against, so these numbers are lower bounds on cost, not guarantees.
- Perplexity's `+N` hover carousel is still mandatory for `citations`. Skipping it was measured to
  undercount citations by 14 of 36 (39 %) and to lose two domains that appear nowhere as single
  chips.
- `pipeline/INTERFACES.md` no longer describes `perplexity` as awaiting its first live-validation
  run; it was validated on 2026-08-08.

## [0.3.3] — 2026-08-12

### Added
- **Perplexity is now a supported engine**, bringing the total to seven, all live-validated against
  the real interface: Google AI Overview, ChatGPT, Claude, Gemini, Yandex Alice / Нейро, DeepSeek
  and Perplexity.

### Fixed
- The Perplexity playbook described a source and citation layout that does not exist. It was drafted
  against a numbered sources strip with inline `[N]` citation markers; the live interface has
  unnumbered source cards and citation chips labelled with a shortened domain, where a single chip
  may stand for several sources at once. A capture following the original text would have
  under-counted citations without reporting any error. The playbook has been rewritten against the
  live interface.
- A malformed `--domain` no longer aborts the audit gate. The fetch layer caught only
  `httpx.HTTPError`, but a domain string can fail before any request is made — a stray control
  character or an over-long name raises `httpx.InvalidURL` / `UnicodeError`, which are not
  `HTTPError` subclasses. Those escaped and killed the whole gate with a traceback; now every
  failure degrades into the ordinary "unreachable" result and the gate returns a readable verdict.
- A `robots.txt` that answers `429 Too Many Requests` is no longer read as "no robots.txt, so
  everything is allowed". Like a timeout or a `5xx`, it is not an answer at all — RFC 9309 tells
  crawlers to treat it as a full disallow — so the robots check now reports crawl access as
  *unverified* instead of asserting access we never confirmed. A `404` remains a genuine pass.
- The DeepSeek and Perplexity playbooks named the browser tools under a namespace that does not
  exist (`mcp__Claude_in_Chrome__*` instead of `mcp__claude-in-chrome__*`).
- The dashboard's PDF endpoint deleted none of the temp files it created: every download left one
  behind in the system temp dir, and every failed render left a partial one. All paths clean up now.
- `/api/metrics?period=all` omitted the `group` key that every other response shape carries.

### Changed
- The audit gate's own failure is now a documented outcome in the `/open-geo` skill: it means
  *readiness unknown*, not *blocked*, and never silently hard-stops a run.

## [0.3.2] — 2026-08-08

A correctness and stability pass. Every item below could previously produce either a false
hard-stop before a run, or a number that looked right and was not.

### Fixed
- Brand names now resolve case- and whitespace-insensitively within a domain, so `--brand
  "Acme"` and `--brand "acme"` no longer split one brand's history into two.
- The pre-run audit no longer grades an engine against an unrelated crawler. An engine with no
  published search-bot user agent (DeepSeek today) makes the robots.txt blocker `skip` instead
  of silently falling back to Googlebot and hard-stopping the run.
- A robots.txt that could not be read (server error or timeout) is now reported as unverified
  rather than as "no robots.txt, everything is allowed".
- An audit is never served for a different engine than the one asked for — including as the
  gate's own cache, where a Google audit could answer a ChatGPT check.
- Framework detection no longer matches ordinary words ("gastronomy" was read as Astro), which
  could turn a server-rendered page into a JS-only hard block.
- A URL-prefix target is fetched as given instead of with a forced trailing slash, so a file
  target no longer 404s and blocks the run.
- Link ranks are validated as 1-based, so a zero-based mistake can no longer report an average
  position better than first place.
- `/api/timeseries` no longer errors on a database created before the `relative_citation`
  column existed.
- The top-domains leaderboard asks the server to re-rank when you sort by citations, instead of
  re-sorting only the top 15 rows it already had.
- An interrupted run is only resumed when it holds a subset of the current question set;
  otherwise a fresh run is created and the abandoned one is named.

### Changed
- The command reference in all four READMEs now documents `--force` and `--repeat`, which
  existed but were missing from the signature and the argument table.

## [0.3.1] — 2026-08-03

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

### Fixed
- The plugin manifests pointed `homepage` at a domain that does not resolve; they now point at the
  repository.

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

[Unreleased]: https://github.com/Pupok462/open-geo/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/Pupok462/open-geo/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/Pupok462/open-geo/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Pupok462/open-geo/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/Pupok462/open-geo/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Pupok462/open-geo/compare/v0.1.0...v0.3.0
[0.1.0]: https://github.com/Pupok462/open-geo/releases/tag/v0.1.0
