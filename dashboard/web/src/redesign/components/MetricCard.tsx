import type { ReactNode } from "react";
import { spreadOf, type MetricDef } from "../lib/metrics";
import type { MetricRow } from "../lib/api";
import { delta as fmtDelta, num, pct } from "../lib/format";
import { useT } from "../lib/i18n";
import { InfoTip, Skeleton } from "./primitives";
import { ArrowDownIcon, ArrowUpIcon, MinusIcon } from "./icons";

const STRIP_LENSES = ["general", "branded", "comparative"] as const;

export function MetricCard({
  def,
  row,
  loading,
  lensRows,
  activeLens,
  repeats,
}: {
  def: MetricDef;
  row: MetricRow | null;
  loading?: boolean;
  lensRows?: MetricRow[];
  activeLens?: string;
  repeats?: number;
}) {
  const t = useT();
  const dash = t("common.dash");
  const raw = row ? def.value(row) : null;
  const valueStr = def.asPct ? pct(raw, dash) : num(raw, 2, dash);
  const d = row ? def.delta(row) : null;
  const sub = row
    ? def.subRender
      ? def.subRender(row, t)
      : t(def.subKey, def.subVars ? def.subVars(row) : undefined)
    : " ";

  let badge: ReactNode = null;
  const spread = row && repeats && repeats > 1 ? spreadOf(def, row) : null;
  if (spread) {
    const fmtOne = (v: number) =>
      def.asPct ? `${(v * 100).toFixed(1)}` : v.toFixed(2);
    const spreadStr = def.asPct
      ? `${fmtOne(spread.min)}–${fmtOne(spread.max)}%`
      : `${fmtOne(spread.min)}–${fmtOne(spread.max)}`;
    badge = (
      <span
        className="inline-flex items-center gap-0.5 rounded-md bg-[var(--surface-2)] px-1.5 py-0.5 text-xs font-medium text-[var(--muted)]"
        title={t("dashboard.spread_title", { n: repeats ?? 0 })}
      >
        {spreadStr}
      </span>
    );
  } else if (d !== null && d !== undefined) {
    const flat = Math.abs(d) < 1e-9;
    const improved = def.higherIsBetter ? d > 0 : d < 0;
    const color = flat
      ? "text-[var(--muted)]"
      : improved
        ? "text-[var(--good)]"
        : "text-[var(--bad)]";
    const Icon = flat ? MinusIcon : d > 0 ? ArrowUpIcon : ArrowDownIcon;
    badge = (
      <span
        className={`inline-flex items-center gap-0.5 rounded-md bg-[var(--surface-2)] px-1.5 py-0.5 text-xs font-medium ${color}`}
        title={t("dashboard.delta_title")}
      >
        <Icon size={13} /> {fmtDelta(d, def.asPct, t("common.pp"))}
      </span>
    );
  }

  const strip = (lensRows ?? []).filter((r) =>
    (STRIP_LENSES as readonly string[]).includes(String(r.lens)),
  );

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 transition-colors hover:border-[var(--border-strong)]">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs uppercase tracking-wide text-[var(--muted)]">
          {t(def.labelKey)}
        </span>
        <InfoTip text={t(def.infoKey)} />
      </div>
      {loading && !row ? (
        <Skeleton className="h-8 w-24" />
      ) : (
        <div className="flex items-end justify-between gap-2">
          <span className="text-2xl font-semibold tabular-nums text-[var(--fg)]">
            {valueStr}
          </span>
          {badge}
        </div>
      )}
      <span className="text-[11px] text-[var(--faint)]">{sub}</span>
      {strip.length > 1 && (
        <div
          role="list"
          aria-label={t("dashboard.card_lens_strip_label")}
          className="flex flex-wrap gap-x-3 gap-y-0.5 border-t border-[var(--border)] pt-1.5 text-[11px] tabular-nums"
        >
          {strip.map((r) => {
            const v = def.value(r);
            const s = def.asPct ? pct(v, dash) : num(v, 1, dash);
            const active = r.lens === activeLens;
            return (
              <span
                role="listitem"
                key={r.lens}
                title={t(`lens.${r.lens}`)}
                className={
                  active
                    ? "font-medium text-[var(--fg)]"
                    : "text-[var(--faint)]"
                }
              >
                {t(`lens.short_${r.lens}`)} {s}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}
