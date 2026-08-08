from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import BaseModel

from pipeline.schema import normalize_domain, normalize_target

_USER_AGENT = "open-geo-audit/1.0 (+https://github.com/Pupok462/open-geo)"


class Fetched(BaseModel):
    url: str
    final_url: Optional[str]
    status: Optional[int]
    ok: bool
    headers: dict[str, str]
    text: Optional[str]
    error: Optional[str]
    redirects: int
    scheme: Optional[str]


class SiteArtifacts(BaseModel):
    target: str
    domain: str
    checked_at: datetime
    homepage: Fetched
    homepage_http: Fetched
    robots: Fetched
    sitemap: Fetched
    llms: Fetched
    security: Fetched
    target_page: Optional[Fetched]


def fetch(client: httpx.Client, url: str, *, timeout: float = 10.0) -> Fetched:
    try:
        resp = client.get(url, follow_redirects=True, timeout=timeout)
    except httpx.HTTPError as exc:
        return Fetched(
            url=url,
            final_url=None,
            status=None,
            ok=False,
            headers={},
            text=None,
            error=str(exc),
            redirects=0,
            scheme=None,
        )
    try:
        text: Optional[str] = resp.text
    except Exception:  # noqa: BLE001
        text = None
    return Fetched(
        url=url,
        final_url=str(resp.url),
        status=resp.status_code,
        ok=resp.status_code == 200,
        headers={key.lower(): value for key, value in resp.headers.items()},
        text=text,
        error=None,
        redirects=len(resp.history),
        scheme=resp.url.scheme,
    )


def gather(
    target: str,
    *,
    client: Optional[httpx.Client] = None,
    timeout: float = 10.0,
) -> SiteArtifacts:
    domain = normalize_domain(target)
    norm = normalize_target(target)
    owned = client is None
    if owned:
        client = httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
    try:
        homepage = fetch(client, f"https://{domain}/", timeout=timeout)
        homepage_http = fetch(client, f"http://{domain}/", timeout=timeout)
        robots = fetch(client, f"https://{domain}/robots.txt", timeout=timeout)
        sitemap = fetch(client, f"https://{domain}/sitemap.xml", timeout=timeout)
        llms = fetch(client, f"https://{domain}/llms.txt", timeout=timeout)
        security = fetch(
            client, f"https://{domain}/.well-known/security.txt", timeout=timeout
        )
        target_page: Optional[Fetched] = None
        if norm != domain:
            target_page = fetch(client, f"https://{norm}", timeout=timeout)
    finally:
        if owned:
            client.close()
    return SiteArtifacts(
        target=norm,
        domain=domain,
        checked_at=datetime.now(timezone.utc),
        homepage=homepage,
        homepage_http=homepage_http,
        robots=robots,
        sitemap=sitemap,
        llms=llms,
        security=security,
        target_page=target_page,
    )


__all__ = ["Fetched", "SiteArtifacts", "fetch", "gather"]
