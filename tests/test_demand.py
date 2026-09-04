from __future__ import annotations

import json

import pytest

from demand import cache, config, doctor, expand, lookup, providers
from demand.providers import base, bing, google_ads, suggest, wordstat
from demand.schema import DemandStat


@pytest.fixture()
def conn(tmp_path):
    connection = cache.get_conn(str(tmp_path / "demand.db"))
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "WORDSTAT_API_KEY", "WORDSTAT_FOLDER_ID", "WORDSTAT_OAUTH_TOKEN",
        "WORDSTAT_BASE_URL", "BING_WEBMASTER_API_KEY", "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_LOGIN_CUSTOMER_ID", "GOOGLE_ADS_API_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_ENV_LOADED", True)


# --- schema / helpers ------------------------------------------------------

def test_demand_stat_rejects_blank_phrase():
    with pytest.raises(ValueError):
        DemandStat(phrase="   ", status="ok", geo="ru")


@pytest.mark.parametrize(
    "raw,expected",
    [("1 719", 1719), ("1719", 1719), (42, 42), (None, None), ("n/a", None)],
)
def test_to_int_never_guesses(raw, expected):
    assert base.to_int(raw) == expected


def test_load_env_does_not_override_real_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('A=1\n# comment\nB="two"\nbroken\n', encoding="utf-8")
    monkeypatch.setenv("A", "already")
    loaded = config.load_env(str(env_file))
    assert loaded == {"A": "1", "B": "two"}
    assert config.env("A") == "already"
    assert config.env("B") == "two"


def test_load_env_missing_file_is_fine(tmp_path):
    assert config.load_env(str(tmp_path / "nope.env")) == {}


def test_geo_maps():
    assert config.yandex_region("ru") == 225
    assert config.yandex_region("zz") is None
    assert config.google_geo_target("us") == 2840
    assert config.google_language("ru-RU") == 1031
    assert config.bing_locale("ru", "ru") == "ru-RU"
    assert config.bing_locale("en-GB", "gb") == "en-GB"
    assert config.bing_locale("xx", "fr") == "xx-FR"


# --- cache -----------------------------------------------------------------

def test_cache_roundtrip_and_ttl(conn):
    cache.put(conn, "wordstat", "k", {"a": 1})
    assert cache.get(conn, "wordstat", "k") == {"a": 1}
    assert cache.get(conn, "wordstat", "k", ttl_days=0) is None
    assert cache.get(conn, "wordstat", "missing") is None
    conn.execute("UPDATE demand_cache SET fetched_epoch = 0")
    assert cache.get(conn, "wordstat", "k") is None


def test_cache_ignores_corrupt_payload(conn):
    conn.execute(
        "INSERT INTO demand_cache(provider,key,payload,fetched_at,fetched_epoch)"
        " VALUES('wordstat','bad','{oops',datetime('now'), 9e18)"
    )
    assert cache.get(conn, "wordstat", "bad") is None


def test_quota_counter(conn):
    assert cache.quota_used(conn, "wordstat") == 0
    cache.quota_bump(conn, "wordstat")
    cache.quota_bump(conn, "wordstat", 2)
    assert cache.quota_used(conn, "wordstat") == 3


# --- wordstat --------------------------------------------------------------

def _wordstat(monkeypatch, conn, payload, **env):
    monkeypatch.setenv("WORDSTAT_API_KEY", env.get("key", "k"))
    monkeypatch.setenv("WORDSTAT_FOLDER_ID", env.get("folder", "f"))
    calls: list[dict] = []

    def fake(method, url, *, headers=None, json_body=None, params=None, **kw):
        calls.append({"url": url, "headers": headers, "body": json_body})
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(wordstat, "http_json", fake)
    return wordstat.WordstatProvider(conn=conn), calls


