# Extraction task — turn a frozen ChatGPT capture into one `QueryCapture` object

You are the capture step of open-geo. A `(query, lens)` has **already** been driven in a real
logged-in Chrome and the browser tool output has been **frozen to disk**. You do not have a browser
and you must not try to open one. Your only job is the part this benchmark measures: **read the
frozen page artifacts and assemble exactly one valid `QueryCapture` JSON object.**

## Inputs (read all of them)

Fixture directory: `bench/fixtures/chatgpt_search__ai_visibility_2026/`

| file | what it is |
|---|---|
| `meta.json` | query, lens, engine, brand, target, capture context |
| `01_get_page_text.txt` | verbatim `get_page_text` output — answer prose, table, inline citation chip labels in reading order |
| `02_read_page_interactive.txt` | verbatim `read_page(filter="interactive")` output, `main` subtree |
| `03_dom_links.json` | verbatim DOM dump of every `<a href>` inside `main`, pristine, in document order |

## Authority

- `pipeline/INTERFACES.md` §1 — the `QueryCapture` contract (fields §1.1, rules §1.2, example §1.3).
- `engines/chatgpt_search.md` — the ChatGPT capture playbook (how sources/citations/the grounded-answer
  gate are defined for this engine).
- `pipeline/schema.py` — `QueryCapture`, `Link`, `normalize_domain`, `target_ranks`.

Read them. Do not invent fields and do not invent data: **every URL you emit must appear in one of
the fixture files.** If something the playbook tells you to open is not present in the fixture,
capture what is actually there and say so in your status line — never fill a gap with a plausible
guess.

## Output

Write your single JSON object (not an array) to the path given to you, then print a one-line status:
whether the answer was grounded, how many sources/citations you found, whether the target appeared.

Validate before you finish:

```bash
.venv/bin/python -c "
import json,sys
from pipeline.schema import QueryCapture
QueryCapture.model_validate(json.load(open(sys.argv[1])))
print('valid')
" <your output path>
```
