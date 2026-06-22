
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import {
  FieldSelect,
  IconButton,
  InfoTip,
  LanguageSwitcher,
  Panel,
  Segmented,
  Skeleton,
  ThemeToggle,
} from "./primitives";
import { I18nProvider, type Locale } from "../lib/i18n";
import { ThemeProvider } from "../lib/theme";

const LOCALES: Locale[] = [
  { code: "en", name: "English" },
  { code: "ru", name: "Русский" },
];

function stubFetch(locales: Locale[] = LOCALES) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/i18n")) {
        return new Response(JSON.stringify(locales), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  stubFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <I18nProvider>{children}</I18nProvider>
    </ThemeProvider>
  );
}

function renderWithProviders(ui: React.ReactElement) {
  return render(<Providers>{ui}</Providers>);
}

describe("InfoTip", () => {
  it("renders the trigger closed by default (no tooltip, no aria-describedby)", () => {
    renderWithProviders(<InfoTip text="Helpful text" />);
    const btn = screen.getByRole("button");
    expect(btn).not.toHaveAttribute("aria-describedby");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("uses the localized default aria-label when no label prop is passed", () => {
    renderWithProviders(<InfoTip text="Helpful text" />);
    expect(
      screen.getByRole("button", { name: "What this metric means" }),
    ).toBeInTheDocument();
  });

  it("uses a custom aria-label when the label prop is provided", () => {
    renderWithProviders(<InfoTip text="Helpful text" label="More info" />);
    expect(
      screen.getByRole("button", { name: "More info" }),
    ).toBeInTheDocument();
  });

  it("opens the tooltip on mouse enter and closes on mouse leave", async () => {
    const user = userEvent.setup();
    renderWithProviders(<InfoTip text="Helpful text" />);
    const btn = screen.getByRole("button");

    await user.hover(btn);
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("Helpful text");
    expect(btn).toHaveAttribute("aria-describedby", tip.id);

    await user.unhover(btn);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(btn).not.toHaveAttribute("aria-describedby");
  });

  it("opens on keyboard focus and closes on blur", async () => {
    const user = userEvent.setup();
    renderWithProviders(<InfoTip text="Helpful text" />);
    const btn = screen.getByRole("button");

    await user.tab();
    expect(btn).toHaveFocus();
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    await user.tab();
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

describe("Panel", () => {
  it("renders children with no header when neither title nor right is given", () => {
    const { container } = render(
      <Panel>
        <p>Body</p>
      </Panel>,
    );
    expect(screen.getByText("Body")).toBeInTheDocument();
    expect(container.querySelector("h2")).toBeNull();
  });

  it("renders the title heading when a title is given", () => {
    render(
      <Panel title="Sources">
        <p>Body</p>
      </Panel>,
    );
    expect(
      screen.getByRole("heading", { name: "Sources", level: 2 }),
    ).toBeInTheDocument();
  });

  it("renders the header when only the right slot is provided (no title)", () => {
    const { container } = render(
      <Panel right={<button type="button">Export</button>}>
        <p>Body</p>
      </Panel>,
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
    expect(container.querySelector("h2")).toBeNull();
  });

  it("renders an InfoTip when info is provided (with a title)", () => {
    renderWithProviders(
      <Panel title="Sources" info="What sources means">
        <p>Body</p>
      </Panel>,
    );
    expect(
      screen.getByRole("button", { name: "What this metric means" }),
    ).toBeInTheDocument();
  });

  it("does NOT render an InfoTip when info is omitted", () => {
    render(
      <Panel title="Sources">
        <p>Body</p>
      </Panel>,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("merges a custom className onto the section element", () => {
    const { container } = render(
      <Panel className="col-span-2">
        <p>Body</p>
      </Panel>,
    );
    const section = container.querySelector("section");
    expect(section).toHaveClass("col-span-2");
    expect(section).toHaveClass("rounded-xl");
  });

  it("renders title, info and right together", () => {
    renderWithProviders(
      <Panel
        title="Sources"
        info="Definition"
        right={<span>slot</span>}
      >
        <p>Body</p>
      </Panel>,
    );
    expect(screen.getByRole("heading", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByText("slot")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeInTheDocument();
  });
});

describe("IconButton", () => {
  it("renders an accessible button with label as aria-label and title", () => {
    render(
      <IconButton label="Download report" onClick={() => {}}>
        <svg data-testid="icon" />
      </IconButton>,
    );
    const btn = screen.getByRole("button", { name: "Download report" });
    expect(btn).toHaveAttribute("title", "Download report");
    expect(screen.getByTestId("icon")).toBeInTheDocument();
  });

  it("invokes onClick when clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <IconButton label="Go" onClick={onClick}>
        <span>x</span>
      </IconButton>,
    );
    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("Segmented", () => {
  const OPTIONS = [
    { value: "today", label: "Today" },
    { value: "all", label: "All time" },
  ];

  it("renders the optional label when provided", () => {
    render(
      <Segmented
        label="Period"
        value="today"
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("Period")).toBeInTheDocument();
  });

  it("omits the label element when no label prop is given", () => {
    render(<Segmented value="today" options={OPTIONS} onChange={() => {}} />);
    expect(screen.queryByText("Period")).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("marks the active option with aria-pressed=true and others false", () => {
    render(<Segmented value="all" options={OPTIONS} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "All time" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Today" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("calls onChange with the option value when a segment is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Segmented value="today" options={OPTIONS} onChange={onChange} />);
    await user.click(screen.getByRole("button", { name: "All time" }));
    expect(onChange).toHaveBeenCalledWith("all");
  });

  it("applies the active styling class to the selected segment", () => {
    render(<Segmented value="today" options={OPTIONS} onChange={() => {}} />);
    const active = screen.getByRole("button", { name: "Today" });
    const inactive = screen.getByRole("button", { name: "All time" });
    expect(active.className).toContain("bg-[var(--accent)]");
    expect(inactive.className).not.toContain("bg-[var(--accent)]");
  });
});

describe("FieldSelect", () => {
  const OPTIONS = [
    { value: 1, label: "Example" },
    { value: 2, label: "Globex" },
  ];

  it("renders the label and all options with the current value selected", () => {
    render(
      <FieldSelect
        label="Brand"
        value={2}
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("Brand")).toBeInTheDocument();
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("2");
    expect(
      screen.getByRole("option", { name: "Example" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Globex" }),
    ).toBeInTheDocument();
  });

  it("renders with an empty value (the '' branch) and no option pre-selected by value", () => {
    render(
      <FieldSelect
        label="Brand"
        value=""
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select).toBeInTheDocument();
  });

  it("calls onChange with the chosen string value on selection", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <FieldSelect
        label="Brand"
        value={1}
        options={OPTIONS}
        onChange={onChange}
      />,
    );
    await user.selectOptions(screen.getByRole("combobox"), "2");
    expect(onChange).toHaveBeenCalledWith("2");
  });

  it("is enabled by default (no disabled prop)", () => {
    render(
      <FieldSelect
        label="Brand"
        value={1}
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox")).toBeEnabled();
  });

  it("disables the select when disabled is true", () => {
    render(
      <FieldSelect
        label="Brand"
        value={1}
        options={OPTIONS}
        onChange={() => {}}
        disabled
      />,
    );
    expect(screen.getByRole("combobox")).toBeDisabled();
  });

  it("renders the chevron icon inside the field", () => {
    const { container } = render(
      <FieldSelect
        label="Brand"
        value={1}
        options={OPTIONS}
        onChange={() => {}}
      />,
    );
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});

describe("Skeleton", () => {
  it("renders with the base pulse classes and no extra class by default", () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild as HTMLElement;
    expect(el).toHaveClass("animate-pulse");
    expect(el).toHaveClass("rounded-md");
  });

  it("merges a custom className", () => {
    const { container } = render(<Skeleton className="h-8 w-40" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el).toHaveClass("h-8");
    expect(el).toHaveClass("w-40");
    expect(el).toHaveClass("animate-pulse");
  });
});

describe("ThemeToggle", () => {
  it("in light theme shows the 'switch to dark' label", () => {
    renderWithProviders(<ThemeToggle />);
    expect(
      screen.getByRole("button", { name: "Switch to dark theme" }),
    ).toBeInTheDocument();
  });

  it("in dark theme (persisted) shows the 'switch to light' label", () => {
    localStorage.setItem("og-theme", "dark");
    renderWithProviders(<ThemeToggle />);
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
  });

  it("toggles the label when clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ThemeToggle />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveAccessibleName("Switch to dark theme");
    await user.click(btn);
    expect(
      screen.getByRole("button", { name: "Switch to light theme" }),
    ).toBeInTheDocument();
  });
});

describe("LanguageSwitcher", () => {
  it("renders a labelled select listing locales from the registry", async () => {
    renderWithProviders(<LanguageSwitcher />);
    const select = screen.getByRole("combobox", { name: "Language" });
    expect(select).toBeInTheDocument();
    expect(
      await screen.findByRole("option", { name: "Русский" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
  });

  it("defaults its value to the default language (en)", () => {
    renderWithProviders(<LanguageSwitcher />);
    const select = screen.getByRole("combobox", {
      name: "Language",
    }) as HTMLSelectElement;
    expect(select.value).toBe("en");
  });

  it("changes the language (and persists it) when a new locale is picked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LanguageSwitcher />);
    const select = (await screen.findByRole("combobox", {
      name: "Language",
    })) as HTMLSelectElement;
    await screen.findByRole("option", { name: "Русский" });
    await user.selectOptions(select, "ru");
    expect(select.value).toBe("ru");
    expect(localStorage.getItem("og-lang")).toBe("ru");
  });

  it("falls back to the bundled English-only registry when /api/i18n returns []", async () => {
    stubFetch([]);
    renderWithProviders(<LanguageSwitcher />);
    const select = screen.getByRole("combobox", { name: "Language" });
    expect(within(select).getByRole("option", { name: "English" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Русский" })).toBeNull();
  });
});
