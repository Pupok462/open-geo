import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

const BASE: string = api
  .reportUrl(0, "x", "all")
  .replace("/api/report?brand_id=0&engine=x&period=all", "");

const u = (path: string): string => `${BASE}${path}`;

function okResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
  } as unknown as Response;
}

function errorJsonResponse(
  status: number,
  statusText: string,
  body: unknown,
): Response {
  return {
    ok: false,
    status,
    statusText,
    json: async () => body,
  } as unknown as Response;
}

function errorNonJsonResponse(status: number, statusText: string): Response {
  return {
    ok: false,
    status,
    statusText,
    json: async () => {
      throw new SyntaxError("Unexpected token < in JSON at position 0");
    },
  } as unknown as Response;
}

function stubFetch(resp: Response) {
  const fn = vi.fn(async () => resp);
  vi.stubGlobal("fetch", fn);
  return fn;
}

function fetchedUrl(fn: ReturnType<typeof vi.fn>): string {
  return fn.mock.calls[0][0] as string;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("getJSON success branch", () => {
  it("returns the parsed JSON body when res.ok is true", async () => {
    const payload = [{ id: 1, name: "Example", domain: "example.com" }];
    stubFetch(okResponse(payload));

    const out = await api.brands();

    expect(out).toEqual(payload);
  });

  it("resolves the SAME object reference returned by res.json()", async () => {
    const payload = {
      brand_id: 7,
      engine: "e",
      period: "today",
      run: null,
      prev_run: null,
      metrics: [],
    };
    stubFetch(okResponse(payload));

    const out = await api.metrics(7, "e", "today");

    expect(out).toBe(payload);
  });

  it("calls fetch with the resolved API_BASE prefix (whatever it is)", async () => {
    const fn = stubFetch(okResponse([]));
    await api.brands();
    expect(fetchedUrl(fn)).toBe(u("/api/brands"));
  });
});

describe("getJSON error branches", () => {
  it("throws `<status>: <detail>` when the error body is JSON with a detail field", async () => {
    stubFetch(errorJsonResponse(404, "Not Found", { detail: "boom" }));

    await expect(api.brands()).rejects.toThrow("404: boom");
  });

  it("falls back to statusText when the JSON error body has NO detail field", async () => {
    stubFetch(errorJsonResponse(400, "Bad Request", { error: "nope" }));

    await expect(api.brands()).rejects.toThrow("400: Bad Request");
  });

  it("falls back to statusText when res.json() REJECTS (non-JSON error body)", async () => {
    stubFetch(errorNonJsonResponse(500, "Internal Server Error"));

    await expect(api.brands()).rejects.toThrow("500: Internal Server Error");
  });

  it("falls back to statusText when the JSON body is null (body?.detail short-circuits)", async () => {
    stubFetch(errorJsonResponse(503, "Service Unavailable", null));

    await expect(api.brands()).rejects.toThrow("503: Service Unavailable");
  });

  it("rejects with an Error instance (not a plain value)", async () => {
    stubFetch(errorJsonResponse(401, "Unauthorized", { detail: "no token" }));

    await expect(api.brands()).rejects.toBeInstanceOf(Error);
    await expect(api.brands()).rejects.toThrow("401: no token");
  });
});

describe("qs querystring builder (via api methods)", () => {
  it("returns no querystring suffix when a method passes no params (brands)", async () => {
    const fn = stubFetch(okResponse([]));

    await api.brands();

    expect(fetchedUrl(fn)).toBe(u("/api/brands"));
    expect(fetchedUrl(fn)).not.toContain("?");
  });

  it("omits undefined values (runs without engine)", async () => {
    const fn = stubFetch(okResponse([]));

    await api.runs(7);

    expect(fetchedUrl(fn)).toBe(u("/api/runs?brand_id=7"));
    expect(fetchedUrl(fn)).not.toContain("engine");
  });

  it("omits empty-string values (results with lens='')", async () => {
    const fn = stubFetch(okResponse({}));

    await api.results(3, "");

    expect(fetchedUrl(fn)).toBe(u("/api/results?run_id=3"));
    expect(fetchedUrl(fn)).not.toContain("lens");
  });

  it("includes numeric values, coercing them to strings", async () => {
    const fn = stubFetch(okResponse([]));

    await api.engines(7);

    expect(fetchedUrl(fn)).toBe(u("/api/engines?brand_id=7"));
  });

  it("includes string values", async () => {
    const fn = stubFetch(okResponse({}));

    await api.timeseries(7, "google", "branded");

    expect(fetchedUrl(fn)).toBe(
      u("/api/timeseries?brand_id=7&engine=google&lens=branded"),
    );
  });

  it("joins multiple present params with & and prefixes a single ?", async () => {
    const fn = stubFetch(okResponse({}));

    await api.metrics(7, "google", "today", "general");

    const url = fetchedUrl(fn);
    expect(url.match(/\?/g)).toHaveLength(1);
    expect(url).toBe(
      u("/api/metrics?brand_id=7&engine=google&period=today&lens=general"),
    );
  });

  it("URL-encodes special characters in string values", async () => {
    const fn = stubFetch(okResponse({}));

    await api.results(3, "a b&c=d/e");

    const url = fetchedUrl(fn);
    expect(url).toContain("run_id=3");
    expect(url).toContain("lens=a+b%26c%3Dd%2Fe");
    expect(url).toBe(u("/api/results?run_id=3&lens=a+b%26c%3Dd%2Fe"));
  });

  it("URL-encodes special characters in the engine name", async () => {
    const fn = stubFetch(okResponse([]));

    await api.runs(7, "engine x/y");

    expect(fetchedUrl(fn)).toBe(u("/api/runs?brand_id=7&engine=engine+x%2Fy"));
  });
});

describe("api method request paths", () => {
  it("brands() -> /api/brands", async () => {
    const fn = stubFetch(okResponse([]));
    await api.brands();
    expect(fetchedUrl(fn)).toBe(u("/api/brands"));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("engines(7) -> /api/engines?brand_id=7", async () => {
    const fn = stubFetch(okResponse([]));
    await api.engines(7);
    expect(fetchedUrl(fn)).toBe(u("/api/engines?brand_id=7"));
  });

  it("runs(7) -> /api/runs?brand_id=7 (engine omitted)", async () => {
    const fn = stubFetch(okResponse([]));
    await api.runs(7);
    expect(fetchedUrl(fn)).toBe(u("/api/runs?brand_id=7"));
  });

  it("runs(7, 'google') -> /api/runs?brand_id=7&engine=google", async () => {
    const fn = stubFetch(okResponse([]));
    await api.runs(7, "google");
    expect(fetchedUrl(fn)).toBe(
      u("/api/runs?brand_id=7&engine=google"),
    );
  });

  it("metrics(7, 'e', 'today') -> /api/metrics?brand_id=7&engine=e&period=today (no lens)", async () => {
    const fn = stubFetch(okResponse({}));
    await api.metrics(7, "e", "today");
    expect(fetchedUrl(fn)).toBe(u("/api/metrics?brand_id=7&engine=e&period=today"));
    expect(fetchedUrl(fn)).not.toContain("lens");
  });

  it("metrics(7, 'e', 'all', 'branded') -> includes the lens param", async () => {
    const fn = stubFetch(okResponse({}));
    await api.metrics(7, "e", "all", "branded");
    expect(fetchedUrl(fn)).toBe(
      u("/api/metrics?brand_id=7&engine=e&period=all&lens=branded"),
    );
  });

  it("timeseries(7, 'e', 'all') -> /api/timeseries?brand_id=7&engine=e&lens=all", async () => {
    const fn = stubFetch(okResponse({}));
    await api.timeseries(7, "e", "all");
    expect(fetchedUrl(fn)).toBe(u("/api/timeseries?brand_id=7&engine=e&lens=all"));
  });

  it("results(3) -> /api/results?run_id=3 (no lens)", async () => {
    const fn = stubFetch(okResponse({}));
    await api.results(3);
    expect(fetchedUrl(fn)).toBe(u("/api/results?run_id=3"));
    expect(fetchedUrl(fn)).not.toContain("lens");
  });

  it("results(3, 'branded') -> /api/results?run_id=3&lens=branded", async () => {
    const fn = stubFetch(okResponse({}));
    await api.results(3, "branded");
    expect(fetchedUrl(fn)).toBe(u("/api/results?run_id=3&lens=branded"));
  });

  it("each method issues exactly one fetch", async () => {
    const fn = stubFetch(okResponse({}));
    await api.timeseries(1, "e", "all");
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

describe("reportUrl", () => {
  it("returns the report URL string and does NOT call fetch", () => {
    const fn = stubFetch(okResponse({}));

    const url = api.reportUrl(7, "e", "all");

    expect(url).toBe(u("/api/report?brand_id=7&engine=e&period=all"));
    expect(fn).not.toHaveBeenCalled();
  });

  it("builds the URL for the 'today' period too", () => {
    stubFetch(okResponse({}));

    expect(api.reportUrl(42, "google", "today")).toBe(
      u("/api/report?brand_id=42&engine=google&period=today"),
    );
  });

  it("URL-encodes special characters in the engine for reportUrl", () => {
    stubFetch(okResponse({}));

    expect(api.reportUrl(1, "a/b", "all")).toBe(
      u("/api/report?brand_id=1&engine=a%2Fb&period=all"),
    );
  });
});

describe("API_BASE prefix", () => {
  it("prefixes the resolved API_BASE, so the request ends with the /api path", async () => {
    const fn = stubFetch(okResponse([]));
    await api.brands();
    expect(fetchedUrl(fn)).toBe(`${BASE}/api/brands`);
    expect(fetchedUrl(fn).endsWith("/api/brands")).toBe(true);
  });
});
