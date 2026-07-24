import { useMemo, useState } from "react";
import type { ResultRow } from "../lib/api";
import { useT } from "../lib/i18n";
import { CheckIcon, MinusIcon } from "./icons";

export type ResultOutcome =
  | "cited"
  | "sources_only"
  | "mention_only"
  | "absent"
  | "no_answer";

export function outcomeOf(r: ResultRow): ResultOutcome {
  if (!r.overview_present) return "no_answer";
  if (r.target_citation_ranks.length > 0) return "cited";
  if (r.target_source_ranks.length > 0) return "sources_only";
  if (r.brand_in_answer_text) return "mention_only";
  return "absent";
}

const FILTERS: readonly ("all" | ResultOutcome)[] = [
  "all",
  "cited",
  "sources_only",
  "mention_only",
  "absent",
  "no_answer",
];

export function ResultsTable({ rows }: { rows: ResultRow[] }) {
  const t = useT();
  const dash = t("common.dash");
  const ranks = (arr: number[]): string => (arr.length ? arr.join(", ") : dash);
  const [filter, setFilter] = useState<"all" | ResultOutcome>("all");

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: rows.length };
    for (const f of FILTERS) if (f !== "all") c[f] = 0;
    for (const r of rows) c[outcomeOf(r)] += 1;
    return c;
  }, [rows]);

  const visible = useMemo(
    () => (filter === "all" ? rows : rows.filter((r) => outcomeOf(r) === filter)),
    [rows, filter],
  );

  if (rows.length === 0) {
    return <div className="text-sm text-[var(--muted)]">{t("dashboard.results_empty")}</div>;
  }

  return (
    <div>
      <div
        role="group"
        aria-label={t("dashboard.results_filter_label")}
        className="mb-3 flex flex-wrap gap-1.5"
      >
        {FILTERS.map((f) => {
          const active = filter === f;
          return (
            <button
              key={f}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(f)}
              className={`inline-flex min-h-[32px] cursor-pointer items-center gap-1.5 rounded-full border px-3 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
                active
                  ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-fg)]"
                  : "border-[var(--border)] bg-[var(--surface-2)] text-[var(--muted)] hover:text-[var(--fg)]"
              }`}
            >
              {t(`dashboard.results_filter_${f}`)}
              <span className="tabular-nums opacity-70">{counts[f]}</span>
            </button>
          );
        })}
      </div>
      {visible.length === 0 ? (
        <div className="text-sm text-[var(--muted)]">
          {t("dashboard.results_filter_empty")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-left text-[var(--muted)]">
                <th scope="col" className="min-w-[260px] py-2 pr-4 font-medium">
                  {t("dashboard.results_col_query")}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("dashboard.results_col_lens")}
                </th>
                <th scope="col" className="px-3 py-2 text-center font-medium">
                  {t("dashboard.results_col_overview")}
                </th>
                <th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-medium">
                  {t("dashboard.results_col_source_ranks")}
                </th>
                <th scope="col" className="whitespace-nowrap px-3 py-2 text-right font-medium">
                  {t("dashboard.results_col_citation_ranks")}
                </th>
                <th scope="col" className="px-3 py-2 text-center font-medium">
                  {t("dashboard.results_col_mention")}
                </th>
                <th scope="col" className="min-w-[280px] py-2 pl-3 font-medium">
                  {t("dashboard.results_col_sentiment")}
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-[var(--border)] align-top text-[var(--fg)]"
                >
                  <th scope="row" className="py-2.5 pr-4 text-left font-normal">
                    {r.query}
                  </th>
                  <td className="whitespace-nowrap px-3 py-2.5 text-[var(--muted)]">
                    {t(`lens.${r.lens}`)}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    {r.overview_present ? (
                      <span
                        className="inline-flex text-[var(--good)]"
                        aria-label={t("dashboard.results_overview_shown")}
                      >
                        <CheckIcon size={16} />
                      </span>
                    ) : (
                      <span
                        className="inline-flex text-[var(--muted)]"
                        aria-label={t("dashboard.results_overview_absent")}
                      >
                        <MinusIcon size={16} />
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {ranks(r.target_source_ranks)}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {ranks(r.target_citation_ranks)}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    {r.brand_in_answer_text ? (
                      <span
                        className="inline-flex text-[var(--good)]"
                        aria-label={t("dashboard.results_mention_yes")}
                      >
                        <CheckIcon size={16} />
                      </span>
                    ) : (
                      <span
                        className="inline-flex text-[var(--muted)]"
                        aria-label={t("dashboard.results_mention_no")}
                      >
                        <MinusIcon size={16} />
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pl-3">
                    {r.sentiment ?? (
                      <span className="italic text-[var(--muted)]">
                        {t("dashboard.results_brand_absent")}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
