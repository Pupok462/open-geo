from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from pipeline.db import create_run, get_conn, get_lens_sentiments, get_or_create_brand, init_db
from pipeline.lens_sentiment import _read_stdin_object, main


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


def _summaries(db_path: str, run_id: int) -> dict[str, str]:
    conn = get_conn(db_path)
    try:
        return get_lens_sentiments(conn, run_id)
    finally:
        conn.close()


def test_main_writes_summaries_and_prints_payload(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    payload_in = {
        "all": "visible across lenses",
        "general": "neutral mention",
        "branded": "owns its brand queries",
        "comparative": "named without an edge",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload_in)))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0

    out = capsys.readouterr()
    lines = [ln for ln in out.out.splitlines() if ln.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert set(payload.keys()) == {"run_id", "written"}
    assert payload["run_id"] == run_id
    assert payload["written"] == ["all", "general", "branded", "comparative"]

    assert _summaries(db_path, run_id) == payload_in


def test_main_written_preserves_input_order(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    payload_in = {"branded": "b", "all": "a", "general": "g"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload_in)))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["written"] == ["branded", "all", "general"]


def test_main_unknown_lens_keys_are_skipped(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    payload_in = {"general": "kept", "bogus": "dropped", "all": "kept too"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload_in)))

    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["written"] == ["general", "all"]
    assert _summaries(db_path, run_id) == {"general": "kept", "all": "kept too"}


def test_main_null_value_clears_summary(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"general": "first"})))
    assert main(["--db", db_path, "--run-id", str(run_id)]) == 0
    capsys.readouterr()
    assert _summaries(db_path, run_id) == {"general": "first"}

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"general": None})))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["written"] == ["general"]
    assert _summaries(db_path, run_id) == {}


def test_main_unknown_run_id_returns_1(tmp_path, capsys):
    db_path, _ = _fresh_db_with_run(tmp_path)
    rc = main(["--db", db_path, "--run-id", "987654"])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "run 987654 not found" in out.err


def test_main_empty_stdin_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "empty input" in out.err


def test_main_malformed_stdin_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_main_stdin_array_rejected_returns_1(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO('["general"]'))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 1
    assert capsys.readouterr().out == ""


def test_main_empty_object_writes_nothing(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {"run_id": run_id, "written": []}
    assert _summaries(db_path, run_id) == {}


def test_main_stdout_is_single_json_object(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"all": "x"})))
    main(["--db", db_path, "--run-id", str(run_id)])
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert set(obj) == {"run_id", "written"}


def test_main_upsert_overwrites_existing(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"general": "old"})))
    main(["--db", db_path, "--run-id", str(run_id)])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"general": "new"})))
    main(["--db", db_path, "--run-id", str(run_id)])
    capsys.readouterr()
    assert _summaries(db_path, run_id) == {"general": "new"}


def test_read_stdin_object_rejects_non_object(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("42"))
    with pytest.raises(ValueError):
        _read_stdin_object()


def test_read_stdin_object_valid_returns_dict(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"all": "x", "general": null}'))
    out = _read_stdin_object()
    assert out == {"all": "x", "general": None}


def test_main_unicode_summary_roundtrips(tmp_path, capsys, monkeypatch):
    db_path, run_id = _fresh_db_with_run(tmp_path)
    phrase = "упомянут нейтрально — без чёткого преимущества ☕"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"general": phrase})))
    rc = main(["--db", db_path, "--run-id", str(run_id)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload == {"run_id": run_id, "written": ["general"]}
    assert _summaries(db_path, run_id) == {"general": phrase}


@pytest.mark.slow
def test_main_subprocess_end_to_end(tmp_path):
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    db_path, run_id = _fresh_db_with_run(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.lens_sentiment", "--db", db_path, "--run-id", str(run_id)],
        cwd=str(repo_root),
        input=json.dumps({"all": "ok", "general": "g"}),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["run_id"] == run_id
    assert payload["written"] == ["all", "general"]
    assert _summaries(db_path, run_id) == {"all": "ok", "general": "g"}