def test_wordstat_lookup_reports_number_with_scope(monkeypatch, conn):
    provider, calls = _wordstat(monkeypatch, conn, {
        "totalCount": "1719",
        "results": [{"phrase": "речевая аналитика звонков", "count": "412"}],
    })
    stat = provider.lookup("речевая аналитика", "ru", "ru", n_related=1)
    assert stat.status == "ok"
    assert stat.volume == 1719
    assert stat.metric == "impressions_per_month"
    assert "1 719 показов/мес" in stat.scope and "Россия" in stat.scope
    assert stat.related[0].volume == 412
    assert calls[0]["headers"]["Authorization"] == "Api-Key k"
    assert calls[0]["body"]["folderId"] == "f"
    assert calls[0]["body"]["regions"] == ["225"]
    # second call is served from cache, no extra HTTP
    again = provider.lookup("речевая аналитика", "ru", "ru", n_related=1)
    assert again.cached is True and len(calls) == 1


def test_wordstat_omits_folder_when_unset(monkeypatch, conn):
    provider, calls = _wordstat(monkeypatch, conn, {"totalCount": 10}, folder="")
    monkeypatch.delenv("WORDSTAT_FOLDER_ID", raising=False)
    provider.lookup("x", "ru", "ru")
    assert "folderId" not in calls[0]["body"]


def test_wordstat_legacy_oauth_form(monkeypatch, conn):
    provider, calls = _wordstat(monkeypatch, conn, {"totalCount": 10})
    monkeypatch.setenv("WORDSTAT_OAUTH_TOKEN", "oauth")
    provider.lookup("x", "ru", "ru")
    assert calls[0]["headers"]["Authorization"] == "Bearer oauth"
    assert "folderId" not in calls[0]["body"]
    assert calls[0]["url"].startswith(wordstat.LEGACY_BASE)


def test_wordstat_zero_and_missing_total(monkeypatch, conn):
    provider, _ = _wordstat(monkeypatch, conn, {"totalCount": "0"})
    zero = provider.lookup("никому не нужная фраза", "ru", "ru")
    assert zero.status == "zero" and zero.volume == 0

    provider2, _ = _wordstat(monkeypatch, conn, {"results": []})
    broken = provider2.lookup("другая фраза", "ru", "ru")
    assert broken.status == "error" and "totalCount" in broken.reason


def test_wordstat_error_and_quota(monkeypatch, conn):
    provider, _ = _wordstat(monkeypatch, conn, base.ProviderError("HTTP 401"))
    failed = provider.lookup("phrase", "ru", "ru")
    assert failed.status == "error" and "401" in failed.reason

    cache.quota_bump(conn, "wordstat", 1000)
    provider2, _ = _wordstat(monkeypatch, conn, {"totalCount": "5"})
    blocked = provider2.lookup("another", "ru", "ru")
    assert blocked.status == "error" and "quota" in blocked.reason


def test_wordstat_supports_only_yandex_locales(conn):
    provider = wordstat.WordstatProvider(conn=conn)
    assert provider.supports("ru", "ru")[0] is True
    assert provider.supports("us", "ru")[0] is True          # russian speakers abroad
    ok, why = provider.supports("us", "en")
    assert ok is False and "google_ads" in why


def test_wordstat_expand_returns_related(monkeypatch, conn):
    provider, _ = _wordstat(monkeypatch, conn, {
        "totalCount": "100",
        "results": [{"phrase": "a", "count": "9"}, {"phrase": "b", "count": "8"}],
    })
    assert [r.phrase for r in provider.expand("seed", "ru", "ru", n=2)] == ["a", "b"]


# --- google ads ------------------------------------------------------------

def _google(monkeypatch, conn, payload):
    for name in (
        "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID",
    ):
        monkeypatch.setenv(name, "x")
    calls: list[dict] = []

    def fake(method, url, *, headers=None, json_body=None, params=None, **kw):
        calls.append({"url": url, "headers": headers, "body": json_body, "params": params})
        if "oauth2" in url:
            return {"access_token": "at"}
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(google_ads, "http_json", fake)
    return google_ads.GoogleAdsProvider(conn=conn), calls


