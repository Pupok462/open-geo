from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard import api
from pipeline.db import (
    create_run,
    get_conn,
    get_or_create_brand,
    init_db,
    update_run_counts,
)

ENGINE = "google"

_DELTA_METRICS = (
    "overview_coverage",
    "visibility_in_sources",
    "visibility_in_citations",
    "avg_source_position",
    "avg_citation_position",
)


def _example_id(client) -> int:
    brands = client.get("/api/brands").json()
    return next(b["id"] for b in brands if b["name"] == "Example")


def test_db_path_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("OPEN_GEO_DB", raising=False)
    expected = str(api._REPO_ROOT / "data" / "aeo.db")
    assert api._db_path() == expected
    assert Path(api._db_path()).is_absolute()


def test_db_path_absolute_env_is_respected(monkeypatch, tmp_path):
    abs_path = tmp_path / "somewhere" / "custom.db"
    monkeypatch.setenv("OPEN_GEO_DB", str(abs_path))
    assert api._db_path() == str(abs_path)


def test_db_path_relative_env_resolved_against_repo_root(monkeypatch):
    monkeypatch.setenv("OPEN_GEO_DB", "data/throwaway.db")
    assert api._db_path() == str(api._REPO_ROOT / "data" / "throwaway.db")


def test_loads_none_returns_default():
    sentinel = ["DEFAULT"]
    assert api._loads(None, sentinel) is sentinel


def test_loads_empty_string_returns_default():
    sentinel = {"d": 1}
    assert api._loads("", sentinel) is sentinel


def test_loads_valid_json_is_parsed():
    assert api._loads('[1, 2, 3]', []) == [1, 2, 3]
    assert api._loads('{"a": 1}', None) == {"a": 1}


def test_loads_malformed_json_returns_default():
    assert api._loads("{not json", []) == []
    assert api._loads("nope", "fallback") == "fallback"


def test_loads_non_string_returns_default():
    assert api._loads(12345, "fb") == "fb"  # type: ignore[arg-type]


def test_connect_missing_db_returns_503(make_client, tmp_path):
    missing = tmp_path / "does_not_exist.db"
    assert not missing.exists()
    client = make_client(missing)
    resp = client.get("/api/brands")
    assert resp.status_code == 503
    assert "database not found" in resp.json()["detail"]


def test_connect_missing_db_503_on_metrics(make_client, tmp_path):
    client = make_client(tmp_path / "nope.db")
    resp = client.get("/api/metrics", params={"brand_id": 1, "engine": ENGINE})
    assert resp.status_code == 503


