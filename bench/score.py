from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.schema import QueryCapture, normalize_domain

FIXTURE_ARTIFACTS = ("01_get_page_text.txt", "02_read_page_interactive.txt", "03_dom_links.json")


def _domains(links: list[dict[str, Any]]) -> list[str]:
    out = []
    for link in links:
        url = link.get("url") or ""
        try:
            out.append(normalize_domain(url))
        except Exception:
            out.append(str(link.get("domain") or ""))
    return out


def _multiset_f1(candidate: list[str], truth: list[str]) -> dict[str, float]:
    c, t = Counter(candidate), Counter(truth)
    tp = sum((c & t).values())
    precision = tp / sum(c.values()) if c else (1.0 if not t else 0.0)
    recall = tp / sum(t.values()) if t else 1.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3)}


def _ranks_ok(candidate: Any, truth: Any) -> bool:
    return list(candidate or []) == list(truth or [])


def _domain_field_accuracy(links: list[dict[str, Any]]) -> float | None:
    if not links:
        return None
    ok = 0
    for link in links:
        try:
            ok += int(str(link.get("domain", "")).lower() == normalize_domain(link.get("url") or ""))
        except Exception:
            pass
    return round(ok / len(links), 3)


def _fabricated(links: list[dict[str, Any]], corpus: str) -> list[str]:
    missing = []
    for link in links:
        url = str(link.get("url") or "")
        probe = url.split("?")[0].rstrip("/")
        if probe and probe not in corpus:
            missing.append(url)
    return missing


def score(candidate_path: Path, fixture_dir: Path, truth_path: Path) -> dict[str, Any]:
    truth = json.loads(truth_path.read_text())
    corpus = "\n".join((fixture_dir / name).read_text() for name in FIXTURE_ARTIFACTS)

    raw = candidate_path.read_text().strip()
    try:
        candidate = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"model": candidate_path.stem, "parse_error": str(exc)}
    if isinstance(candidate, list):
        candidate = candidate[0] if candidate else {}

    try:
        QueryCapture.model_validate(candidate)
        schema_valid = True
        schema_error = None
    except Exception as exc:
        schema_valid = False
        schema_error = str(exc).splitlines()[0]

    cand_sources = candidate.get("sources") or []
    cand_citations = candidate.get("citations") or []
    all_links = list(cand_sources) + list(cand_citations)

    truth_sentiment_null = truth.get("sentiment") is None
    cand_sentiment_null = candidate.get("sentiment") is None

    return {
        "model": candidate_path.stem,
        "schema_valid": schema_valid,
        "schema_error": schema_error,
        "overview_present_ok": candidate.get("overview_present") == truth["overview_present"],
        "brand_in_answer_text_ok": candidate.get("brand_in_answer_text") == truth["brand_in_answer_text"],
        "sentiment_nullness_ok": cand_sentiment_null == truth_sentiment_null,
        "target_source_ranks_ok": _ranks_ok(candidate.get("target_source_ranks"), truth["target_source_ranks"]),
        "target_citation_ranks_ok": _ranks_ok(candidate.get("target_citation_ranks"), truth["target_citation_ranks"]),
        "sources": _multiset_f1(_domains(cand_sources), _domains(truth["sources"])),
        "citations": _multiset_f1(_domains(cand_citations), _domains(truth["citations"])),
        "sources_exact_order": _domains(cand_sources) == _domains(truth["sources"]),
        "citations_exact_order": _domains(cand_citations) == _domains(truth["citations"]),
        "n_sources": len(cand_sources),
        "n_citations": len(cand_citations),
        "domain_field_accuracy": _domain_field_accuracy(all_links),
        "fabricated_urls": _fabricated(all_links, corpus),
        "answer_text_present": bool(candidate.get("answer_text_md")),
    }


def _hard_gates(row: dict[str, Any]) -> list[str]:
    gates = [
        ("schema", row.get("schema_valid")),
        ("gate", row.get("overview_present_ok")),
        ("brand", row.get("brand_in_answer_text_ok")),
        ("sent-null", row.get("sentiment_nullness_ok")),
        ("src-ranks", row.get("target_source_ranks_ok")),
        ("cit-ranks", row.get("target_citation_ranks_ok")),
        ("no-fabrication", not row.get("fabricated_urls")),
    ]
    return [name for name, ok in gates if not ok]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--truth", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    fixture_dir, truth_path = Path(args.fixture), Path(args.truth)
    rows = [score(p, fixture_dir, truth_path) for p in sorted(Path(args.candidates).glob("*.json"))]

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    header = f"{'model':<22}{'schema':<8}{'src F1':<9}{'cit F1':<9}{'n_src':<7}{'n_cit':<7}{'fabricated':<12}failed gates"
    print(header)
    print("-" * len(header))
    for row in rows:
        if "parse_error" in row:
            print(f"{row['model']:<22}INVALID JSON — {row['parse_error']}")
            continue
        failed = _hard_gates(row)
        print(
            f"{row['model']:<22}"
            f"{('ok' if row['schema_valid'] else 'FAIL'):<8}"
            f"{row['sources']['f1']:<9}"
            f"{row['citations']['f1']:<9}"
            f"{row['n_sources']:<7}"
            f"{row['n_citations']:<7}"
            f"{len(row['fabricated_urls']):<12}"
            f"{', '.join(failed) if failed else '—'}"
        )


if __name__ == "__main__":
    main()
