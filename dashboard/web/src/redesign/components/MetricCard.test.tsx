
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { MetricCard } from "./MetricCard";
import { METRICS, type MetricDef } from "../lib/metrics";
import type { MetricRow } from "../lib/api";
import { I18nProvider } from "../lib/i18n";
import { ThemeProvider } from "../lib/theme";


const byKey = (k: MetricDef["key"]): MetricDef => {
  const def = METRICS.find((m) => m.key === k);
  if (!def) throw new Error(`metric def not found: ${k}`);
  return def;
};

const COVERAGE = byKey("overview_coverage");
const VIS_SOURCES = byKey("visibility_in_sources");
const AVG_SRC_POS = byKey("avg_source_position");

function makeRow(overrides: Partial<MetricRow> = {}): MetricRow {
  return {
    lens: "all",
    n_queries: 50,
    n_overviews: 40,
    overview_coverage: 0.8,
    n_in_sources: 30,
    visibility_in_sources: 0.75,
    n_cited: 20,
    visibility_in_citations: 0.5,
    avg_source_position: 3.5,
    avg_citation_position: 2.25,
    relative_citation: 0.6667,
    overview_coverage_delta: 0.1,
    visibility_in_sources_delta: 0.05,
    visibility_in_citations_delta: -0.02,
    avg_source_position_delta: -0.5,
    avg_citation_position_delta: 0.5,
    relative_citation_delta: 0.03,
    ...overrides,
  };
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <ThemeProvider>{children}</ThemeProvider>
    </I18nProvider>
  );
}

function renderCard(props: {
  def: MetricDef;
  row: MetricRow | null;
  loading?: boolean;
  lensRows?: MetricRow[];
  activeLens?: string;
  repeats?: number;
}) {
  return render(<MetricCard {...props} />, { wrapper: Providers });
}

function getBadge(): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    'span[title="vs. the previous completed run"]',
  );
}

const ARROW_UP_D = "m5 12 7-7 7 7";
const ARROW_DOWN_D = "m19 12-7 7-7-7";
const MINUS_D = "M5 12h14";

function badgeArrowD(badge: HTMLElement): string | null {
  const paths = Array.from(badge.querySelectorAll("path")).map((p) =>
    p.getAttribute("d"),
  );
  if (paths.includes(ARROW_UP_D)) return ARROW_UP_D;
  if (paths.includes(ARROW_DOWN_D)) return ARROW_DOWN_D;
  if (paths.includes(MINUS_D)) return MINUS_D;
  return null;
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      } as Response),
    ),
  );
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});


describe("MetricCard — label & info tooltip", () => {
  it("renders the localized metric label", () => {
    renderCard({ def: COVERAGE, row: makeRow() });
    expect(screen.getByText("Answer coverage")).toBeInTheDocument();
  });

  it("renders an (i) info trigger labelled for accessibility", () => {
    renderCard({ def: COVERAGE, row: makeRow() });
    const trigger = screen.getByRole("button", {
      name: "What this metric means",
    });
    expect(trigger).toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("reveals the metric hint on hover and hides it on unhover", async () => {
    const user = userEvent.setup();
    renderCard({ def: COVERAGE, row: makeRow() });
    const trigger = screen.getByRole("button", {
      name: "What this metric means",
    });

    await user.hover(trigger);
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent(/Share of queries where the engine rendered/);
    expect(trigger).toHaveAttribute("aria-describedby", tip.id);

    await user.unhover(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("reveals the metric hint on keyboard focus", async () => {
    const user = userEvent.setup();
    renderCard({ def: AVG_SRC_POS, row: makeRow() });
    await user.tab();
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent(/Lower is better/);
  });
});

describe("MetricCard — value formatting (asPct branch)", () => {
  it("formats a percentage value with one decimal when asPct is true", () => {
    renderCard({ def: COVERAGE, row: makeRow({ overview_coverage: 0.8 }) });
    expect(screen.getByText("80.0%")).toBeInTheDocument();
  });

  it("formats a plain number with two decimals when asPct is false", () => {
    renderCard({ def: AVG_SRC_POS, row: makeRow({ avg_source_position: 3.5 }) });
    expect(screen.getByText("3.50")).toBeInTheDocument();
  });

  it("shows the dash for a null percentage value", () => {
    renderCard({ def: COVERAGE, row: makeRow({ overview_coverage: null }) });
    const value = document.querySelector(".text-2xl");
    expect(value).toHaveTextContent("—");
  });

  it("shows the dash for a null plain-number value", () => {
    renderCard({
      def: AVG_SRC_POS,
      row: makeRow({ avg_source_position: null }),
    });
    const value = document.querySelector(".text-2xl");
    expect(value).toHaveTextContent("—");
  });

  it("shows the dash for an undefined value", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage: undefined }),
    });
    const value = document.querySelector(".text-2xl");
    expect(value).toHaveTextContent("—");
  });

  it("renders the dash (not a value) when row is null", () => {
    renderCard({ def: COVERAGE, row: null });
    const value = document.querySelector(".text-2xl");
    expect(value).toHaveTextContent("—");
  });
});

