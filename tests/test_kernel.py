from __future__ import annotations

from kernel.classify import auto_accept, band, insert_for, intent, rel
from kernel.cluster import is_child, same_question
from kernel.ingest import profile_from_html
from kernel.schema import Question
from kernel import collect


def test_intent_axes():
    assert intent("что умеет claude code") == "informational"
    assert intent("claude code vs cursor") == "comparative"
    assert intent("claude code цена") == "transactional"
    assert intent("обзор claude code") == "commercial"
    assert intent("claude code login") == "navigational"
    assert intent("claude code download") == "navigational"


def test_bands():
    assert band(None) == "unknown"
    assert band(3) == "micro"
    assert band(80) == "low"
    assert band(1200) == "mid"
    assert band(9000) == "high"


def test_rel_brand_and_category():
    assert rel("что умеет claude code", "Claude Code", {"агент"}) == "S1"
    assert rel("лучшие ai coding agents", "Claude Code", {"coding", "agents"}) == "S2"
    assert rel("что такое программирование", "Claude Code", {"агент"}) == "S3"
    assert rel("claude code login", "Claude Code", set()) == "S4"


def test_child_is_not_synonym():
    assert same_question("claude code возможности", "возможности claude code")
    assert not same_question("что умеет claude code", "что умеет claude code кроме программирования")
    assert is_child("что умеет claude code", "что умеет claude code кроме программирования")
    assert not is_child("что умеет claude code кроме программирования", "что умеет claude code")


def test_auto_rejects_head_and_s3():
    head = Question(id="q1", canonical="купить диван", rel="S2", band="high", intent="transactional", insert="own_page")
    s3 = Question(id="q2", canonical="что такое мебель", rel="S3", band="low", intent="informational", insert="skip")
    good = Question(id="q3", canonical="электрическая турка с автоотключением", rel="S2", band="low", intent="commercial", insert="own_page")
    assert auto_accept(head) is False
    assert auto_accept(s3) is False
    assert auto_accept(good) is True


def test_insert_child_is_h2():
    q = Question(id="q2", canonical="кроме программирования", parent_id="q1", rel="S1", band="low", intent="informational")
    q.insert = insert_for(q)
    assert q.insert == "h2_of_parent"


def test_profile_extracts_seeds():
    html = """
    <html><head><title>Korkmaz — турецкая посуда</title>
    <meta property="og:site_name" content="Korkmaz">
    <meta name="description" content="Электрические турки и кастрюли.">
    </head><body><h1>Посуда Korkmaz</h1><h2>Электрические турки</h2></body></html>
    """
    p = profile_from_html("https://korkmaz.ru", html)
    assert p.brand == "Korkmaz"
    assert p.domain == "korkmaz.ru"
    assert any("турк" in s.lower() for s in p.seeds + p.claims)


def test_round_is_iterative_and_respects_reject(tmp_path):
    html = "<html><head><title>Acme Agent</title></head><body><h1>Acme Agent</h1></body></html>"
    kernel = collect.start("https://acme.example", brand="Acme Agent", html=html, root=tmp_path)

    def expand(seed, geo, language, n):
        return {"phrases": [
            {"phrase": "acme agent возможности", "volume": 40, "provider": "wordstat", "scope": "t"},
            {"phrase": "acme agent vs cursor", "volume": 20, "provider": "wordstat", "scope": "t"},
            {"phrase": "что такое программирование", "volume": 8000, "provider": "wordstat", "scope": "t"},
        ]}

    kernel = collect.round(kernel, n=10, expand=expand, root=tmp_path)
    assert kernel.round == 1
    assert kernel.by_status("inbox")
    generic = next(q for q in kernel.questions if "программирование" in q.canonical)
    kernel = collect.decide(kernel, generic.id, "rejected", root=tmp_path)
    n_before = len(kernel.questions)
    kernel = collect.round(kernel, n=10, expand=expand, root=tmp_path)
    assert len(kernel.questions) == n_before
    assert "что такое программирование" in kernel.rejected_memory