def test_google_ads_lookup(monkeypatch, conn):
    provider, calls = _google(monkeypatch, conn, {"results": [
        {"text": "crm for whatsapp", "keywordIdeaMetrics": {"avgMonthlySearches": "2400"}},
        {"text": "whatsapp business api", "keywordIdeaMetrics": {"avgMonthlySearches": 880}},
    ]})
    stat = provider.lookup("crm for whatsapp", "us", "en", n_related=5)
    assert stat.status == "ok" and stat.volume == 2400
    assert stat.metric == "avg_monthly_searches"
    assert "2 400 avg monthly searches" in stat.scope and "US" in stat.scope
    assert stat.related[0].phrase == "whatsapp business api"
    idea_call = calls[-1]
    assert idea_call["body"]["geoTargetConstants"] == ["geoTargetConstants/2840"]
    assert idea_call["body"]["language"] == "languageConstants/1000"
    assert idea_call["headers"]["developer-token"] == "x"


def test_google_ads_phrase_absent_is_zero_not_invented(monkeypatch, conn):
    provider, _ = _google(monkeypatch, conn, {"results": [
        {"text": "something else", "keywordIdeaMetrics": {"avgMonthlySearches": "10"}},
    ]})
    stat = provider.lookup("nobody searches this", "us", "en", n_related=1)
    assert stat.status == "zero" and stat.volume == 0
    assert "not returned as a keyword idea" in stat.scope


def test_google_ads_error_and_login_customer(monkeypatch, conn):
    provider, calls = _google(monkeypatch, conn, {"results": []})
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "123-456-7890")
    provider.lookup("q", "ww", "en")
    assert calls[-1]["headers"]["login-customer-id"] == "1234567890"
    assert "geoTargetConstants" not in calls[-1]["body"]

    failing, _ = _google(monkeypatch, conn, base.ProviderError("HTTP 403"))
    stat = failing.lookup("q2", "us", "en")
    assert stat.status == "error" and "403" in stat.reason


def test_google_ads_supports_and_credentials(conn):
    provider = google_ads.GoogleAdsProvider(conn=conn)
    configured, missing = provider.credentials()
    assert configured is False and "GOOGLE_ADS_DEVELOPER_TOKEN" in missing
    assert provider.supports("zz", "en")[0] is False
    assert provider.supports("us", "zz")[0] is False
    assert provider.supports("us", "en")[0] is True


def test_google_ads_token_failure(monkeypatch, conn):
    for name in (
        "GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_CUSTOMER_ID",
    ):
        monkeypatch.setenv(name, "x")
    monkeypatch.setattr(google_ads, "http_json", lambda *a, **k: {"error": "bad_grant"})
    stat = google_ads.GoogleAdsProvider(conn=conn).lookup("q", "us", "en")
    assert stat.status == "error" and "access_token" in stat.reason


# --- bing ------------------------------------------------------------------

def _bing(monkeypatch, conn, payload):
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "bk")
    calls: list[dict] = []

    def fake(method, url, *, headers=None, json_body=None, params=None, **kw):
        calls.append({"url": url, "params": params})
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(bing, "http_json", fake)
    return bing.BingProvider(conn=conn), calls


def test_bing_sums_last_four_weeks(monkeypatch, conn):
    rows = [{"Impressions": v, "Query": "q"} for v in (10, 20, 30, 40, 50)]
    provider, calls = _bing(monkeypatch, conn, {"d": rows})
    stat = provider.lookup("crm for whatsapp", "gb", "en")
    assert stat.volume == 20 + 30 + 40 + 50
    assert stat.metric == "impressions_4w" and stat.status == "ok"
    assert "GB/en-GB" in stat.scope
    assert calls[0]["params"]["apikey"] == "bk"


def test_bing_no_rows_is_zero(monkeypatch, conn):
    provider, _ = _bing(monkeypatch, conn, {"d": []})
    stat = provider.lookup("q", "ww", "en")
    assert stat.status == "zero" and stat.volume == 0


def test_bing_error_and_related(monkeypatch, conn):
    provider, _ = _bing(monkeypatch, conn, base.ProviderError("HTTP 500"))
    assert provider.lookup("q", "us", "en").status == "error"
    assert provider.expand("q", "us", "en") == []

    ok, _ = _bing(monkeypatch, conn, {"d": [{"Query": "rel", "Impressions": 7}]})
    assert ok.expand("seed", "us", "en")[0].phrase == "rel"


# --- suggest ---------------------------------------------------------------

