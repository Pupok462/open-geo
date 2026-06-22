from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.db import create_run, get_conn, get_or_create_brand, init_db
from pipeline.ingest import (
    _field_path,
    _links_to_jsonable,
    _read_stdin_array,
    ingest_batch,
    insert_capture,
    main,
)
from pipeline.schema import Link, QueryCapture

REPO_ROOT = Path(__file__).resolve().parent.parent


def _valid_capture_dict(**overrides) -> dict:
    base = {
        "query": "best task tracking tools",
        "lens": "general",
        "engine": "google",
        "captured_at": "2026-06-18T20:15:30Z",
        "overview_present": True,
        "sources": [
            {"rank": 1, "url": "https://example.com/catalog/x", "domain": "example.com"},
        ],
        "citations": [],
        "target_source_ranks": [1],
        "target_citation_ranks": [],
        "brand_in_answer_text": True,
        "sentiment": "recommended as one of the options",
    }
    base.update(overrides)
    return base


def _fresh_db_with_run(tmp_path, name="aeo.db") -> tuple[str, int]:
    db_path = str(tmp_path / name)
    conn = get_conn(db_path)
    try:
        init_db(conn)
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
    finally:
        conn.close()
    return db_path, run_id


def _run_row(db_path: str, run_id: int):
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT n_queries, n_ok, n_failed, status FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()


def _results_count(db_path: str, run_id: int) -> int:
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM results WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_field_path_empty_tuple_returns_empty_string():
    assert _field_path(()) == ""


def test_field_path_single_key():
    assert _field_path(("lens",)) == "lens"


def test_field_path_nested_mixed_int_and_str():
    assert _field_path(("sources", 0, "rank")) == "sources.0.rank"


def test_links_to_jsonable_empty_list():
    assert _links_to_jsonable([]) == []


def test_links_to_jsonable_serializes_links_to_plain_dicts():
    links = [
        Link(rank=1, url="https://example.com/a", domain="example.com"),
        Link(rank=2, url="https://other.org/b", domain="other.org"),
    ]
    out = _links_to_jsonable(links)
    assert out == [
        {"rank": 1, "url": "https://example.com/a", "domain": "example.com"},
        {"rank": 2, "url": "https://other.org/b", "domain": "other.org"},
    ]
    assert set(out[0].keys()) == {"rank", "url", "domain"}


def test_links_to_jsonable_preserves_unicode():
    links = [Link(rank=1, url="https://exámple.com/路径", domain="exámple.com")]
    out = _links_to_jsonable(links)
    assert out[0]["url"] == "https://exámple.com/路径"
    assert out[0]["domain"] == "exámple.com"


