
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { LensBreakdown } from "./LensBreakdown";
import { I18nProvider } from "../lib/i18n";
import type { MetricRow } from "../lib/api";


function renderWithProviders(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function makeRow(over: Partial<MetricRow> = {}): MetricRow {
  return {
    lens: "general",
    n_queries: 40,
    n_overviews: 30,
    overview_coverage: 0.75,
    n_in_sources: 12,
    visibility_in_sources: 0.4,
    n_cited: 9,
    visibility_in_citations: 0.3,
    avg_source_position: 2.5,
    avg_citation_position: 3.125,
    relative_citation: 0.75,
    n_brand_mentions: 8,
    brand_mention_rate: 0.25,
    ...over,
  };
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
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe("LensBreakdown — empty data", () => {
  it("renders the empty-state message and no table when rows is empty", () => {
    renderWithProviders(<LensBreakdown rows={[]} />);

    expect(screen.getByText("No metrics for the selected run.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader")).not.toBeInTheDocument();
  });
});


describe("LensBreakdown — table structure", () => {
  it("renders a table with all nine column headers when rows are present", () => {
    renderWithProviders(<LensBreakdown rows={[makeRow()]} />);

    expect(screen.getByRole("table")).toBeInTheDocument();

    const headerLabels = [
      "Lens",
      "Queries",
      "Answered",
      "Coverage",
      "Vis. in sources",
      "Vis. in citations",
      "Mentioned",
      "Avg. src pos.",
      "Avg. cit. pos.",
    ];
    for (const label of headerLabels) {
      expect(
        screen.getByRole("columnheader", { name: label }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(headerLabels.length);
  });

  it("renders one body row per metric row, each keyed by lens", () => {
    const rows = [
      makeRow({ lens: "general" }),
      makeRow({ lens: "branded" }),
      makeRow({ lens: "comparative" }),
    ];
    renderWithProviders(<LensBreakdown rows={rows} />);

    expect(screen.getAllByRole("rowheader")).toHaveLength(3);
  });
});


describe("LensBreakdown — lens labels", () => {
  it("resolves the known lens keys to their English labels", () => {
    const rows = [
      makeRow({ lens: "all" }),
      makeRow({ lens: "general" }),
      makeRow({ lens: "branded" }),
      makeRow({ lens: "comparative" }),
    ];
    renderWithProviders(<LensBreakdown rows={rows} />);

    expect(screen.getByRole("rowheader", { name: "All lenses" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Branded" })).toBeInTheDocument();
    expect(
      screen.getByRole("rowheader", { name: "Comparative" }),
    ).toBeInTheDocument();
  });

  it("falls back to the raw dotted key for an unknown lens string", () => {
    renderWithProviders(<LensBreakdown rows={[makeRow({ lens: "weird" })]} />);

    expect(screen.getByRole("rowheader", { name: "lens.weird" })).toBeInTheDocument();
  });
});


describe("LensBreakdown — aggregate row styling", () => {
  it("applies the aggregate surface + bold classes to the all row only", () => {
    const rows = [makeRow({ lens: "all" }), makeRow({ lens: "general" })];
    renderWithProviders(<LensBreakdown rows={rows} />);

    const allRow = screen.getByRole("rowheader", { name: "All lenses" }).closest("tr");
    const generalRow = screen
      .getByRole("rowheader", { name: "General" })
      .closest("tr");

    expect(allRow).not.toBeNull();
    expect(generalRow).not.toBeNull();

    expect(allRow).toHaveClass("bg-[var(--surface-2)]");
    expect(allRow).toHaveClass("font-medium");

    expect(generalRow).not.toHaveClass("bg-[var(--surface-2)]");
    expect(generalRow).not.toHaveClass("font-medium");
  });
});


describe("LensBreakdown — numeric cell formatting", () => {
  it("renders raw counts and formats percentages and positions", () => {
    const row = makeRow({
      lens: "general",
      n_queries: 40,
      n_overviews: 30,
      overview_coverage: 0.75,
      visibility_in_sources: 0.4,
      visibility_in_citations: 0.3,
      avg_source_position: 2.5,
      avg_citation_position: 3.125,
    });
    renderWithProviders(<LensBreakdown rows={[row]} />);

    const bodyRow = screen.getByRole("rowheader", { name: "General" }).closest("tr")!;
    const cells = within(bodyRow).getAllByRole("cell");
    expect(cells.map((c) => c.textContent)).toEqual([
      "40",
      "30",
      "75.0%",
      "40.0%",
      "30.0%",
      "25.0%",
      "2.50",
      "3.13",
    ]);
  });

  it("formats a zero coverage as 0.0% rather than a dash", () => {
    const row = makeRow({ lens: "general", overview_coverage: 0 });
    renderWithProviders(<LensBreakdown rows={[row]} />);

    const bodyRow = screen.getByRole("rowheader", { name: "General" }).closest("tr")!;
    expect(within(bodyRow).getByText("0.0%")).toBeInTheDocument();
  });
});


describe("LensBreakdown — missing metric values", () => {
  it("renders an em dash for every null percentage/position metric", () => {
    const row = makeRow({
      lens: "general",
      overview_coverage: null,
      visibility_in_sources: null,
      visibility_in_citations: null,
      brand_mention_rate: null,
      avg_source_position: null,
      avg_citation_position: null,
    });
    renderWithProviders(<LensBreakdown rows={[row]} />);

    const bodyRow = screen.getByRole("rowheader", { name: "General" }).closest("tr")!;
    const cells = within(bodyRow).getAllByRole("cell");
    expect(cells.map((c) => c.textContent)).toEqual([
      "40",
      "30",
      "—",
      "—",
      "—",
      "—",
      "—",
      "—",
    ]);
  });

  it("renders an em dash for undefined metric values too", () => {
    const row = makeRow({
      lens: "branded",
      overview_coverage: undefined,
      visibility_in_sources: undefined,
      visibility_in_citations: undefined,
      brand_mention_rate: undefined,
      avg_source_position: undefined,
      avg_citation_position: undefined,
    });
    renderWithProviders(<LensBreakdown rows={[row]} />);

    const bodyRow = screen.getByRole("rowheader", { name: "Branded" }).closest("tr")!;
    const dashes = within(bodyRow).getAllByText("—");
    expect(dashes).toHaveLength(6);
  });

  it("mixes present and missing metrics within a single row", () => {
    const row = makeRow({
      lens: "comparative",
      overview_coverage: 0.5,
      visibility_in_sources: null,
      avg_source_position: 1.0,
      avg_citation_position: null,
    });
    renderWithProviders(<LensBreakdown rows={[row]} />);

    const bodyRow = screen
      .getByRole("rowheader", { name: "Comparative" })
      .closest("tr")!;
    expect(within(bodyRow).getByText("50.0%")).toBeInTheDocument();
    expect(within(bodyRow).getByText("1.00")).toBeInTheDocument();
    expect(within(bodyRow).getAllByText("—")).toHaveLength(2);
  });
});


describe("LensBreakdown — delta fields are ignored", () => {
  it("does not render any *_delta values supplied on the rows", () => {
    const row = makeRow({
      lens: "general",
      overview_coverage: 0.75,
      overview_coverage_delta: 0.12,
      visibility_in_sources_delta: -0.05,
      avg_source_position_delta: 0.5,
    });
    renderWithProviders(<LensBreakdown rows={[row]} />);

    const bodyRow = screen.getByRole("rowheader", { name: "General" }).closest("tr")!;
    expect(within(bodyRow).getAllByRole("cell")).toHaveLength(8);
    expect(within(bodyRow).queryByText(/\+12\.0/)).not.toBeInTheDocument();
    expect(within(bodyRow).queryByText(/pp/)).not.toBeInTheDocument();
  });
});
