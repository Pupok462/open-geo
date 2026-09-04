"""Merge formulations into questions; hang children under parents."""

from __future__ import annotations

from kernel.classify import intent, rel, token_set
from kernel.schema import Formulation, Kernel, Question


def same_question(a: str, b: str) -> bool:
    sa, sb = token_set(a), token_set(b)
    if not sa or not sb:
        return False
    return sa == sb


def is_child(parent: str, child: str) -> bool:
    """child is parent plus extra constraints — not a synonym."""
    p, c = token_set(parent), token_set(child)
    if not p or not c or p == c:
        return False
    return p < c


def attach(
    kernel: Kernel,
    formulation: Formulation,
    *,
    brand: str,
    category_tokens: set[str],
    round_no: int,
) -> Question | None:
    """Put a formulation on an existing question, hang it as a child, or mint a new one."""
    text = formulation.text.strip()
    if not text:
        return None
    known = kernel.known_texts()
    if text.lower() in known:
        for q in kernel.questions:
            if same_question(q.canonical, text):
                if all(f.text.lower() != text.lower() for f in q.formulations):
                    q.formulations.append(formulation)
                    _refresh_volume(q)
                return q
        return None

    for q in kernel.questions:
        if same_question(q.canonical, text):
            q.formulations.append(formulation)
            _refresh_volume(q)
            return q

    parent_id = None
    for q in kernel.questions:
        if q.status == "rejected":
            continue
        if is_child(q.canonical, text):
            parent_id = q.id
            break

    from kernel.classify import band, insert_for, why

    qid = f"q{len(kernel.questions) + 1:03d}"
    q = Question(
        id=qid,
        canonical=text,
        formulations=[formulation],
        intent=intent(text),
        band=band(formulation.volume),
        rel=rel(text, brand, category_tokens),
        parent_id=parent_id,
        status="inbox",
        volume=formulation.volume,
        round=round_no,
    )
    q.insert = insert_for(q)
    q.why = why(q)
    kernel.questions.append(q)
    return q


def _refresh_volume(q: Question) -> None:
    from kernel.classify import band, insert_for, why

    vols = [f.volume for f in q.formulations if f.volume is not None]
    q.volume = max(vols) if vols else None
    q.band = band(q.volume)
    q.insert = insert_for(q)
    q.why = why(q)
