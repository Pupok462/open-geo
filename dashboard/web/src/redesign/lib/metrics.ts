import type { MetricRow } from "./api";
import type { TFn } from "./i18n";

export type MetricKey =
  | "overview_coverage"
  | "visibility_in_sources"
  | "visibility_in_citations"
  | "avg_source_position"
  | "avg_citation_position"
  | "relative_citation"
  | "brand_mention_rate";

export interface MetricDef {
  key: MetricKey;
  asPct: boolean;
  higherIsBetter: boolean;
  value: (row: MetricRow) => number | null | undefined;
  delta: (row: MetricRow) => number | null | undefined;
  labelKey: string;
  infoKey: string;
  subKey: string;
  subVars?: (row: MetricRow) => Record<string, string | number>;
  subRender?: (row: MetricRow, t: TFn) => string;
}

export function spreadOf(
  def: MetricDef,
  row: MetricRow,
): { min: number; max: number } | null {
  const r = row as unknown as Record<string, number | null | undefined>;
  const min = r[`${def.key}_min`];
  const max = r[`${def.key}_max`];
  if (min === null || min === undefined || max === null || max === undefined) {
    return null;
  }
  return { min, max };
}

export const METRICS: MetricDef[] = [
  {
    key: "overview_coverage",
    asPct: true,
    higherIsBetter: true,
    value: (r) => r.overview_coverage,
    delta: (r) => r.overview_coverage_delta,
    labelKey: "metrics.overview_coverage.label",
    infoKey: "metrics.overview_coverage.hint",
    subKey: "report.card_coverage_sub",
    subVars: (r) => ({ n_overviews: r.n_overviews, n_queries: r.n_queries }),
  },
  {
    key: "visibility_in_sources",
    asPct: true,
    higherIsBetter: true,
    value: (r) => r.visibility_in_sources,
    delta: (r) => r.visibility_in_sources_delta,
    labelKey: "metrics.visibility_in_sources.label",
    infoKey: "metrics.visibility_in_sources.hint",
    subKey: "report.card_visibility_sub",
    subVars: (r) => ({ numerator: r.n_in_sources, n_overviews: r.n_overviews }),
  },
  {
    key: "visibility_in_citations",
    asPct: true,
    higherIsBetter: true,
    value: (r) => r.visibility_in_citations,
    delta: (r) => r.visibility_in_citations_delta,
    labelKey: "metrics.visibility_in_citations.label",
    infoKey: "metrics.visibility_in_citations.hint",
    subKey: "report.card_visibility_sub",
    subVars: (r) => ({ numerator: r.n_cited, n_overviews: r.n_overviews }),
  },
  {
    key: "relative_citation",
    asPct: true,
    higherIsBetter: true,
    value: (r) => r.relative_citation,
    delta: (r) => r.relative_citation_delta,
    labelKey: "metrics.relative_citation.label",
    infoKey: "metrics.relative_citation.hint",
    subKey: "common.dash",
    subRender: (r, t) => `${r.n_cited} ${t("common.of")} ${r.n_in_sources}`,
  },
  {
    key: "brand_mention_rate",
    asPct: true,
    higherIsBetter: true,
    value: (r) => r.brand_mention_rate,
    delta: (r) => r.brand_mention_rate_delta,
    labelKey: "metrics.brand_mention_rate.label",
    infoKey: "metrics.brand_mention_rate.hint",
    subKey: "report.card_visibility_sub",
    subVars: (r) => ({
      numerator: r.n_brand_mentions ?? 0,
      n_overviews: r.n_overviews,
    }),
  },
  {
    key: "avg_source_position",
    asPct: false,
    higherIsBetter: false,
    value: (r) => r.avg_source_position,
    delta: (r) => r.avg_source_position_delta,
    labelKey: "metrics.avg_source_position.label",
    infoKey: "metrics.avg_source_position.hint",
    subKey: "common.lower_is_better",
  },
  {
    key: "avg_citation_position",
    asPct: false,
    higherIsBetter: false,
    value: (r) => r.avg_citation_position,
    delta: (r) => r.avg_citation_position_delta,
    labelKey: "metrics.avg_citation_position.label",
    infoKey: "metrics.avg_citation_position.hint",
    subKey: "common.lower_is_better",
  },
];