def test_health_reports_existing_db(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["db"] == seeded_db_path
    assert body["db_exists"] is True


def test_health_reports_missing_db(make_client, tmp_path):
    missing = tmp_path / "ghost.db"
    client = make_client(missing)
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["db"] == str(missing)
    assert body["db_exists"] is False


def test_brands_listed_sorted(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    rows = client.get("/api/brands").json()
    names = [r["name"] for r in rows]
    assert "Example" in names and "Globex" in names
    assert names == sorted(names, key=str.lower)
    for r in rows:
        assert set(r.keys()) == {"id", "name", "domain"}
    example = next(r for r in rows if r["name"] == "Example")
    assert example["domain"] == "example.com"


def test_brands_empty_db_returns_empty_list(make_client, empty_db_path):
    client = make_client(empty_db_path)
    assert client.get("/api/brands").json() == []


def test_engines_distinct_for_brand(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    engines = client.get("/api/engines", params={"brand_id": example}).json()
    assert engines == [ENGINE]


def test_engines_unknown_brand_is_empty(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    assert client.get("/api/engines", params={"brand_id": 999_999}).json() == []


def test_engines_requires_brand_id(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    assert client.get("/api/engines").status_code == 422


def test_runs_newest_first_includes_running(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    runs = client.get("/api/runs", params={"brand_id": example}).json()
    assert len(runs) == 4
    statuses = [r["status"] for r in runs]
    assert "running" in statuses
    run_ats = [r["run_at"] for r in runs]
    assert run_ats == sorted(run_ats, reverse=True)
    assert runs[0]["status"] == "running"
    expected = {"run_id", "run_at", "status", "engine", "n_queries", "n_ok", "n_failed"}
    for r in runs:
        assert set(r.keys()) == expected


def test_runs_engine_filter(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    matching = client.get(
        "/api/runs", params={"brand_id": example, "engine": ENGINE}
    ).json()
    assert len(matching) == 4
    assert all(r["engine"] == ENGINE for r in matching)
    none = client.get(
        "/api/runs", params={"brand_id": example, "engine": "bing_copilot"}
    ).json()
    assert none == []


def test_runs_unknown_brand_empty(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    assert client.get("/api/runs", params={"brand_id": 424_242}).json() == []


def test_metrics_today_shape_and_deltas(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()

    assert body["period"] == "today"
    assert body["run"] is not None
    assert body["prev_run"] is not None
    assert body["run"]["status"] == "done"

    rows = {r["lens"]: r for r in body["metrics"]}
    assert body["metrics"][0]["lens"] == "all"
    assert {"all", "general", "branded", "comparative"} <= set(rows)

    for row in body["metrics"]:
        for m in _DELTA_METRICS:
            assert f"{m}_delta" in row
            assert f"{m}_prev" in row

    all_row = rows["all"]
    assert all_row["overview_coverage_delta"] is not None
    assert all_row["overview_coverage_prev"] is not None
    assert all_row["overview_coverage_delta"] == pytest.approx(
        all_row["overview_coverage"] - all_row["overview_coverage_prev"]
    )


def test_metrics_today_delta_none_when_metric_absent(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()
    comp = next(r for r in body["metrics"] if r["lens"] == "comparative")
    assert comp["avg_citation_position"] is None
    assert comp["avg_citation_position_delta"] is None
    assert comp["avg_citation_position_prev"] is None


def test_metrics_today_lens_filter(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics",
        params={"brand_id": example, "engine": ENGINE, "period": "today", "lens": "branded"},
    ).json()
    lenses = [r["lens"] for r in body["metrics"]]
    assert lenses == ["branded"]


def test_metrics_today_first_run_has_no_prev(make_client, dash_fixture_db_path):
    conn = get_conn(dash_fixture_db_path)
    try:
        example = conn.execute("SELECT id FROM brands WHERE name='Example'").fetchone()["id"]
        oldest = conn.execute(
            "SELECT id FROM runs WHERE brand_id=? AND engine=? AND status='done' "
            "ORDER BY run_at ASC, id ASC LIMIT 1",
            (example, ENGINE),
        ).fetchone()["id"]
        others = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM runs WHERE brand_id=? AND engine=? AND id != ?",
                (example, ENGINE, oldest),
            ).fetchall()
        ]
        for rid in others:
            conn.execute("DELETE FROM domain_stats WHERE run_id=?", (rid,))
            conn.execute("DELETE FROM metrics WHERE run_id=?", (rid,))
            conn.execute("DELETE FROM results WHERE run_id=?", (rid,))
            conn.execute("DELETE FROM runs WHERE id=?", (rid,))
        conn.commit()
    finally:
        conn.close()

    client = make_client(dash_fixture_db_path)
    body = client.get(
        "/api/metrics",
        params={"brand_id": example, "engine": ENGINE, "period": "today"},
    ).json()
    assert body["run"]["run_id"] == oldest
    assert body["prev_run"] is None
    for row in body["metrics"]:
        for m in _DELTA_METRICS:
            assert row[f"{m}_delta"] is None
            assert row[f"{m}_prev"] is None


def test_metrics_today_no_done_runs_returns_empty(make_client, dash_fixture_db_path):
    conn = get_conn(dash_fixture_db_path)
    try:
        fresh = get_or_create_brand(conn, "Freshly", "freshly.example")
        create_run(conn, fresh, ENGINE)
        conn.commit()
    finally:
        conn.close()

    client = make_client(dash_fixture_db_path)
    body = client.get(
        "/api/metrics", params={"brand_id": fresh, "engine": ENGINE, "period": "today"}
    ).json()
    assert body["run"] is None
    assert body["prev_run"] is None
    assert body["metrics"] == []


def test_metrics_invalid_period_400(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.get(
        "/api/metrics",
        params={"brand_id": example, "engine": ENGINE, "period": "yesterday"},
    )
    assert resp.status_code == 400
    assert "today" in resp.json()["detail"]


def test_metrics_all_aggregated(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "all"}
    ).json()

    assert body["period"] == "all"
    assert body["run"] is None and body["prev_run"] is None
    assert body["n_runs"] == 3
    assert body["metrics"]
    assert body["metrics"][0]["lens"] == "all"

    for row in body["metrics"]:
        for m in _DELTA_METRICS:
            assert row[f"{m}_delta"] is None
            assert row[f"{m}_prev"] is None
        for key in ("overview_coverage", "visibility_in_sources", "visibility_in_citations"):
            v = row[key]
            if v is not None:
                assert 0.0 <= v <= 1.0


def test_metrics_all_lens_filter(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics",
        params={"brand_id": example, "engine": ENGINE, "period": "all", "lens": "branded"},
    ).json()
    assert [r["lens"] for r in body["metrics"]] == ["branded"]


def test_aggregate_period_sums_and_recomputes(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        rows = api._aggregate_period(conn, 1, ENGINE, None)
        by_lens = {r["lens"]: r for r in rows}
        agg = by_lens["all"]

        tot = conn.execute(
            """
            SELECT SUM(m.n_queries) q, SUM(m.n_overviews) o,
                   SUM(m.n_in_sources) s, SUM(m.n_cited) c,
                   SUM(CASE WHEN m.avg_source_position IS NOT NULL
                            THEN m.avg_source_position*m.n_in_sources END) ssr,
                   SUM(CASE WHEN m.avg_citation_position IS NOT NULL
                            THEN m.avg_citation_position*m.n_cited END) scr
            FROM metrics m JOIN runs r ON r.id=m.run_id
            WHERE r.brand_id=1 AND r.engine=? AND r.status='done' AND m.lens='all'
            """,
            (ENGINE,),
        ).fetchone()

        assert agg["n_queries"] == tot["q"]
        assert agg["n_overviews"] == tot["o"]
        assert agg["n_in_sources"] == tot["s"]
        assert agg["n_cited"] == tot["c"]
        assert agg["overview_coverage"] == pytest.approx(tot["o"] / tot["q"])
        assert agg["visibility_in_sources"] == pytest.approx(tot["s"] / tot["o"])
        assert agg["visibility_in_citations"] == pytest.approx(tot["c"] / tot["o"])
        assert agg["avg_source_position"] == pytest.approx(tot["ssr"] / tot["s"])
        assert agg["avg_citation_position"] == pytest.approx(tot["scr"] / tot["c"])
    finally:
        conn.close()


def test_aggregate_period_lens_filter(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        rows = api._aggregate_period(conn, 1, ENGINE, "general")
        assert [r["lens"] for r in rows] == ["general"]
    finally:
        conn.close()


def test_aggregate_period_degenerate_guards(empty_conn):
    bid = get_or_create_brand(empty_conn, "Z", "z.example")
    rid = create_run(empty_conn, bid, ENGINE)
    update_run_counts(empty_conn, rid, n_queries=0, n_ok=0, n_failed=0, status="done")
    empty_conn.execute(
        """INSERT INTO metrics (run_id, brand_id, engine, lens, n_queries, n_overviews,
                overview_coverage, n_in_sources, visibility_in_sources, n_cited,
                visibility_in_citations, avg_source_position, avg_citation_position,
                computed_at)
           VALUES (?,?,?,?,0,0,NULL,0,NULL,0,NULL,NULL,NULL,'now')""",
        (rid, bid, ENGINE, "all"),
    )
    empty_conn.commit()

    rows = api._aggregate_period(empty_conn, bid, ENGINE, None)
    assert len(rows) == 1
    row = rows[0]
    assert row["n_queries"] == 0 and row["n_overviews"] == 0
    assert row["overview_coverage"] is None
    assert row["visibility_in_sources"] is None
    assert row["visibility_in_citations"] is None
    assert row["avg_source_position"] is None
    assert row["avg_citation_position"] is None


def test_aggregate_period_no_done_runs_empty(empty_conn):
    bid = get_or_create_brand(empty_conn, "OnlyRunning", "or.example")
    create_run(empty_conn, bid, ENGINE)
    empty_conn.commit()
    assert api._aggregate_period(empty_conn, bid, ENGINE, None) == []


def test_latest_run_id_only_done_excludes_running(dash_fixture_db_path):
    conn = get_conn(dash_fixture_db_path)
    try:
        example = conn.execute("SELECT id FROM brands WHERE name='Example'").fetchone()["id"]
        any_latest = api._latest_run_id(conn, example, ENGINE, only_done=False)
        done_latest = api._latest_run_id(conn, example, ENGINE, only_done=True)
        assert any_latest != done_latest
        assert conn.execute(
            "SELECT status FROM runs WHERE id=?", (any_latest,)
        ).fetchone()["status"] == "running"
        assert conn.execute(
            "SELECT status FROM runs WHERE id=?", (done_latest,)
        ).fetchone()["status"] == "done"
    finally:
        conn.close()


def test_latest_run_id_before_picks_strictly_earlier(dash_fixture_db_path):
    conn = get_conn(dash_fixture_db_path)
    try:
        example = conn.execute("SELECT id FROM brands WHERE name='Example'").fetchone()["id"]
        latest = api._latest_run_id(conn, example, ENGINE, only_done=True)
        run_at = conn.execute(
            "SELECT run_at FROM runs WHERE id=?", (latest,)
        ).fetchone()["run_at"]
        prev = api._latest_run_id(
            conn, example, ENGINE, only_done=True, before_run_at=run_at, before_id=latest
        )
        assert prev is not None
        assert prev != latest
        prev_at = conn.execute(
            "SELECT run_at FROM runs WHERE id=?", (prev,)
        ).fetchone()["run_at"]
        assert prev_at < run_at
    finally:
        conn.close()


def test_latest_run_id_none_when_nothing_matches(empty_conn):
    assert api._latest_run_id(empty_conn, 12345, ENGINE, only_done=True) is None


def test_metrics_by_lens_returns_dict(seeded_db_path):
    conn = get_conn(seeded_db_path)
    try:
        latest = conn.execute(
            "SELECT id FROM runs ORDER BY run_at DESC, id DESC LIMIT 1"
        ).fetchone()["id"]
        by_lens = api._metrics_by_lens(conn, latest)
        assert {"all", "general", "branded", "comparative"} == set(by_lens)
        assert by_lens["all"]["lens"] == "all"
        assert "overview_coverage" in by_lens["all"]
    finally:
        conn.close()


def test_metrics_by_lens_empty_for_unknown_run(empty_conn):
    assert api._metrics_by_lens(empty_conn, 99999) == {}


def test_timeseries_oldest_to_newest_done_only(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/timeseries", params={"brand_id": example, "engine": ENGINE, "lens": "all"}
    ).json()
    assert body["lens"] == "all"
    points = body["points"]
    assert len(points) == 3
    assert all(p["status"] == "done" for p in points)
    run_ats = [p["run_at"] for p in points]
    assert run_ats == sorted(run_ats)
    for col in ("n_queries", "n_overviews", "overview_coverage",
                "visibility_in_sources", "visibility_in_citations",
                "avg_source_position", "avg_citation_position"):
        assert col in points[0]


def test_timeseries_default_lens_is_all(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/timeseries", params={"brand_id": 1, "engine": ENGINE}
    ).json()
    assert body["lens"] == "all"
    assert len(body["points"]) == 5


def test_timeseries_lens_filter(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/timeseries", params={"brand_id": 1, "engine": ENGINE, "lens": "branded"}
    ).json()
    assert body["lens"] == "branded"
    assert len(body["points"]) == 5
    assert all(p["lens"] == "branded" for p in body["points"])


def test_timeseries_unknown_lens_empty(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/timeseries", params={"brand_id": 1, "engine": ENGINE, "lens": "nope"}
    ).json()
    assert body["points"] == []


def test_results_decoded_payload(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    runs = client.get("/api/runs", params={"brand_id": example, "engine": ENGINE}).json()
    done_run = next(r for r in runs if r["status"] == "done")["run_id"]

    body = client.get("/api/results", params={"run_id": done_run}).json()
    assert body["run"]["run_id"] == done_run
    assert body["lens"] is None
    rows = body["results"]
    assert rows

    for r in rows:
        assert isinstance(r["sources"], list)
        assert isinstance(r["citations"], list)
        assert isinstance(r["target_source_ranks"], list)
        assert isinstance(r["target_citation_ranks"], list)
        assert isinstance(r["overview_present"], bool)
        assert isinstance(r["brand_in_answer_text"], bool)
        assert r["sentiment"] is None or isinstance(r["sentiment"], str)

    src_row = next(r for r in rows if r["sources"])
    link = src_row["sources"][0]
    assert {"rank", "url", "domain"} <= set(link)


def test_results_lens_filter(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    runs = client.get("/api/runs", params={"brand_id": example, "engine": ENGINE}).json()
    done_run = next(r for r in runs if r["status"] == "done")["run_id"]

    body = client.get(
        "/api/results", params={"run_id": done_run, "lens": "branded"}
    ).json()
    assert body["lens"] == "branded"
    assert body["results"]
    assert all(r["lens"] == "branded" for r in body["results"])


def test_results_missing_run_404(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    resp = client.get("/api/results", params={"run_id": 7_654_321})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_i18n_locales_registry(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get("/api/i18n").json()
    assert isinstance(body, list)
    codes = {entry["code"] for entry in body}
    assert {"en", "ru"} <= codes


def test_i18n_known_locale_returns_dict(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get("/api/i18n/en").json()
    assert isinstance(body, dict)
    assert "common" in body


def test_i18n_unknown_locale_404(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.get("/api/i18n/zz")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_i18n_path_traversal_encoded_slash_404(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.get("/api/i18n/..%2f..%2fetc%2fpasswd")
    assert resp.status_code == 404


def test_i18n_path_traversal_reaches_handler_sanitized(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.get("/api/i18n/..%5c..%5csecrets")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_i18n_locale_name_strips_directory(seeded_db_path, monkeypatch):
    monkeypatch.setenv("OPEN_GEO_DB", seeded_db_path)
    body = api.i18n_locale("../i18n/en")
    assert isinstance(body, dict)
    assert "common" in body


def test_i18n_locales_fallback_when_registry_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_I18N_DIR", tmp_path)
    body = api.i18n_locales()
    assert body == [{"code": "en", "name": "English"}]


def test_i18n_locales_malformed_registry_500(monkeypatch, tmp_path):
    (tmp_path / "locales.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(api, "_I18N_DIR", tmp_path)
    with pytest.raises(api.HTTPException) as exc:
        api.i18n_locales()
    assert exc.value.status_code == 500
    assert "registry unreadable" in exc.value.detail


def test_i18n_locale_malformed_file_500(monkeypatch, tmp_path):
    (tmp_path / "xx.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(api, "_I18N_DIR", tmp_path)
    with pytest.raises(api.HTTPException) as exc:
        api.i18n_locale("xx")
    assert exc.value.status_code == 500
    assert "unreadable" in exc.value.detail


def test_report_invalid_period_400(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.post(
        "/api/report", params={"brand_id": example, "engine": ENGINE, "period": "weekly"}
    )
    assert resp.status_code == 400
    assert "today" in resp.json()["detail"]


def test_report_missing_brand_404(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    resp = client.post(
        "/api/report", params={"brand_id": 9_090_909, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_report_subprocess_nonzero_returns_500(make_client, seeded_db_path, monkeypatch):
    class _Proc:
        returncode = 2
        stderr = "boom: traceback from report.generate\n"
        stdout = ""

    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: _Proc())
    client = make_client(seeded_db_path)
    resp = client.post(
        "/api/report", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 500
    payload = resp.json()
    assert payload["status"] == "error"
    assert payload["message"] == "report.generate failed"
    assert "boom" in payload["stderr"]
    assert "report.generate" in payload["command"]


def test_report_subprocess_launch_failure_returns_500(make_client, seeded_db_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("cannot spawn interpreter")

    monkeypatch.setattr(api.subprocess, "run", _boom)
    client = make_client(seeded_db_path)
    resp = client.post(
        "/api/report", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 500
    payload = resp.json()
    assert payload["status"] == "error"
    assert "cannot spawn interpreter" in payload["message"]
    assert "report.generate" in payload["command"]


def test_report_missing_report_module_returns_501(make_client, seeded_db_path, monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_REPO_ROOT", tmp_path)
    assert not (tmp_path / "report" / "generate.py").exists()
    client = make_client(seeded_db_path)
    resp = client.post(
        "/api/report", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 501
    payload = resp.json()
    assert payload["status"] == "not_implemented"
    assert "report.generate" in payload["command"]


@pytest.mark.slow
def test_report_generates_pdf(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.post(
        "/api/report", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    assert "example.com" in resp.headers.get("content-disposition", "")


def test_db_path_empty_env_is_not_the_default(monkeypatch):
    monkeypatch.setenv("OPEN_GEO_DB", "")
    got = api._db_path()
    assert got == str(api._REPO_ROOT)
    assert got != str(api._REPO_ROOT / "data" / "aeo.db")


def test_db_path_dotted_relative_env_is_normalized_under_root(monkeypatch):
    monkeypatch.setenv("OPEN_GEO_DB", "./sub/dir/x.db")
    got = Path(api._db_path())
    assert got.is_absolute()
    assert str(got.resolve()).startswith(str(api._REPO_ROOT.resolve()))
    assert got.name == "x.db"


def test_loads_json_null_returns_none_not_default():
    sentinel = ["DEFAULT_SHOULD_NOT_WIN"]
    assert api._loads("null", sentinel) is None


def test_loads_json_false_and_zero_are_returned_verbatim():
    assert api._loads("false", "DEF") is False
    assert api._loads("0", "DEF") == 0
    assert api._loads("[]", "DEF") == []


def test_loads_whitespace_only_string_falls_back_to_default():
    assert api._loads("   ", "WSDEF") == "WSDEF"
    assert api._loads("\n\t", ["x"]) == ["x"]


def test_loads_unicode_payload_roundtrips():
    assert api._loads('{"d": "été — naïve ☕"}', None) == {"d": "été — naïve ☕"}


def test_brands_includes_both_fixture_brands_with_domains(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    rows = client.get("/api/brands").json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["Example"]["domain"] == "example.com"
    assert by_name["Globex"]["domain"] == "globex.com"
    ids = [r["id"] for r in rows]
    assert all(isinstance(i, int) and i > 0 for i in ids)
    assert len(ids) == len(set(ids))


def test_runs_counts_are_ints_and_running_has_no_metrics(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    runs = client.get("/api/runs", params={"brand_id": example}).json()
    for r in runs:
        assert isinstance(r["n_queries"], int)
        assert isinstance(r["n_ok"], int)
        assert isinstance(r["n_failed"], int)
    done = [r for r in runs if r["status"] == "done"]
    assert done and all(r["n_ok"] > 0 for r in done)


def test_runs_do_not_bleed_across_brands(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    rows = client.get("/api/brands").json()
    example = next(r["id"] for r in rows if r["name"] == "Example")
    rest = next(r["id"] for r in rows if r["name"] == "Globex")
    example_runs = {r["run_id"] for r in client.get("/api/runs", params={"brand_id": example}).json()}
    rest_runs = {r["run_id"] for r in client.get("/api/runs", params={"brand_id": rest}).json()}
    assert example_runs and rest_runs
    assert example_runs.isdisjoint(rest_runs)


def test_metrics_today_every_delta_equals_cur_minus_prev(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()
    prev_run = body["prev_run"]
    assert prev_run is not None

    checked_numeric = 0
    for row in body["metrics"]:
        for m in _DELTA_METRICS:
            cur = row[m]
            prev = row[f"{m}_prev"]
            delta = row[f"{m}_delta"]
            if cur is not None and prev is not None:
                assert delta == pytest.approx(cur - prev)
                checked_numeric += 1
            else:
                assert delta is None
    assert checked_numeric > 0


def test_metrics_today_prev_value_matches_previous_run(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()
    prev_run_id = body["prev_run"]["run_id"]

    conn = get_conn(dash_fixture_db_path)
    try:
        prev_rows = {
            r["lens"]: dict(r)
            for r in conn.execute(
                "SELECT * FROM metrics WHERE run_id=?", (prev_run_id,)
            ).fetchall()
        }
    finally:
        conn.close()

    for row in body["metrics"]:
        prev = prev_rows[row["lens"]]
        assert row["overview_coverage_prev"] == pytest.approx(prev["overview_coverage"])
        if row["visibility_in_sources_prev"] is not None:
            assert row["visibility_in_sources_prev"] == pytest.approx(
                prev["visibility_in_sources"]
            )


def test_metrics_today_lens_filter_no_match_returns_empty_metrics(make_client, dash_fixture_db_path):
    conn = get_conn(dash_fixture_db_path)
    try:
        example = conn.execute("SELECT id FROM brands WHERE name='Example'").fetchone()["id"]
        latest = conn.execute(
            "SELECT id FROM runs WHERE brand_id=? AND engine=? AND status='done' "
            "ORDER BY run_at DESC, id DESC LIMIT 1",
            (example, ENGINE),
        ).fetchone()["id"]
        conn.execute(
            "DELETE FROM metrics WHERE run_id=? AND lens != 'all'", (latest,)
        )
        conn.commit()
    finally:
        conn.close()

    client = make_client(dash_fixture_db_path)
    body = client.get(
        "/api/metrics",
        params={"brand_id": example, "engine": ENGINE, "period": "today", "lens": "branded"},
    ).json()
    assert body["run"] is not None
    assert body["run"]["run_id"] == latest
    assert body["metrics"] == []


def test_metrics_today_run_payload_fields(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()
    run = body["run"]
    assert set(run) == {"run_id", "run_at", "status", "n_queries"}
    assert run["status"] == "done"
    assert set(body["prev_run"]) == {"run_id", "run_at", "status"}


def test_metrics_all_matches_direct_aggregate(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "all"}
    ).json()
    http_by_lens = {r["lens"]: r for r in body["metrics"]}

    conn = get_conn(dash_fixture_db_path)
    try:
        direct = {r["lens"]: r for r in api._aggregate_period(conn, example, ENGINE, None)}
    finally:
        conn.close()

    assert set(http_by_lens) == set(direct)
    for lens, hr in http_by_lens.items():
        dr = direct[lens]
        for key in ("n_queries", "n_overviews", "n_in_sources", "n_cited"):
            assert hr[key] == dr[key]
        for key in ("overview_coverage", "visibility_in_sources",
                    "visibility_in_citations", "avg_source_position",
                    "avg_citation_position"):
            if dr[key] is None:
                assert hr[key] is None
            else:
                assert hr[key] == pytest.approx(dr[key])


def test_metrics_all_n_runs_zero_for_unknown_brand(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    body = client.get(
        "/api/metrics",
        params={"brand_id": 987_654, "engine": ENGINE, "period": "all"},
    ).json()
    assert body["n_runs"] == 0
    assert body["metrics"] == []
    assert body["run"] is None and body["prev_run"] is None


def test_metrics_all_globex_independent(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    rows = client.get("/api/brands").json()
    rest = next(r["id"] for r in rows if r["name"] == "Globex")
    body = client.get(
        "/api/metrics", params={"brand_id": rest, "engine": ENGINE, "period": "all"}
    ).json()
    assert body["n_runs"] == 3
    assert body["metrics"][0]["lens"] == "all"


def test_aggregate_period_null_rank_sums_with_positive_counts(empty_conn):
    bid = get_or_create_brand(empty_conn, "NullRank", "nr.example")
    rid = create_run(empty_conn, bid, ENGINE)
    update_run_counts(empty_conn, rid, n_queries=5, n_ok=5, n_failed=0, status="done")
    empty_conn.execute(
        """INSERT INTO metrics (run_id, brand_id, engine, lens, n_queries, n_overviews,
                overview_coverage, n_in_sources, visibility_in_sources, n_cited,
                visibility_in_citations, avg_source_position, avg_citation_position,
                computed_at)
           VALUES (?,?,?,?,5,5,1.0,3,0.6,2,0.4,NULL,NULL,'now')""",
        (rid, bid, ENGINE, "all"),
    )
    empty_conn.commit()

    row = api._aggregate_period(empty_conn, bid, ENGINE, None)[0]
    assert row["n_in_sources"] == 3 and row["n_cited"] == 2
    assert row["visibility_in_sources"] == pytest.approx(0.6)
    assert row["visibility_in_citations"] == pytest.approx(0.4)
    assert row["avg_source_position"] is None
    assert row["avg_citation_position"] is None


def test_aggregate_period_weighted_mean_across_two_runs(empty_conn):
    bid = get_or_create_brand(empty_conn, "Weighted", "w.example")

    def _run(avg_src, n_src, avg_cit, n_cit):
        rid = create_run(empty_conn, bid, ENGINE)
        update_run_counts(empty_conn, rid, n_queries=10, n_ok=10, n_failed=0, status="done")
        empty_conn.execute(
            """INSERT INTO metrics (run_id, brand_id, engine, lens, n_queries, n_overviews,
                    overview_coverage, n_in_sources, visibility_in_sources, n_cited,
                    visibility_in_citations, avg_source_position, avg_citation_position,
                    computed_at)
               VALUES (?,?,?,'all',10,10,1.0,?,?,?,?,?,?,'now')""",
            (rid, bid, ENGINE, n_src, n_src / 10, n_cit, n_cit / 10, avg_src, avg_cit),
        )
        return rid

    _run(2.0, 1, 1.0, 2)
    _run(4.0, 3, 3.0, 4)
    empty_conn.commit()

    row = api._aggregate_period(empty_conn, bid, ENGINE, None)[0]
    assert row["avg_source_position"] == pytest.approx(3.5)
    assert row["avg_citation_position"] == pytest.approx(14 / 6)
    assert row["n_in_sources"] == 4 and row["n_cited"] == 6


def test_aggregate_period_skips_running_runs(empty_conn):
    bid = get_or_create_brand(empty_conn, "Mixed", "m.example")
    done = create_run(empty_conn, bid, ENGINE)
    update_run_counts(empty_conn, done, n_queries=4, n_ok=4, n_failed=0, status="done")
    running = create_run(empty_conn, bid, ENGINE)
    for rid, nq in ((done, 4), (running, 99)):
        empty_conn.execute(
            """INSERT INTO metrics (run_id, brand_id, engine, lens, n_queries, n_overviews,
                    overview_coverage, n_in_sources, visibility_in_sources, n_cited,
                    visibility_in_citations, avg_source_position, avg_citation_position,
                    computed_at)
               VALUES (?,?,?,'all',?,?,1.0,0,0.0,0,0.0,NULL,NULL,'now')""",
            (rid, bid, ENGINE, nq, nq),
        )
    empty_conn.commit()

    row = api._aggregate_period(empty_conn, bid, ENGINE, None)[0]
    assert row["n_queries"] == 4


def test_latest_run_id_tie_break_on_equal_run_at(empty_conn):
    bid = get_or_create_brand(empty_conn, "Tie", "tie.example")
    same_ts = "2026-06-10T00:00:00+00:00"
    r1 = create_run(empty_conn, bid, ENGINE)
    r2 = create_run(empty_conn, bid, ENGINE)
    for rid in (r1, r2):
        empty_conn.execute("UPDATE runs SET run_at=?, status='done' WHERE id=?", (same_ts, rid))
    empty_conn.commit()
    lo, hi = sorted((r1, r2))

    latest = api._latest_run_id(empty_conn, bid, ENGINE, only_done=True)
    assert latest == hi

    prev = api._latest_run_id(
        empty_conn, bid, ENGINE, only_done=True, before_run_at=same_ts, before_id=hi
    )
    assert prev == lo

    none = api._latest_run_id(
        empty_conn, bid, ENGINE, only_done=True, before_run_at=same_ts, before_id=lo
    )
    assert none is None


def test_latest_run_id_only_done_false_includes_running(empty_conn):
    bid = get_or_create_brand(empty_conn, "Inc", "inc.example")
    done = create_run(empty_conn, bid, ENGINE)
    empty_conn.execute(
        "UPDATE runs SET run_at='2026-06-01T00:00:00+00:00', status='done' WHERE id=?",
        (done,),
    )
    running = create_run(empty_conn, bid, ENGINE)
    empty_conn.execute(
        "UPDATE runs SET run_at='2026-06-09T00:00:00+00:00' WHERE id=?", (running,)
    )
    empty_conn.commit()
    assert api._latest_run_id(empty_conn, bid, ENGINE, only_done=False) == running
    assert api._latest_run_id(empty_conn, bid, ENGINE, only_done=True) == done


def test_timeseries_points_carry_run_ids_and_status(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    pts = client.get(
        "/api/timeseries", params={"brand_id": 1, "engine": ENGINE, "lens": "all"}
    ).json()["points"]
    assert len(pts) == 5
    run_ids = [p["run_id"] for p in pts]
    assert len(set(run_ids)) == 5
    assert all(p["status"] == "done" for p in pts)
    run_ats = [p["run_at"] for p in pts]
    assert run_ats == sorted(run_ats)


def test_timeseries_unknown_brand_and_engine_empty(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    assert client.get(
        "/api/timeseries", params={"brand_id": 424_242, "engine": ENGINE}
    ).json()["points"] == []
    assert client.get(
        "/api/timeseries", params={"brand_id": 1, "engine": "bing_copilot"}
    ).json()["points"] == []


def test_timeseries_requires_brand_and_engine(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    assert client.get("/api/timeseries", params={"engine": ENGINE}).status_code == 422
    assert client.get("/api/timeseries", params={"brand_id": 1}).status_code == 422


def test_results_false_bools_and_empty_decodes(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    runs = client.get("/api/runs", params={"brand_id": 1, "engine": ENGINE}).json()
    body = client.get("/api/results", params={"run_id": runs[0]["run_id"]}).json()
    no_ov = [r for r in body["results"] if r["overview_present"] is False]
    assert no_ov, "seed guarantees at least one no-overview row per run"
    r = no_ov[0]
    assert r["overview_present"] is False
    assert isinstance(r["brand_in_answer_text"], bool)
    assert r["sources"] == [] and r["citations"] == []
    assert r["target_source_ranks"] == [] and r["target_citation_ranks"] == []
    assert r["sentiment"] is None


def test_results_rank_arrays_are_ints_and_ordered_by_id(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    runs = client.get("/api/runs", params={"brand_id": 1, "engine": ENGINE}).json()
    body = client.get("/api/results", params={"run_id": runs[0]["run_id"]}).json()
    rows = body["results"]
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)
    ranked = next((r for r in rows if r["target_source_ranks"]), None)
    assert ranked is not None
    assert all(isinstance(x, int) for x in ranked["target_source_ranks"])
    assert set(body["run"]) == {"run_id", "brand_id", "engine", "run_at", "status"}


def test_results_lens_filter_empty_for_absent_lens(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    runs = client.get("/api/runs", params={"brand_id": 1, "engine": ENGINE}).json()
    body = client.get(
        "/api/results", params={"run_id": runs[0]["run_id"], "lens": "nonexistent"}
    ).json()
    assert body["lens"] == "nonexistent"
    assert body["results"] == []


def test_results_run_from_other_brand_is_readable(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    rows = client.get("/api/brands").json()
    rest = next(r["id"] for r in rows if r["name"] == "Globex")
    rest_run = next(
        r["run_id"]
        for r in client.get("/api/runs", params={"brand_id": rest, "engine": ENGINE}).json()
        if r["status"] == "done"
    )
    body = client.get("/api/results", params={"run_id": rest_run}).json()
    assert body["run"]["run_id"] == rest_run
    assert body["run"]["brand_id"] == rest
    assert body["results"]


@pytest.mark.parametrize(
    "payload",
    [
        "../../../../etc/passwd",
        "/etc/passwd",
        "....//....//etc/passwd",
        "en/../../../etc/passwd",
        "..\\..\\secrets",
    ],
)
def test_i18n_locale_path_cannot_escape_dir(payload):
    safe = Path(payload).name
    resolved = (api._I18N_DIR / f"{safe}.json").resolve()
    assert resolved.parent == api._I18N_DIR.resolve()


def test_i18n_registry_entries_have_code_and_name(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get("/api/i18n").json()
    assert isinstance(body, list) and body
    for entry in body:
        assert {"code", "name"} <= set(entry)
        assert isinstance(entry["code"], str) and entry["code"]


def test_i18n_ru_locale_is_dict(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get("/api/i18n/ru").json()
    assert isinstance(body, dict) and body


def test_i18n_locale_with_dotjson_in_code_404(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.get("/api/i18n/en.json")
    assert resp.status_code == 404


def test_i18n_locales_fallback_value_is_well_formed(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_I18N_DIR", tmp_path)
    body = api.i18n_locales()
    assert body == [{"code": "en", "name": "English"}]
    assert body[0]["code"] == "en" and body[0]["name"] == "English"


def test_report_success_streams_pdf_with_argv_contract(make_client, dash_fixture_db_path, monkeypatch):
    captured: dict = {}

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    def _fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["cwd"] = kwargs.get("cwd")
        captured["timeout"] = kwargs.get("timeout")
        out = argv[argv.index("--out") + 1]
        Path(out).write_bytes(b"%PDF-1.4\n% fake pdf for test\n")
        return _Proc()

    monkeypatch.setattr(api.subprocess, "run", _fake_run)

    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.post(
        "/api/report", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    disp = resp.headers.get("content-disposition", "")
    assert "example.com" in disp and ENGINE in disp and "today" in disp

    argv = captured["argv"]
    assert argv[0] == api.sys.executable
    assert argv[1:3] == ["-m", "report.generate"]
    assert argv[argv.index("--brand") + 1] == "Example"
    assert argv[argv.index("--domain") + 1] == "example.com"
    assert argv[argv.index("--engine") + 1] == ENGINE
    assert argv[argv.index("--period") + 1] == "today"
    assert argv[argv.index("--db") + 1] == str(Path(dash_fixture_db_path))
    out_arg = argv[argv.index("--out") + 1]
    assert out_arg.endswith(".pdf")
    assert captured["timeout"] == 180
    assert str(captured["cwd"]) == str(api._REPO_ROOT)


def test_report_returncode_zero_but_no_file_returns_500(make_client, dash_fixture_db_path, monkeypatch):
    class _Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: _Proc())
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.post(
        "/api/report", params={"brand_id": example, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 500
    payload = resp.json()
    assert payload["status"] == "error"
    assert payload["message"] == "report.generate failed"
    assert "report.generate" in payload["command"]


def test_report_default_period_is_all(make_client, dash_fixture_db_path, monkeypatch):
    captured: dict = {}

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    def _fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        Path(argv[argv.index("--out") + 1]).write_bytes(b"%PDF-1.4\n")
        return _Proc()

    monkeypatch.setattr(api.subprocess, "run", _fake_run)
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.post("/api/report", params={"brand_id": example, "engine": ENGINE})
    assert resp.status_code == 200
    assert captured["argv"][captured["argv"].index("--period") + 1] == "all"


def test_report_missing_db_503(make_client, tmp_path):
    client = make_client(tmp_path / "absent.db")
    resp = client.post(
        "/api/report", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 503


def _focus_done_run_id(db_path: str, brand_id: int) -> int:
    conn = get_conn(db_path)
    try:
        return conn.execute(
            "SELECT id FROM runs WHERE brand_id=? AND engine=? AND status='done' "
            "ORDER BY run_at DESC, id DESC LIMIT 1",
            (brand_id, ENGINE),
        ).fetchone()["id"]
    finally:
        conn.close()


def test_metrics_today_rows_carry_sentiment_summary_key(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()
    assert body["metrics"]
    for row in body["metrics"]:
        assert "sentiment_summary" in row


def test_metrics_today_sentiment_summary_value_attached(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    focus = _focus_done_run_id(dash_fixture_db_path, example)

    from pipeline.db import upsert_lens_sentiment

    conn = get_conn(dash_fixture_db_path)
    try:
        upsert_lens_sentiment(conn, focus, "all", "overall neutral readout")
        upsert_lens_sentiment(conn, focus, "branded", "owns branded queries")
    finally:
        conn.close()

    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    ).json()
    rows = {r["lens"]: r for r in body["metrics"]}
    assert rows["all"]["sentiment_summary"] == "overall neutral readout"
    assert rows["branded"]["sentiment_summary"] == "owns branded queries"
    assert rows["general"]["sentiment_summary"] is None


def test_metrics_all_rows_carry_sentiment_summary(make_client, dash_fixture_db_path):
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    focus = _focus_done_run_id(dash_fixture_db_path, example)

    from pipeline.db import upsert_lens_sentiment

    conn = get_conn(dash_fixture_db_path)
    try:
        upsert_lens_sentiment(conn, focus, "all", "period rollup")
    finally:
        conn.close()

    body = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "all"}
    ).json()
    rows = {r["lens"]: r for r in body["metrics"]}
    for row in body["metrics"]:
        assert "sentiment_summary" in row
    assert rows["all"]["sentiment_summary"] == "period rollup"


def _drop_lens_sentiment(db_path: str) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS lens_sentiment")
        conn.commit()
    finally:
        conn.close()


def test_metrics_today_no_500_when_lens_sentiment_table_absent(make_client, dash_fixture_db_path):
    _drop_lens_sentiment(dash_fixture_db_path)
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "today"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]
    for row in body["metrics"]:
        assert row["sentiment_summary"] is None


def test_metrics_all_no_500_when_lens_sentiment_table_absent(make_client, dash_fixture_db_path):
    _drop_lens_sentiment(dash_fixture_db_path)
    client = make_client(dash_fixture_db_path)
    example = _example_id(client)
    resp = client.get(
        "/api/metrics", params={"brand_id": example, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]
    for row in body["metrics"]:
        assert row["sentiment_summary"] is None


_COMPETITOR_KEYS = {
    "domain",
    "is_brand",
    "appearances_sources",
    "appearances_citations",
    "share_sources",
    "share_citations",
    "avg_source_position",
    "avg_citation_position",
}


def test_competitors_today_shape(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "today"}
    ).json()
    assert body["period"] == "today"
    assert body["run"] is not None
    assert body["n_overviews"] > 0
    assert body["domains"]
    for d in body["domains"]:
        assert _COMPETITOR_KEYS <= set(d)
        assert isinstance(d["is_brand"], bool)
    brand_rows = [d for d in body["domains"] if d["is_brand"]]
    assert len(brand_rows) == 1
    assert brand_rows[0]["domain"] == "example.com"


def test_competitors_today_share_matches_appearances(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "today"}
    ).json()
    nov = body["n_overviews"]
    for d in body["domains"]:
        assert d["share_sources"] == pytest.approx(d["appearances_sources"] / nov)
        assert d["share_citations"] == pytest.approx(d["appearances_citations"] / nov)


def test_competitors_default_sort_is_sources_desc(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "today"}
    ).json()
    apps = [d["appearances_sources"] for d in body["domains"]]
    assert apps == sorted(apps, reverse=True)


def test_competitors_limit_applied(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors",
        params={"brand_id": 1, "engine": ENGINE, "period": "today", "limit": 3},
    ).json()
    assert len(body["domains"]) <= 3


def test_competitors_sort_citations(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors",
        params={"brand_id": 1, "engine": ENGINE, "period": "today", "sort": "citations"},
    ).json()
    cits = [d["appearances_citations"] for d in body["domains"]]
    assert cits == sorted(cits, reverse=True)


def test_competitors_all_rollup(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    ).json()
    assert body["period"] == "all"
    assert body["run"] is None
    assert body["n_overviews"] > 0
    assert body["domains"]
    for d in body["domains"]:
        if d["share_sources"] is not None:
            assert 0.0 <= d["share_sources"] <= 1.0


def test_competitors_invalid_period_400(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "weekly"}
    )
    assert resp.status_code == 400


def test_competitors_invalid_sort_400(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    resp = client.get(
        "/api/competitors",
        params={"brand_id": 1, "engine": ENGINE, "sort": "rank"},
    )
    assert resp.status_code == 400


def test_competitors_unknown_brand_empty(make_client, seeded_db_path):
    client = make_client(seeded_db_path)
    body = client.get(
        "/api/competitors",
        params={"brand_id": 987_654, "engine": ENGINE, "period": "today"},
    ).json()
    assert body["domains"] == []
    assert body["run"] is None


def _drop_domain_stats(db_path: str) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS domain_stats")
        conn.commit()
    finally:
        conn.close()


def test_competitors_no_500_when_table_absent_today(make_client, seeded_db_path):
    _drop_domain_stats(seeded_db_path)
    client = make_client(seeded_db_path)
    resp = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "today"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["domains"] == []
    assert body["n_overviews"] > 0


def test_competitors_no_500_when_table_absent_all(make_client, seeded_db_path):
    _drop_domain_stats(seeded_db_path)
    client = make_client(seeded_db_path)
    resp = client.get(
        "/api/competitors", params={"brand_id": 1, "engine": ENGINE, "period": "all"}
    )
    assert resp.status_code == 200
    assert resp.json()["domains"] == []
