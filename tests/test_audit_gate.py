from __future__ import annotations

import json
from datetime import datetime, timezone


from audit.gate import main as gate_main
from audit.schema import AuditResult, CheckResult
from pipeline.db import get_conn


def _result(blocked=False, engine="google"):
    checks = [
        CheckResult(
            id="A3", category="A", title="robots", severity="blocker",
            status="fail" if blocked else "pass", detail="robots detail",
            remediation="allow the bot" if blocked else None,
        ),
        CheckResult(
            id="B1", category="B", title="schema", severity="recommended",
            status="warn", detail="schema warn",
        ),
    ]
    return AuditResult(
        target="example.com",
        domain="example.com",
        engine=engine,
        checked_at=datetime.now(timezone.utc),
        checks=checks,
    )


def _patch(monkeypatch, fn):
    monkeypatch.setattr("audit.gate.run_audit", fn)


def test_gate_fresh_writes_db_and_prints(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "a.db")
    _patch(monkeypatch, lambda target, *, engine=None, timeout=10.0: _result(engine=engine))
    rc = gate_main(["--domain", "https://example.com", "--engine", "google", "--db", db])
    assert rc == 0
    cap = capsys.readouterr()
    payload = json.loads(cap.out)
    assert payload["domain"] == "example.com"
    assert payload["verdict"] == "ready_with_warnings"
    assert "example.com" in cap.err and "google" in cap.err

    conn = get_conn(db)
    rows = conn.execute("SELECT domain, engine, verdict, score, blocked FROM audits").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["domain"] == "example.com"
    assert rows[0]["blocked"] == 0


def test_gate_cache_hit_skips_reaudit(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "a.db")
    calls = {"n": 0}

    def fake(target, *, engine=None, timeout=10.0):
        calls["n"] += 1
        return _result(engine=engine)

    _patch(monkeypatch, fake)
    gate_main(["--domain", "example.com", "--db", db])
    capsys.readouterr()
    rc = gate_main(["--domain", "example.com", "--db", db])
    out = capsys.readouterr()
    assert rc == 0
    assert calls["n"] == 1
    assert json.loads(out.out)["domain"] == "example.com"


def test_gate_no_cache_forces_reaudit(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "a.db")
    calls = {"n": 0}

    def fake(target, *, engine=None, timeout=10.0):
        calls["n"] += 1
        return _result(engine=engine)

    _patch(monkeypatch, fake)
    gate_main(["--domain", "example.com", "--db", db])
    gate_main(["--domain", "example.com", "--db", db, "--no-cache"])
    capsys.readouterr()
    assert calls["n"] == 2


def test_gate_stale_cache_reaudits(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "a.db")
    calls = {"n": 0}

    def fake(target, *, engine=None, timeout=10.0):
        calls["n"] += 1
        return _result(engine=engine)

    _patch(monkeypatch, fake)
    gate_main(["--domain", "example.com", "--db", db])
    gate_main(["--domain", "example.com", "--db", db, "--max-age", "0"])
    capsys.readouterr()
    assert calls["n"] == 2


def test_gate_no_db_does_not_persist(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch, lambda target, *, engine=None, timeout=10.0: _result(engine=None))
    rc = gate_main(["--domain", "example.com", "--no-db"])
    out = capsys.readouterr()
    assert rc == 0
    assert json.loads(out.out)["domain"] == "example.com"
    assert "generic" in out.err


def test_gate_blocked_prints_blockers(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch, lambda target, *, engine=None, timeout=10.0: _result(blocked=True, engine="google"))
    rc = gate_main(["--domain", "example.com", "--no-db"])
    out = capsys.readouterr()
    assert rc == 0
    payload = json.loads(out.out)
    assert payload["verdict"] == "blocked"
    assert "blockers:" in out.err
    assert "A3" in out.err


def test_gate_operational_error_returns_1(monkeypatch, capsys):
    def boom(target, *, engine=None, timeout=10.0):
        raise RuntimeError("kaboom")

    _patch(monkeypatch, boom)
    rc = gate_main(["--domain", "example.com", "--no-db"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "kaboom" in err
