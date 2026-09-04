# Metric glossary for the run summary (STEP 7 detail)

> Loaded when you need the precise reading of a metric. Authority: `pipeline/INTERFACES.md §4`.
> All seven come from the `lens="all"` row of the `pipeline.aggregate` JSON.


- **Answer coverage** (`overview_coverage`) — share of queries where a grounded,
  source-backed answer rendered at all (an AI Overview on `google`; a web-search-backed
  answer on the chat engines).
- **Visibility in sources** (`visibility_in_sources`) — share of overview queries where the
  target domain made it into `sources` (`n_in_sources / n_overviews`).
- **Visibility in citations** (`visibility_in_citations`) — share of overview queries where
  the domain is cited in the answer (`n_cited / n_overviews`).
- **Average source position** (`avg_source_position`) — average best (`min`) rank of the
  domain among sources (lower = better; `—` if the domain never appears in sources).
- **Average citation position** (`avg_citation_position`) — average best (`min`) rank of the
  domain among citations (lower = better; `—` if the domain is never cited).
- **Relative citation** (`relative_citation`) — the **source→citation conversion**: of the
  queries where the domain was in `sources`, the share where it was actually cited
  (`n_cited / n_in_sources`; **higher = better**, `∈ [0, 1]`; `—` if the domain never appears
  in sources). This is the last step of the visibility funnel
  (`n_cited ≤ n_in_sources ≤ n_overviews ≤ n_queries`).
- **Brand mention rate** (`brand_mention_rate`) — of the grounded answers, the share whose
  prose mentions the brand **name**, linked or not (`n_brand_mentions / n_overviews`;
  higher = better). An **adjacent axis, not a funnel stage** — an unlinked mention is
  invisible to the link funnel, so do not read it as nested in sources/citations
  (INTERFACES §4).
