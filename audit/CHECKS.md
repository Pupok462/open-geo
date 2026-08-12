# audit/ — the GEO-Audit Gate checklist (authority)

> This file is the **single source of truth** for the domain GEO-audit gate (ROADMAP
> Feature 2), the audit counterpart of `engines/<engine>.md` (capture) and
> `harvest/METHODOLOGY.md` (harvest). The **contract shapes** live in
> `pipeline/INTERFACES.md §7`; this file is the **check semantics + data + module
> signatures**. Code carries no comments — knowledge lives here.

The gate answers **two separate questions**, and the severity split is the whole point:

1. **Can an AI engine physically read you at all?** → **category-A blockers** (🔴). A failure
   here hard-stops the run (there is no point spending capture tokens on a domain the engine
   cannot reach or render). Overridable only with an explicit `--force`.
2. **Are you optimized to be cited?** → everything else, **advisory** (🟡 recommended / ⚪
   nice-to-have). Reported as clear problems with a fix, but the run continues.

A site can already be cited via third-party mentions with none of the advisory signals, so
advisory checks **never** block — this mirrors the house rule "hard-block only on real
blockers" (`CLAUDE.md`, ROADMAP Feature 2).

---

## 1. Severity, status, verdict, score

- **Severity** (`blocker` 🔴 · `recommended` 🟡 · `nice_to_have` ⚪) — the check's weight and
  whether it can hard-stop. **Only `blocker` checks can block.**
- **Status** per check: `pass` · `warn` (present but suboptimal) · `fail` (absent/broken) ·
  `skip` (not applicable / could not be evaluated — excluded from the score).
- **Verdict** (`AuditResult.verdict`, computed): `blocked` if **any** `blocker` check is
  `fail`; else `ready_with_warnings` if any check is `warn`/`fail`; else `ready`.
- **`passed`** (computed) = `verdict != "blocked"`. The gate hard-stops iff `not passed`
  **and** the operator did not pass `--force`.
