from __future__ import annotations

from datetime import datetime, timezone


def is_fresh(checked_at: str, max_age_s: int) -> bool:
    try:
        raw = checked_at.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError, AttributeError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    return age <= max_age_s


__all__ = ["is_fresh"]
