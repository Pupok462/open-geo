import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { CompetitorsPanel } from "./CompetitorsPanel";
import { I18nProvider } from "../lib/i18n";
import type { CompetitorRow } from "../lib/api";

function renderWithProviders(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function makeRow(over: Partial<CompetitorRow> = {}): CompetitorRow {
  return {
    domain: "x.com",
    is_brand: false,
    appearances_sources: 10,
    appearances_citations: 5,
    share_sources: 0.5,
    share_citations: 0.25,
    avg_source_position: 2.0,
    avg_citation_position: 3.0,
    ...over,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("CompetitorsPanel — empty data", () => {
  it("renders the empty-state message and no table", () => {
    renderWithProviders(<CompetitorsPanel rows={[]} />);
    expect(
      screen.getByText("No domain data for the selected run."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("CompetitorsPanel — structure", () => {
  it("renders five column headers", () => {
    renderWithProviders(<CompetitorsPanel rows={[makeRow()]} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(5);
    for (const label of [
      "Domain",
      "In sources",
      "Avg. src pos.",
      "In citations",
      "Avg. cit. pos.",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders one row header per domain", () => {
    const rows = [makeRow({ domain: "a.com" }), makeRow({ domain: "b.com" })];
    renderWithProviders(<CompetitorsPanel rows={rows} />);
    expect(screen.getAllByRole("rowheader")).toHaveLength(2);
  });
});

describe("CompetitorsPanel — brand highlight", () => {
  it("marks the brand row with the 'you' badge and surface class", () => {
    const rows = [
      makeRow({ domain: "acme.com", is_brand: true }),
      makeRow({ domain: "casper.com" }),
    ];
    renderWithProviders(<CompetitorsPanel rows={rows} />);

    const brandRow = screen.getByText("acme.com").closest("tr")!;
    expect(brandRow).toHaveClass("bg-[var(--surface-2)]");
    expect(within(brandRow).getByText("you")).toBeInTheDocument();

    const otherRow = screen.getByText("casper.com").closest("tr")!;
    expect(otherRow).not.toHaveClass("bg-[var(--surface-2)]");
    expect(within(otherRow).queryByText("you")).not.toBeInTheDocument();
  });
});

describe("CompetitorsPanel — cell formatting", () => {
  it("shows share with appearances count and formats positions", () => {
    const row = makeRow({
      domain: "x.com",
      share_sources: 0.6,
      appearances_sources: 12,
      avg_source_position: 2.5,
    });
    renderWithProviders(<CompetitorsPanel rows={[row]} />);
    const bodyRow = screen.getByText("x.com").closest("tr")!;
    expect(within(bodyRow).getByText(/60\.0%/)).toBeInTheDocument();
    expect(within(bodyRow).getByText(/\(12\)/)).toBeInTheDocument();
    expect(within(bodyRow).getByText("2.50")).toBeInTheDocument();
  });

  it("renders an em dash for null positions and shares", () => {
    const row = makeRow({
      domain: "x.com",
      share_citations: null,
      appearances_citations: 0,
      avg_citation_position: null,
    });
    renderWithProviders(<CompetitorsPanel rows={[row]} />);
    const bodyRow = screen.getByText("x.com").closest("tr")!;
    expect(within(bodyRow).getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});

describe("CompetitorsPanel — sorting", () => {
  const rows = [
    makeRow({ domain: "a.com", appearances_sources: 5, appearances_citations: 9 }),
    makeRow({ domain: "b.com", appearances_sources: 12, appearances_citations: 1 }),
    makeRow({ domain: "c.com", appearances_sources: 8, appearances_citations: 4 }),
  ];

  function topDomain(): string {
    return screen.getAllByRole("rowheader")[0].textContent ?? "";
  }

  it("defaults to sources descending", () => {
    renderWithProviders(<CompetitorsPanel rows={rows} />);
    expect(topDomain()).toContain("b.com");
  });

  it("sorts alphabetically when the Domain header is clicked", () => {
    renderWithProviders(<CompetitorsPanel rows={rows} />);
    fireEvent.click(screen.getByText("Domain"));
    expect(topDomain()).toContain("a.com");
  });

  it("toggles direction when the active column is clicked again", () => {
    renderWithProviders(<CompetitorsPanel rows={rows} />);
    fireEvent.click(screen.getByText("In sources"));
    expect(topDomain()).toContain("a.com");
  });

  it("re-sorts by citations when that column is clicked", () => {
    renderWithProviders(<CompetitorsPanel rows={rows} />);
    fireEvent.click(screen.getByText("In citations"));
    expect(topDomain()).toContain("a.com");
  });
});
