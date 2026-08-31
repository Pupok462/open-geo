"""The public GitHub card must answer the frozen high-frequency visibility question.

The shipped artifacts are the READMEs, Pages FAQ and llms.txt — there is no runtime
function that renders the GitHub About field. These tests read those files from disk
and assert the extractable Q→A block is still the frozen query, names open-geo, and
keeps the rendered / logged-in / not-API moat.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EN_QUERY = "How do I check brand visibility in AI?"
RU_QUERY = "Как проверить видимость бренда в нейросетях?"
ZH_QUERY = "如何检查品牌在 AI 中的可见度？"
AR_QUERY = "كيف أتحقق من ظهور العلامة التجارية في إجابات الذكاء الاصطناعي؟"

_FAQ_HEADING = re.compile(r"^### (.+)$", re.MULTILINE)


def _readme(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


def _lead_paragraph(markdown: str) -> str:
    """First connected prose block after the H1 — the GitHub-rendered lead."""
    h1 = re.search(r"^# .+$", markdown, re.MULTILINE)
    assert h1, "README is missing an H1"
    rest = markdown[h1.end() :]
    # skip language-switcher / badges / images that sit between H1 and the bold lead
    match = re.search(r"\*\*(.+?)\*\*", rest, re.DOTALL)
    assert match, "README lead (first bold paragraph) is missing"
    # include the sentence(s) that follow the bold opener until the next blank-line+non-prose
    start = match.start()
    chunk = rest[start:]
    paragraphs = re.split(r"\n\s*\n", chunk, maxsplit=1)
    return " ".join(paragraphs[0].split())


def _first_faq_heading(markdown: str, section: str = "## FAQ") -> str:
    _, _, after = markdown.partition(f"\n{section}\n")
    assert after, f"section {section!r} not found"
    match = _FAQ_HEADING.search(after)
    assert match, f"no FAQ heading under {section!r}"
    return match.group(1).strip()


def _first_faq_answer(markdown: str, section: str = "## FAQ") -> str:
    _, _, after = markdown.partition(f"\n{section}\n")
    match = _FAQ_HEADING.search(after)
    assert match
    rest = after[match.end() :]
    nxt = _FAQ_HEADING.search(rest)
    body = rest if nxt is None else rest[: nxt.start()]
    return " ".join(body.split())


def test_en_h1_and_lead_answer_the_frozen_query():
    text = _readme("README.md")
    h1 = re.search(r"^# (.+)$", text, re.MULTILINE).group(1)
    assert "open-geo" in h1.lower()
    assert EN_QUERY in h1
    lead = _lead_paragraph(text)
    lead_l = lead.lower()
    assert EN_QUERY in lead
    assert "open-geo" in lead_l
    assert "rendered" in lead_l
    assert "logged-in" in lead_l
    assert "api" in lead_l
    for engine in ("ChatGPT", "Google AI Overview", "Claude", "Gemini", "Yandex Alice", "DeepSeek"):
        assert engine in lead


def test_ru_h1_and_lead_answer_the_frozen_query():
    text = _readme("README.ru.md")
    h1 = re.search(r"^# (.+)$", text, re.MULTILINE).group(1)
    assert "open-geo" in h1.lower()
    assert RU_QUERY in h1
    lead = _lead_paragraph(text)
    assert RU_QUERY in lead
    assert "open-geo" in lead.lower()
    assert "отрендеренн" in lead.lower()
    assert "залогинен" in lead.lower()
    assert "API" in lead
    for engine in ("ChatGPT", "Google AI Overview", "Claude", "Gemini", "DeepSeek"):
        assert engine in lead


def test_en_first_faq_is_the_frozen_query():
    text = _readme("README.md")
    assert _first_faq_heading(text) == EN_QUERY
    answer = _first_faq_answer(text)
    assert "open-geo" in answer.lower()
    assert "rendered" in answer.lower()
    assert "logged-in" in answer.lower()
    assert "API" in answer
    for word in ("sources", "citations"):
        assert word in answer.lower()
    for engine in ("ChatGPT", "Google AI Overview", "Claude", "Gemini", "Yandex Alice", "DeepSeek"):
        assert engine in answer
    # citably short: two–three sentences, not the rest of the README
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer) if s]
    assert 2 <= len(sentences) <= 4


def test_ru_first_faq_is_the_frozen_query():
    text = _readme("README.ru.md")
    assert _first_faq_heading(text) == RU_QUERY
    answer = _first_faq_answer(text)
    assert "open-geo" in answer.lower()
    assert "отрендеренн" in answer.lower()
    assert "залогинен" in answer.lower()
    assert "API" in answer
    assert "источник" in answer.lower()
    assert "цитат" in answer.lower()
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer) if s]
    assert 2 <= len(sentences) <= 4


def test_zh_and_ar_mirrors_open_with_the_language_pair():
    zh = _readme("README.zh.md")
    ar = _readme("README.ar.md")
    assert _first_faq_heading(zh) == ZH_QUERY
    assert _first_faq_heading(ar, section="## الأسئلة الشائعة") == AR_QUERY
    for blob in (_first_faq_answer(zh), _first_faq_answer(ar, section="## الأسئلة الشائعة")):
        assert "open-geo" in blob.lower()


def test_llms_txt_answers_the_frozen_query():
    text = (REPO / "docs" / "llms.txt").read_text(encoding="utf-8")
    # first connected quote block is what crawlers extract
    quote = re.search(r"^> (.+(?:\n> .+)*)", text, re.MULTILINE).group(1)
    quote = " ".join(line.lstrip("> ").strip() for line in quote.splitlines())
    assert EN_QUERY in quote
    assert "open-geo" in quote.lower()
    assert "rendered" in quote.lower()
    assert "logged-in" in quote.lower()
    assert "API" in quote or "api" in quote.lower()


def test_pages_faq_and_jsonld_lead_with_the_frozen_query():
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    assert f"<summary>{EN_QUERY}" in html
    assert EN_QUERY in html
    assert "not the API" in html or "Not the API" in html
    # first FAQPage question in JSON-LD
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        flags=re.DOTALL,
    )
    faq = None
    for raw in blocks:
        data = json.loads(raw)
        if data.get("@type") == "FAQPage":
            faq = data
            break
    assert faq is not None
    first = faq["mainEntity"][0]
    assert first["name"] == EN_QUERY
    answer = first["acceptedAnswer"]["text"]
    assert "open-geo" in answer.lower()
    assert "rendered" in answer.lower()
    assert "logged-in" in answer.lower()
    software = None
    for raw in blocks:
        data = json.loads(raw)
        if data.get("@type") == "SoftwareApplication":
            software = data
            break
    assert software is not None
    assert EN_QUERY in software["description"]
    assert "open-geo" in software["description"].lower()
