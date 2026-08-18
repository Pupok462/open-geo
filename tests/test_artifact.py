from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import pipeline.artifact as artifact_module
from pipeline.aggregate import aggregate_run
from pipeline.artifact import SCHEMA_VERSION, build_run_artifact, write_run_artifact
from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    insert_audit,
    update_run_counts,
    upsert_lens_sentiment,
)
from pipeline.ingest import insert_capture
from pipeline.schema import QueryCapture

REPO_ROOT = Path(__file__).resolve().parent.parent


def _seed_run(db_path: str) -> int:
    conn = get_conn(db_path)
    try:
        brand_id = get_or_create_brand(
            conn, "Example", "https://example.com/products"
        )
        run_id = create_run(conn, brand_id, "google", group_id="repeat-1")
        capture = QueryCapture.model_validate(
            {
                "query": "best example products",
                "lens": "general",
                "engine": "google",
                "captured_at": "2026-08-18T10:00:00Z",
                "overview_present": True,
                "sources": [
                    {
                        "rank": 1,
                        "url": "https://example.com/products/a",
                        "domain": "example.com",
                    }
                ],
                "citations": [
                    {
                        "rank": 1,
                        "url": "https://example.com/products/a",
                        "domain": "example.com",
                    }
                ],
                "target_source_ranks": [1],
                "target_citation_ranks": [1],
                "answer_text_md": "Example is cited.",
                "brand_in_answer_text": True,
                "sentiment": "positive mention",
            }
        )
        insert_capture(conn, run_id, capture)
        conn.commit()
        update_run_counts(
            conn, run_id, n_queries=1, n_ok=1, n_failed=0, status="done"
        )
        aggregate_run(conn, run_id)
        upsert_lens_sentiment(conn, run_id, "general", "Positive mention.")
        upsert_lens_sentiment(conn, run_id, "all", "Positive mention.")
        audit_payload = {
            "target": "https://example.com/products",
            "verdict": "ready",
            "score": 92,
            "blocked": False,
            "checks": [],
        }
        insert_audit(
            conn,
            target="https://example.com/products",
            domain="example.com",
            engine="google",
            checked_at="2026-08-18T09:00:00Z",
            verdict="ready",
            score=92,
            blocked=False,
            result_json=json.dumps(audit_payload),
        )
        return run_id
    finally:
        conn.close()


def test_build_run_artifact_is_complete_and_decoded(empty_db_path):
    run_id = _seed_run(empty_db_path)
    conn = get_conn(empty_db_path)
    try:
        artifact = build_run_artifact(conn, run_id)
    finally:
        conn.close()

    assert artifact["schema_version"] == SCHEMA_VERSION
    assert artifact["run"] == {
        "id": run_id,
        "run_at": artifact["run"]["run_at"],
        "status": "done",
        "engine": "google",
        "group_id": "repeat-1",
        "n_queries": 1,
        "n_ok": 1,
        "n_failed": 0,
    }
    assert artifact["brand"]["target"] == "example.com/products"
    assert artifact["metrics"]["all"]["visibility_in_citations"] == 1.0
    assert artifact["lens_sentiment"]["general"] == "Positive mention."
    assert artifact["results"][0]["sources"][0]["url"].endswith("/products/a")
    assert artifact["results"][0]["overview_present"] is True
    assert artifact["domain_stats"]["all"][0]["is_brand"] is True
    assert artifact["audit"]["blocked"] is False
    assert artifact["audit"]["result"]["score"] == 92


def test_write_run_artifact_is_atomic_and_utf8(empty_db_path, tmp_path):
    run_id = _seed_run(empty_db_path)
    destination = tmp_path / "nested" / "run.json"
    conn = get_conn(empty_db_path)
    try:
        written = write_run_artifact(conn, run_id, destination)
    finally:
        conn.close()

    assert written == destination.resolve()
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["run"]["id"] == run_id
    assert not list(destination.parent.glob("*.tmp"))


def test_build_run_artifact_tolerates_invalid_json_and_missing_audit(empty_db_path):
    run_id = _seed_run(empty_db_path)
    conn = get_conn(empty_db_path)
    try:
        conn.execute("UPDATE results SET sources_json = '{' WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM audits")
        conn.commit()
        payload = build_run_artifact(conn, run_id)
    finally:
        conn.close()

    assert payload["results"][0]["sources"] == []
    assert payload["audit"] is None


def test_build_run_artifact_rejects_unknown_run(empty_db_path):
    conn = get_conn(empty_db_path)
    try:
        with pytest.raises(ValueError, match="run 999 not found"):
            build_run_artifact(conn, 999)
    finally:
        conn.close()


def test_write_run_artifact_removes_temp_file_on_replace_error(
    empty_db_path, tmp_path, monkeypatch
):
    run_id = _seed_run(empty_db_path)
    destination = tmp_path / "run.json"

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(artifact_module.os, "replace", fail_replace)
    conn = get_conn(empty_db_path)
    try:
        with pytest.raises(OSError, match="replace failed"):
            write_run_artifact(conn, run_id, destination)
    finally:
        conn.close()

    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_artifact_cli_prints_machine_readable_path(empty_db_path, tmp_path):
    run_id = _seed_run(empty_db_path)
    destination = tmp_path / "workflow" / "open-geo.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.artifact",
            "--db",
            empty_db_path,
            "--run-id",
            str(run_id),
            "--out",
            str(destination),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    stdout = json.loads(proc.stdout)
    assert stdout == {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "artifact_path": str(destination.resolve()),
    }
    assert destination.exists()


def test_artifact_cli_rejects_unknown_run(empty_db_path, tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.artifact",
            "--db",
            empty_db_path,
            "--run-id",
            "999",
            "--out",
            str(tmp_path / "missing.json"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    assert "run 999 not found" in proc.stderr


def test_main_uses_default_output_and_prints_json(
    empty_db_path, tmp_path, monkeypatch, capsys
):
    run_id = _seed_run(empty_db_path)
    monkeypatch.chdir(tmp_path)

    assert artifact_module.main(["--db", empty_db_path, "--run-id", str(run_id)]) == 0

    stdout = json.loads(capsys.readouterr().out)
    expected = (tmp_path / "reports" / f"run-{run_id}.json").resolve()
    assert stdout["artifact_path"] == str(expected)
    assert expected.exists()


def test_main_reports_unknown_run(empty_db_path, capsys):
    assert artifact_module.main(["--db", empty_db_path, "--run-id", "999"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "run 999 not found" in captured.err
