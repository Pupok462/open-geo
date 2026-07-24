from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, computed_field

Severity = Literal["blocker", "recommended", "nice_to_have"]
CheckStatus = Literal["pass", "warn", "fail", "skip"]
Category = Literal["A", "B", "C", "D"]
Verdict = Literal["ready", "ready_with_warnings", "blocked"]

_SEVERITY_WEIGHT: dict[str, int] = {"blocker": 3, "recommended": 2, "nice_to_have": 1}
_STATUS_CREDIT: dict[str, Optional[float]] = {
    "pass": 1.0,
    "warn": 0.5,
    "fail": 0.0,
    "skip": None,
}


class CheckResult(BaseModel):
    id: str
    category: Category
    title: str
    severity: Severity
    status: CheckStatus
    detail: str
    remediation: Optional[str] = None


class AuditResult(BaseModel):
    target: str
    domain: str
    engine: Optional[str] = None
    checked_at: datetime
    checks: list[CheckResult] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blockers(self) -> list[str]:
        return [
            c.id
            for c in self.checks
            if c.severity == "blocker" and c.status == "fail"
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> Verdict:
        if self.blockers:
            return "blocked"
        if any(c.status in ("fail", "warn") for c in self.checks):
            return "ready_with_warnings"
        return "ready"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return self.verdict != "blocked"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> int:
        weighted_total = 0.0
        weighted_earned = 0.0
        for c in self.checks:
            credit = _STATUS_CREDIT[c.status]
            if credit is None:
                continue
            weight = _SEVERITY_WEIGHT[c.severity]
            weighted_total += weight
            weighted_earned += weight * credit
        if weighted_total == 0:
            return 100
        return round(100 * weighted_earned / weighted_total)


def summarize(result: AuditResult) -> dict:
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in result.checks:
        counts[c.status] += 1
    return {
        "target": result.target,
        "domain": result.domain,
        "engine": result.engine,
        "verdict": result.verdict,
        "score": result.score,
        "passed": result.passed,
        "blockers": result.blockers,
        "counts": counts,
    }


__all__ = [
    "Severity",
    "CheckStatus",
    "Category",
    "Verdict",
    "CheckResult",
    "AuditResult",
    "summarize",
]