@pytest.mark.parametrize("payload,expected", [
    (["q", ["a", "b"]], ["a", "b"]),
    ([{"phrase": "a"}, {"text": "b"}], ["a", "b"]),
    ({"suggestions": ["a"]}, ["a"]),
    ({"nothing": 1}, []),
    ("junk", []),
])
def test_suggest_parses_every_shape(payload, expected):
    assert suggest._parse(payload) == expected


def test_suggest_lookup_exact_and_prefix(monkeypatch, conn):
    monkeypatch.setattr(
        suggest, "http_json",
        lambda *a, **k: ["seed", ["речевая аналитика", "речевая аналитика цена"]],
    )
    provider = suggest.SuggestProvider(conn=conn, engines=("google",))
    exact = provider.lookup("речевая аналитика", "ru", "ru", n_related=3)
    assert exact.status == "ok" and exact.volume is None
    assert "exact autocomplete entry" in exact.scope
    assert exact.related[0].phrase == "речевая аналитика цена"

    prefix = provider.lookup("речевая", "ru", "ru")
    assert prefix.status == "ok" and "live prefix" in prefix.scope


def test_suggest_lookup_no_completion(monkeypatch, conn):
    monkeypatch.setattr(suggest, "http_json", lambda *a, **k: ["seed", []])
    provider = suggest.SuggestProvider(conn=conn, engines=("google",))
    stat = provider.lookup("asdkjhasd", "ru", "ru")
    assert stat.status == "zero" and "no completion" in stat.scope


def test_suggest_survives_engine_failure(monkeypatch, conn):
    def boom(*a, **k):
        raise base.ProviderError("blocked")
    monkeypatch.setattr(suggest, "http_json", boom)
    provider = suggest.SuggestProvider(conn=conn, engines=("google",))
    assert provider.hits("x", "ru", "ru") == []


def test_suggest_deep_expand_sweeps_alphabet(monkeypatch, conn):
    seen: list[str] = []

    def fake(method, url, *, params=None, **kw):
        seen.append(params.get("q") or params.get("part") or params.get("query"))
        return ["s", [f"{params.get('q')} result"]]

    monkeypatch.setattr(suggest, "http_json", fake)
    provider = suggest.SuggestProvider(conn=conn, engines=("google",))
    out = provider.expand("crm", "us", "en", n=5, deep=True)
    assert len(out) == 5
    assert any(q.endswith(" a") for q in seen)


def test_suggest_params_per_engine():
    assert suggest._params("google", "q", "ru", "ru")["gl"] == "ru"
    assert suggest._params("yandex", "q", "ru", "ru")["part"] == "q"
    assert suggest._params("bing", "q", "ru", "ru")["query"] == "q"
    assert suggest._params("duckduckgo", "q", "ru", "ru")["type"] == "list"


# --- registry --------------------------------------------------------------

def test_preference_is_locale_aware():
    assert providers.preference("ru", "ru")[0] == "wordstat"
    assert providers.preference("us", "en")[0] == "google_ads"
    assert providers.preference("de", "ru")[0] == "wordstat"


def test_resolve_reports_why_each_provider_was_skipped(conn, monkeypatch):
    usable, skipped = providers.resolve("us", "en", conn=conn)
    assert usable == []
    reasons = {row["provider"]: row for row in skipped}
    assert reasons["google_ads"]["reason"] == "not configured"
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "k")
    usable, _ = providers.resolve("us", "en", conn=conn)
    assert [p.name for p in usable] == ["bing"]


def test_resolve_explicit_provider_and_unknown(conn, monkeypatch):
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "k")
    usable, _ = providers.resolve("ru", "ru", provider="bing", conn=conn)
    assert [p.name for p in usable] == ["bing"]
    with pytest.raises(KeyError):
        providers.build("nope")


# --- lookup / expand / doctor ---------------------------------------------

def test_lookup_phrases_falls_back_to_presence(monkeypatch, conn):
    monkeypatch.setattr(suggest, "http_json", lambda *a, **k: ["q", ["crm for whatsapp"]])
    payload = lookup.lookup_phrases(["crm for whatsapp", "  "], "us", "en", conn=conn)
    assert payload["providers_used"] == []
    result = payload["results"][0]
    assert len(payload["results"]) == 1
    assert result["provider"] == "suggest" and result["volume"] is None
    assert "no volume provider answered" in result["reason"]


