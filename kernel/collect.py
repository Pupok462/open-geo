"""One round of kernel growth. Expand real phrasings, attach, optionally auto-gate."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from kernel.classify import auto_accept, normalize
from kernel.cluster import attach
from kernel.ingest import category_tokens, profile_from_html, profile_from_url
from kernel.schema import Formulation, Kernel
from kernel.store import save, slugify

ExpandFn = Callable[[str, str, str, int], dict]


def start(
    url: str,
    *,
    brand: str | None = None,
    geo: str = "ru",
    language: str = "ru",
    gate: str = "human",
    html: str | None = None,
    root=None,
) -> Kernel:
    from demand import doctor as demand_doctor

    profile = profile_from_html(url, html, brand=brand) if html is not None else profile_from_url(url, brand=brand)
    report = demand_doctor.diagnose(geo, language)
    kernel = Kernel(
        slug=slugify(profile.brand or profile.domain),
        brand=profile.brand,
        domain=profile.domain,
        url=profile.url,
        geo=geo,
        language=language,
        gate=gate if gate in {"human", "auto"} else "human",
        volume_available=bool(report.get("volume_capable")),
        doctor_verdict=str(report.get("verdict") or ""),
        profile=profile,
    )
    save(kernel, root)
    return kernel


def round(
    kernel: Kernel,
    *,
    n: int = 12,
    expand: ExpandFn | None = None,
    root=None,
) -> Kernel:
    """Grow the inbox by expanding current seeds. Does not invent phrases."""
    kernel.round += 1
    expander = expand or _default_expand
    seeds = _seeds_for_round(kernel)
    cat = category_tokens(kernel.profile) if kernel.profile else set()
    seen = {normalize(t) for t in kernel.known_texts()}
    added = 0
    per_seed = max(4, n // max(len(seeds), 1) + 2)

    for seed in seeds:
        if added >= n:
            break
        try:
            payload = expander(seed, kernel.geo, kernel.language, per_seed)
        except Exception as exc:  # noqa: BLE001
            payload = {"phrases": [], "error": str(exc)}
        for item in payload.get("phrases") or []:
            if added >= n:
                break
            text = str(item.get("phrase") or "").strip()
            key = normalize(text)
            if not key or key in seen:
                continue
            before = {q.id for q in kernel.questions}
            q = attach(
                kernel,
                Formulation(
                    text=text,
                    volume=item.get("volume"),
                    provider=str(item.get("provider") or "suggest"),
                    scope=str(item.get("scope") or ""),
                    source_url=item.get("source_url"),
                ),
                brand=kernel.brand,
                category_tokens=cat,
                round_no=kernel.round,
            )
            seen.add(key)
            if q is None:
                continue
            minted = q.id not in before
            if minted:
                added += 1
                if kernel.gate == "auto":
                    _apply_auto(kernel, q)

    kernel.updated_at = datetime.now(timezone.utc).isoformat()
    save(kernel, root)
    return kernel


def decide(kernel: Kernel, question_id: str, status: str, root=None) -> Kernel:
    if status not in {"accepted", "rejected", "deferred", "inbox"}:
        raise ValueError(f"bad status: {status}")
    for q in kernel.questions:
        if q.id != question_id:
            continue
        q.status = status  # type: ignore[assignment]
        if status == "rejected":
            kernel.rejected_memory.append(q.canonical.lower())
        break
    else:
        raise KeyError(question_id)
    save(kernel, root)
    return kernel


def _apply_auto(kernel: Kernel, q) -> None:
    if auto_accept(q):
        q.status = "accepted"
    else:
        q.status = "deferred"


def _seeds_for_round(kernel: Kernel) -> list[str]:
    seeds: list[str] = []
    if kernel.profile:
        seeds.extend(kernel.profile.seeds)
    for q in kernel.questions:
        if q.status == "accepted":
            seeds.append(q.canonical)
    if kernel.brand and kernel.brand not in seeds:
        seeds.insert(0, kernel.brand)
    # later rounds prefer accepted questions so the lattice grows down, not sideways
    if kernel.round >= 1:
        accepted = [q.canonical for q in kernel.questions if q.status == "accepted"]
        if accepted:
            seeds = accepted + [s for s in seeds if s not in accepted]
    seen: set[str] = set()
    out: list[str] = []
    for s in seeds:
        key = normalize(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out[:10]


def _default_expand(seed: str, geo: str, language: str, n: int) -> dict:
    from demand.expand import expand_seed

    return expand_seed(seed, geo, language, n=n, deep=True)
