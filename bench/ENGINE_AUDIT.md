# Live engine audit — 2026-08-12

Every row below is a **direct live probe**, not a reading of the playbook. Canary query
`best AI search visibility tracking tools` (Google needed a second query — see below). One browser,
strictly sequential: fanning capture workers out onto a single browser / single account is the
documented way to corrupt state and burn per-account quota.

Method per engine: navigate → submit → wait for the answer to settle → **one `javascript_tool`
structural probe** returning counts and link shapes. The probe is the cheap unit of drift detection:
it answers "does the control the playbook tells us to click still exist" in a single tool call.

---

## `google` — Google AI Overview

| probe | result |
|---|---|
| `get_page_text` returns the AI Overview block | **no** — playbook claim **confirmed**; full SERP text came back (Web results, Sponsored, People also ask) with the AI block absent |
| AI Overview on canary query `best AI search visibility tracking tools` | **not rendered** → `overview_present=false` is the correct capture, valid data |
| AI Overview on `what is generative engine optimization` | **rendered**: block located, 6 639 chars, **78 anchors inside the block** |
| `javascript_tool` usable | **conditionally** — see G1 |

**G1 — new constraint. `javascript_tool` on Google is blocked whenever the returned value contains
query strings.** A probe returning `a.href` came back `[BLOCKED: Cookie/query string data]`; the
identical probe returning `hostname + pathname` succeeded. Consequence: a scripted extractor on
Google **must** strip the query string before returning. That is not a limitation in practice —
`normalize_domain` discards the query string anyway, and URL-prefix target matching only needs the
path.

**G2 — the raw anchor count is not a source count.** Of the 78 anchors inside the AI Overview block,
many are duplicates of the same article (one source rendered as both an inline chip and a right-hand
card) plus `support.google.com` "about this result" helpers and `youtube.com/watch` carousel items. A
naive script that emits all 78 would overcount sources by roughly 5×. Filtering and dedup rules have
to be authored per engine, not inferred.

---

## `gemini` — Google Gemini

| probe | result |
|---|---|
| answer settled but chips rendered before reload | **3 buttons, 0 grounding chips**, 0 external links |
| after **one** `navigate` to the same chat URL | **27 buttons, 24 grounding chips**, still 0 external links |
| chips are links | **no** — buttons; real URLs are absent from the DOM until a popup is opened |
| synthetic `.click()` on all 9 domain-labelled chips | **0 popups opened, 0 URLs** — failed silently |
| **real** click via `computer` on one `Ещё 1` chip | **popup opened, 2 URLs** (`nightwatch.io/...`, `kime.ai/...`) |

**Playbook gotcha "reload the chat before reading sources" — confirmed, with numbers: 0 → 24 chips
after a single reload.** One reload was enough on this run; the playbook's "sometimes twice" was not
needed here.

**GEM1 — new finding: synthetic clicks do not work on Gemini chips.** `HTMLElement.click()` dispatched
from `javascript_tool` opened nothing on any of the nine chips tried, while a real `computer`
`left_click` on the same kind of chip opened the popup immediately. So the scripted fast path **cannot
resolve Gemini source URLs at all** — it can only enumerate chip labels and group sizes. URL
resolution stays at real-click cost: 24 chips × (click + read) ≈ 48+ tool calls for a full capture,
far above what the playbook implies.

**GEM2 — chip labels are not domains.** The 24 chips include `KIME`, `LLM Pulse`, `Searchable`
alongside `nightwatch.io`, `topify.ai`, `Frase.io`. Labels alone cannot be turned into
`normalize_domain` output, which is why GEM1 bites: there is no label-only shortcut.

`Ещё 1` = the named source **plus 1**, confirmed against the popup (2 URLs).

---

## `claude_search` — Claude web search

| probe | result |
|---|---|
| `+` menu still carries the toggles the playbook names | **yes** — `Web search` (on) and `Research` (separate, off), exactly as documented |
| external links present in the DOM without any expansion | **13 anchors → 6 distinct URLs** |
| research-trace card | present: `best AI search visibility tracking tools GEO 2026 · 6 results` — matches the playbook's "query — N results" card |
| DOM virtualized (scrolled the answer container top→bottom in 3 steps) | **no** — 13 anchors at **every** position, accumulated set stayed at 6 |

