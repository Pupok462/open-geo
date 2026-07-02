from __future__ import annotations

import argparse
import csv
import io
import json
import sys

from pydantic import ValidationError

from harvest.schema import QuestionCandidate, contains_brand, normalize_query

LENSES = ("general", "branded", "comparative")


def _error(index: int, raw: object, field: str, msg: str) -> dict:
    query = raw.get("query") if isinstance(raw, dict) else None
    return {"index": index, "query": query, "field": field, "msg": msg}


def _lens_error(index: int, cand: QuestionCandidate, brand: str) -> dict | None:
    if not brand:
        return None
    has_brand = contains_brand(cand.query, brand)
    if cand.lens == "general" and has_brand:
        return _error(
            index, cand.model_dump(), "lens",
            "general lens must not name the brand",
        )
    if cand.lens == "branded" and not has_brand:
        return _error(
            index, cand.model_dump(), "lens",
            "branded lens must name the brand",
        )
    return None


def build(raw_items: list, brand: str = "") -> dict:
    errors: list[dict] = []
    accepted: list[QuestionCandidate] = []

    for index, raw in enumerate(raw_items):
        try:
            cand = QuestionCandidate.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first.get("loc", ())) or "?"
            errors.append(_error(index, raw, field, first.get("msg", "invalid")))
            continue
        lens_err = _lens_error(index, cand, brand)
        if lens_err is not None:
            errors.append(lens_err)
            continue
        accepted.append(cand)

    seen: set[str] = set()
    kept: list[QuestionCandidate] = []
    dropped_dups = 0
    for cand in accepted:
        key = normalize_query(cand.query)
        if key in seen:
            dropped_dups += 1
            continue
        seen.add(key)
        kept.append(cand)

    by_lens = {lens: sum(1 for c in kept if c.lens == lens) for lens in LENSES}
    return {
        "kept": kept,
        "written": len(kept),
        "by_lens": by_lens,
        "dropped_dups": dropped_dups,
        "errors": errors,
    }


def to_csv(candidates: list[QuestionCandidate]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["query", "lens"])
    for cand in candidates:
        writer.writerow([cand.query, cand.lens])
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harvest.build")
    parser.add_argument("--out", required=True)
    parser.add_argument("--brand", default="")
    args = parser.parse_args(argv)

    try:
        raw_items = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"stdin is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw_items, list):
        print("stdin must be a JSON array of QuestionCandidate objects", file=sys.stderr)
        return 1

    result = build(raw_items, brand=args.brand)

    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        fh.write(to_csv(result["kept"]))

    print(json.dumps({
        "out": args.out,
        "written": result["written"],
        "by_lens": result["by_lens"],
        "dropped_dups": result["dropped_dups"],
        "errors": result["errors"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
