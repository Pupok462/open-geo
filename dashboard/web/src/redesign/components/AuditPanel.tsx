import { useMemo } from "react";
import type { AuditCheck, AuditResult } from "../lib/api";
import { fmtDateTime } from "../lib/format";
import { useT } from "../lib/i18n";

const STATUS_RANK: Record<string, number> = { fail: 0, warn: 1, pass: 2, skip: 3 };
const SEVERITY_RANK: Record<string, number> = {
  blocker: 0,
  recommended: 1,
  nice_to_have: 2,
};

const VERDICT_TONE: Record<string, string> = {
  ready: "var(--good)",
  ready_with_warnings: "var(--warn)",
  blocked: "var(--bad)",
};

const STATUS_TONE: Record<string, string> = {
  pass: "var(--good)",
  warn: "var(--warn)",
  fail: "var(--bad)",
  skip: "var(--faint)",
};

function rank(map: Record<string, number>, key: string): number {
  return key in map ? map[key] : 99;
}

export function AuditPanel({ audit }: { audit: AuditResult | null }) {
  const t = useT();

  const sorted = useMemo(() => {
    const out = [...(audit?.checks ?? [])];
    out.sort(
      (a, b) =>
        rank(STATUS_RANK, a.status) - rank(STATUS_RANK, b.status) ||
        rank(SEVERITY_RANK, a.severity) - rank(SEVERITY_RANK, b.severity),
    );
    return out;
  }, [audit]);

  if (!audit) {
    return (
      <div className="text-sm text-[var(--muted)]">{t("dashboard.audit_empty")}</div>
    );
  }

  const verdictTone = VERDICT_TONE[audit.verdict] ?? "var(--muted)";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <span
          className="inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold text-[var(--accent-fg)]"
          style={{ backgroundColor: verdictTone }}
        >
          {t(`audit.verdict_${audit.verdict}`)}
        </span>
        <span className="text-sm text-[var(--muted)]">
          {t("audit.score")}:{" "}
          <span className="font-semibold tabular-nums text-[var(--fg)]">
            {audit.score}
          </span>
          /100
        </span>
        <span className="text-xs text-[var(--faint)]">
          {t("dashboard.audit_checked_at", {
            datetime: fmtDateTime(audit.checked_at),
          })}
        </span>
      </div>

      {audit.blockers.length > 0 && (
        <div className="text-sm text-[var(--bad)]">
          <span className="font-medium">{t("audit.blockers")}:</span>{" "}
          <span className="tabular-nums">{audit.blockers.join(", ")}</span>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-[var(--muted)]">
              <th scope="col" className="py-2 pr-3 text-left font-medium">
                {t("audit.col_check")}
              </th>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                {t("audit.col_severity")}
              </th>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                {t("audit.col_status")}
              </th>
              <th scope="col" className="py-2 pl-3 text-left font-medium">
                {t("audit.col_detail")}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <AuditRow key={c.id} check={c} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AuditRow({ check }: { check: AuditCheck }) {
  const t = useT();
  const showFix =
    (check.status === "fail" || check.status === "warn") && !!check.remediation;
  return (
    <tr className="border-b border-[var(--border)] align-top">
      <th scope="row" className="py-2 pr-3 text-left font-normal">
        <span className="text-[var(--faint)] tabular-nums">{check.id}</span>{" "}
        <span className="text-[var(--fg)]">{check.title}</span>
      </th>
      <td className="px-3 py-2 text-[var(--muted)]">
        {t(`audit.severity_${check.severity}`)}
      </td>
      <td className="px-3 py-2">
        <span style={{ color: STATUS_TONE[check.status] ?? "var(--muted)" }}>
          {t(`audit.status_${check.status}`)}
        </span>
      </td>
      <td className="py-2 pl-3 text-[var(--muted)]">
        <span>{check.detail}</span>
        {showFix && (
          <div className="mt-1 text-[var(--faint)]">
            <span className="font-medium">{t("audit.col_fix")}:</span>{" "}
            {check.remediation}
          </div>
        )}
      </td>
    </tr>
  );
}
