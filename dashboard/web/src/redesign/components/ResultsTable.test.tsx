
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enDict from "../../../../../i18n/en.json";
import type { LinkRef, ResultRow } from "../lib/api";
import { I18nProvider } from "../lib/i18n";
import { ResultsTable } from "./ResultsTable";

const D = enDict.dashboard;
const DASH = enDict.common.dash;

const link = (rank: number, domain = "example.com"): LinkRef => ({
  rank,
  url: `https://${domain}/page-${rank}`,
  domain,
});

function makeRow(overrides: Partial<ResultRow> = {}): ResultRow {
  return {
    id: 1,
    query: "best running shoes",
    lens: "general",
    captured_at: "2026-06-19T10:00:00Z",
    overview_present: true,
    answer_text_md: "Some answer about shoes.",
    screenshot_path: null,
    sources: [],
    citations: [],
    target_source_ranks: [],
    target_citation_ranks: [],
    brand_in_answer_text: false,
    sentiment: null,
    ...overrides,
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

describe("ResultsTable — empty state", () => {
  it("renders the empty message and NO table when rows is empty", () => {
    renderWithProviders(<ResultsTable rows={[]} />);
    expect(screen.getByText(D.results_empty)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("does not render any column headers in the empty state", () => {
    renderWithProviders(<ResultsTable rows={[]} />);
    expect(screen.queryByText(D.results_col_query)).not.toBeInTheDocument();
    expect(screen.queryByText(D.results_col_sentiment)).not.toBeInTheDocument();
  });
});

describe("ResultsTable — table structure & headers", () => {
  it("renders a table with all six column headers when rows are present", () => {
    renderWithProviders(<ResultsTable rows={[makeRow()]} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    const headers = screen.getAllByRole("columnheader");
    expect(headers).toHaveLength(6);
    expect(screen.getByRole("columnheader", { name: D.results_col_query })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: D.results_col_lens })).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: D.results_col_overview }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: D.results_col_source_ranks }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: D.results_col_citation_ranks }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: D.results_col_sentiment }),
    ).toBeInTheDocument();
  });

  it("renders one body row per ResultRow (rendered as a row-scope header cell)", () => {
    const rows = [
      makeRow({ id: 1, query: "alpha" }),
      makeRow({ id: 2, query: "beta" }),
      makeRow({ id: 3, query: "gamma" }),
    ];
    renderWithProviders(<ResultsTable rows={rows} />);
    const rowHeaders = screen.getAllByRole("rowheader");
    expect(rowHeaders).toHaveLength(3);
    expect(rowHeaders.map((h) => h.textContent)).toEqual(["alpha", "beta", "gamma"]);
  });

  it("keys rows by id (distinct ids render distinct rows without collapsing)", () => {
    const rows = [makeRow({ id: 10, query: "q10" }), makeRow({ id: 11, query: "q11" })];
    renderWithProviders(<ResultsTable rows={rows} />);
    expect(screen.getByRole("rowheader", { name: "q10" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "q11" })).toBeInTheDocument();
  });
});

describe("ResultsTable — query text (verbatim DATA)", () => {
  it("renders the query text exactly as given, untranslated", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ query: "Какой пылесос купить?" })]} />);
    expect(screen.getByRole("rowheader", { name: "Какой пылесос купить?" })).toBeInTheDocument();
  });

  it("renders an empty query string without crashing", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ query: "" })]} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    const rowHeaders = screen.getAllByRole("rowheader");
    expect(rowHeaders).toHaveLength(1);
    expect(rowHeaders[0]).toHaveTextContent("");
  });
});

describe("ResultsTable — lens label", () => {
  it("translates a known lens key to its English label", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ lens: "branded" })]} />);
    expect(screen.getByText(enDict.lens.branded)).toBeInTheDocument();
  });

  it.each([
    ["general", enDict.lens.general],
    ["branded", enDict.lens.branded],
    ["comparative", enDict.lens.comparative],
  ])("renders the %s lens label as %s", (lens, label) => {
    renderWithProviders(<ResultsTable rows={[makeRow({ lens })]} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("falls back to the dotted key itself for an unknown lens", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ lens: "mystery" })]} />);
    expect(screen.getByText("lens.mystery")).toBeInTheDocument();
  });
});

describe("ResultsTable — overview presence badge", () => {
  it("shows the CheckIcon with the 'shown' aria-label when overview_present is true", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ overview_present: true })]} />);
    const shown = screen.getByLabelText(D.results_overview_shown);
    expect(shown).toBeInTheDocument();
    expect(shown.querySelector("svg")).toBeInTheDocument();
    expect(screen.queryByLabelText(D.results_overview_absent)).not.toBeInTheDocument();
  });

  it("shows the MinusIcon with the 'absent' aria-label when overview_present is false", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ overview_present: false })]} />);
    const absent = screen.getByLabelText(D.results_overview_absent);
    expect(absent).toBeInTheDocument();
    expect(absent.querySelector("svg")).toBeInTheDocument();
    expect(screen.queryByLabelText(D.results_overview_shown)).not.toBeInTheDocument();
  });

  it("renders both badge variants across a mixed set of rows", () => {
    const rows = [
      makeRow({ id: 1, overview_present: true }),
      makeRow({ id: 2, overview_present: false }),
    ];
    renderWithProviders(<ResultsTable rows={rows} />);
    expect(screen.getByLabelText(D.results_overview_shown)).toBeInTheDocument();
    expect(screen.getByLabelText(D.results_overview_absent)).toBeInTheDocument();
  });
});

