
import { render } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";
import { I18nProvider } from "../lib/i18n";
import { fmtDateShort } from "../lib/format";
import type { TimeseriesPoint } from "../lib/api";

type AnyProps = Record<string, unknown>;
const captured: {
  lineChart?: AnyProps;
  tooltip?: AnyProps;
  yAxes: AnyProps[];
  lines: AnyProps[];
  xAxis?: AnyProps;
} = { yAxes: [], lines: [] };

vi.mock("recharts", () => {
  const passthrough =
    (name: string) =>
    ({ children }: { children?: React.ReactNode }) => (
      <div data-recharts={name}>{children}</div>
    );
  return {
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
      <div data-recharts="ResponsiveContainer">{children}</div>
    ),
    LineChart: ({
      children,
      ...rest
    }: { children?: React.ReactNode } & AnyProps) => {
      captured.lineChart = rest;
      return <div data-recharts="LineChart">{children}</div>;
    },
    Tooltip: (props: AnyProps) => {
      captured.tooltip = props;
      return <div data-recharts="Tooltip" />;
    },
    YAxis: (props: AnyProps) => {
      captured.yAxes.push(props);
      return <div data-recharts="YAxis" />;
    },
    Line: (props: AnyProps) => {
      captured.lines.push(props);
      return <div data-recharts="Line" />;
    },
    XAxis: (props: AnyProps) => {
      captured.xAxis = props;
      return <div data-recharts="XAxis" />;
    },
    CartesianGrid: passthrough("CartesianGrid"),
    Legend: passthrough("Legend"),
  };
});

import { MetricsChart } from "./MetricsChart";

function renderChart(points: TimeseriesPoint[]) {
  return render(
    <I18nProvider>
      <MetricsChart points={points} />
    </I18nProvider>,
  );
}

function fullPoint(over: Partial<TimeseriesPoint> = {}): TimeseriesPoint {
  return {
    run_id: 1,
    run_at: "2026-06-18T20:15:00Z",
    status: "completed",
    lens: "all",
    n_queries: 40,
    n_overviews: 30,
    overview_coverage: 0.75,
    visibility_in_sources: 0.5,
    visibility_in_citations: 0.333,
    avg_source_position: 2.4,
    avg_citation_position: 1.8,
    ...over,
  };
}

type FormatterFn = (
  value: unknown,
  name: unknown,
  item?: { dataKey?: unknown },
) => [unknown, unknown];

