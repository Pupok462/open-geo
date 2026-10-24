"""Execute the skill's documented commands against isolated synthetic captures.

The commands are read from canonical references so a documentation/CLI drift fails
here. Bind the documented runtime Python to pytest's interpreter: CI installs the
same dependencies directly rather than creating a project .venv.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".agentsmesh/skills/open-geo"


def _block(path: Path, fragment: str) -> str:
    matches = [textwrap.dedent(b) for _, b in re.findall(r"^([ \t]*)```bash\n(.*?)\n\1```", path.read_text(), re.S | re.M)
               if fragment in b]
    assert len(matches) == 1, (path, fragment, len(matches))
    return matches[0]


def _shell(command: str, env: dict[str, str]):
    command = re.sub(r"(?m)^\.venv/bin/python(?= )", lambda _: shlex.quote(sys.executable), command)
    proc = subprocess.run(["bash", "-euc", command], cwd=ROOT,
                          env={**os.environ, **env}, capture_output=True, text=True)
    return proc


def _run(command: str, env: dict[str, str], *, success: bool = True):
    proc = _shell(command, env)
    if success:
        assert proc.returncode == 0, proc.stderr
        values = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        return values[0] if len(values) == 1 else values
    assert proc.returncode != 0
    return proc


@pytest.fixture
def replay(tmp_path):
    caller = tmp_path / "caller with spaces"
    caller.mkdir()
    csv_path = caller / "questions.csv"
    rows = [("SYNTHETIC инструменты GEO", "general"),
            ("SYNTHETIC Example alternatives", "comparative"),
            ("SYNTHETIC Example no answer", "branded")]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["query", "lens"])
        writer.writerows(rows + rows[:1])
    env = {"CSV": str(csv_path), "DB": str(tmp_path / "isolated.db"),
           "ARTIFACT": str(caller / "run.json"), "WORK": str(tmp_path),
           "BRAND": "Example", "TARGET": "github.com/example/project", "ENGINE": "google",
           "CAPTURE_OUT": str(tmp_path / "capture.json"),
           "CHUNK": str(tmp_path / "chunk.json"),
           "SUMMARIES": str(tmp_path / "summaries.json")}
    captures = []
    for i, (query, lens) in enumerate(rows):
        url = "https://github.com/example/project" if i == 0 else "https://github.com/other/repo"
        links = [{"rank": 1, "url": url, "domain": "github.com"}]
        captures.append({"query": query, "lens": lens, "engine": "google",
                         "captured_at": "2026-10-25T00:00:00Z",
                         "overview_present": i != 2, "sources": links if i != 2 else [],
                         "citations": links if i == 0 else [],
                         "target_source_ranks": [], "target_citation_ranks": [],
                         "answer_text_md": "Example is cited." if i == 0 else None,
                         "brand_in_answer_text": i == 0,
                         "sentiment": "Упомянут со ссылкой." if i == 0 else None})
    Path(env["CAPTURE_OUT"]).write_text(json.dumps(captures, ensure_ascii=False))
    worker = ROOT / ".agentsmesh/agents/capture-worker.md"
    proc = _shell(_block(worker, "QueryCapture"), env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "valid"
    captures = json.loads(Path(env["CAPTURE_OUT"]).read_text())
    return env, captures


def _doc(fragment, env, **kwargs):
    return _run(_block(SKILL / "references/run.md", fragment), env, **kwargs)


def test_documented_resume_ingest_finalize_export(replay):
    env, captures = replay
    assert _doc("n_unique", env)["n_unique"] == 3
    assert not Path(env["DB"]).exists()
    assert _doc("--resume-check", env)["run_id"] is None
    created = _doc("--new-run", env)
    env["RUN_ID"] = str(created["run_id"])
    Path(env["CHUNK"]).write_text(json.dumps(captures[:1]))
    assert _doc("< \"$CHUNK\"", env)["ok"] == [0]
    resumed = _doc("--resume-check", env)
    assert resumed["resumable"] and resumed["n_captured"] == 1
    assert resumed["n_missing"] == 2
    repeated = _doc("< \"$CHUNK\"", env)
    assert repeated == {"run_id": created["run_id"], "ok": [], "skipped": [0], "errors": []}
    Path(env["CHUNK"]).write_text(json.dumps(captures[1:]))
    assert _doc("< \"$CHUNK\"", env)["errors"] == []
    pending = _doc("--pending", env)
    assert pending["n_total"] == pending["n_captured"] == 3
    assert pending["pending"] == []
    stored = _doc("sqlite3.connect", env)
    assert stored == {"expected": 3, "stored": 3, "missing": [], "extra": []}
    env.update(TOTAL=str(pending["n_total"]), STORED=str(stored["stored"]))
    assert _doc("--finalize", env)["n_failed"] == 0
    aggregated, sentiments = _doc("-m pipeline.aggregate", env)
    assert len(sentiments) == 3
    summaries = {"all": "Упомянут со ссылкой.", "general": "Упомянут со ссылкой.",
                 "branded": None, "comparative": None}
    Path(env["SUMMARIES"]).write_text(json.dumps(summaries, ensure_ascii=False))
    assert set(_doc("-m pipeline.lens_sentiment", env)["written"]) == set(summaries)
    exported = _doc("-m pipeline.artifact", env)
    a = json.loads(Path(exported["artifact_path"]).read_text())
    assert a["schema_version"] == "open-geo.run-artifact.v1"
    assert a["run"]["status"] == "done" and a["run"]["n_ok"] == 3
    assert a["run"]["n_queries"] == 3 and a["run"]["n_failed"] == 0
    assert a["lens_sentiment"] == summaries
    m = a["metrics"]["all"]
    reported = next(row for row in aggregated["metrics"] if row["lens"] == "all")
    assert all(m[key] == value for key, value in reported.items())
    assert m["overview_coverage"] == pytest.approx(2 / 3)
    assert m["visibility_in_sources"] == m["visibility_in_citations"] == 0.5
    assert m["brand_mention_rate"] == 0.5 and m["relative_citation"] == 1
    assert a["metrics"]["branded"]["visibility_in_sources"] is None
    assert a["results"][1]["target_source_ranks"] == []
    assert a["domain_stats"]["all"][0]["appearances_sources"] == 2


def test_documented_preflight_rejects_bad_csv_without_creating_db(replay):
    env, _ = replay
    Path(env["CSV"]).write_text("query,lens\ninvalid,promotional\n")
    result = _doc("n_unique", env, success=False)
    assert "promotional" in result.stderr
    assert not Path(env["DB"]).exists()


def test_documented_partial_export_keeps_missing_separate_from_no_answer(replay):
    env, captures = replay
    env["RUN_ID"] = str(_doc("--new-run", env)["run_id"])
    Path(env["CHUNK"]).write_text(json.dumps(captures[:1]))
    _doc("< \"$CHUNK\"", env)
    pending = _doc("--pending", env)
    assert pending["n_pending"] == 2
    assert _doc("--resume-check", env)["resumable"]
    env.update(TOTAL=str(pending["n_total"]), STORED=str(pending["n_captured"]))
    command = _block(SKILL / "references/run.md", "--finalize")
    final = _run(command.replace("--status done", "--status failed"), env)
    assert final["status"] == "failed" and final["n_failed"] == 2
    _doc("-m pipeline.aggregate", env)
    _doc("-m pipeline.artifact", env)
    a = json.loads(Path(env["ARTIFACT"]).read_text())
    assert a["run"]["n_queries"] == 3 and len(a["results"]) == 1
    assert a["metrics"]["all"]["n_queries"] == 1
    assert a["metrics"]["all"]["overview_coverage"] == 1
    assert not _doc("--resume-check", env)["resumable"]


def test_documented_pause_export_keeps_expected_counts_and_resume(replay):
    env, captures = replay
    env["RUN_ID"] = str(_doc("--new-run", env)["run_id"])
    Path(env["CHUNK"]).write_text(json.dumps(captures[:1]))
    _doc("< \"$CHUNK\"", env)
    pending = _doc("--pending", env)
    env.update(TOTAL=str(pending["n_total"]), STORED=str(pending["n_captured"]))
    paused = _doc("update_run_counts", env)
    assert paused["status"] == "running" and paused["n_pending"] == 2
    _doc("-m pipeline.aggregate", env)
    _doc("-m pipeline.artifact", env)
    a = json.loads(Path(env["ARTIFACT"]).read_text())
    assert a["run"]["status"] == "running"
    assert a["run"]["n_queries"] == 3 and a["run"]["n_ok"] == 1
    assert a["run"]["n_failed"] == 0 and len(a["results"]) == 1
    assert a["metrics"]["all"]["n_queries"] == 1
    resumed = _doc("--resume-check", env)
    assert resumed["resumable"] and resumed["n_missing"] == 2


@pytest.mark.parametrize("root", [".agentsmesh", ".agents", ".claude", ".cursor", ".gemini", ".grok"])
def test_skill_entrypoint_budget_and_reference_links(root):
    path = ROOT / root / "skills/open-geo/SKILL.md"
    text = path.read_text()
    description = re.search(r"^description: (.+)$", text, re.M).group(1)
    assert len(description) <= 1024
    assert len(text.splitlines()) <= 500
    links = re.findall(r"\]\((\.?/?references/[^)]+)\)", text)
    assert links
    for link in links:
        assert (path.parent / link).is_file(), (path, link)
