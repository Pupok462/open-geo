import { useMemo, useState } from "react";
import type { CompetitorRow } from "../lib/api";
import { num, pct } from "../lib/format";
import { useT } from "../lib/i18n";

type SortKey =
  | "domain"
  | "appearances_sources"
  | "avg_source_position"
  | "appearances_citations"
  | "avg_citation_position";

type Dir = "asc" | "desc";

const DEFAULT_DIR: Record<SortKey, Dir> = {
  domain: "asc",
  appearances_sources: "desc",
  avg_source_position: "asc",
  appearances_citations: "desc",
  avg_citation_position: "asc",
};

function compare(a: CompetitorRow, b: CompetitorRow, key: SortKey): number {
  if (key === "domain") return a.domain.localeCompare(b.domain);
  const av = a[key];
  const bv = b[key];
  const an = av === null || av === undefined;
  const bn = bv === null || bv === undefined;
  if (an && bn) return 0;
  if (an) return 1;
  if (bn) return -1;
  return (av as number) - (bv as number);
}

export function CompetitorsPanel({ rows }: { rows: CompetitorRow[] }) {
  const t = useT();
  const dash = t("common.dash");
  const [sortKey, setSortKey] = useState<SortKey>("appearances_sources");
  const [dir, setDir] = useState<Dir>("desc");

  const sorted = useMemo(() => {
    const out = [...rows];
    out.sort((a, b) => {
      const base = compare(a, b, sortKey);
      const primary = dir === "asc" ? base : -base;
      if (primary !== 0) return primary;
      return (
        b.appearances_sources - a.appearances_sources ||
        a.domain.localeCompare(b.domain)
      );
    });
    return out;
  }, [rows, sortKey, dir]);

  if (rows.length === 0) {
    return (
      <div className="text-sm text-[var(--muted)]">
        {t("dashboard.competitors_empty")}
      </div>
    );
  }

  function onSort(key: SortKey) {
    if (key === sortKey) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDir(DEFAULT_DIR[key]);
    }
  }

  const cols: { key: SortKey; label: string; align: "left" | "right" }[] = [
    { key: "domain", label: t("dashboard.competitors_col_domain"), align: "left" },
    { key: "appearances_sources", label: t("dashboard.competitors_col_sources"), align: "right" },
    { key: "avg_source_position", label: t("dashboard.competitors_col_position_sources"), align: "right" },
    { key: "appearances_citations", label: t("dashboard.competitors_col_citations"), align: "right" },
    { key: "avg_citation_position", label: t("dashboard.competitors_col_position_citations"), align: "right" },
  ];

  const you = t("dashboard.competitors_you");

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-[var(--muted)]">
            {cols.map((c) => {
              const active = c.key === sortKey;
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={
                    active ? (dir === "asc" ? "ascending" : "descending") : "none"
                  }
                  className={`py-2 font-medium ${
                    c.align === "right" ? "px-3 text-right" : "pr-3 text-left"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onSort(c.key)}
                    className={`inline-flex cursor-pointer items-center gap-1 hover:text-[var(--fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
                      c.align === "right" ? "flex-row-reverse" : ""
                    } ${active ? "text-[var(--fg)]" : ""}`}
                  >
                    {c.label}
                    <span aria-hidden className="text-[10px] text-[var(--faint)]">
                      {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.domain}
              className={`border-b border-[var(--border)] ${
                r.is_brand ? "bg-[var(--surface-2)] font-medium" : ""
              }`}
            >
              <th scope="row" className="py-2 pr-3 text-left font-normal">
                <span className={r.is_brand ? "text-[var(--fg)]" : ""}>
                  {r.domain}
                </span>
                {r.is_brand && (
                  <span className="ml-2 rounded bg-[var(--accent)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--accent-fg)]">
                    {you}
                  </span>
                )}
              </th>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.share_sources, dash)}
                <span className="ml-1 text-[var(--faint)]">
                  ({r.appearances_sources})
                </span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {num(r.avg_source_position, 2, dash)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.share_citations, dash)}
                <span className="ml-1 text-[var(--faint)]">
                  ({r.appearances_citations})
                </span>
              </td>
              <td className="py-2 pl-3 text-right tabular-nums">
                {num(r.avg_citation_position, 2, dash)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
