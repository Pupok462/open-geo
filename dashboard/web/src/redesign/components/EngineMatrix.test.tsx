
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { EngineMatrix } from "./EngineMatrix";
import { I18nProvider } from "../lib/i18n";
import type { EngineMatrixRow } from "../lib/api";

function makeRow(over: Partial<EngineMatrixRow> = {}): EngineMatrixRow {
  return {
    engine: "google",
    run: { run_id: 5, run_at: "2026-06-09T16:00:00Z", status: "done" },
    n_runs: 5,
    n_queries: 24,
    n_overviews: 20,
    overview_coverage: 0.833,
    n_in_sources: 12,
    visibility_in_sources: 0.6,
    n_cited: 9,
    visibility_in_citations: 0.45,
    avg_source_position: 2.5,
    avg_citation_position: 1.0,
    relative_citation: 0.75,
    n_brand_mentions: 14,
    brand_mention_rate: 0.7,
    ...over,
  };
}

function renderWithProviders(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

beforeEach(() => {
  window.localStorage.clear();
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
  vi.clearAllMocks();
  window.localStorage.clear();
});

describe("EngineMatrix — empty state", () => {
  it("renders the empty message and no table for zero rows", () => {
    renderWithProviders(<EngineMatrix rows={[]} />);
    expect(
      screen.getByText("No engines with runs for this brand."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("EngineMatrix — table structure", () => {
  it("renders all ten column headers", () => {
    renderWithProviders(<EngineMatrix rows={[makeRow()]} />);
    const labels = [
      "Engine",
      "Queries",
      "Answered",
      "Coverage",
      "Vis. in sources",
      "Vis. in citations",
      "Mentioned",
      "Src→cit conv.",
      "Avg. src pos.",
      "Avg. cit. pos.",
    ];
    for (const label of labels) {
      expect(screen.getByRole("columnheader", { name: label })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(labels.length);
  });

  it("renders one row per engine with formatted values", () => {
    renderWithProviders(
      <EngineMatrix
        rows={[makeRow(), makeRow({ engine: "chatgpt_search", overview_coverage: 1.0 })]}
      />,
    );
    expect(screen.getAllByRole("rowheader")).toHaveLength(2);
    const googleRow = screen.getByRole("row", { name: /google/ });
    const cells = within(googleRow).getAllByRole("cell");
    expect(cells.map((c) => c.textContent)).toEqual([
      "24",
      "20",
      "83.3%",
      "60.0%",
      "45.0%",
      "70.0%",
      "75.0%",
      "2.50",
      "1.00",
    ]);
  });

  it("renders dashes for an engine whose metrics are null (no done run)", () => {
    renderWithProviders(
      <EngineMatrix
        rows={[
          makeRow({
            engine: "perplexity",
            run: null,
            n_runs: 0,
            n_queries: null,
            n_overviews: null,
            overview_coverage: null,
            n_in_sources: null,
            visibility_in_sources: null,
            n_cited: null,
            visibility_in_citations: null,
            avg_source_position: null,
            avg_citation_position: null,
            relative_citation: null,
            n_brand_mentions: null,
            brand_mention_rate: null,
          }),
        ]}
      />,
    );
    const row = screen.getByRole("row", { name: /perplexity/ });
    const cells = within(row).getAllByRole("cell");
    expect(cells.every((c) => c.textContent === "—")).toBe(true);
  });
});

describe("EngineMatrix — engine drill-in", () => {
  it("fires onSelect with the engine id when its button is clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderWithProviders(
      <EngineMatrix
        rows={[makeRow(), makeRow({ engine: "chatgpt_search" })]}
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByRole("button", { name: "chatgpt_search" }));
    expect(onSelect).toHaveBeenCalledWith("chatgpt_search");
  });

  it("renders plain text engine names when no onSelect is given", () => {
    renderWithProviders(<EngineMatrix rows={[makeRow()]} />);
    expect(screen.queryByRole("button", { name: "google" })).not.toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "google" })).toBeInTheDocument();
  });
});