def test_insert_capture_persists_full_row_and_returns_lastrowid(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(
            {
                "query": "best project management software",
                "lens": "general",
                "engine": "google",
                "captured_at": "2026-06-18T20:15:30Z",
                "answer_text_md": "Example is solid.",
                "screenshot_path": "data/screenshots/1/0.png",
                "overview_present": True,
                "sources": [
                    {"rank": 1, "url": "https://sf.org/x", "domain": "sf.org"},
                    {"rank": 2, "url": "https://example.com/a", "domain": "example.com"},
                    {"rank": 4, "url": "https://example.com/b", "domain": "example.com"},
                ],
                "citations": [
                    {"rank": 1, "url": "https://example.com/a", "domain": "example.com"},
                ],
                "target_source_ranks": [2, 4],
                "target_citation_ranks": [1],
                "brand_in_answer_text": True,
                "sentiment": None,
            }
        )
        rowid = insert_capture(conn, run_id, cap)
        conn.commit()
        assert isinstance(rowid, int)
        assert rowid > 0

        row = conn.execute(
            "SELECT * FROM results WHERE id = ?", (rowid,)
        ).fetchone()

        assert row["run_id"] == run_id
        assert row["query"] == "best project management software"
        assert row["lens"] == "general"
        assert row["answer_text_md"] == "Example is solid."
        assert row["screenshot_path"] == "data/screenshots/1/0.png"

        assert row["overview_present"] == 1
        assert row["brand_in_answer_text"] == 1
        assert isinstance(row["overview_present"], int)

        assert row["captured_at"] == cap.captured_at.isoformat()
        assert isinstance(row["captured_at"], str)

        assert row["sentiment"] is None

        sources = json.loads(row["sources_json"])
        citations = json.loads(row["citations_json"])
        src_ranks = json.loads(row["target_source_ranks_json"])
        cit_ranks = json.loads(row["target_citation_ranks_json"])

        assert sources == [
            {"rank": 1, "url": "https://sf.org/x", "domain": "sf.org"},
            {"rank": 2, "url": "https://example.com/a", "domain": "example.com"},
            {"rank": 4, "url": "https://example.com/b", "domain": "example.com"},
        ]
        assert citations == [
            {"rank": 1, "url": "https://example.com/a", "domain": "example.com"},
        ]
        assert src_ranks == [2, 4]
        assert cit_ranks == [1]
    finally:
        conn.close()


def test_insert_capture_false_booleans_and_empty_arrays(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(
            {
                "query": "no overview here",
                "lens": "branded",
                "engine": "google",
                "captured_at": "2026-06-18T00:00:00Z",
                "overview_present": False,
                "brand_in_answer_text": False,
            }
        )
        rowid = insert_capture(conn, run_id, cap)
        conn.commit()
        row = conn.execute("SELECT * FROM results WHERE id = ?", (rowid,)).fetchone()
        assert row["overview_present"] == 0
        assert row["brand_in_answer_text"] == 0
        assert json.loads(row["sources_json"]) == []
        assert json.loads(row["citations_json"]) == []
        assert json.loads(row["target_source_ranks_json"]) == []
        assert json.loads(row["target_citation_ranks_json"]) == []
    finally:
        conn.close()


def test_insert_capture_unicode_round_trips(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(
            {
                "query": "проекты",
                "lens": "general",
                "engine": "google",
                "captured_at": "2026-06-18T00:00:00Z",
                "overview_present": True,
                "sources": [
                    {"rank": 1, "url": "https://example.com/проект", "domain": "example.com"},
                ],
                "target_source_ranks": [1],
                "brand_in_answer_text": False,
                "sentiment": "упомянут нейтрально",
            }
        )
        rowid = insert_capture(conn, run_id, cap)
        conn.commit()
        row = conn.execute("SELECT * FROM results WHERE id = ?", (rowid,)).fetchone()
        assert row["sentiment"] == "упомянут нейтрально"
        assert "проект" in row["sources_json"]
        assert json.loads(row["sources_json"])[0]["url"] == "https://example.com/проект"
    finally:
        conn.close()


def test_insert_capture_duplicate_key_is_idempotent_noop(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(_valid_capture_dict())
        id1 = insert_capture(conn, run_id, cap)
        id2 = insert_capture(conn, run_id, cap)
        conn.commit()
        assert isinstance(id1, int) and id1 > 0
        assert id2 is None
        assert _results_count(db_path, run_id) == 1
    finally:
        conn.close()


def test_insert_capture_distinct_keys_each_insert_a_row(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        a = insert_capture(
            conn, run_id, QueryCapture.model_validate(_valid_capture_dict(query="a"))
        )
        b = insert_capture(
            conn, run_id, QueryCapture.model_validate(_valid_capture_dict(query="b"))
        )
        conn.commit()
        assert isinstance(a, int) and isinstance(b, int)
        assert b > a
        assert _results_count(db_path, run_id) == 2
    finally:
        conn.close()


def test_ingest_batch_all_valid(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        b0 = _valid_capture_dict(query="q0", lens="general")
        b1 = _valid_capture_dict(query="q1", lens="branded")
        b2 = _valid_capture_dict(query="q2", lens="comparative")
        result = ingest_batch(conn, run_id, [b0, b1, b2])
    finally:
        conn.close()

    assert result == {"run_id": run_id, "ok": [0, 1, 2], "skipped": [], "errors": []}

    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 3
    assert run["status"] == "running"
    assert _results_count(db_path, run_id) == 3


def test_ingest_batch_all_invalid(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        bad0 = _valid_capture_dict(query="q0", lens="nonsense")
        bad1 = _valid_capture_dict(query="q1")
        del bad1["overview_present"]
        result = ingest_batch(conn, run_id, [bad0, bad1])
    finally:
        conn.close()

    assert result["run_id"] == run_id
    assert result["ok"] == []
    assert len(result["errors"]) == 2

    e0, e1 = result["errors"]
    assert e0["index"] == 0
    assert e0["query"] == "q0"
    assert e0["field"] == "lens"
    assert e0["msg"]

    assert e1["index"] == 1
    assert e1["query"] == "q1"
    assert e1["field"] == "overview_present"
    assert e1["msg"]

    assert result["skipped"] == []
    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 0
    assert run["status"] == "running"
    assert _results_count(db_path, run_id) == 0


def test_ingest_batch_mixed_valid_and_invalid_keeps_indices(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        good0 = _valid_capture_dict(query="good0")
        bad1 = _valid_capture_dict(query="bad1", lens="oops")
        good2 = _valid_capture_dict(query="good2", lens="branded")
        result = ingest_batch(conn, run_id, [good0, bad1, good2])
    finally:
        conn.close()

    assert result["ok"] == [0, 2]
    assert len(result["errors"]) == 1
    assert result["errors"][0]["index"] == 1
    assert result["errors"][0]["query"] == "bad1"
    assert result["errors"][0]["field"] == "lens"

    assert result["skipped"] == []
    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 2
    assert run["status"] == "running"
    assert _results_count(db_path, run_id) == 2


def test_ingest_batch_empty_batch(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        result = ingest_batch(conn, run_id, [])
    finally:
        conn.close()

    assert result == {"run_id": run_id, "ok": [], "skipped": [], "errors": []}
    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 0
    assert run["status"] == "running"
    assert _results_count(db_path, run_id) == 0


def test_ingest_batch_non_dict_element_does_not_crash(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        good = _valid_capture_dict(query="good")
        result = ingest_batch(conn, run_id, [good, "x", 5])
    finally:
        conn.close()

    assert result["ok"] == [0]
    assert len(result["errors"]) == 2

    for err, idx in zip(result["errors"], (1, 2)):
        assert err["index"] == idx
        assert err["query"] is None
        assert err["field"] == ""
        assert err["msg"]

    assert result["skipped"] == []
    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 1
    assert run["status"] == "running"
    assert _results_count(db_path, run_id) == 1


def test_read_stdin_array_empty_raises_value_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(ValueError, match="empty input"):
        _read_stdin_array()


def test_read_stdin_array_whitespace_only_raises_value_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n\t  "))
    with pytest.raises(ValueError, match="empty input"):
        _read_stdin_array()


def test_read_stdin_array_json_object_raises_value_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"query": "x"}'))
    with pytest.raises(ValueError, match="got dict"):
        _read_stdin_array()


def test_read_stdin_array_json_number_raises_value_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("42"))
    with pytest.raises(ValueError, match="got int"):
        _read_stdin_array()


def test_read_stdin_array_malformed_json_raises_decode_error(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{not valid json"))
    with pytest.raises(json.JSONDecodeError):
        _read_stdin_array()


def test_read_stdin_array_valid_array_returns_list(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('[{"a": 1}, 2, "three"]'))
    out = _read_stdin_array()
    assert out == [{"a": 1}, 2, "three"]


def test_read_stdin_array_empty_array_returns_empty_list(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
    assert _read_stdin_array() == []


def test_main_both_modes_returns_2(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    rc = main(["--db", db_path, "--new-run", "--run-id", "1"])
    assert rc == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "exactly one mode" in out.err


def test_main_neither_mode_returns_2(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    rc = main(["--db", db_path])
    assert rc == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "exactly one mode" in out.err


@pytest.mark.parametrize(
    "missing",
    ["brand", "domain", "engine"],
)
def test_main_new_run_missing_required_arg_returns_2(tmp_path, capsys, missing):
    db_path = str(tmp_path / "aeo.db")
    args = {
        "brand": ["--brand", "Example"],
        "domain": ["--domain", "example.com"],
        "engine": ["--engine", "google"],
    }
    argv = ["--db", db_path, "--new-run"]
    for key, flag in args.items():
        if key != missing:
            argv += flag
    rc = main(argv)
    assert rc == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "--new-run requires" in out.err


def test_main_new_run_creates_brand_and_run(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    rc = main(
        [
            "--db", db_path,
            "--brand", "Example",
            "--domain", "https://www.example.com",
            "--engine", "google",
            "--new-run",
        ]
    )
    assert rc == 0

    out = capsys.readouterr()
    lines = [ln for ln in out.out.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert set(payload.keys()) == {"run_id"}
    run_id = payload["run_id"]
    assert isinstance(run_id, int)

    conn = get_conn(db_path)
    try:
        brand = conn.execute("SELECT name, domain FROM brands").fetchone()
        assert brand["name"] == "Example"
        assert brand["domain"] == "example.com"

        run = conn.execute(
            "SELECT engine, status FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert run["engine"] == "google"
        assert run["status"] == "running"
    finally:
        conn.close()


def test_main_run_id_nonexistent_returns_1(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    conn = get_conn(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()

    rc = main(["--db", db_path, "--run-id", "999"])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "run 999 not found" in out.err


def test_main_run_id_valid_batch_ingests_and_prints_payload(
    tmp_path, capsys, monkeypatch
):
    db_path, run_id = _fresh_db_with_run(tmp_path)

    batch = [
        _valid_capture_dict(query="q0", lens="general"),
        _valid_capture_dict(query="q1", lens="branded"),
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(batch)))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0

    out = capsys.readouterr()
    lines = [ln for ln in out.out.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["run_id"] == run_id
    assert payload["ok"] == [0, 1]
    assert payload["skipped"] == []
    assert payload["errors"] == []

    assert _results_count(db_path, run_id) == 2
    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 2
    assert run["status"] == "running"


def test_main_run_id_valid_batch_with_one_invalid_still_returns_0(
    tmp_path, capsys, monkeypatch
):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    batch = [
        _valid_capture_dict(query="good"),
        _valid_capture_dict(query="bad", lens="oops"),
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(batch)))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] == [0]
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["index"] == 1
    assert payload["errors"][0]["field"] == "lens"
    assert _results_count(db_path, run_id) == 1


def test_main_run_id_empty_stdin_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "empty input" in out.err
    run = _run_row(db_path, run_id)
    assert (run["n_queries"], run["n_ok"], run["n_failed"]) == (0, 0, 0)
    assert run["status"] == "running"


def test_main_run_id_malformed_stdin_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_main_run_id_non_array_stdin_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"query": "x"}'))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "got dict" in out.err


def test_main_run_id_empty_array_stdin_returns_0(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("[]"))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {"run_id": run_id, "ok": [], "skipped": [], "errors": []}
    run = _run_row(db_path, run_id)
    assert run["status"] == "running"
    assert run["n_ok"] == 0


def test_field_path_single_int_part_is_stringified():
    assert _field_path((0,)) == "0"


def test_field_path_deeply_nested_all_parts_joined():
    assert _field_path(("citations", 3, "url", "scheme")) == "citations.3.url.scheme"


def test_links_to_jsonable_single_link_exact_shape():
    out = _links_to_jsonable([Link(rank=7, url="https://x.io/p", domain="x.io")])
    assert out == [{"rank": 7, "url": "https://x.io/p", "domain": "x.io"}]
    assert isinstance(out[0]["rank"], int)


def test_links_to_jsonable_preserves_input_order_and_duplicate_domains():
    links = [
        Link(rank=1, url="https://example.com/a", domain="example.com"),
        Link(rank=2, url="https://b.org/x", domain="b.org"),
        Link(rank=3, url="https://example.com/c", domain="example.com"),
    ]
    out = _links_to_jsonable(links)
    assert [d["rank"] for d in out] == [1, 2, 3]
    assert [d["domain"] for d in out] == ["example.com", "b.org", "example.com"]


def test_insert_capture_duplicate_domain_sources_and_rank_arrays_preserved(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(
            {
                "query": "dupes",
                "lens": "comparative",
                "engine": "google",
                "captured_at": "2026-06-18T20:15:30Z",
                "overview_present": True,
                "sources": [
                    {"rank": 1, "url": "https://example.com/a", "domain": "example.com"},
                    {"rank": 2, "url": "https://example.com/b", "domain": "example.com"},
                    {"rank": 3, "url": "https://other.org/c", "domain": "other.org"},
                ],
                "citations": [
                    {"rank": 1, "url": "https://example.com/a", "domain": "example.com"},
                    {"rank": 2, "url": "https://example.com/b", "domain": "example.com"},
                ],
                "target_source_ranks": [1, 2],
                "target_citation_ranks": [1, 2],
                "brand_in_answer_text": True,
                "sentiment": "named twice",
            }
        )
        rowid = insert_capture(conn, run_id, cap)
        conn.commit()
        row = conn.execute("SELECT * FROM results WHERE id = ?", (rowid,)).fetchone()
        assert [s["domain"] for s in json.loads(row["sources_json"])] == [
            "example.com", "example.com", "other.org",
        ]
        assert json.loads(row["target_source_ranks_json"]) == [1, 2]
        assert json.loads(row["target_citation_ranks_json"]) == [1, 2]
        assert all(isinstance(r, int) for r in json.loads(row["target_source_ranks_json"]))
    finally:
        conn.close()


def test_insert_capture_null_answer_and_screenshot_stored_as_sql_null(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(
            {
                "query": "no overview",
                "lens": "general",
                "engine": "google",
                "captured_at": "2026-06-18T00:00:00Z",
                "overview_present": False,
                "brand_in_answer_text": False,
            }
        )
        rowid = insert_capture(conn, run_id, cap)
        conn.commit()
        row = conn.execute("SELECT * FROM results WHERE id = ?", (rowid,)).fetchone()
        assert row["answer_text_md"] is None
        assert row["screenshot_path"] is None
        assert row["sentiment"] is None
    finally:
        conn.close()


def test_insert_capture_does_not_autocommit(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    writer = get_conn(db_path)
    try:
        cap = QueryCapture.model_validate(_valid_capture_dict())
        insert_capture(writer, run_id, cap)
        assert _results_count(db_path, run_id) == 0
        writer.commit()
        assert _results_count(db_path, run_id) == 1
    finally:
        writer.close()


def test_ingest_batch_dict_missing_query_echoes_none_with_field_path(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        result = ingest_batch(conn, run_id, [{}])
    finally:
        conn.close()
    assert result["ok"] == []
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["index"] == 0
    assert err["query"] is None
    assert err["field"] == "query"
    assert err["msg"]


def test_ingest_batch_dict_with_query_but_invalid_echoes_that_query(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        bad = _valid_capture_dict(query="echo me", lens="not-a-lens")
        result = ingest_batch(conn, run_id, [bad])
    finally:
        conn.close()
    assert result["errors"][0]["query"] == "echo me"
    assert result["errors"][0]["field"] == "lens"


@pytest.mark.parametrize("element", [None, True, [1, 2], 3.14, ""])
def test_ingest_batch_assorted_non_dict_elements_become_errors(tmp_path, element):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        result = ingest_batch(conn, run_id, [element])
    finally:
        conn.close()
    assert result["ok"] == []
    assert len(result["errors"]) == 1
    assert result["errors"][0]["query"] is None
    assert result["errors"][0]["field"] == ""
    assert _results_count(db_path, run_id) == 0


def test_ingest_batch_incremental_calls_accumulate(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        r1 = ingest_batch(conn, run_id, [_valid_capture_dict(query="a")])
        assert r1["ok"] == [0] and r1["skipped"] == []
        run_after_1 = _run_row(db_path, run_id)
        assert run_after_1["n_ok"] == 1
        assert run_after_1["status"] == "running"

        r2 = ingest_batch(
            conn,
            run_id,
            [_valid_capture_dict(query="b"), _valid_capture_dict(query="c")],
        )
        assert r2["ok"] == [0, 1] and r2["skipped"] == []
    finally:
        conn.close()

    run_after_2 = _run_row(db_path, run_id)
    assert run_after_2["n_ok"] == 3
    assert run_after_2["status"] == "running"
    assert _results_count(db_path, run_id) == 3


def test_ingest_batch_resend_same_keys_skips_idempotently(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        first = ingest_batch(
            conn,
            run_id,
            [
                _valid_capture_dict(query="a", lens="general"),
                _valid_capture_dict(query="b", lens="branded"),
            ],
        )
        assert first["ok"] == [0, 1]
        assert first["skipped"] == []

        again = ingest_batch(
            conn,
            run_id,
            [
                _valid_capture_dict(query="a", lens="general"),
                _valid_capture_dict(query="b", lens="branded"),
                _valid_capture_dict(query="c", lens="comparative"),
            ],
        )
        assert again["ok"] == [2]
        assert again["skipped"] == [0, 1]
        assert again["errors"] == []
    finally:
        conn.close()

    assert _results_count(db_path, run_id) == 3


def test_ingest_batch_first_error_only_reported_per_row(tmp_path):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    conn = get_conn(db_path)
    try:
        multi_bad = _valid_capture_dict(query="multi", lens="bogus")
        del multi_bad["overview_present"]
        result = ingest_batch(conn, run_id, [multi_bad])
    finally:
        conn.close()
    assert len(result["errors"]) == 1
    assert result["errors"][0]["query"] == "multi"
    assert result["errors"][0]["field"]


@pytest.mark.parametrize(
    "text, type_name",
    [
        ("true", "bool"),
        ("null", "NoneType"),
        ('"hello"', "str"),
        ("3.14", "float"),
        ('{"k": 1}', "dict"),
    ],
)
def test_read_stdin_array_non_list_json_reports_python_type(monkeypatch, text, type_name):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    with pytest.raises(ValueError, match=f"got {type_name}"):
        _read_stdin_array()


def test_read_stdin_array_nested_array_returned_verbatim(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('[[1, 2], {"x": 3}, null]'))
    assert _read_stdin_array() == [[1, 2], {"x": 3}, None]


def test_read_stdin_array_surrounding_whitespace_is_tolerated(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n\t  [1, 2, 3]  \n"))
    assert _read_stdin_array() == [1, 2, 3]


def test_main_run_id_zero_is_a_valid_mode_not_neither(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    conn = get_conn(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()

    rc = main(["--db", db_path, "--run-id", "0"])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "run 0 not found" in out.err
    assert "exactly one mode" not in out.err


def test_main_new_run_and_run_id_zero_is_still_both_modes(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    rc = main(["--db", db_path, "--new-run", "--run-id", "0"])
    assert rc == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "exactly one mode" in out.err


def test_main_new_run_twice_reuses_brand_distinct_runs(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    base = [
        "--db", db_path,
        "--brand", "Example", "--domain", "example.com",
        "--engine", "google", "--new-run",
    ]
    assert main(base) == 0
    run_id_1 = json.loads(capsys.readouterr().out.strip())["run_id"]
    assert main(base) == 0
    run_id_2 = json.loads(capsys.readouterr().out.strip())["run_id"]

    assert run_id_2 != run_id_1

    conn = get_conn(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM brands").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        brand_ids = {
            r["brand_id"]
            for r in conn.execute("SELECT brand_id FROM runs").fetchall()
        }
        assert len(brand_ids) == 1
    finally:
        conn.close()


def test_main_new_run_creates_missing_parent_directories(tmp_path, capsys):
    nested = tmp_path / "deep" / "nested" / "dir" / "aeo.db"
    assert not nested.parent.exists()
    rc = main(
        [
            "--db", str(nested),
            "--brand", "Example", "--domain", "example.com",
            "--engine", "google", "--new-run",
        ]
    )
    assert rc == 0
    assert nested.exists()
    payload = json.loads(capsys.readouterr().out.strip())
    assert isinstance(payload["run_id"], int)


def test_main_new_run_only_brand_given_returns_2(tmp_path, capsys):
    db_path = str(tmp_path / "aeo.db")
    rc = main(["--db", db_path, "--new-run", "--brand", "Example"])
    assert rc == 2
    out = capsys.readouterr()
    assert out.out == ""
    assert "--new-run requires" in out.err


def test_main_run_id_default_db_path_not_used(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "explicit.db"
    conn = get_conn(str(db_path))
    try:
        init_db(conn)
    finally:
        conn.close()
    rc = main(["--db", str(db_path), "--run-id", "12345"])
    assert rc == 1
    assert db_path.exists()
    assert "run 12345 not found" in capsys.readouterr().err


def test_main_run_id_valid_with_all_invalid_batch_returns_0(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    batch = [
        _valid_capture_dict(query="b0", lens="nope"),
        {"not": "a capture"},
    ]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(batch)))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] == []
    assert payload["skipped"] == []
    assert len(payload["errors"]) == 2
    assert _results_count(db_path, run_id) == 0
    run = _run_row(db_path, run_id)
    assert run["n_ok"] == 0
    assert run["status"] == "running"


def test_main_run_id_whitespace_only_stdin_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n\t "))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "empty input" in out.err
    run = _run_row(db_path, run_id)
    assert run["status"] == "running"


def test_main_run_id_json_array_stdin_number_element_ingests_with_error(
    tmp_path, capsys, monkeypatch
):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    batch_json = json.dumps([_valid_capture_dict(query="ok0"), 5])
    monkeypatch.setattr("sys.stdin", io.StringIO(batch_json))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] == [0]
    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["index"] == 1
    assert payload["errors"][0]["query"] is None
    assert payload["errors"][0]["field"] == ""
    assert _results_count(db_path, run_id) == 1


@pytest.mark.slow
def test_main_subprocess_new_run_then_ingest_end_to_end(tmp_path):
    db_path = tmp_path / "aeo.db"

    created = subprocess.run(
        [
            sys.executable, "-m", "pipeline.ingest",
            "--db", str(db_path),
            "--brand", "Example", "--domain", "example.com",
            "--engine", "google", "--new-run",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert created.returncode == 0, created.stderr
    run_id = json.loads(created.stdout)["run_id"]

    ingested = subprocess.run(
        [
            sys.executable, "-m", "pipeline.ingest",
            "--db", str(db_path), "--run-id", str(run_id),
        ],
        cwd=str(REPO_ROOT),
        input=json.dumps([_valid_capture_dict(query="e2e")]),
        capture_output=True,
        text=True,
    )
    assert ingested.returncode == 0, ingested.stderr
    payload = json.loads(ingested.stdout)
    assert payload["run_id"] == run_id
    assert payload["ok"] == [0]
    assert payload["skipped"] == []
    assert payload["errors"] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
