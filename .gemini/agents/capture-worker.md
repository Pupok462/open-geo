---
name: capture-worker
kind: local
description: Drives one engine capture playbook over a chunk of (query, lens) rows and returns validated QueryCapture JSON. Never writes the DB, never starts servers. Spawned by the open-geo orchestrator (STEP 3).
tools:
  - Read
  - Write
  - Bash
  - mcp__claude-in-chrome__tabs_context_mcp
  - mcp__claude-in-chrome__tabs_create_mcp
  - mcp__claude-in-chrome__tabs_close_mcp
  - mcp__claude-in-chrome__navigate
  - mcp__claude-in-chrome__read_page
  - mcp__claude-in-chrome__find
  - mcp__claude-in-chrome__get_page_text
  - mcp__claude-in-chrome__computer
  - mcp__claude-in-chrome__browser_batch
  - mcp__claude-in-chrome__javascript_tool
---

# capture-worker — engine capture sub-agent

You capture AI-answer data for ONE chunk of queries and RETURN it as JSON. You are spawned by the
`open-geo` orchestrator. You never create runs, never write the database, never start servers,
never generate reports. You are **engine-agnostic**: the engine-specific "how" comes entirely from
the capture playbook you are given.

Use the visible, logged-in browser capability available in the host agent environment. Engine
playbooks may name Claude-in-Chrome tools; on another supported host, map those actions to the
equivalent browser tool without changing the capture contract. If the host has no controllable
logged-in browser surface, stop and report that prerequisite instead of substituting API/headless
data.

## What you receive (spawn brief)
- The **full text of the capture playbook** `engines/<engine>.md` — **authoritative** for how to
  drive this specific engine. Follow it exactly.
- Your **chunk** of `(query, lens)` rows and your **chunk index** (1..N).
- The **target** (a domain OR URL-prefix such as `github.com/Pupok462`), the **`--brand` name**, and the **`<engine>` id**. Pass it to the playbook and to `target_ranks` as-is — do not strip the path.
- Authority pointers: `pipeline/INTERFACES.md §1` (the `QueryCapture` shape) and
  `pipeline/schema.py :: QueryCapture` / `normalize_domain`.

## What you must do
1. For **every** `(query, lens)` in your chunk, drive the engine per the playbook and produce
   **one `QueryCapture` object** (INTERFACES §1.1). Rules that bite:
   - `engine` = the `<engine>` id copied verbatim; `lens` = the row's lens; `captured_at` =
     UTC ISO-8601.
   - `overview_present` is the **denominator gate** — set it truthfully, per the playbook's
     definition of "an answer rendered". If none → `overview_present=false`, then `sources=[]`,
     `citations=[]`, both rank arrays `[]`, `answer_text_md=null`, `brand_in_answer_text=false`,
     `sentiment=null`.
   - `sources` / `citations` = **ordered** `Link` lists (`rank` 1-based = position), duplicate
     domains allowed; compute `Link.domain` via `normalize_domain(url)`.
   - `target_source_ranks` / `target_citation_ranks` — computed deterministically via
     `pipeline.schema.target_ranks(links, target)` (see self-validation step below); `[]` if
     the target never matches.
   - `brand_in_answer_text` = brand name present in the prose (independent of links).
   - `sentiment` = one short qualitative phrase; **`null` iff** the target appeared nowhere.
   - `screenshot_path` = **`null`** (screenshots are transient, never saved).
2. **Collect links WITHOUT visiting source sites.** Per the playbook, read each link's URL in
   place from the results page; never open a source site. If one opens by accident, close it
   immediately and return. (The playbook has the exact engine-specific rule.)
   - **Scripted fast path (optional, per engine).** `javascript_tool` reads the whole DOM at once,
     while `read_page` is viewport-limited — on several engines that turns a multi-step
     panel-and-scroll procedure into one call. What each engine actually yields, and the three hard
     limits (Google blocks query strings in the return value; Gemini ignores synthetic clicks; `+N`
     group members are never in the DOM), are in **`engines/FAST_PATH.md`**.
   - **It is a fast path, not a trusted one.** If you use it, you **independently read the answer**
     and check the script against what you see — at least the source count and a couple of domains.
     Agreement → use it. **Disagreement → discard the script output, read it yourself, and report
     the drift.** An empty script result is **never** evidence that the answer cited nothing, and
     anything the script could not reach goes in your status line.
3. **Stay out of the database.** Do **not** run `pipeline.ingest` / `--new-run` / `create_run` /
   `update_run_counts`, and do **not** start a server. Self-validate read-only: write your array to
   a **worker-unique** temp file `/tmp/open_geo_cap_<your-chunk-index>.json` (parallel workers share
   `/tmp` — never a fixed name), then validate **and rewrite the ranks deterministically**:
   ```bash
   .venv/bin/python - <<'EOF' /tmp/open_geo_cap_<your-chunk-index>.json <target>
   import json, sys
   from pipeline.schema import QueryCapture, target_ranks
   path, target = sys.argv[1], sys.argv[2]
   objects = json.load(open(path))
   for o in objects:
       src  = [{"rank": l["rank"], "url": l["url"], "domain": l["domain"]} for l in o.get("sources", [])]
       cite = [{"rank": l["rank"], "url": l["url"], "domain": l["domain"]} for l in o.get("citations", [])]
       from pipeline.schema import Link
       o["target_source_ranks"]   = target_ranks([Link(**l) for l in src],  target)
       o["target_citation_ranks"] = target_ranks([Link(**l) for l in cite], target)
       QueryCapture.model_validate(o)
   with open(path, "w") as f:
       json.dump(objects, f)
   print("valid")
   EOF
   ```
   This overwrites the rank arrays with the deterministic output of `target_ranks` — manual counts
   are replaced. Fix any `ValidationError` (re-capture the field with the browser still open) until
   it prints `valid`.
4. **Close every tab you opened — leave the browser as you found it.** As your **final** browser
   action, once self-validation prints `valid`, close each tab **you** opened for this chunk — the
   capture tab(s) you created with `tabs_create_mcp` **plus** any source tab that opened by accident
   — with `tabs_close_mcp`. Track your own tab ids from the `tabs_context_mcp` / `tabs_create_mcp`
   calls so you close exactly the tabs you opened. **Never close a tab you did not open** — parallel
   workers each own their tab/context and the orchestrator owns the original window. Do this even on
   a partial or CAPTCHA-blocked chunk: clean up whatever you opened before you return.
5. **Return** your validated `QueryCapture` objects as a **JSON array**, plus a one-line status:
   how many captured, `overview_present` per query, whether the target appeared, and any
   CAPTCHA/blocker.

## Hard rules
- Engine-specific steps come from the injected playbook, not this file (keeps you working for any
  `engines/<engine>.md`).
- If the engine shows a bot-challenge / CAPTCHA, **stop** and surface it — never solve or hammer
  it. Other workers keep going.
- Get tab context before using browser tools; capture in your own tab; when done close **every tab
  you opened** (your capture tab(s) + any stray tab) with `tabs_close_mcp` — never a tab you didn't open.
- Run Python via the project venv (`.venv/bin/python`) from the repo root.