from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, get_args

from pydantic import BaseModel, Field, ValidationError, field_validator

from harvest.build import build as harvest_build, to_csv
from harvest.schema import QuestionCandidate
from pipeline.schema import Lens

Intent = Literal["informational", "commercial", "navigational", "comparative"]

LENSES = get_args(Lens)


class CorePhrase(BaseModel):
    """One measured phrase behind a cluster — the evidence a question stands on."""

    phrase: str
    provider: Optional[str] = None
    volume: Optional[int] = None
    metric: Optional[str] = None
    scope: str = ""
    source_url: Optional[str] = None

    @field_validator("phrase")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("must be a non-empty string")
        return str(v).strip()


class CoreCluster(BaseModel):
    """A demand cluster: measured phrases + the assistant prompts they justify."""

    name: str
    intent: Intent
    lens: Lens
    geo: str
    language: str
    phrases: list[CorePhrase] = Field(min_length=1)
    questions: list[str] = Field(min_length=1)
    note: Optional[str] = None


class SemanticCore(BaseModel):
    brand: str
    domain: str
    market: str = ""
    generated_at: str
    geos: list[str] = []
    languages: list[str] = []
    clusters: list[CoreCluster] = []
    questions_csv: str = ""
    rationale_md: str = ""
    totals: dict = {}
    notes: list[str] = []


def _measured(phrase: CorePhrase) -> bool:
    """A phrase counts as evidence only when a provider actually answered for it."""
    return bool(phrase.provider) and bool(phrase.scope.strip())


def _best_phrase(cluster: CoreCluster) -> Optional[CorePhrase]:
    measured = [p for p in cluster.phrases if _measured(p)]
    if not measured:
        return None
    with_volume = [p for p in measured if p.volume]
    pool = with_volume or measured
    return max(pool, key=lambda p: (p.volume or 0))


def to_candidates(core: SemanticCore) -> tuple[list[QuestionCandidate], list[dict]]:
    """Cluster questions -> QuestionCandidate rows, carrying the demand evidence.

    A cluster whose phrases were never measured cannot mint questions: that is the
    whole point of routing the harvest through the demand APIs, so an unmeasured
    cluster is an error row rather than a silently shipped guess.
    """
    candidates: list[QuestionCandidate] = []
    errors: list[dict] = []
    for index, cluster in enumerate(core.clusters):
        anchor = _best_phrase(cluster)
        if anchor is None:
            errors.append({
                "index": index, "cluster": cluster.name, "field": "phrases",
                "msg": "no measured phrase (provider+scope) — cluster cannot ship questions",
            })
            continue
        for question in cluster.questions:
            text = str(question).strip()
            if not text:
                errors.append({
                    "index": index, "cluster": cluster.name, "field": "questions",
                    "msg": "empty question",
                })
                continue
            candidates.append(QuestionCandidate(
                query=text,
                lens=cluster.lens,
                segment=cluster.name,
                signal=anchor.scope,
                source_url=anchor.source_url or "https://wordstat.yandex.ru/",
                note=cluster.note,
            ))
    return candidates, errors


def coverage(core: SemanticCore) -> dict:
    phrases = [p for cluster in core.clusters for p in cluster.phrases]
    measured = [p for p in phrases if _measured(p)]
    return {
        "phrases": len(phrases),
        "measured": len(measured),
        "with_volume": len([p for p in measured if p.volume]),
        "presence_only": len([p for p in measured if not p.volume]),
        "unmeasured": len(phrases) - len(measured),
        "total_volume": sum(p.volume or 0 for p in measured),
    }


def build_core(payload: dict, *, brand: str = "", domain: str = "") -> dict:
    """Validate a core, mint its questions, and return everything the caller writes."""
    data = dict(payload)
    data.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    if brand:
        data["brand"] = brand
    if domain:
        data["domain"] = domain
    data.setdefault("brand", "")
    data.setdefault("domain", "")

    try:
        core = SemanticCore.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ())) or "?"
        return {"core": None, "errors": [{"field": field, "msg": first.get("msg", "invalid")}]}

    if not core.geos:
        core.geos = sorted({c.geo for c in core.clusters})
    if not core.languages:
        core.languages = sorted({c.language for c in core.clusters})

    candidates, errors = to_candidates(core)
    result = harvest_build([c.model_dump() for c in candidates], brand=core.brand)
    errors += result["errors"]

    core.totals = {
        "clusters": len(core.clusters),
        "questions": result["written"],
        "by_lens": result["by_lens"],
        "dropped_dups": result["dropped_dups"],
        "coverage": coverage(core),
    }
    return {"core": core, "candidates": result["kept"], "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demand.core",
        description=(
            "Commit a measured semantic core: validate clusters, mint questions.csv "
            "through harvest.build, and write the core.json hand-off open-geo reads."
        ),
    )
    parser.add_argument("--out", required=True, help="core.json destination")
    parser.add_argument("--questions-out", required=True, help="questions.csv destination")
    parser.add_argument("--brand", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--rationale", default="", help="path of the sibling rationale .md (recorded only)")
    args = parser.parse_args(argv)

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"stdin is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("stdin must be a SemanticCore JSON object", file=sys.stderr)
        return 1

    built = build_core(payload, brand=args.brand, domain=args.domain)
    core: Optional[SemanticCore] = built["core"]
    if core is None:
        print(json.dumps({"out": args.out, "errors": built["errors"]}, ensure_ascii=False))
        return 1

    questions_path = Path(args.questions_out)
    if questions_path.parent and not questions_path.parent.exists():
        questions_path.parent.mkdir(parents=True, exist_ok=True)
    questions_path.write_text(to_csv(built["candidates"]), encoding="utf-8")

    core.questions_csv = str(questions_path)
    core.rationale_md = args.rationale
    core_path = Path(args.out)
    if core_path.parent and not core_path.parent.exists():
        core_path.parent.mkdir(parents=True, exist_ok=True)
    core_path.write_text(
        json.dumps(core.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps({
        "core": str(core_path),
        "questions_csv": str(questions_path),
        "brand": core.brand,
        "domain": core.domain,
        "clusters": core.totals["clusters"],
        "written": core.totals["questions"],
        "by_lens": core.totals["by_lens"],
        "coverage": core.totals["coverage"],
        "errors": built["errors"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
