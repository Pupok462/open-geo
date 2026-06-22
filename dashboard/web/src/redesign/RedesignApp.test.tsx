import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RedesignApp from "./RedesignApp";
import type {
  Brand,
  CompetitorsResponse,
  MetricRow,
  MetricsResponse,
  ResultRow,
  ResultsResponse,
  Run,
  TimeseriesPoint,
  TimeseriesResponse,
} from "./lib/api";


const BRANDS: Brand[] = [
  { id: 1, name: "Example", domain: "example.com" },
  { id: 2, name: "Globex", domain: "globex.com" },
];

const ENGINES_BY_BRAND: Record<number, string[]> = {
  1: ["google", "perplexity"],
  2: ["google"],
};

function metricRow(lens: string, over: Partial<MetricRow> = {}): MetricRow {
  return {
    lens,
    n_queries: 20,
    n_overviews: 12,
    overview_coverage: 0.6,
    n_in_sources: 6,
    visibility_in_sources: 0.5,
    n_cited: 3,
    visibility_in_citations: 0.25,
    avg_source_position: 2.5,
    avg_citation_position: 4.0,
    relative_citation: 0.45,
    overview_coverage_delta: 0.05,
    visibility_in_sources_delta: -0.1,
    visibility_in_citations_delta: 0,
    avg_source_position_delta: -0.3,
    avg_citation_position_delta: 0.2,
    relative_citation_delta: 0.04,
    ...over,
  };
}

function makeMetrics(over: Partial<MetricsResponse> = {}): MetricsResponse {
  return {
    brand_id: 1,
    engine: "google",
    period: "today",
    run: { run_id: 42, run_at: "2026-06-18T12:00:00Z", status: "done", n_queries: 20 },
    prev_run: { run_id: 41, run_at: "2026-06-17T12:00:00Z", status: "done" },
    n_runs: 5,
    metrics: [
      metricRow("all"),
      metricRow("general", { n_queries: 8 }),
      metricRow("branded", { n_queries: 6 }),
      metricRow("comparative", { n_queries: 6 }),
    ],
    ...over,
  };
}

function tsPoint(runId: number, over: Partial<TimeseriesPoint> = {}): TimeseriesPoint {
  return {
    run_id: runId,
    run_at: "2026-06-18T12:00:00Z",
    status: "done",
    lens: "all",
    n_queries: 20,
    n_overviews: 12,
    overview_coverage: 0.6,
    visibility_in_sources: 0.5,
    visibility_in_citations: 0.25,
    avg_source_position: 2.5,
    avg_citation_position: 4.0,
    ...over,
  };
}

function makeTimeseries(points: TimeseriesPoint[]): TimeseriesResponse {
  return { brand_id: 1, engine: "google", lens: "all", points };
}

const RUNS: Run[] = [
  {
    run_id: 42,
    run_at: "2026-06-18T12:00:00Z",
    status: "done",
    engine: "google",
    n_queries: 20,
    n_ok: 19,
    n_failed: 1,
  },
  {
    run_id: 40,
    run_at: "2026-06-16T12:00:00Z",
    status: "running",
    engine: "google",
    n_queries: 20,
    n_ok: 0,
    n_failed: 0,
  },
];

function resultRow(over: Partial<ResultRow> = {}): ResultRow {
  return {
    id: 100,
    query: "best running shoes",
    lens: "general",
    captured_at: "2026-06-18T12:00:00Z",
    overview_present: true,
    answer_text_md: "Some answer",
    screenshot_path: null,
    sources: [{ rank: 1, url: "https://example.com/x", domain: "example.com" }],
    citations: [],
    target_source_ranks: [1],
    target_citation_ranks: [],
    brand_in_answer_text: true,
    sentiment: "positive mention",
    ...over,
  };
}

function makeResults(over: Partial<ResultsResponse> = {}): ResultsResponse {
  return {
    run: {
      run_id: 42,
      brand_id: 1,
      engine: "google",
      run_at: "2026-06-18T12:00:00Z",
      status: "done",
    },
    lens: null,
    results: [resultRow(), resultRow({ id: 101, query: "example vs globex", lens: "comparative" })],
    ...over,
  };
}