def test_lookup_phrases_unavailable_without_suggest(conn):
    payload = lookup.lookup_phrases(["x"], "us", "en", with_suggest=False, conn=conn)
    assert payload["results"][0]["status"] == "unavailable"


def test_lookup_phrases_uses_volume_provider(monkeypatch, conn):
    monkeypatch.setenv("WORDSTAT_API_KEY", "k")
    monkeypatch.setenv("WORDSTAT_FOLDER_ID", "f")
    monkeypatch.setattr(wordstat, "http_json", lambda *a, **k: {"totalCount": "500"})
    payload = lookup.lookup_phrases(["фраза"], "ru", "ru", conn=conn)
    assert payload["results"][0]["volume"] == 500
    assert payload["quota"]["wordstat"]["daily_limit"] == 1000


def test_lookup_falls_forward_when_first_provider_errors(monkeypatch, conn):
    monkeypatch.setenv("WORDSTAT_API_KEY", "k")
    monkeypatch.setenv("WORDSTAT_FOLDER_ID", "f")
    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "b")

    def wordstat_down(*a, **k):
        raise base.ProviderError("HTTP 401")

    monkeypatch.setattr(wordstat, "http_json", wordstat_down)
    monkeypatch.setattr(bing, "http_json", lambda *a, **k: {"d": [{"Impressions": 9}]})
    payload = lookup.lookup_phrases(["фраза"], "ru", "ru", conn=conn)
    assert payload["results"][0]["provider"] == "bing"


def test_expand_seed_merges_and_sorts(monkeypatch, conn):
    monkeypatch.setenv("WORDSTAT_API_KEY", "k")
    monkeypatch.setenv("WORDSTAT_FOLDER_ID", "f")
    monkeypatch.setattr(wordstat, "http_json", lambda *a, **k: {
        "totalCount": "900",
        "results": [{"phrase": "низкий", "count": "10"}, {"phrase": "высокий", "count": "800"}],
    })
    monkeypatch.setattr(suggest, "http_json", lambda *a, **k: ["s", ["из подсказок", "высокий"]])
    payload = expand.expand_seed("seed", "ru", "ru", n=10, conn=conn)
    phrases = [p["phrase"] for p in payload["phrases"]]
    assert phrases[:2] == ["высокий", "низкий"]      # volume desc
    assert phrases[-1] == "из подсказок"             # no volume last
    assert payload["phrases"][0]["scope"].startswith("wordstat:")
    assert payload["phrases"][-1]["metric"] == "suggest_presence"


def test_expand_seed_min_volume_filter(monkeypatch, conn):
    monkeypatch.setenv("WORDSTAT_API_KEY", "k")
    monkeypatch.setenv("WORDSTAT_FOLDER_ID", "f")
    monkeypatch.setattr(wordstat, "http_json", lambda *a, **k: {
        "totalCount": "900",
        "results": [{"phrase": "мало", "count": "3"}, {"phrase": "много", "count": "300"}],
    })
    payload = expand.expand_seed(
        "seed", "ru", "ru", n=10, min_volume=100, with_suggest=False, conn=conn
    )
    assert [p["phrase"] for p in payload["phrases"]] == ["много"]


def test_doctor_verdict_and_render(tmp_path, monkeypatch):
    db = str(tmp_path / "d.db")
    report = doctor.diagnose("us", db_path=db)
    assert report["verdict"].startswith("presence only")
    assert report["language"] == "en"
    text = doctor.render(report)
    assert "google_ads" in text and "missing:" in text

    monkeypatch.setenv("BING_WEBMASTER_API_KEY", "k")
    ready = doctor.diagnose("us", db_path=db)
    assert ready["verdict"] == "volume available"
    assert "bing" in ready["volume_capable"]