**CS1 — the virtualization warning is about `read_page`, not the DOM.** The playbook warns that the
answer body is virtualized so chips near the viewport are all you get. That is true of
`read_page(filter="interactive")` and **false** of `javascript_tool`, which sees the whole DOM. One
JS call replaced the documented expand-trace → click "N results" → read-popup → scroll sequence.

6 distinct domains == the trace's own "6 results", i.e. the inline chips already were the retrieved
set on this answer.

---

## `deepseek` — DeepSeek web search

| probe | result |
|---|---|
| playbook's pinned controls | **all three confirmed**: `Быстрый` mode, `Умный поиск` ON, `Глубокое мышление` OFF |
| numbered `[N]` inline badges | **17** |
| external links in the DOM **before** opening the panel | **17 anchors → 11 distinct URLs** |
| after **one** click on the sources counter | **29 anchors → 12 distinct URLs** (+`raw.githubusercontent.com`) |
| counter label vs playbook | playbook says `Прочитано N веб-страниц` at the top; live it rendered as **`12 веб-страниц` at the bottom** of the answer |

12 distinct URLs == the counter's own "12". Cheapest engine of the seven: two tool calls (one click,
one JS read) for the complete set, against the playbook's click → scroll-panel → read-cards loop.

---

## `yandex_neuro` — Yandex Alice

| probe | result |
|---|---|
| `Источники` panel exists | **yes** — playbook confirmed |
| `Промо` advertising cards present | **yes** — the Yandex-specific trap is real and must stay out of `sources`/`citations` |
| external links in the DOM | **28 anchors → 7 distinct URLs** |
| chip shape | **single chip = `A` with a real href; `+N` chip = `SPAN` badge with no href** — exactly the split the playbook describes |

**YA1 — new: `Enter` does not submit.** Pressing Return opened the autocomplete dropdown and left the
query unsent; the send **arrow** worked. This is the same trap already documented for Perplexity and
was not in the Yandex playbook.

---

## `perplexity` — Perplexity (one query only: search quota is per **account**, not per worker)

| probe | result |
|---|---|
| grounded-answer landmarks | all present: `Источники 40` counter, `Ответ / Ссылки / Изображения` tabs, inline `+N` chips |
| Incognito | already on, toggle in the **top bar** as documented |
| external links in the DOM on the **Answer** tab, before any click | **41 anchors → 40 distinct URLs** |
| after switching to the `Ссылки` tab | **40 anchors → 40 distinct** — the same set |
| inline chip shapes | 9 chip-like elements: **5 `+N` groups as `SPAN` with no href**, singles resolve to real URLs |

**PX1 — ⚠️ WITHDRAWN, see [`FASTPATH_AB.md`](FASTPATH_AB.md).** This section originally claimed the
complete 40-source set sits in the DOM on the Answer tab before anything is clicked. A real capture
worker **could not reproduce it**: the settled Answer tab held only **11 anchors — the single,
non-group chips** — and the full set came from the **Links tab, one click away**. The 40 seen here
were almost certainly in the DOM because the right-hand sources rail was already expanded during
this probe. **Corrected: one click + one read, not zero clicks.** Still much cheaper than scrolling
the virtualized panel — the `read_page`-vs-DOM point stands — but the headline number was wrong.

**PX2 — the carousel is still required, but only for `citations`.** `+N` groups carry no href, so
which source is attached to which sentence still needs hover-cycling. Source *discovery* no longer
does.

---

## Summary — what actually changed

| engine | drift found | playbook fixed | sources in 1 JS call |
|---|---|---|---|
| `chatgpt_search` | **yes** — Sources panel gone, replaced by hover carousel; labels mutate | yes (earlier this session) | primaries only |
| `gemini` | no drift; **new limit**: synthetic clicks dead | pointer added | **0** |
| `google` | no drift (`get_page_text` does drop the AI block); **new limit**: query-string block | pointer added | needs filtering (78 raw anchors) |
| `claude_search` | no drift; virtualization warning over-stated | pointer added | **6/6** |
| `deepseek` | minor: counter label/position differ | pointer added | 11/12, then 12/12 |
| `yandex_neuro` | **yes** — `Enter` does not submit | yes | 7 singles |
| `perplexity` | no drift; panel-scroll procedure unnecessary | pointer added | **40/40** |

Every number above came from a direct probe on a live answer, not from reading the playbooks.