describe("ResultsTable — source rank cell", () => {
  it("renders a dash when target_source_ranks is empty", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ target_source_ranks: [] })]} />);
    const row = screen.getByRole("row", { name: /best running shoes/i });
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent(DASH);
  });

  it("renders a single rank as its number", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ target_source_ranks: [3] })]} />);
    const row = screen.getByRole("row", { name: /best running shoes/i });
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("3");
  });

  it("joins multiple source ranks with ', '", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ target_source_ranks: [1, 4, 9] })]} />);
    const row = screen.getByRole("row", { name: /best running shoes/i });
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("1, 4, 9");
  });
});

describe("ResultsTable — citation rank cell", () => {
  it("renders a dash when target_citation_ranks is empty", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ target_citation_ranks: [] })]} />);
    const row = screen.getByRole("row", { name: /best running shoes/i });
    const cells = within(row).getAllByRole("cell");
    expect(cells[3]).toHaveTextContent(DASH);
  });

  it("joins multiple citation ranks with ', '", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ target_citation_ranks: [2, 5] })]} />);
    const row = screen.getByRole("row", { name: /best running shoes/i });
    const cells = within(row).getAllByRole("cell");
    expect(cells[3]).toHaveTextContent("2, 5");
  });

  it("treats source and citation ranks independently (source set, citation empty)", () => {
    renderWithProviders(
      <ResultsTable
        rows={[makeRow({ target_source_ranks: [1, 2], target_citation_ranks: [] })]}
      />,
    );
    const row = screen.getByRole("row", { name: /best running shoes/i });
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("1, 2");
    expect(cells[3]).toHaveTextContent(DASH);
  });
});

describe("ResultsTable — sentiment cell", () => {
  it("renders the sentiment string verbatim when present", () => {
    const sentiment = "Mentioned positively as a top pick.";
    renderWithProviders(<ResultsTable rows={[makeRow({ sentiment })]} />);
    expect(screen.getByText(sentiment)).toBeInTheDocument();
    expect(screen.queryByText(D.results_brand_absent)).not.toBeInTheDocument();
  });

  it("renders the italic 'brand not mentioned' placeholder when sentiment is null", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ sentiment: null })]} />);
    const placeholder = screen.getByText(D.results_brand_absent);
    expect(placeholder).toBeInTheDocument();
    expect(placeholder.tagName).toBe("SPAN");
    expect(placeholder).toHaveClass("italic");
  });

  it("renders an empty-string sentiment as the placeholder (?? only catches null/undefined, but empty string is falsy here it is kept)", () => {
    renderWithProviders(<ResultsTable rows={[makeRow({ sentiment: "" })]} />);
    expect(screen.queryByText(D.results_brand_absent)).not.toBeInTheDocument();
  });

  it("shows verbatim sentiment for one row and the placeholder for another", () => {
    const rows = [
      makeRow({ id: 1, sentiment: "Neutral mention." }),
      makeRow({ id: 2, sentiment: null }),
    ];
    renderWithProviders(<ResultsTable rows={rows} />);
    expect(screen.getByText("Neutral mention.")).toBeInTheDocument();
    expect(screen.getByText(D.results_brand_absent)).toBeInTheDocument();
  });
});

describe("ResultsTable — combined realistic rows", () => {
  it("renders a fully-populated row (overview, sources, citations, sentiment, brand in text)", () => {
    const row = makeRow({
      id: 42,
      query: "compare example vs rival",
      lens: "comparative",
      overview_present: true,
      sources: [link(1), link(2)],
      citations: [link(2)],
      target_source_ranks: [1, 2],
      target_citation_ranks: [2],
      brand_in_answer_text: true,
      sentiment: "Cited as the more affordable option.",
    });
    renderWithProviders(<ResultsTable rows={[row]} />);

    expect(screen.getByRole("rowheader", { name: "compare example vs rival" })).toBeInTheDocument();
    expect(screen.getByText(enDict.lens.comparative)).toBeInTheDocument();
    expect(screen.getByLabelText(D.results_overview_shown)).toBeInTheDocument();

    const dataRow = screen.getByRole("row", { name: /compare example vs rival/i });
    const cells = within(dataRow).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("1, 2");
    expect(cells[3]).toHaveTextContent("2");
    expect(screen.getByText("Cited as the more affordable option.")).toBeInTheDocument();
  });

  it("renders an absent-overview row with no ranks and no sentiment", () => {
    const row = makeRow({
      id: 7,
      query: "niche query",
      lens: "general",
      overview_present: false,
      sources: [],
      citations: [],
      target_source_ranks: [],
      target_citation_ranks: [],
      brand_in_answer_text: false,
      sentiment: null,
    });
    renderWithProviders(<ResultsTable rows={[row]} />);

    expect(screen.getByLabelText(D.results_overview_absent)).toBeInTheDocument();
    const dataRow = screen.getByRole("row", { name: /niche query/i });
    const cells = within(dataRow).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent(DASH);
    expect(cells[3]).toHaveTextContent(DASH);
    expect(screen.getByText(D.results_brand_absent)).toBeInTheDocument();
  });

  it("does NOT surface raw source/citation URLs or domains (only ranks are shown)", () => {
    const row = makeRow({
      sources: [link(1, "secret.example")],
      citations: [link(1, "secret.example")],
      target_source_ranks: [1],
      target_citation_ranks: [1],
    });
    renderWithProviders(<ResultsTable rows={[row]} />);
    expect(screen.queryByText(/secret\.example/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
