import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TimeseriesPoint } from "../lib/api";
import { fmtDateShort } from "../lib/format";
import { useT } from "../lib/i18n";

type Row = {
  label: string;
  overview_coverage: number | null;
  visibility_in_sources: number | null;
  visibility_in_citations: number | null;
  brand_mention_rate: number | null;
  avg_source_position: number | null;
  avg_citation_position: number | null;
};

const POSITION_KEYS = new Set(["avg_source_position", "avg_citation_position"]);

const LINES: {
  dataKey: string;
  yAxisId: "pct" | "pos";
  nameKey: string;
  stroke: string;
  dashed?: boolean;
}[] = [
  {
    dataKey: "overview_coverage",
    yAxisId: "pct",
    nameKey: "dashboard.chart_series_coverage",
    stroke: "var(--c-coverage)",
  },
  {
    dataKey: "visibility_in_sources",
    yAxisId: "pct",
    nameKey: "dashboard.chart_series_visibility_sources",
    stroke: "var(--c-vis-src)",
  },
  {
    dataKey: "visibility_in_citations",
    yAxisId: "pct",
    nameKey: "dashboard.chart_series_visibility_citations",
    stroke: "var(--c-vis-cit)",
  },
  {
    dataKey: "brand_mention_rate",
    yAxisId: "pct",
    nameKey: "dashboard.chart_series_mention_rate",
    stroke: "var(--c-mention)",
  },
  {
    dataKey: "avg_source_position",
    yAxisId: "pos",
    nameKey: "dashboard.chart_series_position_sources",
    stroke: "var(--c-pos-src)",
    dashed: true,
  },
  {
    dataKey: "avg_citation_position",
    yAxisId: "pos",
    nameKey: "dashboard.chart_series_position_citations",
    stroke: "var(--c-pos-cit)",
    dashed: true,
  },
];

const toPct = (v: number | null | undefined): number | null =>
  v === null || v === undefined ? null : +(v * 100).toFixed(1);

const toRaw = (v: number | null | undefined): number | null =>
  v === null || v === undefined ? null : v;

export function MetricsChart({ points }: { points: TimeseriesPoint[] }) {
  const t = useT();

  if (points.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-[var(--muted)]">
        {t("dashboard.chart_empty")}
      </div>
    );
  }

  const data: Row[] = points.map((p) => ({
    label: p.week ?? fmtDateShort(p.run_at),
    overview_coverage: toPct(p.overview_coverage),
    visibility_in_sources: toPct(p.visibility_in_sources),
    visibility_in_citations: toPct(p.visibility_in_citations),
    brand_mention_rate: toPct(p.brand_mention_rate),
    avg_source_position: toRaw(p.avg_source_position),
    avg_citation_position: toRaw(p.avg_citation_position),
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis
          dataKey="label"
          stroke="var(--muted)"
          tick={{ fill: "var(--muted)", fontSize: 12 }}
          fontSize={12}
          tickMargin={8}
        />
        <YAxis
          yAxisId="pct"
          domain={[0, 100]}
          tickFormatter={(v) => `${v}%`}
          width={48}
          stroke="var(--muted)"
          tick={{ fill: "var(--muted)", fontSize: 12 }}
          fontSize={12}
        />
        <YAxis
          yAxisId="pos"
          orientation="right"
          stroke="var(--muted)"
          tick={{ fill: "var(--muted)", fontSize: 12 }}
          fontSize={12}
          width={34}
          allowDecimals
        />
        <Tooltip
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            color: "var(--fg)",
          }}
          labelStyle={{ color: "var(--muted)" }}
          formatter={(value, name, item) => {
            const v = value ?? t("common.dash");
            const key = (item?.dataKey as string) ?? "";
            if (POSITION_KEYS.has(key)) return [v, name];
            return [`${v}%`, name];
          }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {LINES.map((l) => (
          <Line
            key={l.dataKey}
            yAxisId={l.yAxisId}
            type="monotone"
            dataKey={l.dataKey}
            name={t(l.nameKey)}
            stroke={l.stroke}
            strokeWidth={2}
            strokeDasharray={l.dashed ? "5 3" : undefined}
            dot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
