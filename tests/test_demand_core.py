from __future__ import annotations

import json

from demand import core


def _cluster(**over) -> dict:
    base = {
        "name": "demand-primary",
        "intent": "commercial",
        "lens": "general",
        "geo": "ru",
        "language": "ru",
        "phrases": [{
            "phrase": "речевая аналитика",
            "provider": "wordstat",
            "volume": 1719,
            "metric": "impressions_per_month",
            "scope": "wordstat api: «речевая аналитика» — 1 719 показов/мес, Россия",
            "source_url": "https://wordstat.yandex.ru/?words=x",
        }],
        "questions": ["какой сервис речевой аналитики выбрать"],
    }
    base.update(over)
    return base


def _payload(**over) -> dict:
    base = {"brand": "Ectem", "domain": "ectem.ru", "clusters": [_cluster()]}
    base.update(over)
    return base


def test_build_core_mints_questions_from_measured_clusters():
    built = core.build_core(_payload())
    assert built["errors"] == []
    assert [c.query for c in built["candidates"]] == ["какой сервис речевой аналитики выбрать"]
    candidate = built["candidates"][0]
    assert candidate.segment == "demand-primary"
    assert "1 719 показов/мес" in candidate.signal      # evidence travels with the question
    totals = built["core"].totals
    assert totals["questions"] == 1
    assert totals["coverage"]["with_volume"] == 1
    assert totals["coverage"]["total_volume"] == 1719


def test_geos_and_languages_are_derived_when_absent():
    built = core.build_core(_payload(clusters=[
        _cluster(), _cluster(name="ww", geo="us", language="en"),
    ]))
    assert built["core"].geos == ["ru", "us"]
    assert built["core"].languages == ["en", "ru"]


def test_unmeasured_cluster_cannot_ship_questions():
    built = core.build_core(_payload(clusters=[
        _cluster(name="guessed", phrases=[{"phrase": "выдуманное"}]),
    ]))
    assert built["candidates"] == []
    assert built["errors"][0]["msg"].startswith("no measured phrase")


def test_scope_without_provider_is_not_evidence():
    built = core.build_core(_payload(clusters=[
        _cluster(phrases=[{"phrase": "x", "scope": "я так думаю"}]),
    ]))
    assert built["errors"][0]["field"] == "phrases"


def test_anchor_is_the_highest_volume_measured_phrase():
    built = core.build_core(_payload(clusters=[_cluster(phrases=[
        {"phrase": "малый", "provider": "wordstat", "volume": 10, "scope": "малый: 10"},
        {"phrase": "большой", "provider": "wordstat", "volume": 900, "scope": "большой: 900"},
    ])]))
    assert built["candidates"][0].signal == "большой: 900"


def test_presence_only_cluster_still_ships_with_its_signal():
    built = core.build_core(_payload(clusters=[_cluster(
        lens="branded",
        phrases=[{
            "phrase": "ectem отзывы", "provider": "suggest",
            "scope": "suggest (yandex): 'ectem отзывы' — exact autocomplete entry; presence only",
        }],
        questions=["что за сервис Ectem"],
    )]))
    assert built["errors"] == []
    assert "presence only" in built["candidates"][0].signal
    assert built["core"].totals["coverage"]["presence_only"] == 1


def test_empty_question_is_an_error_row():
    built = core.build_core(_payload(clusters=[_cluster(questions=["ok question", "   "])]))
    assert len(built["candidates"]) == 1
    assert built["errors"][0]["msg"] == "empty question"


def test_lens_brand_invariant_is_inherited_from_harvest_build():
    built = core.build_core(_payload(clusters=[
        _cluster(questions=["чем Ectem отличается от конкурентов"]),   # general naming the brand
    ]))
    assert built["candidates"] == []
    assert built["errors"][0]["field"] == "lens"


def test_invalid_core_returns_field_error():
    built = core.build_core({"brand": "X", "domain": "y", "clusters": [
        {"name": "n", "intent": "commercial", "lens": "general", "geo": "ru",
         "language": "ru", "phrases": [], "questions": ["q"]},
    ]})
    assert built["core"] is None
    assert "phrases" in built["errors"][0]["field"]


def test_cli_writes_core_and_csv(tmp_path, capsys, monkeypatch):
    payload = _payload(clusters=[_cluster(), _cluster(
        name="branded", lens="branded", questions=["что такое Ectem"],
    )])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(payload)))
    out = tmp_path / "nested" / "core.json"
    csv_path = tmp_path / "nested" / "ectem_questions.csv"
    assert core.main([
        "--out", str(out), "--questions-out", str(csv_path),
        "--brand", "Ectem", "--domain", "ectem.ru", "--rationale", "r.md",
    ]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["written"] == 2 and summary["errors"] == []
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "query,lens"
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["questions_csv"] == str(csv_path)
    assert written["rationale_md"] == "r.md"
    assert written["totals"]["by_lens"]["branded"] == 1


def test_cli_rejects_bad_stdin(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{oops"))
    assert core.main(["--out", str(tmp_path / "c.json"), "--questions-out", str(tmp_path / "q.csv")]) == 1
    assert "not valid JSON" in capsys.readouterr().err

    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("[]"))
    assert core.main(["--out", str(tmp_path / "c.json"), "--questions-out", str(tmp_path / "q.csv")]) == 1
    assert "SemanticCore" in capsys.readouterr().err


def test_cli_reports_invalid_core_without_writing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"clusters": "nope"})))
    out = tmp_path / "c.json"
    assert core.main(["--out", str(out), "--questions-out", str(tmp_path / "q.csv")]) == 1
    assert json.loads(capsys.readouterr().out)["errors"]
    assert not out.exists()
