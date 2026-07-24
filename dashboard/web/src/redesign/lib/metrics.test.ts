import { describe, it, expect } from "vitest";
import type { MetricRow } from "./api";
import { METRICS, type MetricDef, type MetricKey } from "./metrics";

const fullRow: MetricRow = {
  lens: "all",
  n_queries: 100,
  n_overviews: 80,
  overview_coverage: 0.8,
  n_in_sources: 50,
  visibility_in_sources: 0.625,
  n_cited: 30,
  visibility_in_citations: 0.375,
  avg_source_position: 2.4,
  avg_citation_position: 3.7,
  relative_citation: 0.6,
  n_brand_mentions: 40,
  brand_mention_rate: 0.5,
  overview_coverage_delta: 0.11,
  visibility_in_sources_delta: -0.22,
  visibility_in_citations_delta: 0.33,
  avg_source_position_delta: -0.44,
  avg_citation_position_delta: 0.55,
  relative_citation_delta: 0.66,
  brand_mention_rate_delta: 0.77,
};

const byKey = (k: MetricKey): MetricDef => {
  const def = METRICS.find((d) => d.key === k);
  if (!def) throw new Error(`missing metric def: ${k}`);
  return def;
};

describe("METRICS array shape", () => {
  it("contains exactly seven metric defs", () => {
    expect(METRICS).toHaveLength(7);
  });

  it("exposes the seven contract keys in the documented order", () => {
    expect(METRICS.map((d) => d.key)).toEqual([
      "overview_coverage",
      "visibility_in_sources",
      "visibility_in_citations",
      "relative_citation",
      "brand_mention_rate",
      "avg_source_position",
      "avg_citation_position",
    ]);
  });

  it("has unique keys", () => {
    const keys = METRICS.map((d) => d.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("derives every i18n key from its metric key (label/hint namespaces)", () => {
    for (const d of METRICS) {
      expect(d.labelKey).toBe(`metrics.${d.key}.label`);
      expect(d.infoKey).toBe(`metrics.${d.key}.hint`);
    }
  });

  it("marks the five rate metrics as percentages and the two positions as not", () => {
    const pctKeys = METRICS.filter((d) => d.asPct).map((d) => d.key);
    expect(pctKeys).toEqual([
      "overview_coverage",
      "visibility_in_sources",
      "visibility_in_citations",
      "relative_citation",
      "brand_mention_rate",
    ]);
    const nonPctKeys = METRICS.filter((d) => !d.asPct).map((d) => d.key);
    expect(nonPctKeys).toEqual(["avg_source_position", "avg_citation_position"]);
  });

  it("treats rates as higher-is-better and positions as lower-is-better", () => {
    expect(METRICS.filter((d) => d.higherIsBetter).map((d) => d.key)).toEqual([
      "overview_coverage",
      "visibility_in_sources",
      "visibility_in_citations",
      "relative_citation",
      "brand_mention_rate",
    ]);
    expect(METRICS.filter((d) => !d.higherIsBetter).map((d) => d.key)).toEqual([
      "avg_source_position",
      "avg_citation_position",
    ]);
  });
});

describe("overview_coverage def", () => {
  const def = byKey("overview_coverage");

  it("has the expected static fields", () => {
    expect(def.key).toBe("overview_coverage");
    expect(def.asPct).toBe(true);
    expect(def.higherIsBetter).toBe(true);
    expect(def.labelKey).toBe("metrics.overview_coverage.label");
    expect(def.infoKey).toBe("metrics.overview_coverage.hint");
    expect(def.subKey).toBe("report.card_coverage_sub");
  });

  it("value() maps to row.overview_coverage", () => {
    expect(def.value(fullRow)).toBe(0.8);
    expect(def.value(fullRow)).toBe(fullRow.overview_coverage);
  });

  it("delta() maps to row.overview_coverage_delta", () => {
    expect(def.delta(fullRow)).toBe(0.11);
    expect(def.delta(fullRow)).toBe(fullRow.overview_coverage_delta);
  });

  it("subVars() returns the coverage numerator/denominator counts", () => {
    expect(def.subVars).toBeDefined();
    expect(def.subVars!(fullRow)).toEqual({ n_overviews: 80, n_queries: 100 });
  });
});

describe("visibility_in_sources def", () => {
  const def = byKey("visibility_in_sources");

  it("has the expected static fields", () => {
    expect(def.key).toBe("visibility_in_sources");
    expect(def.asPct).toBe(true);
    expect(def.higherIsBetter).toBe(true);
    expect(def.labelKey).toBe("metrics.visibility_in_sources.label");
    expect(def.infoKey).toBe("metrics.visibility_in_sources.hint");
    expect(def.subKey).toBe("report.card_visibility_sub");
  });

  it("value() maps to row.visibility_in_sources", () => {
    expect(def.value(fullRow)).toBe(0.625);
    expect(def.value(fullRow)).toBe(fullRow.visibility_in_sources);
  });

  it("delta() maps to row.visibility_in_sources_delta", () => {
    expect(def.delta(fullRow)).toBe(-0.22);
    expect(def.delta(fullRow)).toBe(fullRow.visibility_in_sources_delta);
  });

  it("subVars() returns n_in_sources as the numerator over n_overviews", () => {
    expect(def.subVars).toBeDefined();
    expect(def.subVars!(fullRow)).toEqual({ numerator: 50, n_overviews: 80 });
  });
});

describe("visibility_in_citations def", () => {
  const def = byKey("visibility_in_citations");

  it("has the expected static fields", () => {
    expect(def.key).toBe("visibility_in_citations");
    expect(def.asPct).toBe(true);
    expect(def.higherIsBetter).toBe(true);
    expect(def.labelKey).toBe("metrics.visibility_in_citations.label");
    expect(def.infoKey).toBe("metrics.visibility_in_citations.hint");
    expect(def.subKey).toBe("report.card_visibility_sub");
  });

  it("value() maps to row.visibility_in_citations", () => {
    expect(def.value(fullRow)).toBe(0.375);
    expect(def.value(fullRow)).toBe(fullRow.visibility_in_citations);
  });

  it("delta() maps to row.visibility_in_citations_delta", () => {
    expect(def.delta(fullRow)).toBe(0.33);
    expect(def.delta(fullRow)).toBe(fullRow.visibility_in_citations_delta);
  });

  it("subVars() returns n_cited as the numerator over n_overviews", () => {
    expect(def.subVars).toBeDefined();
    expect(def.subVars!(fullRow)).toEqual({ numerator: 30, n_overviews: 80 });
  });
});

describe("relative_citation def", () => {
  const def = byKey("relative_citation");

  it("has the expected static fields", () => {
    expect(def.key).toBe("relative_citation");
    expect(def.asPct).toBe(true);
    expect(def.higherIsBetter).toBe(true);
    expect(def.labelKey).toBe("metrics.relative_citation.label");
    expect(def.infoKey).toBe("metrics.relative_citation.hint");
  });

  it("value() maps to row.relative_citation", () => {
    expect(def.value(fullRow)).toBe(0.6);
    expect(def.value(fullRow)).toBe(fullRow.relative_citation);
  });

  it("delta() maps to row.relative_citation_delta", () => {
    expect(def.delta(fullRow)).toBe(0.66);
    expect(def.delta(fullRow)).toBe(fullRow.relative_citation_delta);
  });

  it("uses subRender to compose the cited-of-in-sources count line", () => {
    expect(def.subRender).toBeDefined();
    const line = def.subRender!(fullRow, (k) => k);
    expect(line).toContain(String(fullRow.n_cited));
    expect(line).toContain(String(fullRow.n_in_sources));
  });
});

describe("brand_mention_rate def", () => {
  const def = byKey("brand_mention_rate");

  it("has the expected static fields", () => {
    expect(def.key).toBe("brand_mention_rate");
    expect(def.asPct).toBe(true);
    expect(def.higherIsBetter).toBe(true);
    expect(def.labelKey).toBe("metrics.brand_mention_rate.label");
    expect(def.infoKey).toBe("metrics.brand_mention_rate.hint");
    expect(def.subKey).toBe("report.card_visibility_sub");
  });

  it("value() maps to row.brand_mention_rate", () => {
    expect(def.value(fullRow)).toBe(0.5);
    expect(def.value(fullRow)).toBe(fullRow.brand_mention_rate);
  });

  it("delta() maps to row.brand_mention_rate_delta", () => {
    expect(def.delta(fullRow)).toBe(0.77);
    expect(def.delta(fullRow)).toBe(fullRow.brand_mention_rate_delta);
  });

  it("subVars() returns n_brand_mentions as the numerator over n_overviews", () => {
    expect(def.subVars).toBeDefined();
    expect(def.subVars!(fullRow)).toEqual({ numerator: 40, n_overviews: 80 });
  });

  it("subVars() falls back to 0 when n_brand_mentions is absent (old DB)", () => {
    const { n_brand_mentions: _omitted, ...rest } = fullRow;
    expect(def.subVars!(rest as typeof fullRow)).toEqual({
      numerator: 0,
      n_overviews: 80,
    });
  });
});

describe("avg_source_position def", () => {
  const def = byKey("avg_source_position");

  it("has the expected static fields", () => {
    expect(def.key).toBe("avg_source_position");
    expect(def.asPct).toBe(false);
    expect(def.higherIsBetter).toBe(false);
    expect(def.labelKey).toBe("metrics.avg_source_position.label");
    expect(def.infoKey).toBe("metrics.avg_source_position.hint");
    expect(def.subKey).toBe("common.lower_is_better");
  });

  it("value() maps to row.avg_source_position", () => {
    expect(def.value(fullRow)).toBe(2.4);
    expect(def.value(fullRow)).toBe(fullRow.avg_source_position);
  });

  it("delta() maps to row.avg_source_position_delta", () => {
    expect(def.delta(fullRow)).toBe(-0.44);
    expect(def.delta(fullRow)).toBe(fullRow.avg_source_position_delta);
  });

  it("has no subVars (position cards use the static lower-is-better sub-line)", () => {
    expect(def.subVars).toBeUndefined();
  });
});

describe("avg_citation_position def", () => {
  const def = byKey("avg_citation_position");

  it("has the expected static fields", () => {
    expect(def.key).toBe("avg_citation_position");
    expect(def.asPct).toBe(false);
    expect(def.higherIsBetter).toBe(false);
    expect(def.labelKey).toBe("metrics.avg_citation_position.label");
    expect(def.infoKey).toBe("metrics.avg_citation_position.hint");
    expect(def.subKey).toBe("common.lower_is_better");
  });

  it("value() maps to row.avg_citation_position", () => {
    expect(def.value(fullRow)).toBe(3.7);
    expect(def.value(fullRow)).toBe(fullRow.avg_citation_position);
  });

  it("delta() maps to row.avg_citation_position_delta", () => {
    expect(def.delta(fullRow)).toBe(0.55);
    expect(def.delta(fullRow)).toBe(fullRow.avg_citation_position_delta);
  });

  it("has no subVars (position cards use the static lower-is-better sub-line)", () => {
    expect(def.subVars).toBeUndefined();
  });
});

describe("defensive null / undefined pass-through", () => {
  const nullRow: MetricRow = {
    lens: "general",
    n_queries: 0,
    n_overviews: 0,
    overview_coverage: null,
    n_in_sources: 0,
    visibility_in_sources: null,
    n_cited: 0,
    visibility_in_citations: null,
    avg_source_position: null,
    avg_citation_position: null,
    relative_citation: null,
    n_brand_mentions: null,
    brand_mention_rate: null,
  };

  it("value() returns null when the underlying metric is null", () => {
    for (const d of METRICS) {
      expect(d.value(nullRow)).toBeNull();
    }
  });

  it("delta() returns undefined when the delta field is absent", () => {
    for (const d of METRICS) {
      expect(d.delta(nullRow)).toBeUndefined();
    }
  });

  it("subVars() still returns the count object even when rates are null", () => {
    expect(byKey("overview_coverage").subVars!(nullRow)).toEqual({
      n_overviews: 0,
      n_queries: 0,
    });
    expect(byKey("visibility_in_sources").subVars!(nullRow)).toEqual({
      numerator: 0,
      n_overviews: 0,
    });
    expect(byKey("visibility_in_citations").subVars!(nullRow)).toEqual({
      numerator: 0,
      n_overviews: 0,
    });
  });
});
