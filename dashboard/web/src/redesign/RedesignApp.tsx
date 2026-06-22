import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type Brand,
  type CompetitorsResponse,
  type MetricRow,
  type MetricsResponse,
  type ResultsResponse,
  type TimeseriesResponse,
} from "./lib/api";
import { ThemeProvider } from "./lib/theme";
import { I18nProvider, useI18n } from "./lib/i18n";
import { fmtDateTime } from "./lib/format";
import { METRICS } from "./lib/metrics";
import { MetricCard } from "./components/MetricCard";
import {
  FieldSelect,
  LanguageSwitcher,
  Panel,
  Segmented,
  ThemeToggle,
} from "./components/primitives";
import { MetricsChart } from "./components/MetricsChart";
import { LensBreakdown } from "./components/LensBreakdown";
import { LensSentiment } from "./components/LensSentiment";
import { CompetitorsPanel } from "./components/CompetitorsPanel";
import { ResultsTable } from "./components/ResultsTable";
import { ChevronDownIcon, DownloadIcon } from "./components/icons";

const LENSES = ["all", "general", "branded", "comparative"] as const;

function Dashboard() {
  const { t, lang } = useI18n();

  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandId, setBrandId] = useState<number | "">("");
  const [engines, setEngines] = useState<string[]>([]);
  const [engine, setEngine] = useState<string>("");
  const [period, setPeriod] = useState<"today" | "all">("today");
  const [lens, setLens] = useState<string>("all");

  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [timeseries, setTimeseries] = useState<TimeseriesResponse | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorsResponse | null>(null);
  const [results, setResults] = useState<ResultsResponse | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [resultsExpanded, setResultsExpanded] = useState(false);

  useEffect(() => {
    api
      .brands()
      .then((b) => {
        setBrands(b);
        if (b.length > 0) setBrandId(b[0].id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (brandId === "") return;
    setEngine("");
    api
      .engines(brandId)
      .then((es) => {
        setEngines(es);
        if (es.length > 0) setEngine(es[0]);
      })
      .catch((e) => setError(String(e)));
  }, [brandId]);

  const loadAll = useCallback(async () => {
    if (brandId === "" || !engine) return;
    setLoading(true);
    setError(null);
    try {
      const [r, m, ts, comp] = await Promise.all([
        api.runs(brandId, engine),
        api.metrics(brandId, engine, period),
        api.timeseries(brandId, engine, lens),
        api.competitors(brandId, engine, period, lens),
      ]);
      setMetrics(m);
      setTimeseries(ts);
      setCompetitors(comp);

      const runId =
        m.run?.run_id ?? r.find((x) => x.status === "done")?.run_id ?? r[0]?.run_id;
      if (runId != null) {
        const res = await api.results(runId, lens === "all" ? undefined : lens);
        setResults(res);
      } else {
        setResults(null);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [brandId, engine, period, lens]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const allRow: MetricRow | null = useMemo(
    () => metrics?.metrics.find((m) => m.lens === "all") ?? null,
    [metrics],
  );

  const currentBrand = brands.find((b) => b.id === brandId);

  async function downloadPdf() {
    if (brandId === "" || !engine) return;
    setDownloading(true);
    setError(null);
    try {
      const res = await fetch(api.reportUrl(brandId, engine, period, lang), {
        method: "POST",
      });
      if (!res.ok) {
        let msg = t("dashboard.report_error", { status: res.status });
        try {
          const body = await res.json();
          msg = body.message ?? msg;
          if (body.command) msg += `\n\n${t("dashboard.report_cli_label")}\n${body.command}`;
        } catch {}
        setError(msg);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `open-geo_${currentBrand?.domain ?? "report"}_${period}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="mx-auto min-h-full max-w-7xl px-5 py-6" aria-busy={loading}>
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--fg)]">
            {t("common.app_title")}{" "}
            <span className="font-normal text-[var(--muted)]">
              / {t("common.app_subtitle")}
            </span>
          </h1>
          <p className="mt-0.5 text-sm text-[var(--muted)]">{t("common.app_tagline")}</p>
        </div>
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <ThemeToggle />
          <button
            onClick={downloadPdf}
            disabled={downloading || brandId === "" || !engine}
            className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-fg)] transition-opacity duration-200 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <DownloadIcon size={16} />{" "}
            {downloading ? t("common.download_pdf_busy") : t("common.download_pdf")}
          </button>
        </div>
      </header>

      <div className="mb-6 flex flex-wrap items-end gap-3">
        <FieldSelect
          label={t("dashboard.control_brand")}
          value={brandId}
          options={brands.map((b) => ({ value: b.id, label: `${b.name} (${b.domain})` }))}
          onChange={(v) => setBrandId(Number(v))}
        />
        <FieldSelect
          label={t("dashboard.control_engine")}
          value={engine}
          options={engines.map((e) => ({ value: e, label: e }))}
          onChange={setEngine}
          disabled={engines.length === 0}
        />
        <Segmented<"today" | "all">
          label={t("dashboard.control_period")}
          value={period}
          options={[
            { value: "today", label: t("period.today") },
            { value: "all", label: t("period.all") },
          ]}
          onChange={setPeriod}
        />
        <FieldSelect
          label={t("dashboard.control_lens")}
          value={lens}
          options={LENSES.map((l) => ({ value: l, label: t(`lens.${l}`) }))}
          onChange={setLens}
        />
      </div>

      {error && (
        <div
          role="alert"
          className="mb-6 whitespace-pre-wrap rounded-lg border border-[var(--bad)] bg-[var(--bad)]/10 px-4 py-3 text-sm text-[var(--bad)]"
        >
          {error}
        </div>
      )}

      {metrics && (
        <div className="mb-4 text-sm text-[var(--muted)]">
          {period === "all" ? (
            t("dashboard.run_context_all", { n: metrics.n_runs ?? t("common.dash") })
          ) : metrics.run ? (
            <>
              {t("dashboard.run_context_run", {
                id: metrics.run.run_id,
                datetime: fmtDateTime(metrics.run.run_at),
                status: t(`status.${metrics.run.status}`),
              })}
              {metrics.prev_run && (
                <>
                  {" · "}
                  {t("dashboard.run_context_compare", {
                    id: metrics.prev_run.run_id,
                    datetime: fmtDateTime(metrics.prev_run.run_at),
                  })}
                </>
              )}
            </>
          ) : (
            t("dashboard.run_context_empty")
          )}
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {METRICS.map((def) => (
          <MetricCard key={def.key} def={def} row={allRow} loading={loading} />
        ))}
      </div>

      {period === "all" && (
        <Panel
          title={t("dashboard.chart_title")}
          info={t("dashboard.chart_info")}
          className="mb-6"
          right={
            <span className="text-xs text-[var(--muted)]">
              {t("dashboard.chart_lens", { lens: t(`lens.${lens}`) })}
            </span>
          }
        >
          <MetricsChart points={timeseries?.points ?? []} />
        </Panel>
      )}

      <Panel
        title={t("dashboard.lens_panel_title")}
        info={t("dashboard.lens_panel_info")}
        className="mb-6"
      >
        <LensBreakdown rows={metrics?.metrics ?? []} />
      </Panel>

      <Panel
        title={t("dashboard.competitors_panel_title")}
        info={t("dashboard.competitors_panel_info")}
        className="mb-6"
        right={
          competitors && competitors.n_overviews > 0 ? (
            <span className="text-xs text-[var(--muted)]">
              {t("dashboard.competitors_meta", {
                n: competitors.domains.length,
                nov: competitors.n_overviews,
              })}
            </span>
          ) : undefined
        }
      >
        <CompetitorsPanel rows={competitors?.domains ?? []} />
      </Panel>

      <Panel
        title={t("dashboard.sentiment_panel_title")}
        info={t("dashboard.sentiment_panel_info")}
        className="mb-6"
      >
        <LensSentiment rows={metrics?.metrics ?? []} />
      </Panel>

      <Panel
        title={t("dashboard.results_title")}
        right={
          <div className="flex items-center gap-3">
            {results?.run && (
              <span className="text-xs text-[var(--muted)]">
                {t("dashboard.results_meta", {
                  id: results.run.run_id,
                  n: results.results.length,
                })}
              </span>
            )}
            {(results?.results.length ?? 0) > 0 && (
              <button
                type="button"
                aria-expanded={resultsExpanded}
                aria-controls="results-table-region"
                onClick={() => setResultsExpanded((v) => !v)}
                className="inline-flex min-h-[36px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 text-sm text-[var(--muted)] transition-colors hover:text-[var(--fg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
              >
                {resultsExpanded
                  ? t("dashboard.results_collapse")
                  : t("dashboard.results_expand")}
                <ChevronDownIcon
                  size={16}
                  className={`transition-transform ${resultsExpanded ? "rotate-180" : ""}`}
                />
              </button>
            )}
          </div>
        }
      >
        <div id="results-table-region">
          {(results?.results.length ?? 0) === 0 || resultsExpanded ? (
            <ResultsTable rows={results?.results ?? []} />
          ) : (
            <p className="text-sm text-[var(--muted)]">
              {t("dashboard.results_collapsed_hint", {
                n: results?.results.length ?? 0,
              })}
            </p>
          )}
        </div>
      </Panel>

      <footer className="mt-8 text-xs text-[var(--faint)]">
        {loading ? t("common.loading") : t("dashboard.footer")}
      </footer>
    </div>
  );
}

export default function RedesignApp() {
  return (
    <I18nProvider>
      <ThemeProvider>
        <Dashboard />
      </ThemeProvider>
    </I18nProvider>
  );
}