describe("MetricCard — delta chip: presence & null handling", () => {
  it("renders no badge when row is null", () => {
    renderCard({ def: COVERAGE, row: null });
    expect(getBadge()).toBeNull();
  });

  it("renders no badge when the delta is null", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: null }),
    });
    expect(getBadge()).toBeNull();
  });

  it("renders no badge when the delta is undefined", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: undefined }),
    });
    expect(getBadge()).toBeNull();
  });

  it("renders a badge when a non-null delta is present", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: 0.1 }),
    });
    expect(getBadge()).not.toBeNull();
  });
});

describe("MetricCard — delta chip: flat (zero) delta", () => {
  it("shows the muted color and a minus glyph for an exactly-zero delta", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: 0 }),
    });
    const badge = getBadge()!;
    expect(badge.className).toContain("text-[var(--muted)]");
    expect(badge.className).not.toContain("text-[var(--good)]");
    expect(badge.className).not.toContain("text-[var(--bad)]");
    expect(badgeArrowD(badge)).toBe(MINUS_D);
  });

  it("treats a sub-epsilon delta (|d| < 1e-9) as flat", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: 1e-12 }),
    });
    const badge = getBadge()!;
    expect(badge.className).toContain("text-[var(--muted)]");
    expect(badgeArrowD(badge)).toBe(MINUS_D);
  });

  it("formats a zero pct delta as +0.0 pp", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: 0 }),
    });
    expect(getBadge()!).toHaveTextContent("0.0 pp");
  });
});

describe("MetricCard — delta chip: higherIsBetter=true (rates)", () => {
  it("positive delta on a rate is GOOD with an up arrow", () => {
    renderCard({
      def: VIS_SOURCES,
      row: makeRow({ visibility_in_sources_delta: 0.05 }),
    });
    const badge = getBadge()!;
    expect(badge.className).toContain("text-[var(--good)]");
    expect(badgeArrowD(badge)).toBe(ARROW_UP_D);
    expect(badge).toHaveTextContent("+5.0 pp");
  });

  it("negative delta on a rate is BAD with a down arrow", () => {
    renderCard({
      def: VIS_SOURCES,
      row: makeRow({ visibility_in_sources_delta: -0.05 }),
    });
    const badge = getBadge()!;
    expect(badge.className).toContain("text-[var(--bad)]");
    expect(badgeArrowD(badge)).toBe(ARROW_DOWN_D);
    expect(badge).toHaveTextContent("-5.0 pp");
  });
});

describe("MetricCard — delta chip: higherIsBetter=false (avg positions)", () => {
  it("negative delta on an avg position is GOOD with a DOWN arrow", () => {
    renderCard({
      def: AVG_SRC_POS,
      row: makeRow({ avg_source_position_delta: -0.5 }),
    });
    const badge = getBadge()!;
    expect(badge.className).toContain("text-[var(--good)]");
    expect(badgeArrowD(badge)).toBe(ARROW_DOWN_D);
    expect(badge).toHaveTextContent("-0.50");
    expect(badge).not.toHaveTextContent("pp");
  });

  it("positive delta on an avg position is BAD with an UP arrow (worse number -> bad)", () => {
    renderCard({
      def: AVG_SRC_POS,
      row: makeRow({ avg_source_position_delta: 0.5 }),
    });
    const badge = getBadge()!;
    expect(badge.className).toContain("text-[var(--bad)]");
    expect(badgeArrowD(badge)).toBe(ARROW_UP_D);
    expect(badge).toHaveTextContent("+0.50");
  });

  it("carries the localized 'vs previous run' title on the chip", () => {
    renderCard({
      def: AVG_SRC_POS,
      row: makeRow({ avg_source_position_delta: 0.5 }),
    });
    expect(getBadge()).toHaveAttribute(
      "title",
      "vs. the previous completed run",
    );
  });
});

describe("MetricCard — sub-line", () => {
  it("renders counts via subVars for the coverage card", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ n_overviews: 40, n_queries: 50 }),
    });
    expect(screen.getByText("40 of 50 queries")).toBeInTheDocument();
  });

  it("renders counts via subVars for the visibility card", () => {
    renderCard({
      def: VIS_SOURCES,
      row: makeRow({ n_in_sources: 30, n_overviews: 40 }),
    });
    expect(screen.getByText("30 of 40 answers")).toBeInTheDocument();
  });

  it("renders the static 'lower is better' sub-line for an avg-position card (no subVars)", () => {
    renderCard({ def: AVG_SRC_POS, row: makeRow() });
    expect(screen.getByText("lower is better")).toBeInTheDocument();
  });

  it("renders a non-breaking-space placeholder sub-line when row is null", () => {
    renderCard({ def: COVERAGE, row: null });
    expect(screen.queryByText(/of .* queries/)).not.toBeInTheDocument();
    const subSpan = document.querySelector(".text-\\[11px\\]");
    expect(subSpan).not.toBeNull();
    expect(subSpan!.textContent).toBe(" ");
  });
});

