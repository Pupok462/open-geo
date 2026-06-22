const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export type Lens = "all" | "general" | "branded" | "comparative";

export type Brand = { id: number; name: string; domain: string };

export type Run = {
  run_id: number;
  run_at: string;
  status: string;
  engine: string;
  n_queries: number;
  n_ok: number;
  n_failed: number;
};

type Num = number | null | undefined;

export type MetricRow = {
  lens: Lens | string;
  n_queries: number;
  n_overviews: number;
  overview_coverage: Num;
  n_in_sources: number;
  visibility_in_sources: Num;
  n_cited: number;
  visibility_in_citations: Num;
  avg_source_position: Num;
  avg_citation_position: Num;
  relative_citation: Num;
  sentiment_summary?: string | null;
  overview_coverage_delta?: Num;
  visibility_in_sources_delta?: Num;
  visibility_in_citations_delta?: Num;
  avg_source_position_delta?: Num;
  avg_citation_position_delta?: Num;
  relative_citation_delta?: Num;
};

export type MetricsResponse = {
  brand_id: number;
  engine: string;
  period: "today" | "all";
  run: { run_id: number; run_at: string; status: string; n_queries?: number } | null;
  prev_run: { run_id: number; run_at: string; status: string } | null;
  n_runs?: number;
  metrics: MetricRow[];
};

export type TimeseriesPoint = {
  run_id: number;
  run_at: string;
  status: string;
  lens: string;
  n_queries: number;
  n_overviews: number;
  overview_coverage: Num;
  visibility_in_sources: Num;
  visibility_in_citations: Num;
  avg_source_position: Num;
  avg_citation_position: Num;
};

export type TimeseriesResponse = {
  brand_id: number;
  engine: string;
  lens: string;
  points: TimeseriesPoint[];
};

export type LinkRef = { rank: number; url: string; domain: string };

export type ResultRow = {
  id: number;
  query: string;
  lens: string;
  captured_at: string | null;
  overview_present: boolean;
  answer_text_md: string | null;
  screenshot_path: string | null;
  sources: LinkRef[];
  citations: LinkRef[];
  target_source_ranks: number[];
  target_citation_ranks: number[];
  brand_in_answer_text: boolean;
  sentiment: string | null;
};

export type ResultsResponse = {
  run: { run_id: number; brand_id: number; engine: string; run_at: string; status: string };
  lens: string | null;
  results: ResultRow[];
};

export type CompetitorRow = {
  domain: string;
  is_brand: boolean;
  appearances_sources: number;
  appearances_citations: number;
  share_sources: Num;
  share_citations: Num;
  avg_source_position: Num;
  avg_citation_position: Num;
};

export type CompetitorsResponse = {
  brand_id: number;
  engine: string;
  period: "today" | "all";
  lens: string;
  n_overviews: number;
  run: { run_id: number; run_at: string; status: string } | null;
  domains: CompetitorRow[];
};

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | undefined>): string => {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
};

export const api = {
  brands: () => getJSON<Brand[]>("/api/brands"),
  engines: (brandId: number) => getJSON<string[]>(`/api/engines${qs({ brand_id: brandId })}`),
  runs: (brandId: number, engine?: string) =>
    getJSON<Run[]>(`/api/runs${qs({ brand_id: brandId, engine })}`),
  metrics: (brandId: number, engine: string, period: "today" | "all", lens?: string) =>
    getJSON<MetricsResponse>(`/api/metrics${qs({ brand_id: brandId, engine, period, lens })}`),
  timeseries: (brandId: number, engine: string, lens: string) =>
    getJSON<TimeseriesResponse>(`/api/timeseries${qs({ brand_id: brandId, engine, lens })}`),
  results: (runId: number, lens?: string) =>
    getJSON<ResultsResponse>(`/api/results${qs({ run_id: runId, lens })}`),
  competitors: (
    brandId: number,
    engine: string,
    period: "today" | "all",
    lens?: string,
    limit = 15,
  ) =>
    getJSON<CompetitorsResponse>(
      `/api/competitors${qs({ brand_id: brandId, engine, period, lens, limit })}`,
    ),
  reportUrl: (brandId: number, engine: string, period: "today" | "all", lang?: string) =>
    `${API_BASE}/api/report${qs({ brand_id: brandId, engine, period, lang })}`,
};