type RouterOverrides = {
  brands?: () => Promise<Response> | Response;
  engines?: (brandId: number) => Promise<Response> | Response;
  runs?: () => Promise<Response> | Response;
  metrics?: (period: string, lens: string | null) => Promise<Response> | Response;
  timeseries?: (lens: string) => Promise<Response> | Response;
  competitors?: (period: string, lens: string | null) => Promise<Response> | Response;
  results?: (runId: string | null, lens: string | null) => Promise<Response> | Response;
  report?: (init?: RequestInit) => Promise<Response> | Response;
  i18nRegistry?: () => Promise<Response> | Response;
};

function makeCompetitors(over: Partial<CompetitorsResponse> = {}): CompetitorsResponse {
  return {
    brand_id: 1,
    engine: "google",
    period: "today",
    lens: "all",
    n_overviews: 12,
    run: { run_id: 42, run_at: "2026-06-09T00:00:00Z", status: "done" },
    domains: [
      {
        domain: "example.com",
        is_brand: true,
        appearances_sources: 7,
        appearances_citations: 3,
        share_sources: 0.58,
        share_citations: 0.25,
        avg_source_position: 2.1,
        avg_citation_position: 1.5,
      },
      {
        domain: "reddit.com",
        is_brand: false,
        appearances_sources: 6,
        appearances_citations: 0,
        share_sources: 0.5,
        share_citations: 0.0,
        avg_source_position: 2.6,
        avg_citation_position: null,
      },
    ],
    ...over,
  };
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

function pdfResponse(): Response {
  return {
    ok: true,
    status: 200,
    blob: () =>
      Promise.resolve(new Blob(["%PDF-1.4 fake"], { type: "application/pdf" })),
  } as unknown as Response;
}

function installFetch(overrides: RouterOverrides = {}) {
  const calls: { url: string; method: string }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ url, method });
    const u = new URL(url, "http://localhost");
    const path = u.pathname;
    const params = u.searchParams;

    if (path === "/api/report") {
      if (overrides.report) return overrides.report(init);
      return pdfResponse();
    }

    if (path === "/api/i18n") {
      if (overrides.i18nRegistry) return overrides.i18nRegistry();
      return jsonResponse([
        { code: "en", name: "English" },
        { code: "ru", name: "Русский" },
      ]);
    }
    if (path.startsWith("/api/i18n/")) {
      return jsonResponse({});
    }

    if (path === "/api/brands") {
      if (overrides.brands) return overrides.brands();
      return jsonResponse(BRANDS);
    }
    if (path === "/api/engines") {
      const brandId = Number(params.get("brand_id"));
      if (overrides.engines) return overrides.engines(brandId);
      return jsonResponse(ENGINES_BY_BRAND[brandId] ?? ["google"]);
    }
    if (path === "/api/runs") {
      if (overrides.runs) return overrides.runs();
      return jsonResponse(RUNS);
    }
    if (path === "/api/metrics") {
      const period = params.get("period") ?? "today";
      const lens = params.get("lens");
      if (overrides.metrics) return overrides.metrics(period, lens);
      return jsonResponse(makeMetrics({ period: period as "today" | "all" }));
    }
    if (path === "/api/timeseries") {
      const lens = params.get("lens") ?? "all";
      if (overrides.timeseries) return overrides.timeseries(lens);
      return jsonResponse(makeTimeseries([tsPoint(40), tsPoint(42)]));
    }
    if (path === "/api/competitors") {
      const period = params.get("period") ?? "today";
      const lens = params.get("lens");
      if (overrides.competitors) return overrides.competitors(period, lens);
      return jsonResponse(makeCompetitors({ period: period as "today" | "all" }));
    }
    if (path === "/api/results") {
      const runId = params.get("run_id");
      const lens = params.get("lens");
      if (overrides.results) return overrides.results(runId, lens);
      return jsonResponse(makeResults());
    }

    throw new Error(`unhandled fetch path in test: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

const callsTo = (calls: { url: string; method: string }[], path: string) =>
  calls.filter((c) => new URL(c.url, "http://localhost").pathname === path);

function stubObjectURL() {
  const createObjectURL = vi
    .spyOn(URL, "createObjectURL")
    .mockReturnValue("blob:fake-url");
  const revokeObjectURL = vi
    .spyOn(URL, "revokeObjectURL")
    .mockImplementation(() => {});
  return { createObjectURL, revokeObjectURL };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("lang");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("RedesignApp — initial load", () => {
  it("renders the header chrome immediately (before any data)", () => {
    installFetch();
    render(<RedesignApp />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("open-geo");
    expect(screen.getByText(/AI visibility/i)).toBeInTheDocument();
  });

  it("fetches brands, auto-selects the first, then loads engines and metrics", async () => {
    const { calls } = installFetch();
    render(<RedesignApp />);

    await waitFor(() =>
      expect(screen.getByText(/Run #42/)).toBeInTheDocument(),
    );

    expect(callsTo(calls, "/api/brands").length).toBe(1);
    expect(callsTo(calls, "/api/engines").length).toBeGreaterThanOrEqual(1);
    expect(callsTo(calls, "/api/metrics").length).toBeGreaterThanOrEqual(1);
    expect(callsTo(calls, "/api/timeseries").length).toBeGreaterThanOrEqual(1);
    expect(callsTo(calls, "/api/runs").length).toBeGreaterThanOrEqual(1);

    const brandSelect = screen.getByLabelText("Brand") as HTMLSelectElement;
    expect(brandSelect.value).toBe("1");
    const engineSelect = screen.getByLabelText("Engine") as HTMLSelectElement;
    expect(engineSelect.value).toBe("google");
  });

  it("renders the six KPI cards with formatted values from the 'all' lens row", async () => {
    installFetch();
    const { container } = render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    const grid = container.querySelector(".xl\\:grid-cols-6") as HTMLElement;
    expect(grid).toBeTruthy();
    const kpis = within(grid);
    expect(kpis.getByText("60.0%")).toBeInTheDocument();
    expect(kpis.getByText("50.0%")).toBeInTheDocument();
    expect(kpis.getByText("25.0%")).toBeInTheDocument();
    expect(kpis.getByText("45.0%")).toBeInTheDocument();
    expect(kpis.getByText("2.50")).toBeInTheDocument();
    expect(kpis.getByText("4.00")).toBeInTheDocument();
  });

  it("latest-run view hides the trend chart but still renders lens + results tables", async () => {
    const user = userEvent.setup();
    installFetch();
    const { container } = render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    expect(container.querySelector(".recharts-responsive-container")).toBeNull();
    expect(screen.queryByText("Trend across runs")).not.toBeInTheDocument();
    expect(screen.getByText(/run #42 · 2 rows/)).toBeInTheDocument();
    expect(screen.queryByText("best running shoes")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByText("best running shoes")).toBeInTheDocument();
    expect(screen.getByText("example vs globex")).toBeInTheDocument();
  });

  it("trend chart is hidden in latest-run and revealed when switching to whole-period", async () => {
    const user = userEvent.setup();
    installFetch();
    const { container } = render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    expect(container.querySelector(".recharts-responsive-container")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Whole period" }));
    await waitFor(() =>
      expect(container.querySelector(".recharts-responsive-container")).toBeTruthy(),
    );
    expect(screen.getByText("Trend across runs")).toBeInTheDocument();
  });

  it("sets aria-busy=false once loading settles", async () => {
    installFetch();
    const { container } = render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await waitFor(() =>
      expect(container.querySelector('[aria-busy="false"]')).toBeTruthy(),
    );
  });
});

describe("RedesignApp — empty & null states", () => {
  it("no brands: never auto-selects, leaves engine disabled, fires no metrics", async () => {
    const { calls } = installFetch({ brands: () => jsonResponse([]) });
    render(<RedesignApp />);
    await waitFor(() => expect(callsTo(calls, "/api/brands").length).toBe(1));
    await new Promise((r) => setTimeout(r, 0));
    expect(callsTo(calls, "/api/engines").length).toBe(0);
    expect(callsTo(calls, "/api/metrics").length).toBe(0);
    const engineSelect = screen.getByLabelText("Engine") as HTMLSelectElement;
    expect(engineSelect).toBeDisabled();
    expect(screen.getByText("open-geo dashboard")).toBeInTheDocument();
  });

  it("brand resolves but it has no engines: loadAll bails, empty tables shown", async () => {
    const { calls } = installFetch({ engines: () => jsonResponse([]) });
    render(<RedesignApp />);
    await waitFor(() => expect(callsTo(calls, "/api/engines").length).toBe(1));
    await new Promise((r) => setTimeout(r, 0));
    expect(callsTo(calls, "/api/runs").length).toBe(0);
    expect(callsTo(calls, "/api/metrics").length).toBe(0);
    expect(screen.getAllByText("No metrics for the selected run.")).toHaveLength(2);
    expect(
      screen.getByText("No result rows for the selected run / lens."),
    ).toBeInTheDocument();
  });

  it("metrics with run=null and empty metrics array: run_context_empty + dash KPIs", async () => {
    installFetch({
      metrics: () =>
        jsonResponse(makeMetrics({ run: null, prev_run: null, metrics: [] })),
    });
    render(<RedesignApp />);
    await waitFor(() =>
      expect(
        screen.getByText("No data for the selected brand / engine."),
      ).toBeInTheDocument(),
    );
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(5);
  });

  it("metrics.run present but no prev_run: run line shown without the compare clause", async () => {
    installFetch({
      metrics: () => jsonResponse(makeMetrics({ prev_run: null })),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    expect(screen.queryByText(/compared with/)).not.toBeInTheDocument();
  });

  it("empty timeseries points in whole-period view -> chart empty-state copy", async () => {
    const user = userEvent.setup();
    installFetch({ timeseries: () => jsonResponse(makeTimeseries([])) });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Whole period" }));
    await waitFor(() =>
      expect(screen.getByText("No completed runs to plot a trend.")).toBeInTheDocument(),
    );
  });

  it("runId resolution: metrics.run null but a 'done' run exists -> results fetched for that run", async () => {
    let resultsRunId: string | null = null;
    installFetch({
      metrics: () => jsonResponse(makeMetrics({ run: null, metrics: [] })),
      results: (runId) => {
        resultsRunId = runId;
        return jsonResponse(makeResults());
      },
    });
    render(<RedesignApp />);
    await waitFor(() => expect(resultsRunId).toBe("42"));
  });

  it("runId resolution: no metrics.run and no 'done' run -> falls back to runs[0], still fetches", async () => {
    const onlyRunning: Run[] = [{ ...RUNS[1], run_id: 77 }];
    let resultsRunId: string | null = null;
    installFetch({
      metrics: () => jsonResponse(makeMetrics({ run: null, metrics: [] })),
      runs: () => jsonResponse(onlyRunning),
      results: (runId) => {
        resultsRunId = runId;
        return jsonResponse(makeResults());
      },
    });
    render(<RedesignApp />);
    await waitFor(() => expect(resultsRunId).toBe("77"));
  });

  it("runId resolution: no metrics.run and an EMPTY runs array -> results=null, empty results copy", async () => {
    const { calls } = installFetch({
      metrics: () => jsonResponse(makeMetrics({ run: null, metrics: [] })),
      runs: () => jsonResponse([]),
    });
    const { container } = render(<RedesignApp />);
    await waitFor(() =>
      expect(
        screen.getByText("No data for the selected brand / engine."),
      ).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(container.querySelector('[aria-busy="false"]')).toBeTruthy(),
    );
    expect(
      screen.getByText("No result rows for the selected run / lens."),
    ).toBeInTheDocument();
    expect(callsTo(calls, "/api/results").length).toBe(0);
  });
});

describe("RedesignApp — error states", () => {
  it("brands fetch non-ok -> error alert (brands().catch)", async () => {
    installFetch({
      brands: () => jsonResponse({ detail: "boom" }, { status: 500 }),
    });
    render(<RedesignApp />);
    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent(/500/);
    });
  });

  it("engines fetch non-ok -> error alert (engines().catch)", async () => {
    installFetch({
      engines: () => jsonResponse({ detail: "no engines" }, { status: 503 }),
    });
    render(<RedesignApp />);
    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent(/503/);
    });
  });

  it("loadAll Promise.all rejection (metrics 500) -> error alert and loading cleared", async () => {
    installFetch({
      metrics: () => jsonResponse({ detail: "metrics down" }, { status: 500 }),
    });
    const { container } = render(<RedesignApp />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/500/));
    await waitFor(() =>
      expect(container.querySelector('[aria-busy="false"]')).toBeTruthy(),
    );
  });

  it("results fetch rejects after metrics succeed -> error alert", async () => {
    installFetch({
      results: () => jsonResponse({ detail: "results gone" }, { status: 404 }),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/404/));
  });

  it("a fetch that rejects at the network layer surfaces via String(e)", async () => {
    installFetch({
      brands: () => Promise.reject(new Error("network exploded")),
    });
    render(<RedesignApp />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/network exploded/),
    );
  });
});

describe("RedesignApp — controls re-fetch", () => {
  it("switching the brand reloads engines for the new brand", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch();
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    const enginesBefore = callsTo(calls, "/api/engines").length;
    const brandSelect = screen.getByLabelText("Brand") as HTMLSelectElement;
    await user.selectOptions(brandSelect, "2");

    await waitFor(() =>
      expect(callsTo(calls, "/api/engines").length).toBeGreaterThan(enginesBefore),
    );
    const lastEngines = callsTo(calls, "/api/engines").at(-1)!;
    expect(new URL(lastEngines.url, "http://localhost").searchParams.get("brand_id")).toBe(
      "2",
    );
  });

  it("switching the engine triggers a fresh loadAll for that engine", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch();
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    const metricsBefore = callsTo(calls, "/api/metrics").length;
    const engineSelect = screen.getByLabelText("Engine") as HTMLSelectElement;
    await user.selectOptions(engineSelect, "perplexity");

    await waitFor(() =>
      expect(callsTo(calls, "/api/metrics").length).toBeGreaterThan(metricsBefore),
    );
    const lastMetrics = callsTo(calls, "/api/metrics").at(-1)!;
    expect(new URL(lastMetrics.url, "http://localhost").searchParams.get("engine")).toBe(
      "perplexity",
    );
  });

  it("switching period to 'all' re-fetches metrics with period=all and shows the whole-period line", async () => {
    const user = userEvent.setup();
    const { calls } = installFetch({
      metrics: (period) =>
        jsonResponse(
          makeMetrics({
            period: period as "today" | "all",
            run: period === "all" ? null : makeMetrics().run,
            n_runs: 7,
          }),
        ),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    const allBtn = screen.getByRole("button", { name: "Whole period" });
    await user.click(allBtn);

    await waitFor(() =>
      expect(screen.getByText(/Whole-period summary · completed runs: 7/)).toBeInTheDocument(),
    );
    const lastMetrics = callsTo(calls, "/api/metrics").at(-1)!;
    expect(new URL(lastMetrics.url, "http://localhost").searchParams.get("period")).toBe(
      "all",
    );
    expect(allBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("run_context_all uses the em-dash when n_runs is absent (period=all, undefined n_runs)", async () => {
    const user = userEvent.setup();
    installFetch({
      metrics: (period) =>
        jsonResponse(
          makeMetrics({
            period: period as "today" | "all",
            run: period === "all" ? null : makeMetrics().run,
            n_runs: period === "all" ? undefined : 5,
          }),
        ),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Whole period" }));
    await waitFor(() =>
      expect(
        screen.getByText(/Whole-period summary · completed runs: —/),
      ).toBeInTheDocument(),
    );
  });

  it("switching the lens re-fetches timeseries + results scoped to that lens (lens passed through)", async () => {
    const user = userEvent.setup();
    let lastResultsLens: string | null = "UNSET";
    let lastTsLens = "UNSET";
    const { calls } = installFetch({
      timeseries: (lens) => {
        lastTsLens = lens;
        return jsonResponse(makeTimeseries([tsPoint(42)]));
      },
      results: (_runId, lens) => {
        lastResultsLens = lens;
        return jsonResponse(makeResults());
      },
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    const tsBefore = callsTo(calls, "/api/timeseries").length;
    const lensSelect = screen.getByLabelText("Lens") as HTMLSelectElement;
    await user.selectOptions(lensSelect, "branded");

    await waitFor(() =>
      expect(callsTo(calls, "/api/timeseries").length).toBeGreaterThan(tsBefore),
    );
    await waitFor(() => expect(lastTsLens).toBe("branded"));
    await waitFor(() => expect(lastResultsLens).toBe("branded"));
  });

  it("default lens 'all' omits the lens query-param on results (lens === 'all' -> undefined)", async () => {
    let lastResultsLens: string | null = "UNSET";
    installFetch({
      results: (_runId, lens) => {
        lastResultsLens = lens;
        return jsonResponse(makeResults());
      },
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await waitFor(() => expect(lastResultsLens).toBeNull());
  });
});

describe("RedesignApp — theme & language", () => {
  it("theme toggle flips the <html> dark class and persists to localStorage", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    expect(document.documentElement.classList.contains("dark")).toBe(false);
    const toggle = screen.getByRole("button", { name: "Switch to dark theme" });
    await user.click(toggle);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("og-theme")).toBe("dark");
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
  });

  it("language switcher lists locales from /api/i18n and persists the choice", async () => {
    const user = userEvent.setup();
    installFetch();
    render(<RedesignApp />);
    const langSelect = await screen.findByLabelText("Language");
    await waitFor(() =>
      expect(within(langSelect).getByRole("option", { name: "Русский" })).toBeInTheDocument(),
    );
    await user.selectOptions(langSelect, "ru");
    await waitFor(() => expect(localStorage.getItem("og-lang")).toBe("ru"));
    await waitFor(() =>
      expect(document.documentElement.getAttribute("lang")).toBe("ru"),
    );
  });

  it("honours a persisted dark theme from localStorage on mount", async () => {
    localStorage.setItem("og-theme", "dark");
    installFetch();
    render(<RedesignApp />);
    await waitFor(() =>
      expect(document.documentElement.classList.contains("dark")).toBe(true),
    );
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
  });
});

describe("RedesignApp — PDF export", () => {
  it("is disabled until a brand + engine are selected, then enabled", async () => {
    installFetch({ brands: () => jsonResponse([]) });
    render(<RedesignApp />);
    const btn = screen.getByRole("button", { name: /Download PDF/i });
    expect(btn).toBeDisabled();
  });

  it("successful export POSTs to /api/report and triggers an anchor download", async () => {
    const user = userEvent.setup();

    const { createObjectURL, revokeObjectURL } = stubObjectURL();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    const { calls } = installFetch();
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    const btn = screen.getByRole("button", { name: /Download PDF/i });
    await user.click(btn);

    await waitFor(() => expect(callsTo(calls, "/api/report").length).toBe(1));
    const reportCall = callsTo(calls, "/api/report")[0];
    expect(reportCall.method).toBe("POST");
    const rp = new URL(reportCall.url, "http://localhost").searchParams;
    expect(rp.get("brand_id")).toBe("1");
    expect(rp.get("engine")).toBe("google");
    expect(rp.get("period")).toBe("today");
    expect(rp.get("lang")).toBe("en");

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    clickSpy.mockRestore();
  });

  it("H4: export sends the currently-selected UI locale (switch to ru -> lang=ru)", async () => {
    const user = userEvent.setup();
    stubObjectURL();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    const { calls } = installFetch();
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    const langSelect = await screen.findByLabelText("Language");
    await user.selectOptions(langSelect, "ru");
    await waitFor(() => expect(localStorage.getItem("og-lang")).toBe("ru"));

    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await waitFor(() => expect(callsTo(calls, "/api/report").length).toBe(1));
    const rp = new URL(callsTo(calls, "/api/report")[0].url, "http://localhost")
      .searchParams;
    expect(rp.get("lang")).toBe("ru");

    clickSpy.mockRestore();
  });

  it("names the downloaded file with the current brand's domain + period", async () => {
    const user = userEvent.setup();
    stubObjectURL();

    let downloadName = "";
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloadName = this.download;
      });

    installFetch();
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));

    await waitFor(() => expect(downloadName).toBe("open-geo_example.com_today.pdf"));
    clickSpy.mockRestore();
  });

  it("report non-ok with JSON {message, command} renders both in the error alert", async () => {
    const user = userEvent.setup();
    installFetch({
      report: () =>
        jsonResponse(
          { message: "report.generate not ready", command: "python -m report.generate ..." },
          { status: 503 },
        ),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("report.generate not ready");
      expect(alert).toHaveTextContent("CLI command:");
      expect(alert).toHaveTextContent("python -m report.generate ...");
    });
  });

  it("report non-ok with JSON body but NO message falls back to the localized status error", async () => {
    const user = userEvent.setup();
    installFetch({
      report: () => jsonResponse({ something: "else" }, { status: 500 }),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Report error (500)"),
    );
  });

  it("report non-ok with a NON-JSON body uses the status fallback (json() throws, caught)", async () => {
    const user = userEvent.setup();
    installFetch({
      report: () =>
        new Response("plain text error", {
          status: 502,
          headers: { "Content-Type": "text/plain" },
        }),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Report error (502)"),
    );
  });

  it("report fetch rejecting at the network layer surfaces via String(e) (downloadPdf catch)", async () => {
    const user = userEvent.setup();
    installFetch({
      report: () => Promise.reject(new Error("report network down")),
    });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("report network down"),
    );
  });

  it("shows the busy label on the export button while the report request is in flight", async () => {
    const user = userEvent.setup();
    let resolveReport!: (r: Response) => void;
    const pending = new Promise<Response>((res) => {
      resolveReport = res;
    });
    installFetch({ report: () => pending });
    render(<RedesignApp />);
    await waitFor(() => expect(screen.getByText(/Run #42/)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /Download PDF/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Preparing PDF/i })).toBeDisabled(),
    );

    stubObjectURL();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    resolveReport(pdfResponse());
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Download PDF/i })).toBeEnabled(),
    );
    clickSpy.mockRestore();
  });
});
