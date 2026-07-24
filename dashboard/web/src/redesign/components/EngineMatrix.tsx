import type { EngineMatrixRow } from "../lib/api";
import { num, pct } from "../lib/format";
import { useT } from "../lib/i18n";

export function EngineMatrix({
  rows,
  onSelect,
}: {
  rows: EngineMatrixRow[];
  onSelect?: (engine: string) => void;
}) {
  const t = useT();
  const dash = t("common.dash");

  if (rows.length === 0) {
    return <div className="text-sm text-[var(--muted)]">{t("dashboard.matrix_empty")}</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-left text-[var(--muted)]">
            <th scope="col" className="py-2 pr-4 font-medium">
              {t("dashboard.matrix_col_engine")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_queries")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_overview")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_coverage")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_visibility_sources")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_visibility_citations")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_mentions")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.matrix_col_relative")}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              {t("dashboard.lens_col_position_sources")}
            </th>
            <th scope="col" className="py-2 pl-3 text-right font-medium">
              {t("dashboard.lens_col_position_citations")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.engine} className="border-b border-[var(--border)]">
              <th scope="row" className="py-2 pr-4 text-left font-normal">
                {onSelect ? (
                  <button
                    type="button"
                    onClick={() => onSelect(r.engine)}
                    title={t("dashboard.matrix_open_engine")}
                    className="cursor-pointer rounded text-[var(--accent)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  >
                    {r.engine}
                  </button>
                ) : (
                  r.engine
                )}
              </th>
              <td className="px-3 py-2 text-right tabular-nums">
                {r.n_queries ?? dash}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {r.n_overviews ?? dash}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.overview_coverage, dash)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.visibility_in_sources, dash)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.visibility_in_citations, dash)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.brand_mention_rate, dash)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {pct(r.relative_citation, dash)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {num(r.avg_source_position, 2, dash)}
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
