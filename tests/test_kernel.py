from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from kernel import collect, store
from kernel.__main__ import main
from kernel.classify import auto_accept, band, insert_for, intent, rel
from kernel.cluster import is_child, same_question
from kernel.ingest import profile_from_html
from kernel.schema import BrandProfile, Formulation, Kernel, Question
from kernel.serve import app


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


def _kernel(slug: str = "acme-agent") -> Kernel:
    profile = BrandProfile(
        url="https://acme.example",
        domain="acme.example",
        brand="Acme Agent",
        seeds=["Acme Agent"],
    )
    return Kernel(
        slug=slug,
        brand="Acme Agent",
        domain="acme.example",
        url="https://acme.example",
        profile=profile,
        questions=[
            Question(
                id="q001",
                canonical="acme agent возможности",
                formulations=[Formulation(text="acme agent возможности", volume=40)],
                rel="S1",
                band="low",
                status="inbox",
            )
        ],
    )


def test_cli_show_round_start_and_serve(monkeypatch, tmp_path, capsys):
    kernel = _kernel()
    store.save(kernel, tmp_path)
    monkeypatch.setattr(store, "CORE_DIR", tmp_path)

    assert main(["show", "--slug", kernel.slug]) == 0
    assert json.loads(capsys.readouterr().out)["slug"] == kernel.slug

    monkeypatch.setattr(collect, "round", lambda current, n=12: current)
    assert main(["round", "--slug", kernel.slug, "--n", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["round"] == 0

    monkeypatch.setattr(collect, "start", lambda *args, **kwargs: _kernel("started"))
    assert main(["start", "--url", "https://acme.example", "--gate", "auto"]) == 0
    assert json.loads(capsys.readouterr().out)["slug"] == "started"

    called = {}
    monkeypatch.setattr(
        "kernel.serve.run",
        lambda **kwargs: called.update(kwargs),
    )
    assert main(["serve", "--host", "0.0.0.0", "--port", "8123", "--open"]) == 0
    assert called == {"host": "0.0.0.0", "port": 8123, "open_browser": True}


def test_board_api_crud_and_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "CORE_DIR", tmp_path)
    kernel = _kernel()
    store.save(kernel)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "Семантическое ядро" in response.text

    response = client.get(f"/api/board/{kernel.slug}")
    assert response.status_code == 200
    assert response.json()["counts"] == {"inbox": 1, "accepted": 0, "rejected": 0, "deferred": 0}
    assert client.get("/api/board/missing").status_code == 404

    response = client.post(
        "/api/decide",
        json={"slug": kernel.slug, "question_id": "q001", "status": "accepted"},
    )
    assert response.status_code == 200
    assert response.json()["counts"]["accepted"] == 1
    assert client.post(
        "/api/decide",
        json={"slug": kernel.slug, "question_id": "missing", "status": "accepted"},
    ).status_code == 404
    assert client.post(
        "/api/decide",
        json={"slug": kernel.slug, "question_id": "q001", "status": "bad"},
    ).status_code == 400
    assert client.post(
        "/api/decide",
        json={"slug": "missing", "question_id": "q001", "status": "accepted"},
    ).status_code == 404

    response = client.post("/api/gate", json={"slug": kernel.slug, "gate": "auto"})
    assert response.status_code == 200
    assert response.json()["gate"] == "auto"
    assert client.post("/api/gate", json={"slug": kernel.slug, "gate": "bad"}).status_code == 400
    assert client.post("/api/gate", json={"slug": "missing", "gate": "human"}).status_code == 404

    monkeypatch.setattr(collect, "round", lambda current, n=12: current)
    assert client.post("/api/round", json={"slug": kernel.slug, "n": 2}).status_code == 200
    assert client.post("/api/round", json={"slug": "missing", "n": 2}).status_code == 404

    monkeypatch.setattr(collect, "start", lambda *args, **kwargs: _kernel("created"))
    response = client.post(
        "/api/start",
        json={"url": "https://acme.example", "brand": "Acme Agent", "n": 2},
    )
    assert response.status_code == 200
    assert response.json()["slug"] == "created"


def test_serve_run_delegates_to_uvicorn(monkeypatch):
    import kernel.serve as serve

    opened = []
    calls = []
    monkeypatch.setattr(serve.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    serve.run(host="127.0.0.2", port=8124, open_browser=True)

    assert opened == ["http://127.0.0.2:8124/"]
    assert calls == [((serve.app,), {"host": "127.0.0.2", "port": 8124, "log_level": "info"})]


def test_cluster_duplicate_formulation_and_empty_text():
    from kernel.cluster import attach

    kernel = _kernel()
    existing = kernel.questions[0]
    assert attach(
        kernel,
        Formulation(text="   "),
        brand=kernel.brand,
        category_tokens={"agent"},
        round_no=1,
    ) is None
    same = attach(
        kernel,
        Formulation(text="возможности acme agent", volume=80),
        brand=kernel.brand,
        category_tokens={"agent"},
        round_no=1,
    )
    assert same is existing
    assert existing.volume == 80


def test_ingest_fetch_and_helpers(monkeypatch):
    import kernel.ingest as ingest

    class Response:
        text = "<title>Acme</title>"

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            assert url == "https://acme.example"
            return Response()

    monkeypatch.setattr(ingest.httpx, "Client", Client)
    assert ingest.fetch_html("acme.example") == "<title>Acme</title>"
    assert ingest.re_split("Acme | Agent – Search") == ["Acme", "Agent", "Search"]
    assert ingest.re_split("  ") == ["  "]
    assert profile_from_html("https://www.com", "<html></html>").brand == "com"


def test_collect_error_auto_gate_and_decide_errors(tmp_path):
    kernel = _kernel()
    kernel.gate = "auto"

    def expand(seed, geo, language, n):
        if seed == "Acme Agent":
            return {"phrases": [
                {"phrase": "acme agent цена", "volume": 40},
                {"phrase": "что такое программирование", "volume": 8000},
            ]}
        raise RuntimeError("provider unavailable")

    kernel = collect.round(kernel, n=4, expand=expand, root=tmp_path)
    statuses = {q.canonical: q.status for q in kernel.questions}
    assert statuses["acme agent цена"] == "accepted"
    assert statuses["что такое программирование"] == "deferred"

    with pytest.raises(ValueError, match="bad status"):
        collect.decide(kernel, "q001", "bad", root=tmp_path)
    with pytest.raises(KeyError, match="missing"):
        collect.decide(kernel, "missing", "accepted", root=tmp_path)
