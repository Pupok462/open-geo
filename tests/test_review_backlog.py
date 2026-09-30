"""Locks the review invariants and the branches the 94.79% CI run left red."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from demand import config, providers
from demand.providers import bing
from kernel import collect
from kernel.classify import auto_accept, insert_for, rel, why
from kernel.cluster import attach, is_child, same_question
from kernel.ingest import profile_from_html, profile_from_url
from kernel.schema import BrandProfile, Formulation, Kernel, Question
from pipeline.artifact import build_run_artifact
from pipeline.db import (
    backfill_question_set_identity,
    create_run,
    get_conn,
    get_domain_stats,
    get_lens_sentiments,
    get_or_create_brand,
    init_db,
    question_set_digest,
    run_identity,
    set_run_question_set_hash,
)
from pipeline.db import comparable
from pipeline.ingest import ingest_batch, insert_capture
from pipeline.run import read_question_keys, resume_check
from pipeline.schema import QueryCapture
from report.generate import LensMetrics, ReportData, _engine_matrix_table
from report.i18n import Translator


def _kernel() -> Kernel:
    profile = BrandProfile(
        url="https://acme.example",
        domain="acme.example",
        brand="Acme Agent",
        seeds=["Acme Agent"],
    )
    return Kernel(
        slug="acme-agent",
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


def _attach(kernel: Kernel, text: str, *, volume: int | None = None) -> Question | None:
    return attach(
        kernel,
        Formulation(text=text, volume=volume, provider="suggest", scope="t"),
        brand=kernel.brand,
        category_tokens={"agent"},
        round_no=1,
    )


def _capture(query: str, lens: str) -> dict:
    return {
        "query": query,
        "lens": lens,
        "engine": "google",
        "captured_at": "2026-08-26T10:00:00Z",
        "overview_present": False,
        "answer_text_md": None,
        "sources": [],
        "citations": [],
        "target_source_ranks": [],
        "target_citation_ranks": [],
        "brand_in_answer_text": False,
        "sentiment": None,
        "screenshot_path": None,
    }


def _running_subset(db_path: str, csv_path: str) -> tuple[int, str]:
    keys = read_question_keys(csv_path)
    conn = get_conn(db_path)
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        query, lens = keys[0]
        ingested = ingest_batch(conn, run_id, [_capture(query, lens)])
        assert ingested["errors"] == []
        assert ingested["ok"]
    finally:
        conn.close()
    return run_id, question_set_digest(keys)


# --- invariants the review named ------------------------------------------


def test_comparable_same_different_and_unknown():
    assert comparable("v1", "abc", "other", "abc") == "same"
    assert comparable("v1", "abc", "other", "def") == "different"
    assert comparable("v1", None, "v1", None) == "same"
    assert comparable("v1", None, "v2", None) == "different"
    assert comparable("v1", None, None, "abc") == "unknown"
    assert comparable(None, None, None, None) == "unknown"
    assert comparable("  ", "  ", "v1", "  ") == "unknown"
    assert run_identity(None) == (None, None)
    assert run_identity({}) == (None, None)

    class _Attr:
        question_set = "v1"
        question_set_hash = "abc"

    assert run_identity(_Attr()) == ("v1", "abc")


def test_resume_check_hash_decides_whether_two_sets_are_one_measurement(tmp_path):
    csv_path = tmp_path / "questions.csv"
    csv_path.write_text(
        "query,lens\nhow to choose a tracker,general\nExample reviews,branded\n",
        encoding="utf-8",
    )
    db_path = str(tmp_path / "aeo.db")
    run_id, digest = _running_subset(db_path, str(csv_path))
    conn = get_conn(db_path)
    try:
        set_run_question_set_hash(conn, run_id, digest)
        same = resume_check(conn, "Example", "example.com", "google", str(csv_path))
        set_run_question_set_hash(conn, run_id, "ffffffffffffffff")
        different = resume_check(conn, "Example", "example.com", "google", str(csv_path))
    finally:
        conn.close()

    assert same["resumable"] is True
    assert same["n_captured"] == 1
    assert different["resumable"] is False
    assert different["n_captured"] == 1


def test_prior_context_survives_capture_sqlite_and_artifact(empty_db_path):
    leak = "Учитывая, что вы интересовались карнизами, вот три варианта."
    cap = QueryCapture(
        query="карнизы",
        lens="general",
        engine="alice",
        captured_at=datetime.now(timezone.utc),
        answer_text_md=leak,
        overview_present=True,
        sources=[{"rank": 1, "url": "https://example.com/a", "domain": "example.com"}],
        citations=[{"rank": 1, "url": "https://example.com/a", "domain": "example.com"}],
        target_source_ranks=[1],
        target_citation_ranks=[1],
        brand_in_answer_text=False,
    )
    assert cap.prior_context is True
    assert cap.prior_context_evidence
    assert "карнизами" in cap.prior_context_evidence

    conn = get_conn(empty_db_path)
    try:
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "alice")
        insert_capture(conn, run_id, cap)
        conn.commit()
        stored = conn.execute(
            "SELECT prior_context, prior_context_evidence FROM results WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        artifact = build_run_artifact(conn, run_id)
    finally:
        conn.close()

    assert stored["prior_context"] == 1
    assert "карнизами" in stored["prior_context_evidence"]
    row = artifact["results"][0]
    assert row["prior_context"] is True
    assert row["prior_context_evidence"] == stored["prior_context_evidence"]


def _metrics(visibility_in_citations: float) -> LensMetrics:
    return LensMetrics(
        lens="all",
        n_queries=4,
        n_overviews=4,
        overview_coverage=1.0,
        n_in_sources=4,
        visibility_in_sources=1.0,
        n_cited=2,
        visibility_in_citations=visibility_in_citations,
        avg_source_position=1.5,
        avg_citation_position=1.0,
        relative_citation=0.5,
        n_brand_mentions=1,
        brand_mention_rate=0.25,
    )


def _report(engine: str, visibility_in_citations: float) -> ReportData:
    return ReportData(
        brand_name="Example",
        brand_domain="example.com",
        engine=engine,
        period="today",
        run_id=1,
        run_at="2026-09-01T00:00:00Z",
        prev_run_id=None,
        prev_run_at=None,
        metrics={"all": _metrics(visibility_in_citations)},
        prev_metrics={},
        sentiments={},
    )


def test_all_engines_matrix_does_not_blend_scores():
    _, rows = _engine_matrix_table(
        Translator("en"),
        [_report("google", 0.25), _report("alice", 0.50)],
    )
    assert [row.cells[0].text for row in rows] == ["google", "alice"]
    assert rows[0].cells[3].text == "25%"
    assert rows[1].cells[3].text == "50%"


# --- branches the red run left uncovered ----------------------------------


def test_classify_partial_brand_long_phrase_and_gate():
    assert rel("claude weekly notes", "Claude Code", set()) == "S1"
    assert rel("modern methods of model training", "Claude Code", set()) == "S3"

    nav = Question(
        id="q", canonical="login", rel="S1", intent="navigational",
        band="low", insert="own_page",
    )
    assert insert_for(nav) == "skip"

    child = Question(
        id="q", canonical="child", rel="S1", intent="informational",
        band="low", parent_id="q1", volume=None,
    )
    text = why(child)
    assert "child of q1" in text
    assert "volume unknown" in text

    assert auto_accept(nav) is False
    skipped = Question(
        id="q", canonical="x", rel="S2", intent="informational",
        band="low", insert="skip",
    )
    assert auto_accept(skipped) is False
    unknown = Question(
        id="q", canonical="x", rel="S2", intent="informational",
        band="unknown", insert="own_page",
    )
    assert auto_accept(unknown) is False


def test_cluster_known_text_child_and_empty_tokens():
    assert same_question("и в на", "на в и") is False
    assert is_child("и в на", "electric turk with timer") is False
    assert is_child("electric turk", "turk electric") is False

    kernel = _kernel()
    again = _attach(kernel, "acme agent возможности", volume=5)
    assert again is kernel.questions[0]
    assert again.volume is None
    assert len(again.formulations) == 1

    bare = Kernel(
        slug="bare", brand="Acme", domain="acme.example", url="https://acme.example",
        questions=[Question(id="q001", canonical="Hello World", formulations=[])],
    )
    refreshed = _attach(bare, "Hello World", volume=9)
    assert refreshed is bare.questions[0]
    assert refreshed.volume == 9
    assert refreshed.formulations[0].text == "Hello World"

    orphan = _kernel()
    orphan.rejected_memory.append("orphan phrase here")
    assert _attach(orphan, "orphan phrase here") is None

    rejected = _kernel()
    rejected.questions[0].canonical = "electric turk"
    rejected.questions[0].status = "rejected"
    child = _attach(rejected, "electric turk with timer")
    assert child is not None
    assert child.parent_id is None

    parented = _kernel()
    parented.questions[0].canonical = "electric turk"
    parented.questions[0].status = "inbox"
    hung = _attach(parented, "electric turk with timer")
    assert hung is not None
    assert hung.parent_id == "q001"


def test_collect_caps_errors_seeds_and_default_expand(tmp_path, monkeypatch):
    kernel = _kernel()

    def explode(seed, geo, language, n):
        raise RuntimeError(f"down:{seed}")

    exploded = collect.round(kernel, n=3, expand=explode, root=tmp_path)
    assert [q.id for q in exploded.questions] == ["q001"]

    capped = _kernel()
    capped.questions = []
    capped.profile.seeds = ["Alpha Brand", "Beta Brand"]
    capped.brand = "Alpha Brand"
    seen_seeds: list[str] = []

    def two(seed, geo, language, n):
        seen_seeds.append(seed)
        return {"phrases": [
            {"phrase": f"{seed} first option", "volume": 10, "provider": "suggest"},
            {"phrase": f"{seed} second option", "volume": 11, "provider": "suggest"},
        ]}

    capped = collect.round(capped, n=1, expand=two, root=tmp_path)
    assert seen_seeds == ["Alpha Brand"]
    assert [q.canonical for q in capped.questions] == ["Alpha Brand first option"]

    synonym = _kernel()

    def same_tokens(seed, geo, language, n):
        return {"phrases": [
            {"phrase": "возможности acme agent", "volume": 15, "provider": "suggest"},
        ]}

    synonym = collect.round(synonym, n=4, expand=same_tokens, root=tmp_path)
    assert len(synonym.questions) == 1
    assert any(f.text == "возможности acme agent" for f in synonym.questions[0].formulations)

    ordered = _kernel()
    ordered.questions[0].status = "accepted"
    ordered.questions[0].canonical = "accepted question here"
    ordered.profile.seeds = ["Acme Agent", "Acme Agent"]
    ordered.brand = "Other Brand"
    order: list[str] = []

    def record(seed, geo, language, n):
        order.append(seed)
        return {"phrases": []}

    collect.round(ordered, n=5, expand=record, root=tmp_path)
    assert order == ["accepted question here", "Other Brand", "Acme Agent"]

    fresh = _kernel()
    fresh.profile = None
    fresh.round = -1
    fresh.questions = []
    fresh.brand = "Solo Brand"
    solo: list[str] = []

    def record_solo(seed, geo, language, n):
        solo.append(seed)
        return {"phrases": []}

    stepped = collect.round(fresh, n=2, expand=record_solo, root=tmp_path)
    assert stepped.round == 0
    assert solo == ["Solo Brand"]

    import demand.expand as expand_mod

    monkeypatch.setattr(
        expand_mod,
        "expand_seed",
        lambda seed, geo, language, n, deep: {
            "phrases": [{
                "phrase": "acme agent новая формулировка",
                "volume": 3,
                "provider": "suggest",
            }],
        },
    )
    grown = collect.round(_kernel(), n=2, root=tmp_path)
    assert any("новая формулировка" in q.canonical for q in grown.questions)


def test_ingest_scheme_tags_seed_cap_and_profile_from_url(monkeypatch):
    import kernel.ingest as ingest

    html = (
        "<html><head>"
        "<script>secret token</script><style>.x{}</style><noscript>off</noscript>"
        '<meta name="description" content="">'
        '<meta property="og:description" content="Visible description of the product line.">'
        "<title>Brand Title — Part Two</title>"
        "</head><body><h1>Main Heading</h1>"
        + "".join(f"<h2>Heading topic {i} detailed</h2>" for i in range(12))
        + "</body></html>"
    )
    profile = profile_from_html("example.com/path", html, brand="Yo")
    assert profile.url == "https://example.com/path"
    assert profile.description.startswith("Visible description")
    assert profile.seeds[0] == "Yo"
    assert len(profile.seeds) == 13
    assert "secret" not in " ".join(profile.seeds)

    class Response:
        text = "<title>Acme</title>"

        @staticmethod
        def raise_for_status():
            return None

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url):
            assert url == "https://acme.example/x"
            return Response()

    monkeypatch.setattr(ingest.httpx, "Client", Client)
    assert ingest.fetch_html("https://acme.example/x") == "<title>Acme</title>"

    monkeypatch.setattr(ingest, "fetch_html", lambda url: "<title>Zed Tool</title>")
    loaded = profile_from_url("zed.example", brand="Zed")
    assert loaded.brand == "Zed"
    assert loaded.url.startswith("https://")


def test_demand_config_blank_key_env_autoload_and_worldwide_locale(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_ENV_LOADED", False)
    env_file = tmp_path / "probe.env"
    env_file.write_text("=novalue\n =alsoblank\nGOOD=1\n", encoding="utf-8")
    loaded = config.load_env(str(env_file))
    assert loaded == {"GOOD": "1"}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "_ENV_LOADED", False)
    monkeypatch.setenv("REVIEW_PROBE", "  spaced  ")
    assert config.env("REVIEW_PROBE") == "spaced"
    assert config.env("MISSING_REVIEW_PROBE", "fallback") == "fallback"

    assert config.bing_locale("en", "ww") == "en-US"
    assert config.bing_locale("xx", "zz") == "xx-US"
    assert config.bing_locale("", "") == "en-US"


def test_resolve_skips_provider_that_does_not_support_locale(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_ENV_LOADED", True)
    monkeypatch.setenv("WORDSTAT_API_KEY", "k")
    from demand import cache

    conn = cache.get_conn(str(tmp_path / "demand.db"))
    try:
        usable, skipped = providers.resolve("us", "en", provider="wordstat", conn=conn)
    finally:
        conn.close()
    assert usable == []
    assert skipped[0]["provider"] == "wordstat"
    assert skipped[0]["missing_env"] == []
    assert "wordstat measures" in skipped[0]["reason"]


def test_bing_uses_cache_and_skips_dirty_related_rows(tmp_path, monkeypatch):
    from demand import cache

    monkeypatch.setattr(config, "_ENV_LOADED", True)
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "bk")
    calls: list[str] = []

    def fake(method, url, *, headers=None, json_body=None, params=None, **kwargs):
        calls.append(url)
        return {"d": [
            {"Impressions": 10, "Query": "related phrase"},
            {"Impressions": 5, "Query": "  "},
            "nope",
        ]}

    monkeypatch.setattr(bing, "http_json", fake)
    conn = cache.get_conn(str(tmp_path / "demand.db"))
    try:
        provider = bing.BingProvider(conn=conn)
        stat = provider.lookup("crm", "gb", "en", n_related=3)
        cached = provider.lookup("crm", "gb", "en", n_related=3)
    finally:
        conn.close()

    assert stat.volume == 15
    assert [item.phrase for item in stat.related] == ["related phrase"]
    assert cached.cached is True
    assert cached.related[0].phrase == "related phrase"
    assert len(calls) == 2


def test_question_set_backfill_edges(tmp_path, monkeypatch):
    import pipeline.db as db

    bare = sqlite3.connect(":memory:")
    try:
        assert backfill_question_set_identity(bare) == 0
    finally:
        bare.close()

    db_path = tmp_path / "aeo.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        conn.execute("UPDATE runs SET status = 'done' WHERE id = ?", (run_id,))
        conn.commit()
        assert backfill_question_set_identity(conn, repo_root=tmp_path) == 0
    finally:
        conn.close()

    root = tmp_path / "repo"
    root.mkdir()
    (root / "astramed_questions.csv").write_text(
        "query,lens\nhello,general\n,branded\nonly,\n",
        encoding="utf-8",
    )
    (root / "astramed_questions_v2.csv").write_text(
        "query,lens\nx,general\n",
        encoding="utf-8",
    )
    (root / "astramed_questions_v3.csv").write_text(
        "query,lens\n,\nonly,\n",
        encoding="utf-8",
    )
    real = db._csv_question_keys

    def wrapped(path):
        if path.name == "astramed_questions_v2.csv":
            raise OSError("unreadable")
        return real(path)

    monkeypatch.setattr(db, "_csv_question_keys", wrapped)
    labels = db._known_question_set_labels(root)
    digest = question_set_digest([("hello", "general")])
    assert labels == {digest: "v1 · 08.08"}
    assert real(root / "astramed_questions.csv") == [("hello", "general")]


def test_stats_readers_reraise_unexpected_sql(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE lens_sentiment (lens TEXT)")
    conn.execute("CREATE TABLE domain_stats (domain TEXT)")
    with pytest.raises(sqlite3.OperationalError, match="summary"):
        get_lens_sentiments(conn, 1)
    with pytest.raises(sqlite3.OperationalError, match="is_brand"):
        get_domain_stats(conn, 1)
    conn.close()