def test_cli_entrypoints(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "cli.db")
    monkeypatch.setattr(suggest, "http_json", lambda *a, **k: ["q", ["crm pricing"]])
    assert lookup.main(["--phrase", "crm pricing", "--geo", "us", "--db", db]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["provider"] == "suggest"

    assert expand.main(["--seed", "crm", "--geo", "us", "--n", "3", "--db", db]) == 0
    assert json.loads(capsys.readouterr().out)["seeds"][0]["seed"] == "crm"

    assert doctor.main(["--geo", "ru", "--json", "--db", db]) == 0
    assert json.loads(capsys.readouterr().out)["geo"] == "ru"


def test_lookup_cli_requires_phrases(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert lookup.main(["--geo", "us", "--db", str(tmp_path / "x.db")]) == 2
    assert "no phrases" in capsys.readouterr().err


def test_lookup_cli_reads_file(tmp_path, monkeypatch, capsys):
    listing = tmp_path / "phrases.txt"
    listing.write_text("alpha\n\nbeta\n", encoding="utf-8")
    monkeypatch.setattr(suggest, "http_json", lambda *a, **k: ["q", []])
    assert lookup.main([
        "--file", str(listing), "--geo", "us", "--db", str(tmp_path / "y.db"),
    ]) == 0
    assert len(json.loads(capsys.readouterr().out)["results"]) == 2


# --- http transport --------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _fake_httpx(monkeypatch, responses):
    import types
    calls: list[tuple] = []
    queue = list(responses)

    def request(method, url, **kwargs):
        calls.append((method, url))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    module = types.SimpleNamespace(request=request)
    monkeypatch.setitem(__import__("sys").modules, "httpx", module)
    return calls


def test_http_json_returns_payload(monkeypatch):
    _fake_httpx(monkeypatch, [_FakeResponse(200, {"ok": True})])
    assert base.http_json("GET", "https://x") == {"ok": True}


def test_http_json_retries_then_succeeds(monkeypatch):
    calls = _fake_httpx(monkeypatch, [
        _FakeResponse(503, text="busy"), _FakeResponse(200, {"ok": 1}),
    ])
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    assert base.http_json("GET", "https://x") == {"ok": 1}
    assert len(calls) == 2


def test_http_json_gives_up_after_retries(monkeypatch):
    _fake_httpx(monkeypatch, [_FakeResponse(429, text="slow down")] * 3)
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    with pytest.raises(base.ProviderError, match="429"):
        base.http_json("GET", "https://x")


def test_http_json_raises_on_client_error(monkeypatch):
    _fake_httpx(monkeypatch, [_FakeResponse(401, text="unauthorized")])
    with pytest.raises(base.ProviderError, match="401"):
        base.http_json("GET", "https://x")


def test_http_json_network_error_is_wrapped(monkeypatch):
    _fake_httpx(monkeypatch, [OSError("dns"), OSError("dns")])
    monkeypatch.setattr(base.time, "sleep", lambda *_: None)
    with pytest.raises(base.ProviderError, match="OSError"):
        base.http_json("GET", "https://x", retries=1)


def test_http_json_non_json_body(monkeypatch):
    _fake_httpx(monkeypatch, [_FakeResponse(200, ValueError("not json"))])
    with pytest.raises(base.ProviderError, match="non-JSON"):
        base.http_json("GET", "https://x")


def test_provider_without_cache_connection(monkeypatch):
    """Providers must work standalone — the cache is an optimisation, not a dependency."""
    monkeypatch.setenv("WORDSTAT_API_KEY", "k")
    monkeypatch.setenv("WORDSTAT_FOLDER_ID", "f")
    monkeypatch.setattr(wordstat, "http_json", lambda *a, **k: {"totalCount": "7"})
    provider = wordstat.WordstatProvider()
    assert provider.quota_used() == 0
    assert provider.quota_exhausted() is False
    stat = provider.lookup("phrase", "ru", "ru")
    assert stat.volume == 7 and stat.cached is False


def test_suggest_hits_source_url_per_engine(monkeypatch, conn):
    monkeypatch.setattr(suggest, "http_json", lambda *a, **k: ["s", ["one"]])
    provider = suggest.SuggestProvider(conn=conn, engines=("yandex",))
    hit = provider.hits("seed", "ru", "ru")[0]
    assert "part=seed" in hit.source_url and hit.engine == "yandex"
