from __future__ import annotations


from audit.schema import AuditResult, CheckResult, summarize


def _check(id="A1", category="A", title="t", severity="blocker", status="pass", detail="d", remediation=None):
    return CheckResult(
        id=id,
        category=category,
        title=title,
        severity=severity,
        status=status,
        detail=detail,
        remediation=remediation,
    )


def _audit(checks, engine="google"):
    return AuditResult(
        target="example.com",
        domain="example.com",
        engine=engine,
        checked_at="2026-07-08T00:00:00Z",
        checks=checks,
    )


def test_check_result_defaults_remediation_none():
    c = _check()
    assert c.remediation is None
    assert c.status == "pass"


def test_verdict_ready_all_pass():
    a = _audit([_check(status="pass"), _check(id="B1", severity="recommended", status="pass")])
    assert a.verdict == "ready"
    assert a.passed is True
    assert a.blockers == []
    assert a.score == 100


def test_verdict_ready_with_warnings_on_advisory_warn():
    a = _audit([
        _check(status="pass"),
        _check(id="B1", severity="recommended", status="warn"),
    ])
    assert a.verdict == "ready_with_warnings"
    assert a.passed is True
    assert a.blockers == []


def test_verdict_ready_with_warnings_on_advisory_fail_not_blocking():
    a = _audit([
        _check(status="pass"),
        _check(id="B4", severity="nice_to_have", status="fail"),
    ])
    assert a.verdict == "ready_with_warnings"
    assert a.passed is True
    assert a.blockers == []


def test_verdict_blocked_on_blocker_fail():
    a = _audit([
        _check(id="A3", severity="blocker", status="fail"),
        _check(id="B1", severity="recommended", status="pass"),
    ])
    assert a.verdict == "blocked"
    assert a.passed is False
    assert a.blockers == ["A3"]


def test_blockers_lists_only_failing_blockers():
    a = _audit([
        _check(id="A1", severity="blocker", status="pass"),
        _check(id="A2", severity="blocker", status="fail"),
        _check(id="A5", severity="blocker", status="fail"),
        _check(id="B3", severity="recommended", status="fail"),
    ])
    assert a.blockers == ["A2", "A5"]


def test_score_weighted_mix():
    a = _audit([
        _check(id="A1", severity="blocker", status="pass"),
        _check(id="A3", severity="blocker", status="fail"),
        _check(id="B1", severity="recommended", status="warn"),
        _check(id="B4", severity="nice_to_have", status="fail"),
    ])
    assert a.score == 44


def test_score_skip_excluded_and_empty_is_100():
    empty = _audit([])
    assert empty.score == 100
    assert empty.verdict == "ready"

    all_skip = _audit([_check(status="skip"), _check(id="B1", severity="recommended", status="skip")])
    assert all_skip.score == 100
    assert all_skip.verdict == "ready"


def test_score_skip_does_not_change_ratio():
    without = _audit([_check(status="pass"), _check(id="A3", severity="blocker", status="fail")])
    with_skip = _audit([
        _check(status="pass"),
        _check(id="A3", severity="blocker", status="fail"),
        _check(id="B4", severity="nice_to_have", status="skip"),
    ])
    assert without.score == with_skip.score == 50


def test_summarize_shape_and_counts():
    a = _audit([
        _check(id="A1", severity="blocker", status="pass"),
        _check(id="A3", severity="blocker", status="fail"),
        _check(id="B1", severity="recommended", status="warn"),
        _check(id="D3", severity="nice_to_have", status="skip"),
    ])
    s = summarize(a)
    assert s["verdict"] == "blocked"
    assert s["passed"] is False
    assert s["blockers"] == ["A3"]
    assert s["counts"] == {"pass": 1, "warn": 1, "fail": 1, "skip": 1}
    assert s["domain"] == "example.com"
    assert s["engine"] == "google"


def test_roundtrip_ignores_computed_fields():
    a = _audit([
        _check(id="A3", severity="blocker", status="fail", remediation="Allow Googlebot"),
        _check(id="B1", severity="recommended", status="warn"),
    ])
    dumped = a.model_dump_json()
    assert '"verdict":"blocked"' in dumped
    assert '"score":' in dumped
    back = AuditResult.model_validate_json(dumped)
    assert back.verdict == "blocked"
    assert back.blockers == ["A3"]
    assert back.score == a.score
    assert len(back.checks) == 2
    assert back.checks[0].remediation == "Allow Googlebot"


def test_engine_optional_defaults_none():
    a = AuditResult(target="x.com", domain="x.com", checked_at="2026-07-08T00:00:00Z", checks=[])
    assert a.engine is None
    assert summarize(a)["engine"] is None