- **`score`** 0–100 (computed) = weighted pass-rate, weight by severity
  `{blocker:3, recommended:2, nice_to_have:1}`, credit `{pass:1.0, warn:0.5, fail:0.0}`,
  `skip` excluded. `100` when nothing was evaluable. It is a **readout beside the two axes**,
  never the verdict — the verdict is driven only by blocker fails (INTERFACES §4's "no
  composite index as a verdict" spirit).

---

## 2. The AI-crawler matrix (`audit/bots.py`)

The load-bearing correctness point: **blocking a *training* bot ≠ blocking citations.** Each
bot is one of three tiers:

- **`search`** — the retrieval/index crawler whose block **kills citation visibility** for its
  engine → a block here can be a 🔴 blocker (see A3). `OAI-SearchBot`, `Claude-SearchBot`,
  `PerplexityBot`, `Googlebot`, `Bingbot`, `YandexBot`.
- **`training`** — model-training opt-out. Blocking is a **policy choice, not a self-inflicted
  wound** → advisory/informational only, never a blocker. `GPTBot`, `Google-Extended`,
  `ClaudeBot`, `CCBot`, `Applebot-Extended`, `Amazonbot`, `Meta-ExternalAgent`, `Bytespider`.
- **`user`** — on-demand fetch when a user pastes/asks for a URL. Advisory. `ChatGPT-User`,
  `Claude-User`, `Perplexity-User`, `DuckAssistBot`, `MistralAI-User`.

**Engine → gating search-UA** (`ENGINE_GATING_UA`) — the one UA whose block breaks **that
engine's** citations, so A3 is **engine-aware**:

| engine | gating search UA | note |
|---|---|---|
| `google` | `Googlebot` | AI Overviews draw on the live Search index — **`Google-Extended` is training/grounding only; blocking it does NOT remove AI-Overview eligibility** (common trap). |
| `gemini` | `Googlebot` | same index basis; `Google-Extended` block affects grounding/training only → advisory. |
| `chatgpt_search` | `OAI-SearchBot` | **not** `GPTBot` (training). |
| `claude_search` | `Claude-SearchBot` | **not** `ClaudeBot` (training). |
| `yandex_neuro` | `YandexBot` | |
| `perplexity` | `PerplexityBot` | ⚠ `Perplexity-User` documentedly ignores robots.txt (+ reported stealth UAs), so a "block" is not a guarantee — report as blocker but note the caveat. |

**Engine with no published search-bot UA → A3 is `skip`, never `fail`.** `deepseek` is the live
case: it is a fully implemented capture engine, but its retrieval crawler has no documented,
verifiable user-agent, so there is nothing to grade `robots.txt` against. Grading it against
`Googlebot` anyway would hard-stop a run over a bot that has nothing to do with the engine —
a false stop on a readable site, which costs more trust than a missed warning (same reasoning
as A5 warning on thin-but-server-rendered HTML). `audit.bots.is_engine_mapped` decides this;
`skip` is excluded from `score` and can never enter `blockers`. **Do not invent a UA to fill
this row** — a fabricated mapping produces confidently wrong verdicts. When an operator
publishes one, add it to `ENGINE_GATING_UA` (plus its `Bot` entry) and A3 starts grading it.

`--engine` omitted entirely (generic audit) → `DEFAULT_GATING_UA = "Googlebot"` (broadest
reach), and A3 does grade it; other search bots stay advisory via A3b.

**robots.txt we could not read → A3 is `skip`, never `pass`.** Same rule, other direction: a
`404` is a real answer ("no robots.txt, everything is allowed") and stays a `pass`, but a
**timeout, a 5xx, or a `429`** is not an answer. RFC 9309 tells crawlers to treat those as a
full disallow, so we are not entitled to report access we never verified — the analysis flags
`RobotsAnalysis.unreadable`, A3 goes `skip` (out of `score`, never a blocker) and A3b `warn`s
that access is *unverified, not confirmed*. Other 4xx (`401`/`403`/`410`) follow the RFC's
client-error rule and are treated like `404`.

Source of the registry: official operator docs + the community `ai-robots-txt/ai.robots.txt`
(MIT). Curated here because "which UA gates which engine" is a product decision, not raw data.

---

## 3. The checklist

Severity 🔴 blocker · 🟡 recommended · ⚪ nice-to-have. Only 🔴 fails block.

### Category A — crawl access & protocol

| id | title | sev | pass / warn / fail |
|---|---|---|---|
| **A1** | Domain resolves, HTTPS valid, HTTP→HTTPS redirect | 🔴 | **pass**: `https://<domain>/` returns a response over valid TLS. **warn**: https OK but `http://` does not redirect to https. **fail**: no response / DNS / TLS error (unreachable). |
| **A2** | Homepage returns 200 (no 4xx/5xx, no long redirect chain) | 🔴 | **pass**: final status 200. **warn**: 200 but reached via >2 redirects. **fail**: 4xx/5xx or no final 200. |
| **A3** | robots.txt does not block the engine's **search** bot | 🔴 | **pass**: the engine's gating search UA may fetch `/`. **fail**: it is disallowed (🔴 hard-block). **skip**: the engine has no mapped search UA (see above), or robots.txt was **unreadable** (see below). Sub-signals folded into detail: other `search` bots blocked → the check is still `pass` for the engine but the detail lists them; they surface as **A3b** (🟡). |
| **A3b** | Other search bots / robots hygiene | 🟡 | **pass**: no other `search`-tier bot blocked. **warn**: another `search` bot blocked, robots.txt malformed, or robots.txt unreadable (access unverified). **skip**: no robots.txt (everything allowed). Training-tier blocks are reported as **informational only** (policy), never warn/fail. |
| **A4** | sitemap.xml present, valid XML, referenced in robots.txt | 🟡 | **pass**: `/sitemap.xml` 200 + well-formed XML + a `Sitemap:` line in robots.txt. **warn**: present but not referenced / not well-formed. **fail**: absent. |
| **A5** | Primary content in raw HTML (SSR), not JS-only | 🔴 | **pass**: content is accessible without JS (see §4). **fail** (hard-block): JS-dependent **with SPA evidence** — an empty mount-root (`<div id="root">`…) or a framework marker. **warn** (advisory, does NOT block): JS-dependent by **thin text alone** with no SPA marker — the page is readable, just sparse (e.g. a landing/link page), so it is flagged not stopped. Precision matters: a hard-block on a readable-but-short page is a false stop (moat #3). |

### Category B — machine-readability & structure

| id | title | sev | pass / warn / fail |
|---|---|---|---|
| **B1** | Structured data (schema.org JSON-LD) present & valid | 🟡 | **pass**: ≥1 valid JSON-LD block with a recognized `@type` (Organization, WebSite, Article/BlogPosting, FAQPage, Product, BreadcrumbList, HowTo). **warn**: JSON-LD present but no key type, or some blocks are invalid JSON. **fail**: none. |
| **B2** | Semantic HTML (single `<h1>`, `<main>`/`<article>`, sane heading order) | 🟡 | **pass**: exactly one `<h1>` **and** a `<main>` or `<article>`. **warn**: 0/≥2 `<h1>`, or no main/article, or heading levels skip. **fail**: no headings at all. |
| **B3** | Meta basics: title, description, canonical, `lang`, OG; not `noindex` | 🟡 | **pass**: title + description + canonical present and page is not `noindex`. **warn**: some of title/description/canonical/lang/OG missing. **fail**: `noindex` present (page asks to be excluded — high-impact, still advisory per the category-A-only gate policy). |
| **B4** | `llms.txt` present (+ minimal structure) | ⚪ | **pass**: `/llms.txt` 200 with an H1. **warn**: present but malformed (no H1 / empty). **fail**: absent. Emerging convention (~10–15% adoption, unproven ranking factor) — cheap to add. |

### Category C — entity & trust

| id | title | sev | pass / warn / fail |
|---|---|---|---|
| **C1** | About / Contact pages linked from homepage | 🟡 | **pass**: both an about-like and a contact-like link found. **warn**: one present. **fail**: neither. |
| **C2** | Organization schema with `logo` + `sameAs` | 🟡 | **pass**: JSON-LD Organization with `logo` and ≥1 `sameAs`. **warn**: Organization present but missing `logo`/`sameAs`. **fail**: no Organization schema. |

### Category D — freshness & feeds

| id | title | sev | pass / warn / fail |
|---|---|---|---|
| **D1** | Visible publication / update dates | ⚪ | **pass**: `datePublished`/`dateModified` in JSON-LD or a `<time datetime>` on the homepage. **fail**: none. |
| **D2** | RSS / Atom feed | ⚪ | **pass**: `<link rel="alternate" type="application/rss+xml"\|"application/atom+xml">`. **fail**: none. |
| **D3** | `/.well-known/security.txt` | ⚪ | **pass**: 200. **fail**: absent. Standardized discovery point; proxy for `/.well-known/` hygiene. |

> **URL-prefix target.** When `--domain` is a URL prefix (`github.com/user/repo`), the
> host-level checks (A1/A3/A4, robots/sitemap/llms/well-known) audit the **registrable
> domain**; A2/A5 additionally evaluate the **specific prefix URL** when present (that exact
> page's status + SSR), because that is the page you are trying to get cited.

---

## 4. SSR / JS-render heuristic (A5) — ported method

No headless browser (deliberate — matches the project's "no headless / no system libs"
stance). Fetch raw HTML and decide from its text, ported from the reference implementation:

- **`raw_word_count`** — words in `<body>` text, excluding `<script>` / `<style>` / `<noscript>`.
- **`heading_count`** — number of `<h1>`…`<h6>` in the raw HTML.
- **empty-root markers** — presence of an SPA mount node with `<50` chars of inner text:
  `<div id="root">`, `<div id="app">`, `<div id="__next">`, `<div id="__nuxt">`,
  `<div id="gatsby-focus-wrapper">`.
- **framework markers** (first 10k chars, informational): Next (`/__next/`, `_next/static`),
  Nuxt (`__nuxt`, `_nuxt/`), React (`react` + `id="root"`/`createRoot`), Angular
  (`ng-version`, `ng-app`), Vue (`data-v-`, `id="app"`), Gatsby (`gatsby`), Astro (`_astro/`).
- **`has_noscript`** — `<noscript>` inner text `>20` chars (fallback content present).

Thresholds (constants in `audit/html.py`): `JS_SPA_WORDS = 200`, `JS_EMPTY_ROOT_WORDS = 100`,
`JS_CRITICAL_WORDS = 50`. Decision (`js_dependent = True` ⟹ A5 fail), in order:

1. `raw_word_count < JS_SPA_WORDS` **and** `heading_count == 0` → JS-dependent.
2. an empty-root marker present **and** `raw_word_count < JS_EMPTY_ROOT_WORDS` → JS-dependent.
3. `raw_word_count < JS_CRITICAL_WORDS` → JS-dependent (critically low).
4. otherwise → content accessible without JS.

`js_dependent` is the raw heuristic (in `audit/html.py`). **A5 severity then splits on SPA
evidence** (in `audit/checks.py`, per §3): `js_dependent` **with** an empty-root marker or a
framework marker ⟹ **fail** (real SPA shell, hard-block); `js_dependent` from **thin text
alone** (rule 3 with no marker) ⟹ **warn** (readable but sparse — advisory, never blocks). This
keeps the hard-block **high-precision**: a short static page is not stopped, only a true
JS-only shell is.

---

## 5. Remediation snippets (data, attached to failing checks)

Each failing/warning check carries a concrete `remediation`. Canonical snippets:

- **A3 (robots allow)** —
  ```
  User-agent: Googlebot
  Allow: /
  User-agent: OAI-SearchBot
  Allow: /
  # …one block per engine's search bot you want to be cited in
  Sitemap: https://<domain>/sitemap.xml
  ```
- **B1/C2 (Organization JSON-LD)** —
  ```html
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"Organization","name":"<Brand>",
   "url":"https://<domain>/","logo":"https://<domain>/logo.png",
   "sameAs":["https://www.linkedin.com/company/<brand>","https://en.wikipedia.org/wiki/<Brand>"]}
  </script>
  ```
- **B4 (minimal llms.txt at `/llms.txt`)** —
  ```
  # <Brand>
  > One-sentence description of what <Brand> is.
  ## Docs
  - [Getting started](https://<domain>/docs): setup and first steps
  ```

---

## 6. Module contract (frozen signatures — Phase-1 leaf modules build to these)

All pydantic v2, no comments/docstrings, deterministic, offline-testable.

### `audit/fetch.py`
```python
class Fetched(BaseModel):
    url: str
    final_url: Optional[str]        # after redirects; None on network error
    status: Optional[int]           # None on network error
    ok: bool                        # status == 200
    headers: dict[str, str]         # header names lowercased
    text: Optional[str]             # body text, None on error / non-text
    error: Optional[str]            # network/timeout error message, else None
    redirects: int                  # number of hops followed
    scheme: Optional[str]           # final URL scheme

class SiteArtifacts(BaseModel):
    target: str                     # normalize_target(input)
    domain: str                     # normalize_domain(host)
    checked_at: datetime
    homepage: Fetched               # https://<domain>/
    homepage_http: Fetched          # http://<domain>/  (for A1 redirect check)
    robots: Fetched                 # https://<domain>/robots.txt
    sitemap: Fetched                # https://<domain>/sitemap.xml
    llms: Fetched                   # https://<domain>/llms.txt
    security: Fetched               # https://<domain>/.well-known/security.txt
    target_page: Optional[Fetched]  # the exact prefix URL, only if target has a path

def fetch(client: httpx.Client, url: str, *, timeout: float = 10.0) -> Fetched: ...
def gather(target: str, *, client: Optional[httpx.Client] = None,
           timeout: float = 10.0) -> SiteArtifacts: ...
```
`fetch` **never raises** — any failure is recorded in `error` with `status=None`. "Any" is
literal and load-bearing: not just `httpx.HTTPError`, but also the URL-level failures a
user-supplied `--domain` can produce before a socket is ever opened (`httpx.InvalidURL` on a
control character, `UnicodeError` on an over-long IDNA label). Those are not `HTTPError`
subclasses, so catching only that class let them escape `gather` and abort the whole gate with
a traceback instead of grading A1 `fail` — a bad domain must degrade into a readable verdict,
never into a crash. Tests inject an `httpx.Client(transport=httpx.MockTransport(...))`; no live
network in tests.

### `audit/robots.py`
```python
class BotPolicy(BaseModel):
    ua: str
    operator: str
    tier: str                       # "search" | "training" | "user"
    allowed: bool                   # may it fetch "/"?

class RobotsAnalysis(BaseModel):
    fetched: bool                   # robots.txt returned a body (status 200 with text)
    present: bool                   # a non-empty robots.txt exists
    malformed: bool                 # parse produced nothing usable
    sitemaps: list[str]             # Sitemap: directives
    policies: list[BotPolicy]       # one per bot in audit.bots.AI_CRAWLERS
    unreadable: bool                # no answer at all: timeout / 5xx / 429 (see A3)

def analyze_robots(text: Optional[str], status: Optional[int]) -> RobotsAnalysis: ...
```
Decoupled from `fetch` on purpose (takes the raw robots body + HTTP status, not a `Fetched`).
Use `protego` (`Protego.parse(text)`, `.can_fetch("/", ua)`); absent robots (status != 200 or
empty body) ⟹ everything allowed (`present=False`, `fetched = status==200`, all
`allowed=True`). Extract `Sitemap:` lines (protego exposes them, else parse lines). One
`BotPolicy` per `AI_CRAWLERS` bot, carrying its tier from `audit.bots`.

`unreadable` is the narrower question "did we get an answer at all?", and only it drives the
A3 `skip`: `status is None` (timeout / network error), `status >= 500`, or `status == 429` —
the last two are what RFC 9309 calls *unavailable* and tells crawlers to read as a full
disallow, and a request that never completed tells us even less than those do. It
is deliberately **not** the same as `not present`: a `404` is an answer, so it stays readable
and A3 passes.

### `audit/html.py`
```python
class HtmlAnalysis(BaseModel):
    # A5 SSR
    raw_word_count: int
    heading_count: int
    empty_root_markers: list[str]
    framework: Optional[str]
    has_noscript: bool
    js_dependent: bool
    # B2 semantic
    h1_count: int
    has_main_or_article: bool
    heading_order_ok: bool
    # B3 meta
    title: Optional[str]
    meta_description: Optional[str]
    canonical: Optional[str]
    lang: Optional[str]
    noindex: bool
    og_present: bool
    # B1 JSON-LD
    jsonld_types: list[str]         # every @type string found (deduped, order-preserved)
    jsonld_blocks: int
    jsonld_invalid: int             # blocks that failed json.loads
    has_organization: bool
    org_logo: bool
    org_sameas: int                 # count of sameAs entries on Organization
    # C1 entity
    has_about_link: bool
    has_contact_link: bool
    # D freshness
    has_dates: bool                 # datePublished/dateModified in JSON-LD or <time datetime>
    has_feed: bool                  # <link rel=alternate type=rss|atom>

def analyze_html(html: Optional[str]) -> HtmlAnalysis: ...
```
Use `selectolax` (`HTMLParser`). JSON-LD via `<script type="application/ld+json">` nodes +
stdlib `json.loads` (a block may be a list or a `@graph`; walk it for `@type` and
Organization). `analyze_html(None)` (no HTML) returns an all-empty analysis with
`js_dependent=True` (no readable content). Thresholds/markers per §4.

### `audit/cache.py` (TTL over the `audits` table)
```python
def is_fresh(checked_at: str, max_age_s: int) -> bool: ...   # parse ISO, compare to now(UTC)
```
The gate uses `pipeline.db.get_latest_audit` + `is_fresh` to decide reuse-vs-refresh; the
`audits` table is both the history and the cache. `--no-cache` forces a fresh audit;
`--max-age` (default 86400) is the TTL.

### `audit/checks.py` + `audit/gate.py` (Phase 2 — orchestrator-owned)
`build_checks(artifacts, robots, html, *, engine) -> list[CheckResult]` maps the analyses to
the §3 checklist; `run_audit(target, *, engine, client, timeout) -> AuditResult` gathers +
analyzes + builds. `gate.py` is the CLI in §7 of INTERFACES: fetch/cache → `AuditResult` →
persist (`insert_audit`) → JSON on STDOUT, human summary on STDERR.