describe("MetricsChart (data mapping & formatter)", () => {
  beforeEach(() => {
    captured.lineChart = undefined;
    captured.tooltip = undefined;
    captured.xAxis = undefined;
    captured.yAxes = [];
    captured.lines = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => [],
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("does not render any chart parts for an empty points array", () => {
    renderChart([]);
    expect(captured.lineChart).toBeUndefined();
    expect(captured.tooltip).toBeUndefined();
    expect(captured.yAxes).toHaveLength(0);
    expect(captured.lines).toHaveLength(0);
  });

  it("scales percentage metrics to 0..100 and keeps position metrics raw", () => {
    renderChart([fullPoint()]);
    const data = captured.lineChart?.data as Array<Record<string, unknown>>;
    expect(Array.isArray(data)).toBe(true);
    expect(data).toHaveLength(1);
    const row = data[0];
    expect(row.overview_coverage).toBe(75);
    expect(row.visibility_in_sources).toBe(50);
    expect(row.visibility_in_citations).toBe(33.3);
    expect(row.avg_source_position).toBe(2.4);
    expect(row.avg_citation_position).toBe(1.8);
    expect(row.label).toBe(fmtDateShort("2026-06-18T20:15:00Z"));
    expect(row.label).toMatch(/^\d{2}\/\d{2}$/);
  });

  it("maps null percentage and null position values to null (gaps preserved)", () => {
    renderChart([
      fullPoint({
        overview_coverage: null,
        visibility_in_sources: null,
        visibility_in_citations: null,
        avg_source_position: null,
        avg_citation_position: null,
      }),
    ]);
    const row = (captured.lineChart?.data as Array<Record<string, unknown>>)[0];
    expect(row.overview_coverage).toBeNull();
    expect(row.visibility_in_sources).toBeNull();
    expect(row.visibility_in_citations).toBeNull();
    expect(row.avg_source_position).toBeNull();
    expect(row.avg_citation_position).toBeNull();
  });

  it("maps undefined values to null as well (server omitted fields)", () => {
    const partial: TimeseriesPoint = {
      run_id: 9,
      run_at: "2026-06-19T00:00:00Z",
      status: "completed",
      lens: "general",
      n_queries: 5,
      n_overviews: 2,
      overview_coverage: undefined,
      visibility_in_sources: undefined,
      visibility_in_citations: undefined,
      avg_source_position: undefined,
      avg_citation_position: undefined,
    };
    renderChart([partial]);
    const row = (captured.lineChart?.data as Array<Record<string, unknown>>)[0];
    expect(row.overview_coverage).toBeNull();
    expect(row.visibility_in_sources).toBeNull();
    expect(row.visibility_in_citations).toBeNull();
    expect(row.avg_source_position).toBeNull();
    expect(row.avg_citation_position).toBeNull();
  });

  it("builds one data row per point, preserving order", () => {
    renderChart([
      fullPoint({ run_id: 1, run_at: "2026-06-16T10:00:00Z", overview_coverage: 0.1 }),
      fullPoint({ run_id: 2, run_at: "2026-06-17T10:00:00Z", overview_coverage: 0.2 }),
      fullPoint({ run_id: 3, run_at: "2026-06-18T10:00:00Z", overview_coverage: 0.3 }),
    ]);
    const data = captured.lineChart?.data as Array<Record<string, unknown>>;
    expect(data.map((r) => r.overview_coverage)).toEqual([10, 20, 30]);
  });

  it("wires two Y axes (percentage left, position right) and six lines", () => {
    renderChart([fullPoint()]);
    expect(captured.yAxes).toHaveLength(2);
    const pctAxis = captured.yAxes.find((a) => a.yAxisId === "pct");
    const posAxis = captured.yAxes.find((a) => a.yAxisId === "pos");
    expect(pctAxis?.domain).toEqual([0, 100]);
    expect(posAxis?.orientation).toBe("right");

    const tickFormatter = pctAxis?.tickFormatter as (v: number) => string;
    expect(typeof tickFormatter).toBe("function");
    expect(tickFormatter(0)).toBe("0%");
    expect(tickFormatter(50)).toBe("50%");
    expect(tickFormatter(100)).toBe("100%");

    expect(captured.lines).toHaveLength(6);
    const pctLines = captured.lines.filter((l) => l.yAxisId === "pct");
    const posLines = captured.lines.filter((l) => l.yAxisId === "pos");
    expect(pctLines.map((l) => l.dataKey)).toEqual([
      "overview_coverage",
      "visibility_in_sources",
      "visibility_in_citations",
      "brand_mention_rate",
    ]);
    expect(posLines.map((l) => l.dataKey)).toEqual([
      "avg_source_position",
      "avg_citation_position",
    ]);
    expect(captured.lines.every((l) => l.connectNulls === true)).toBe(true);
  });

  it("labels each line with the English i18n series name", () => {
    renderChart([fullPoint()]);
    const byKey = Object.fromEntries(
      captured.lines.map((l) => [l.dataKey as string, l.name]),
    );
    expect(byKey.overview_coverage).toBe("Answer coverage");
    expect(byKey.visibility_in_sources).toBe("Visibility in sources");
    expect(byKey.visibility_in_citations).toBe("Visibility in citations");
    expect(byKey.brand_mention_rate).toBe("Brand mentioned");
    expect(byKey.avg_source_position).toBe("Avg. source position");
    expect(byKey.avg_citation_position).toBe("Avg. citation position");
  });

  describe("Tooltip formatter branches", () => {
    function getFormatter(): FormatterFn {
      renderChart([fullPoint()]);
      const fmt = captured.tooltip?.formatter as FormatterFn | undefined;
      expect(typeof fmt).toBe("function");
      return fmt as FormatterFn;
    }

    it("formats a percentage series value with a % suffix", () => {
      const fmt = getFormatter();
      const out = fmt(75, "Answer coverage", {
        dataKey: "overview_coverage",
      });
      expect(out).toEqual(["75%", "Answer coverage"]);
    });

    it("formats a position series value raw (no % suffix)", () => {
      const fmt = getFormatter();
      const out = fmt(2.4, "Avg. source position", {
        dataKey: "avg_source_position",
      });
      expect(out).toEqual([2.4, "Avg. source position"]);
      const out2 = fmt(1.8, "Avg. citation position", {
        dataKey: "avg_citation_position",
      });
      expect(out2).toEqual([1.8, "Avg. citation position"]);
    });

    it("substitutes the em-dash for a null value on a percentage series", () => {
      const fmt = getFormatter();
      const out = fmt(null, "Visibility in sources", {
        dataKey: "visibility_in_sources",
      });
      expect(out).toEqual(["—%", "Visibility in sources"]);
    });

    it("substitutes the em-dash for an undefined value on a position series", () => {
      const fmt = getFormatter();
      const out = fmt(undefined, "Avg. source position", {
        dataKey: "avg_source_position",
      });
      expect(out).toEqual(["—", "Avg. source position"]);
    });

    it("falls back to an empty key (percentage branch) when item is undefined", () => {
      const fmt = getFormatter();
      const out = fmt(42, "Something", undefined);
      expect(out).toEqual(["42%", "Something"]);
    });

    it("falls back to an empty key when item has no dataKey", () => {
      const fmt = getFormatter();
      const out = fmt(0, "Zero", {});
      expect(out).toEqual(["0%", "Zero"]);
    });
  });

  it("passes a non-empty data array reference into LineChart for one point", () => {
    renderChart([fullPoint()]);
    expect((globalThis.fetch as Mock).mock.calls.length).toBeGreaterThan(0);
    expect((captured.lineChart?.data as unknown[]).length).toBe(1);
  });
});

describe("weekly bucket points", () => {
  it("labels a point by its ISO week when the week field is present", () => {
    renderChart([
      fullPoint({ run_id: null, week: "2026-W28" }),
      fullPoint({ run_id: 2, week: null }),
    ]);
    const data = captured.lineChart?.data as Array<Record<string, unknown>>;
    expect(data[0].label).toBe("2026-W28");
    expect(data[1].label).not.toBe("2026-W28");
  });
});
