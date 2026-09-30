# Review backlog

Tree reviewed: `27244fd` (`main` = `origin/main`).

GitHub Actions run [35872916742](https://github.com/Pupok462/open-geo/actions/runs/35872916742) (`feat: flag answers that reuse earlier chat context`). Frontend job succeeded. Python job failed after the tests themselves passed:

```
TOTAL                             4930    181   1362    119  94.8%
FAIL Required test coverage of 95% not reached. Total coverage: 94.79%
1356 passed, 1 warning in 41.74s
```

CPython 3.11.16 on Ubuntu. Files under 95 on that run: `kernel/cluster.py` (69.7), `kernel/collect.py` (84.4), `kernel/classify.py` (88.1), `kernel/ingest.py` (90.4), `pipeline/db.py` (84.0), `demand/config.py` (90.2), `demand/providers/bing.py` (92.1), `demand/providers/__init__.py` (94.4).

Local re-run of the CI command (`python -m pytest --cov --cov-report=term-missing --cov-report=xml --cov-fail-under=95`, CPython 3.11.6) is the check that the gate is closed. Pushing `origin/main` is out of scope, so the Actions badge stays red until that push.

| Area | Result | Evidence |
|---|---|---|
| Coverage shortfall on the eight files above | fixed | `tests/test_review_backlog.py` calls the shipped functions on the red-run lines: `test_classify_partial_brand_long_phrase_and_gate`, `test_cluster_known_text_child_and_empty_tokens`, `test_collect_caps_errors_seeds_and_default_expand`, `test_ingest_scheme_tags_seed_cap_and_profile_from_url`, `test_comparable_same_different_and_unknown`, `test_resume_check_hash_decides_whether_two_sets_are_one_measurement`, `test_question_set_backfill_edges`, `test_stats_readers_reraise_unexpected_sql`, `test_demand_config_blank_key_env_autoload_and_worldwide_locale`, `test_bing_uses_cache_and_skips_dirty_related_rows`, `test_resolve_skips_provider_that_does_not_support_locale`. After that run the eight files are at 100% (`pipeline/db.py` included). One dead branch was removed; see below. The 95% gate and the `source` / `omit` lists in `pyproject.toml` and `.github/workflows/ci.yml` are unchanged. |
| Funnel `n_cited ≤ n_in_sources ≤ n_overviews ≤ n_queries` and citations ⊆ sources | no defect | `pipeline/schema.py` `QueryCapture._citations_subset_of_sources` rejects a cited domain absent from sources, and a non-empty `target_citation_ranks` without `target_source_ranks`. `pipeline/aggregate.py` `_compute_scope` counts both source and citation hits only on overview rows. `tests/test_pipeline.py::test_funnel_relative_citation` asserts the inequality on a stored run (`n_cited` 2, `n_in_sources` 3, `n_overviews` 4, `n_queries` 4). `tests/test_pipeline.py::test_schema_citation_not_in_sources_raises` and `test_schema_citation_subset_of_sources_ok`. `tests/test_aggregate.py::test_scope_funnel_relative_citation_conversion`. |
| `prior_context` / `prior_context_evidence` survive capture schema → SQLite → run artifact, and the PDF states the marker | no defect | `tests/test_review_backlog.py::test_prior_context_survives_capture_sqlite_and_artifact`: a `QueryCapture` whose answer contains «Учитывая, что вы интересовались…» stores `prior_context = 1` and the same evidence string, and `build_run_artifact` returns that pair. PDF row: `tests/test_report_format.py::test_result_row_marks_prior_context` puts `report.prior_context_marker` on the result cell when the flag is set. |
| Two runs with different question-set hashes are not one measurement | no defect | `pipeline/db.py` `comparable`: both hashes → `same` or `different`; both labels and no hashes → `same` or `different`; anything else → `unknown`. `tests/test_review_backlog.py::test_comparable_same_different_and_unknown`. `resume_check` refuses a captured subset when the running run's hash differs from the CSV hash, and accepts it when the hash matches: `test_resume_check_hash_decides_whether_two_sets_are_one_measurement`. |
| An all-engines compare does not blend engines into one score | no defect | `report/generate.py` `_engine_matrix_table` emits one row per engine from that engine's own `metrics["all"]`. `tests/test_review_backlog.py::test_all_engines_matrix_does_not_blend_scores`: google stays 25% visibility in citations, alice stays 50%. Dashboard matrix keeps per-engine rates in `tests/test_api.py::test_engine_matrix_today_lists_every_engine`. |
| Demand refuses to emit questions from a cluster that has no measurement | no defect | `demand/core.py` `to_candidates` appends an error and ships nothing when no phrase has both `provider` and `scope`. `tests/test_demand_core.py::test_unmeasured_cluster_cannot_ship_questions` (`candidates == []`, error starts with `no measured phrase`). `test_scope_without_provider_is_not_evidence`. |

## Coverage fix, file by file

Red-run missing lines, and the test that now runs them:

| File | Red-run lines | Test |
|---|---|---|
| `kernel/classify.py` | 82, 87, 94, 107, 109, 120, 124, 126 | `test_classify_partial_brand_long_phrase_and_gate` |
| `kernel/cluster.py` | 12, 20, 38-44, 55, 57-58 | `test_cluster_known_text_child_and_empty_tokens` |
| `kernel/collect.py` | 65, 68-69, 72, 95→70, 130→132, 134, 136, 138→142, 141, 147, 154-156 | `test_collect_caps_errors_seeds_and_default_expand` |
| `kernel/ingest.py` | 18→20, 28, 32, 42, 68-69, 114, 116 | `test_ingest_scheme_tags_seed_cap_and_profile_from_url` |
| `pipeline/db.py` | 106, 109-110, 141, 143-144, 355-365, 375-380, 393, 404, 498, 521 | `test_comparable_same_different_and_unknown`, `test_resume_check_hash_decides_whether_two_sets_are_one_measurement`, `test_question_set_backfill_edges`, `test_stats_readers_reraise_unexpected_sql` |
| `demand/config.py` | 30, 39, 112 | `test_demand_config_blank_key_env_autoload_and_worldwide_locale` |
| `demand/providers/bing.py` | 53→66, 89, 107→117, 121, 123→119 | `test_bing_uses_cache_and_skips_dirty_related_rows` |
| `demand/providers/__init__.py` | 72-73 | `test_resolve_skips_provider_that_does_not_support_locale` |

`kernel/collect.py` line 93 (`if q is None: continue`) was dead. `round` already drops an empty phrase and any phrase whose normalized text is already known, and those are the only inputs for which `attach` returns `None`. The branch could not change a result. It was deleted. Question attachment, the cap, and the auto-gate are unchanged (`pipeline/INTERFACES.md` does not define this kernel loop).

No `ROADMAP.md` item is marked fixed here.
