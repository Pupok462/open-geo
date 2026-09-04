from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from demand.schema import DemandStat, RelatedPhrase

DEFAULT_TIMEOUT = 20.0
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """A provider was called and the call failed (auth, quota, network, shape)."""


def http_json(
    method: str,
    url: str,
    *,
    headers: Optional[dict] = None,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
) -> Any:
    """One JSON call with bounded retries. Raises ProviderError on failure.

    Imported lazily so the package stays importable (for `doctor`) on a machine
    where httpx is not installed yet.
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ProviderError(f"httpx is required for live lookups: {exc}") from exc

    last: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            response = httpx.request(
                method, url, headers=headers, json=json_body, params=params,
                timeout=timeout,
            )
        except Exception as exc:  # network-level
            last = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code in _RETRY_STATUS:
                last = f"HTTP {response.status_code}: {response.text[:200]}"
            elif response.status_code >= 400:
                raise ProviderError(f"HTTP {response.status_code}: {response.text[:400]}")
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ProviderError(f"non-JSON response: {exc}") from exc
        if attempt < retries:
            time.sleep(0.6 * (attempt + 1))
    raise ProviderError(last or "request failed")


def to_int(value: Any) -> Optional[int]:
    """Providers return counts as str (protobuf→JSON) or int. Never guess."""
    if value is None:
        return None
    try:
        return int(str(value).replace(" ", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


class Provider(ABC):
    """One demand source behind a single contract.

    A provider never invents a number: when it cannot answer it says why, and the
    caller surfaces that instead of a figure.
    """

    name: str = "base"
    # Human instructions printed by `demand.doctor` when credentials are missing.
    howto: str = ""
    env_vars: tuple[str, ...] = ()
    daily_limit: Optional[int] = None

    def __init__(self, conn: Any = None, ttl_days: int = 7) -> None:
        self.conn = conn          # sqlite cache connection (demand.cache), optional
        self.ttl_days = ttl_days
        self.last_from_cache = False

    # --- cache / quota helpers ------------------------------------------
    def _cache_get(self, key: str) -> Any:
        if self.conn is None:
            return None
        from demand import cache
        return cache.get(self.conn, self.name, key, ttl_days=self.ttl_days)

    def _cache_put(self, key: str, payload: Any) -> None:
        if self.conn is None:
            return
        from demand import cache
        cache.put(self.conn, self.name, key, payload)

    def quota_used(self) -> int:
        if self.conn is None:
            return 0
        from demand import cache
        return cache.quota_used(self.conn, self.name)

    def _quota_bump(self, n: int = 1) -> None:
        if self.conn is None:
            return
        from demand import cache
        cache.quota_bump(self.conn, self.name, n)

    def quota_exhausted(self) -> bool:
        if self.daily_limit is None:
            return False
        return self.quota_used() >= self.daily_limit

    @abstractmethod
    def credentials(self) -> tuple[bool, list[str]]:
        """(configured, missing env var names)."""

    @abstractmethod
    def supports(self, geo: str, language: str) -> tuple[bool, str]:
        """(can serve this locale, reason when it cannot)."""

    @abstractmethod
    def lookup(
        self, phrase: str, geo: str, language: str, *, n_related: int = 0
    ) -> DemandStat:
        """Demand for ONE phrase in one locale."""

    def expand(
        self, seed: str, geo: str, language: str, *, n: int = 30
    ) -> list[RelatedPhrase]:
        """Real phrasings around a seed. Default: none."""
        return []


__all__ = ["Provider", "ProviderError", "http_json", "to_int", "DEFAULT_TIMEOUT"]
