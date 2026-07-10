import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { AuditPanel } from "./AuditPanel";
import { I18nProvider } from "../lib/i18n";
import type { AuditCheck, AuditResult } from "../lib/api";

function renderWithProviders(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function makeCheck(over: Partial<AuditCheck> = {}): AuditCheck {
  return {
    id: "A1",
    category: "A",
    title: "HTTPS reachable",
    severity: "blocker",
    status: "pass",
    detail: "200 over HTTPS",
    remediation: null,
    ...over,
  };
}

function makeAudit(over: Partial<AuditResult> = {}): AuditResult {
  return {
    target: "example.com",
    domain: "example.com",
    engine: "google",
    checked_at: "2026-06-18T09:00:00Z",
    verdict: "ready",
    score: 91,
    passed: true,
    blockers: [],
    checks: [makeCheck()],
    ...over,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AuditPanel — empty", () => {
  it("renders the empty-state copy and no table when audit is null", () => {
    renderWithProviders(<AuditPanel audit={null} />);
    expect(screen.getByText("No audit for this domain yet.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("AuditPanel — verdict + score + chrome", () => {
  it("ready verdict badge, score/100, and localized checked-at", () => {
    renderWithProviders(<AuditPanel audit={makeAudit()} />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText(/GEO-readiness/)).toBeInTheDocument();
    expect(screen.getByText("91")).toBeInTheDocument();
    expect(screen.getByText(/Audited/)).toBeInTheDocument();
  });

  it("ready_with_warnings verdict badge carries the warn tone", () => {
    renderWithProviders(
      <AuditPanel audit={makeAudit({ verdict: "ready_with_warnings" })} />,
    );
    const badge = screen.getByText("Ready with warnings");
    expect(badge).toHaveStyle({ backgroundColor: "var(--warn)" });
  });

  it("blocked verdict badge lists blockers and carries the bad tone", () => {
    renderWithProviders(
      <AuditPanel
        audit={makeAudit({
          verdict: "blocked",
          passed: false,
          blockers: ["A3", "A5"],
          checks: [makeCheck({ id: "A3", status: "fail", detail: "bot blocked" })],
        })}
      />,
    );
    const badge = screen.getByText("Blocked");
    expect(badge).toHaveStyle({ backgroundColor: "var(--bad)" });
    expect(screen.getByText("Blockers:")).toBeInTheDocument();
    expect(screen.getByText("A3, A5")).toBeInTheDocument();
  });

  it("falls back to a neutral tone for an unknown verdict", () => {
    renderWithProviders(<AuditPanel audit={makeAudit({ verdict: "weird" })} />);
    const badge = screen.getByText("audit.verdict_weird");
    expect(badge).toHaveStyle({ backgroundColor: "var(--muted)" });
  });

  it("does not render the blockers line when there are none", () => {
    renderWithProviders(<AuditPanel audit={makeAudit()} />);
    expect(screen.queryByText("Blockers:")).not.toBeInTheDocument();
  });
});

describe("AuditPanel — table", () => {
  it("renders the four localized column headers", () => {
    renderWithProviders(<AuditPanel audit={makeAudit()} />);
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
    for (const label of ["Check", "Severity", "Status", "Detail"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders localized severity and status labels per row", () => {
    renderWithProviders(
      <AuditPanel
        audit={makeAudit({
          checks: [
            makeCheck({ id: "A1", severity: "blocker", status: "pass" }),
            makeCheck({
              id: "B1",
              severity: "recommended",
              status: "warn",
              remediation: "add JSON-LD",
            }),
            makeCheck({ id: "C1", severity: "nice_to_have", status: "skip" }),
          ],
        })}
      />,
    );
    expect(screen.getByText("Blocker")).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    expect(screen.getByText("Nice to have")).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.getByText("Warn")).toBeInTheDocument();
    expect(screen.getByText("Skip")).toBeInTheDocument();
  });

  it("shows the 'How to fix' remediation only for fail/warn rows that have one", () => {
    renderWithProviders(
      <AuditPanel
        audit={makeAudit({
          checks: [
            makeCheck({ id: "A1", status: "pass", remediation: "ignored on pass" }),
            makeCheck({
              id: "B1",
              status: "warn",
              detail: "no JSON-LD",
              remediation: "Add Organization JSON-LD",
            }),
            makeCheck({
              id: "B2",
              status: "fail",
              detail: "no fix text",
              remediation: null,
            }),
          ],
        })}
      />,
    );
    expect(screen.getByText("Add Organization JSON-LD")).toBeInTheDocument();
    expect(screen.getByText("How to fix:")).toBeInTheDocument();
    expect(screen.queryByText("ignored on pass")).not.toBeInTheDocument();
    expect(screen.getAllByText("How to fix:")).toHaveLength(1);
  });

  it("colors an unknown status with the neutral fallback tone", () => {
    renderWithProviders(
      <AuditPanel
        audit={makeAudit({
          checks: [makeCheck({ id: "Z9", status: "mystery", severity: "unknown" })],
        })}
      />,
    );
    const label = screen.getByText("audit.status_mystery");
    expect(label).toHaveStyle({ color: "var(--muted)" });
  });
});

describe("AuditPanel — sort", () => {
  it("orders fails and warns before passes, blocker severity first within a status", () => {
    const rows = [
      makeCheck({ id: "P1", status: "pass", severity: "blocker" }),
      makeCheck({
        id: "W1",
        status: "warn",
        severity: "recommended",
        remediation: "x",
      }),
      makeCheck({
        id: "F1",
        status: "fail",
        severity: "recommended",
        remediation: "y",
      }),
      makeCheck({
        id: "F0",
        status: "fail",
        severity: "blocker",
        remediation: "z",
      }),
      makeCheck({ id: "S1", status: "skip", severity: "nice_to_have" }),
      makeCheck({ id: "U0", status: "mystery", severity: "unknown" }),
    ];
    renderWithProviders(<AuditPanel audit={makeAudit({ checks: rows })} />);
    const ids = screen
      .getAllByRole("rowheader")
      .map((th) => within(th).getByText(/^[A-Z]\d$/).textContent);
    expect(ids).toEqual(["F0", "F1", "W1", "P1", "S1", "U0"]);
  });
});
