from __future__ import annotations

import json

import pytest

from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    init_db,
    question_set_digest,
    update_run_counts,
)
from pipeline.ingest import ingest_batch
from pipeline.run import main, read_question_keys

CSV_BODY = (
    "query,lens\n"
    "how to choose a tracker,general\n"
    "Example reviews,branded\n"
    "Example vs Globex,comparative\n"
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


@pytest.fixture
def csv_path(tmp_path) -> str:
    p = tmp_path / "questions.csv"
    p.write_text(CSV_BODY, encoding="utf-8")
    return str(p)


@pytest.fixture
def db_with_brand(tmp_path) -> str:
    db_path = str(tmp_path / "aeo.db")
    conn = get_conn(db_path)
    try:
        init_db(conn)
        get_or_create_brand(conn, "Example", "example.com")
    finally:
        conn.close()
    return db_path


def _stdout_json(capsys):
    return json.loads(capsys.readouterr().out.strip())


def _open_run(db_path: str, captures: list[dict] | None = None) -> int:
    conn = get_conn(db_path)
    try:
        brand_id = get_or_create_brand(conn, "Example", "example.com")
        run_id = create_run(conn, brand_id, "google")
        if captures:
            ingest_batch(conn, run_id, captures)
    finally:
        conn.close()
    return run_id


# --------------------------------------------------------------------------
# read_question_keys
# --------------------------------------------------------------------------


def test_read_question_keys_preserves_order(csv_path):
    assert read_question_keys(csv_path) == [
        ("how to choose a tracker", "general"),
        ("Example reviews", "branded"),
        ("Example vs Globex", "comparative"),
    ]


def test_read_question_keys_rejects_unknown_lens(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("query,lens\nsomething,informational\n", encoding="utf-8")
    with pytest.raises(ValueError, match="informational"):
        read_question_keys(str(p))


def test_read_question_keys_rejects_missing_header(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("question,view\na,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        read_question_keys(str(p))


def test_read_question_keys_rejects_empty_body(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("query,lens\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no data rows"):
        read_question_keys(str(p))


# --------------------------------------------------------------------------
# --resume-check
# --------------------------------------------------------------------------


def test_resume_check_reports_nothing_to_resume(db_with_brand, csv_path, capsys):
    rc = main(
        [
            "--resume-check",
            "--brand",
            "Example",
            "--domain",
            "example.com",
            "--engine",
            "google",
            "--csv",
            csv_path,
            "--db",
            db_with_brand,
        ]
    )
    assert rc == 0
    payload = _stdout_json(capsys)
    assert payload == {
        "run_id": None,
        "resumable": False,
        "run_at": None,
        "n_captured": 0,
        "n_missing": 0,
    }


def test_resume_check_marks_subset_run_resumable(db_with_brand, csv_path, capsys):
    run_id = _open_run(db_with_brand, [_capture("how to choose a tracker", "general")])

    rc = main(
        [
            "--resume-check",
            "--brand",
            "Example",
            "--domain",
            "example.com",
            "--engine",
            "google",
            "--csv",
            csv_path,
            "--db",
            db_with_brand,
        ]
    )
    assert rc == 0
    payload = _stdout_json(capsys)
    assert payload["run_id"] == run_id
    assert payload["resumable"] is True
    assert payload["n_captured"] == 1
    assert payload["n_missing"] == 2
    assert payload["run_at"] is not None


def test_resume_check_refuses_foreign_question_set(db_with_brand, csv_path, capsys):
    """A running run captured from a DIFFERENT CSV must not be resumable."""
    _open_run(db_with_brand, [_capture("a question from another set", "general")])

    main(
        [
            "--resume-check",
            "--brand",
            "Example",
            "--domain",
            "example.com",
            "--engine",
            "google",
            "--csv",
            csv_path,
            "--db",
            db_with_brand,
        ]
    )
    payload = _stdout_json(capsys)
    assert payload["resumable"] is False
    assert payload["n_captured"] == 1


def test_resume_check_ignores_finished_runs(db_with_brand, csv_path, capsys):
    run_id = _open_run(db_with_brand, [_capture("how to choose a tracker", "general")])
    conn = get_conn(db_with_brand)
    try:
        update_run_counts(conn, run_id=run_id, status="done")
    finally:
        conn.close()

    main(
        [
            "--resume-check",
            "--brand",
            "Example",
            "--domain",
            "example.com",
            "--engine",
            "google",
            "--csv",
            csv_path,
            "--db",
            db_with_brand,
        ]
    )
    assert _stdout_json(capsys)["run_id"] is None


def test_resume_check_requires_all_inputs(db_with_brand, capsys):
    rc = main(["--resume-check", "--brand", "Example", "--db", db_with_brand])
    assert rc == 2
    assert "requires" in capsys.readouterr().err


def test_resume_check_reports_unreadable_csv(db_with_brand, tmp_path, capsys):
    rc = main(
        [
            "--resume-check",
            "--brand",
            "Example",
            "--domain",
            "example.com",
            "--engine",
            "google",
            "--csv",
            str(tmp_path / "nope.csv"),
            "--db",
            db_with_brand,
        ]
    )
    # No unfinished run exists, so a missing CSV is never read — the check is a
    # clean "nothing to resume", not a crash.
    assert rc == 0
    assert _stdout_json(capsys)["run_id"] is None


def test_resume_check_fails_loudly_on_bad_csv_when_run_exists(
    db_with_brand, tmp_path, capsys
):
    _open_run(db_with_brand, [_capture("how to choose a tracker", "general")])
    bad = tmp_path / "bad.csv"
    bad.write_text("query,lens\nsomething,informational\n", encoding="utf-8")

    rc = main(
        [
            "--resume-check",
            "--brand",
            "Example",
            "--domain",
            "example.com",
            "--engine",
            "google",
            "--csv",
            str(bad),
            "--db",
            db_with_brand,
        ]
    )
    assert rc == 1
    assert "informational" in capsys.readouterr().err


# --------------------------------------------------------------------------
# --pending
# --------------------------------------------------------------------------


def test_pending_lists_uncaptured_rows_in_file_order(
    db_with_brand, csv_path, capsys
):
    run_id = _open_run(db_with_brand, [_capture("Example reviews", "branded")])

    rc = main(
        ["--pending", "--run-id", str(run_id), "--csv", csv_path, "--db", db_with_brand]
    )
    assert rc == 0
    payload = _stdout_json(capsys)
    assert payload["n_total"] == 3
    assert payload["n_captured"] == 1
    assert payload["pending"] == [
        ["how to choose a tracker", "general"],
        ["Example vs Globex", "comparative"],
    ]


def test_pending_empty_when_everything_captured(db_with_brand, csv_path, capsys):
    run_id = _open_run(
        db_with_brand,
        [
            _capture("how to choose a tracker", "general"),
            _capture("Example reviews", "branded"),
            _capture("Example vs Globex", "comparative"),
        ],
    )

    main(
        ["--pending", "--run-id", str(run_id), "--csv", csv_path, "--db", db_with_brand]
    )
    payload = _stdout_json(capsys)
    assert payload["n_pending"] == 0
    assert payload["pending"] == []


def test_pending_dedups_repeated_csv_rows(db_with_brand, tmp_path, capsys):
    p = tmp_path / "dupes.csv"
    p.write_text(
        "query,lens\nsame question,general\nsame question,general\n", encoding="utf-8"
    )
    run_id = _open_run(db_with_brand)

    main(["--pending", "--run-id", str(run_id), "--csv", str(p), "--db", db_with_brand])
    payload = _stdout_json(capsys)
    assert payload["n_total"] == 1
    assert payload["pending"] == [["same question", "general"]]


def test_pending_rejects_unknown_run(db_with_brand, csv_path, capsys):
    rc = main(
        ["--pending", "--run-id", "999", "--csv", csv_path, "--db", db_with_brand]
    )
    assert rc == 1
    assert "not found" in capsys.readouterr().err


# --------------------------------------------------------------------------
# --finalize
# --------------------------------------------------------------------------


def test_finalize_writes_counts_and_status(db_with_brand, capsys):
    run_id = _open_run(db_with_brand)

    rc = main(
        [
            "--finalize",
            "--run-id",
            str(run_id),
            "--n-queries",
            "6",
            "--n-ok",
            "4",
            "--status",
            "done",
            "--db",
            db_with_brand,
        ]
    )
    assert rc == 0
    payload = _stdout_json(capsys)
    assert payload == {
        "run_id": run_id,
        "n_queries": 6,
        "n_ok": 4,
        "n_failed": 2,
        "status": "done",
    }

    conn = get_conn(db_with_brand)
    try:
        row = conn.execute(
            "SELECT n_queries, n_ok, n_failed, status FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert dict(row) == {
        "n_queries": 6,
        "n_ok": 4,
        "n_failed": 2,
        "status": "done",
    }


def test_finalize_stamps_question_set_hash(db_with_brand, capsys):
    captures = [
        _capture("how to choose a tracker", "general"),
        _capture("Example reviews", "branded"),
    ]
    run_id = _open_run(db_with_brand, captures)
    rc = main(
        [
            "--finalize",
            "--run-id",
            str(run_id),
            "--n-queries",
            "2",
            "--n-ok",
            "2",
            "--status",
            "done",
            "--db",
            db_with_brand,
        ]
    )
    assert rc == 0
    conn = get_conn(db_with_brand)
    try:
        row = conn.execute(
            "SELECT question_set_hash FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    expected = question_set_digest(
        [("how to choose a tracker", "general"), ("Example reviews", "branded")]
    )
    assert row["question_set_hash"] == expected


def test_question_set_digest_ignores_order():
    a = question_set_digest([("q1", "general"), ("q2", "branded")])
    b = question_set_digest([("q2", "branded"), ("q1", "general")])
    assert a == b
    assert len(a) == 16


def test_finalize_honours_explicit_n_failed(db_with_brand, capsys):
    run_id = _open_run(db_with_brand)
    main(
        [
            "--finalize",
            "--run-id",
            str(run_id),
            "--n-queries",
            "6",
            "--n-ok",
            "4",
            "--n-failed",
            "0",
            "--status",
            "failed",
            "--db",
            db_with_brand,
        ]
    )
    assert _stdout_json(capsys)["n_failed"] == 0


def test_finalize_rejects_non_terminal_status(db_with_brand):
    run_id = _open_run(db_with_brand)
    with pytest.raises(SystemExit):
        main(
            [
                "--finalize",
                "--run-id",
                str(run_id),
                "--n-queries",
                "1",
                "--n-ok",
                "1",
                "--status",
                "running",
                "--db",
                db_with_brand,
            ]
        )


def test_finalize_rejects_unknown_run(db_with_brand, capsys):
    rc = main(
        [
            "--finalize",
            "--run-id",
            "999",
            "--n-queries",
            "1",
            "--n-ok",
            "1",
            "--status",
            "done",
            "--db",
            db_with_brand,
        ]
    )
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_finalize_requires_counts(db_with_brand, capsys):
    run_id = _open_run(db_with_brand)
    rc = main(
        ["--finalize", "--run-id", str(run_id), "--status", "done", "--db", db_with_brand]
    )
    assert rc == 2
    assert "requires" in capsys.readouterr().err


# --------------------------------------------------------------------------
# --sentiments
# --------------------------------------------------------------------------


def test_sentiments_returns_rows_grouped_by_lens(db_with_brand, capsys):
    cap_a = _capture("how to choose a tracker", "general")
    cap_b = _capture("Example reviews", "branded")
    cap_b.update(overview_present=True, sentiment="named as a solid option")
    run_id = _open_run(db_with_brand, [cap_a, cap_b])

    rc = main(["--sentiments", "--run-id", str(run_id), "--db", db_with_brand])
    assert rc == 0
    rows = _stdout_json(capsys)
    assert [r["lens"] for r in rows] == ["branded", "general"]
    assert rows[0]["sentiment"] == "named as a solid option"
    assert rows[1]["sentiment"] is None
    assert rows[0]["query"] == "Example reviews"


def test_sentiments_rejects_unknown_run(db_with_brand, capsys):
    rc = main(["--sentiments", "--run-id", "999", "--db", db_with_brand])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_mode_is_required(db_with_brand):
    with pytest.raises(SystemExit):
        main(["--db", db_with_brand])


def test_read_question_keys_rejects_empty_query_cell(tmp_path):
    p = tmp_path / "blank.csv"
    p.write_text("query,lens\n   ,general\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty query"):
        read_question_keys(str(p))


def test_pending_requires_run_id_and_csv(db_with_brand, csv_path, capsys):
    rc = main(["--pending", "--csv", csv_path, "--db", db_with_brand])
    assert rc == 2
    assert "requires" in capsys.readouterr().err


def test_pending_reports_bad_csv(db_with_brand, tmp_path, capsys):
    run_id = _open_run(db_with_brand)
    bad = tmp_path / "bad.csv"
    bad.write_text("query,lens\nsomething,informational\n", encoding="utf-8")

    rc = main(
        ["--pending", "--run-id", str(run_id), "--csv", str(bad), "--db", db_with_brand]
    )
    assert rc == 1
    assert "informational" in capsys.readouterr().err


def test_sentiments_requires_run_id(db_with_brand, capsys):
    rc = main(["--sentiments", "--db", db_with_brand])
    assert rc == 2
    assert "requires" in capsys.readouterr().err
