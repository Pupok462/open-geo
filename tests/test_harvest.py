from __future__ import annotations

import io
import json

import pytest
from pydantic import ValidationError

from harvest import build as build_mod
from harvest.build import build, main, to_csv
from harvest.schema import QuestionCandidate, contains_brand, normalize_query


def _cand(query, lens="general", segment="seg", signal="sig", source_url="https://x.example/1", note=None):
    return {
        "query": query,
        "lens": lens,
        "segment": segment,
        "signal": signal,
        "source_url": source_url,
        "note": note,
    }


def test_candidate_valid_and_strips():
    c = QuestionCandidate.model_validate(_cand("  hello  "))
    assert c.query == "hello"
    assert c.note is None


@pytest.mark.parametrize("field", ["query", "segment", "signal", "source_url"])
def test_candidate_rejects_empty_field(field):
    raw = _cand("q")
    raw[field] = "   "
    with pytest.raises(ValidationError):
        QuestionCandidate.model_validate(raw)


def test_candidate_rejects_bad_lens():
    with pytest.raises(ValidationError):
        QuestionCandidate.model_validate(_cand("q", lens="promo"))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  Cheapest GPU  for LLM inference? ", "cheapest gpu for llm inference"),
        ("Is Gonka legit!!!", "is gonka legit"),
        ("", ""),
        ("A, B, C.", "a, b, c"),
    ],
)
def test_normalize_query(raw, expected):
    assert normalize_query(raw) == expected


def test_contains_brand_word_boundary():
    assert contains_brand("gonka vs akash", "Gonka") is True
    assert contains_brand("gonkanauts unite", "Gonka") is False
    assert contains_brand("what is example app pricing", "Example App") is True
    assert contains_brand("example reviews", "Example App") is False
    assert contains_brand("anything", "") is False
    assert contains_brand("anything", "   ") is False


def test_contains_brand_cyrillic():
    assert contains_brand("матрас аскона отзывы", "Аскона") is True
    assert contains_brand("матрас askona отзывы", "Аскона") is False
    assert contains_brand("АСКОНА цена", "аскона") is True
    assert contains_brand("асконаленд обзор", "Аскона") is False
    assert contains_brand("askona vs ormatek", "Askona") is True


def test_contains_brand_multi_token():
    assert contains_brand("отзывы про аскона матрас премиум", "Аскона Матрас") is True
    assert contains_brand("отзывы про аскона диван", "Аскона Матрас") is False
    assert contains_brand("what is example app pricing", "Example App") is True


def test_build_happy_path_counts_lenses():
    items = [
        _cand("cheapest gpu cloud", "general"),
        _cand("what is gonka", "branded"),
        _cand("gonka vs akash", "comparative"),
    ]
    r = build(items, brand="Gonka")
    assert r["written"] == 3
    assert r["by_lens"] == {"general": 1, "branded": 1, "comparative": 1}
    assert r["dropped_dups"] == 0
    assert r["errors"] == []


def test_build_dedups_by_normalized_query():
    items = [
        _cand("cheapest gpu cloud for llm inference", "general"),
        _cand("Cheapest GPU cloud for LLM inference?", "general"),
    ]
    r = build(items)
    assert r["written"] == 1
    assert r["dropped_dups"] == 1


def test_build_lens_brand_guard():
    items = [
        _cand("gonka is cheap", "general"),
        _cand("best gpu cloud", "branded"),
    ]
    r = build(items, brand="Gonka")
    assert r["written"] == 0
    fields = {e["field"] for e in r["errors"]}
    assert fields == {"lens"}
    assert r["errors"][0]["query"] == "gonka is cheap"


def test_build_no_brand_skips_lens_guard():
    items = [_cand("gonka is cheap", "general"), _cand("best gpu cloud", "branded")]
    r = build(items, brand="")
    assert r["written"] == 2
    assert r["errors"] == []


def test_build_validation_error_does_not_abort_batch():
    items = [
        _cand("", "general"),
        _cand("good one", "general"),
    ]
    r = build(items)
    assert r["written"] == 1
    assert len(r["errors"]) == 1
    err = r["errors"][0]
    assert err["index"] == 0
    assert err["field"] == "query"
    assert err["query"] == ""


def test_build_validation_error_query_none_when_not_dict():
    r = build(["not-a-dict"])
    assert r["written"] == 0
    assert r["errors"][0]["query"] is None
    assert r["errors"][0]["index"] == 0


def test_to_csv_header_and_quoting():
    cands = build([_cand("a, b, c", "general")])["kept"]
    text = to_csv(cands)
    lines = text.splitlines()
    assert lines[0] == "query,lens"
    assert lines[1] == '"a, b, c",general'


def test_main_writes_csv_and_prints_summary(tmp_path, monkeypatch, capsys):
    out = tmp_path / "q.csv"
    payload = [
        _cand("cheapest gpu cloud", "general"),
        _cand("what is gonka", "branded"),
        _cand("gonka is cheap", "general"),
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = main(["--out", str(out), "--brand", "Gonka"])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["out"] == str(out)
    assert summary["written"] == 2
    assert summary["by_lens"]["general"] == 1
    assert len(summary["errors"]) == 1
    body = out.read_text(encoding="utf-8")
    assert body.startswith("query,lens\n")
    assert "gonka is cheap" not in body


def test_main_rejects_non_list_stdin(tmp_path, monkeypatch, capsys):
    out = tmp_path / "q.csv"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"not": "a list"})))
    rc = main(["--out", str(out)])
    assert rc == 1
    assert "JSON array" in capsys.readouterr().err
    assert not out.exists()


def test_lenses_constant():
    assert build_mod.LENSES == ("general", "branded", "comparative")
