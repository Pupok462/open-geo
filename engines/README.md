# engines/ — capture playbooks (the multi-engine extension point)

Each `engines/<engine>.md` is a **capture playbook**: the per-engine instructions a
Claude-in-Chrome agent follows to turn **one `(query, lens)`** into **exactly one
`QueryCapture` JSON object** (the contract in [`../pipeline/INTERFACES.md`](../pipeline/INTERFACES.md) §1).
The `<engine>` argument of the `/open-geo` command selects which playbook the capture
workers load, and is written verbatim into every `QueryCapture.engine` and onto the run.

This directory **is** how open-geo becomes multi-engine. The pipeline, contract, DB,
`ingest`/`aggregate`, dashboard and report are all **engine-agnostic** (`engine` is an open
`snake_case` string everywhere). Supporting a new engine is therefore mostly **"add one
playbook here and validate it"** — no schema or pipeline changes in the common case. The full
backlog spec is **ROADMAP Feature 3**.

## Status

| engine id | surface | status |
|---|---|---|
| `google` | Google Search → AI Overview | **implemented** — [`google.md`](google.md) (reference playbook) |
| `chatgpt_search` | ChatGPT with web search | **implemented** — [`chatgpt_search.md`](chatgpt_search.md) (grounded-answer gate) |
| `claude_search` | Claude with web search | **implemented** — [`claude_search.md`](claude_search.md) (grounded-answer gate) |
| `gemini` | Google Gemini | **implemented** — [`gemini.md`](gemini.md) (grounded-answer gate) |
| `yandex_neuro` | Yandex Alice / Нейро | **implemented** — [`yandex_neuro.md`](yandex_neuro.md) (grounded-answer gate) |
| `perplexity` | Perplexity | **implemented** — [`perplexity.md`](perplexity.md) (grounded-answer gate) |
| `deepseek` | DeepSeek with web search | **implemented** — [`deepseek.md`](deepseek.md) (grounded-answer gate) |
| … | Bing / Microsoft Copilot, You.com, Baidu, … | future, as the market evolves |

> The implemented ids are **`google`**, **`chatgpt_search`**, **`claude_search`**,
> **`yandex_neuro`**, **`gemini`**, **`deepseek`** and **`perplexity`** — each canonical because it
> equals its playbook basename (`engines/google.md`, `engines/chatgpt_search.md`,
> `engines/claude_search.md`, `engines/yandex_neuro.md`, `engines/gemini.md`,
> `engines/deepseek.md`, `engines/perplexity.md`; INTERFACES §1.1) and the value written to the live
> run/DB; that is what `/open-geo` expects. The `<vendor>_<surface>` naming
> scheme is now in use (`chatgpt_search` = ChatGPT's *search* surface, the one GEO measures).
> **`perplexity`** passed its live-validation run on **2026-08-08**; that run rewrote the playbook's
> citation model (the drafted "numbered sources + `[N]` pills" surface does not exist — see the
> validation note at the top of `perplexity.md`), which is exactly what step 6 below is for.
> The remaining **planned** ids
> (Bing/Copilot, You.com, …) are still **proposals** for ROADMAP Feature 3. If `/open-geo` is
> invoked with an engine whose `engines/<engine>.md` is missing, the skill **stops and asks for the
> playbook** — it never invents a capture procedure.

## How to add an engine

1. **Pick the id** (`snake_case`) and create `engines/<id>.md`. Start from
   [`google.md`](google.md) — it is the reference for structure and tone.
2. **Honor the contract, not the engine's chrome.** The playbook's only job is to emit a
   valid `QueryCapture` per `../pipeline/INTERFACES.md` §1. Map *this* engine's UI onto:
   - `sources` — the **full relied-on / retrieved set**, in display order, duplicates allowed.
   - `citations` — the **inline-attached** links in the answer prose. **Fold every cited link
     into `sources`** so the invariant **citations ⊆ sources** holds (enforced by
     `QueryCapture`'s validator).
   - `target_source_ranks` / `target_citation_ranks`, `brand_in_answer_text`, qualitative
     `sentiment` (free text, `null` iff the target appeared nowhere), `screenshot_path`.
3. **Decide the denominator gate (`overview_present`).** On Google an overview may not render,
   so the gate is real. On always-answering assistants (ChatGPT/Claude/Gemini/Perplexity/
   DeepSeek) an answer almost always renders — reinterpret the gate as **"a grounded / sourced
   answer rendered"** (see the §4 Scope note in INTERFACES and ROADMAP Feature 3). Document
   the chosen interpretation in the playbook.
4. **Document the per-engine knobs:** logged-in session/account required; locale/region control
   (Google uses `hl`/`gl`; others use account/UI settings); whether a model/mode picker affects
   the answer (and which default you pin); how sources vs inline citations render; any
   redirect-unwrapping needed for URLs.
5. **Keep the universal guardrails:** visible Claude-in-Chrome (not headless/API), capture what
   rendered **once** (no rerolling for a "better" answer — absence is valid data), **stop on
   CAPTCHA / anti-bot challenges** and hand off to the human, use a dedicated account at low
   volume (ToS is per-engine — review before any volume).
6. **Validate live** on a small query set across all three lenses
   (`general` / `branded` / `comparative`), confirm `ingest` accepts the batch and the
   `sources ⊇ citations` invariant holds, then add the engine to the table above.

See [`../pipeline/INTERFACES.md`](../pipeline/INTERFACES.md) (§1 contract, §4 metric model)
for the authoritative detail; multi-engine expansion is tracked as **ROADMAP Feature 3**.