describe("MetricCard — loading state", () => {
  it("shows a skeleton (and no value/badge) when loading and row is null", () => {
    const { container } = renderCard({
      def: COVERAGE,
      row: null,
      loading: true,
    });
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    expect(document.querySelector(".text-2xl")).toBeNull();
    expect(getBadge()).toBeNull();
  });

  it("shows the value (NOT a skeleton) when loading is true but a row is present", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage: 0.8 }),
      loading: true,
    });
    expect(document.querySelector(".animate-pulse")).toBeNull();
    expect(screen.getByText("80.0%")).toBeInTheDocument();
  });

  it("shows the value when not loading and row is present (loading prop omitted)", () => {
    renderCard({ def: COVERAGE, row: makeRow({ overview_coverage: 0.8 }) });
    expect(document.querySelector(".animate-pulse")).toBeNull();
    expect(screen.getByText("80.0%")).toBeInTheDocument();
  });

  it("shows the dash value (not a skeleton) when row is null and NOT loading", () => {
    renderCard({ def: COVERAGE, row: null, loading: false });
    expect(document.querySelector(".animate-pulse")).toBeNull();
    expect(document.querySelector(".text-2xl")).toHaveTextContent("—");
  });
});

describe("MetricCard — value + badge live together", () => {
  it("renders both the value and the delta chip within the same row", () => {
    renderCard({
      def: VIS_SOURCES,
      row: makeRow({ visibility_in_sources: 0.75, visibility_in_sources_delta: 0.05 }),
    });
    expect(screen.getByText("75.0%")).toBeInTheDocument();
    const badge = getBadge()!;
    expect(within(badge).getByText(/\+5\.0 pp/)).toBeInTheDocument();
  });
});

describe("MetricCard — per-lens distribution strip", () => {
  const stripRows = [
    makeRow({ lens: "general", overview_coverage: 0.9 }),
    makeRow({ lens: "branded", overview_coverage: 0.5 }),
    makeRow({ lens: "comparative", overview_coverage: null }),
  ];

  it("renders one item per lens with formatted values (dash for null)", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow(),
      lensRows: stripRows,
      activeLens: "all",
    });
    const list = screen.getByRole("list", { name: "By query type" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "Gen 90.0%",
      "Brand 50.0%",
      "Comp —",
    ]);
  });

  it("highlights the active lens item only", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow(),
      lensRows: stripRows,
      activeLens: "branded",
    });
    const list = screen.getByRole("list", { name: "By query type" });
    const items = within(list).getAllByRole("listitem");
    expect(items[1]).toHaveClass("font-medium");
    expect(items[0]).not.toHaveClass("font-medium");
    expect(items[2]).not.toHaveClass("font-medium");
  });

  it("formats position metrics as plain numbers in the strip", () => {
    renderCard({
      def: AVG_SRC_POS,
      row: makeRow(),
      lensRows: [
        makeRow({ lens: "general", avg_source_position: 2.25 }),
        makeRow({ lens: "branded", avg_source_position: null }),
      ],
      activeLens: "all",
    });
    const list = screen.getByRole("list", { name: "By query type" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual(["Gen 2.3", "Brand —"]);
  });

  it("renders no strip without lensRows or with a single lens row", () => {
    renderCard({ def: COVERAGE, row: makeRow() });
    expect(screen.queryByRole("list", { name: "By query type" })).not.toBeInTheDocument();
    renderCard({
      def: COVERAGE,
      row: makeRow(),
      lensRows: [makeRow({ lens: "general" })],
      activeLens: "all",
    });
    expect(screen.queryByRole("list", { name: "By query type" })).not.toBeInTheDocument();
  });

  it("ignores non-strip lenses such as the all row", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow(),
      lensRows: [makeRow({ lens: "all" }), ...stripRows],
      activeLens: "all",
    });
    const list = screen.getByRole("list", { name: "By query type" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  });
});

describe("MetricCard — repeat-group spread chip", () => {
  it("shows the min–max spread instead of the delta when repeats > 1", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({
        overview_coverage: 0.9,
        overview_coverage_min: 0.8,
        overview_coverage_max: 1.0,
        overview_coverage_delta: 0.5,
      }),
      repeats: 3,
    });
    expect(screen.getByText("80.0–100.0%")).toBeInTheDocument();
    expect(getBadge()).toBeNull();
  });

  it("formats position spread as plain numbers", () => {
    renderCard({
      def: AVG_SRC_POS,
      row: makeRow({
        avg_source_position: 2.5,
        avg_source_position_min: 2.0,
        avg_source_position_max: 3.0,
      }),
      repeats: 2,
    });
    expect(screen.getByText("2.00–3.00")).toBeInTheDocument();
  });

  it("falls back to the delta badge when repeats is 1 or spread fields absent", () => {
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: 0.1 }),
      repeats: 1,
    });
    expect(getBadge()).not.toBeNull();
    renderCard({
      def: COVERAGE,
      row: makeRow({ overview_coverage_delta: 0.1 }),
      repeats: 3,
    });
    expect(getBadge()).not.toBeNull();
  });
});
