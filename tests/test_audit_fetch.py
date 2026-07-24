from __future__ import annotations

from datetime import datetime, timezone

import httpx

from audit import cache
from audit.fetch import Fetched, SiteArtifacts, fetch, gather


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _capturing_handler(requested):
    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, text="ok")

    return handler


def test_fetch_ok_200_lowercases_headers():
    def handler(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html", "X-Custom": "1"},
            text="hello world",
        )

    with _client(handler) as client:
        f = fetch(client, "https://example.com/")
    assert isinstance(f, Fetched)
    assert f.status == 200
    assert f.ok is True
    assert f.error is None
    assert f.redirects == 0
    assert f.scheme == "https"
    assert f.final_url == "https://example.com/"
    assert f.url == "https://example.com/"
    assert f.text == "hello world"
    assert "content-type" in f.headers
    assert "x-custom" in f.headers
    assert all(key == key.lower() for key in f.headers)


def test_fetch_404_not_ok():
    def handler(request):
        return httpx.Response(404, text="nope")

    with _client(handler) as client:
        f = fetch(client, "https://example.com/missing")
    assert f.status == 404
    assert f.ok is False
    assert f.error is None
    assert f.text == "nope"


def test_fetch_follows_redirect():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "https://example.com/end"})
        return httpx.Response(200, text="done")

    with _client(handler) as client:
        f = fetch(client, "https://example.com/start")
    assert f.ok is True
    assert f.redirects == 1
    assert f.final_url == "https://example.com/end"
    assert f.url == "https://example.com/start"


def test_fetch_transport_error():
    def handler(request):
        raise httpx.ConnectError("boom")

    with _client(handler) as client:
        f = fetch(client, "https://example.com/")
    assert f.status is None
    assert f.ok is False
    assert f.final_url is None
    assert f.headers == {}
    assert f.text is None
    assert f.redirects == 0
    assert f.scheme is None
    assert f.error is not None
    assert "boom" in f.error


class _RaisingText:
    def __init__(self):
        self.status_code = 200
        self.url = httpx.URL("https://example.com/x")
        self.headers = httpx.Headers({"content-type": "text/html"})
        self.history: list = []

    @property
    def text(self):
        raise ValueError("decode failed")


class _RaisingTextClient:
    def get(self, url, **kwargs):
        return _RaisingText()


def test_fetch_text_guard_returns_none_on_read_error():
    f = fetch(_RaisingTextClient(), "https://example.com/x")
    assert f.text is None
    assert f.status == 200
    assert f.ok is True
    assert f.error is None
    assert f.scheme == "https"
    assert f.final_url == "https://example.com/x"


def test_gather_bare_domain_request_set():
    requested = []
    with _client(_capturing_handler(requested)) as client:
        arts = gather("https://www.example.com/", client=client)
    assert isinstance(arts, SiteArtifacts)
    assert arts.domain == "example.com"
    assert arts.target == "example.com"
    assert arts.target_page is None
    assert set(requested) == {
        "https://example.com/",
        "http://example.com/",
        "https://example.com/robots.txt",
        "https://example.com/sitemap.xml",
        "https://example.com/llms.txt",
        "https://example.com/.well-known/security.txt",
    }
    assert len(requested) == 6
    assert arts.homepage.ok is True
    assert arts.homepage_http.final_url == "http://example.com/"


def test_gather_path_target_adds_target_page():
    requested = []
    with _client(_capturing_handler(requested)) as client:
        arts = gather("github.com/user/repo", client=client)
    assert arts.domain == "github.com"
    assert arts.target == "github.com/user/repo"
    assert isinstance(arts.target_page, Fetched)
    assert arts.target_page.ok is True
    assert "https://github.com/user/repo/" in requested
    assert len(requested) == 7


def test_gather_creates_client_when_none(monkeypatch):
    real_client_cls = httpx.Client
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, text="ok")

    def factory(*args, **kwargs):
        return real_client_cls(
            transport=httpx.MockTransport(handler), follow_redirects=True
        )

    monkeypatch.setattr(httpx, "Client", factory)
    arts = gather("example.com")
    assert arts.domain == "example.com"
    assert arts.target == "example.com"
    assert arts.target_page is None
    assert len(requested) == 6


def test_is_fresh_recent_true():
    ts = datetime.now(timezone.utc).isoformat()
    assert cache.is_fresh(ts, 3600) is True


def test_is_fresh_old_naive_false():
    assert cache.is_fresh("2000-01-01T00:00:00", 3600) is False


def test_is_fresh_z_suffix_true():
    ts = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    assert ts.endswith("Z")
    assert cache.is_fresh(ts, 3600) is True


def test_is_fresh_garbage_false():
    assert cache.is_fresh("not-a-timestamp", 3600) is False


def test_is_fresh_non_string_false():
    assert cache.is_fresh(None, 3600) is False  # type: ignore[arg-type]
