#!/usr/bin/env python3
"""Emit Grok-native skill and agent files from `.agentsmesh`.

agentsmesh 0.32 cannot name a `grok-cli` target. Grok discovers project skills
from `.grok/skills/` and spawnable agent types from `.grok/agents/`. This script
is the adapter for that host: it copies the canonical trees, rewrites worker
pointers so they resolve *inside* `.grok/`, and writes Grok agent frontmatter
without Claude-in-Chrome MCP tool names.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANON = REPO_ROOT / ".agentsmesh"
GROK_ROOT = REPO_ROOT / ".grok"
GROK_SKILLS = GROK_ROOT / "skills"
GROK_AGENTS = GROK_ROOT / "agents"

SKILLS = ("open-geo", "semantic-core")
WORKERS = (
    "capture-worker",
    "harvest-worker",
    "harvest-skeptic",
    "core-worker",
)

WORKER_POINTER_RE = re.compile(
    r"`([^`]*?(?:capture-worker|harvest-worker|harvest-skeptic|core-worker)\.(?:md|toml))`"
)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def _frontmatter_field(block: str, key: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(key)}:\s*(?:>(?:\n(?:[ \t].*)?)+|.+)$",
        re.MULTILINE,
    )
    match = pattern.search(block)
    if not match:
        return ""
    raw = match.group(0).split(":", 1)[1].strip()
    if raw.startswith(">"):
        lines = raw.lstrip(">").splitlines()
        return " ".join(line.strip() for line in lines if line.strip())
    return raw.strip().strip('"').strip("'")


def split_frontmatter(text: str) -> tuple[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def rewrite_worker_pointers(text: str, src_file: Path) -> str:
    def repl(match: re.Match[str]) -> str:
        name = Path(match.group(1)).stem
        target = GROK_AGENTS / f"{name}.md"
        rel = Path(os_relpath(target, src_file.parent)).as_posix()
        return f"`{rel}`"

    return WORKER_POINTER_RE.sub(repl, text)


def os_relpath(target: Path, start: Path) -> str:
    import os

    return os.path.relpath(target, start)


def emit_skills() -> None:
    if GROK_SKILLS.exists():
        shutil.rmtree(GROK_SKILLS)
    for skill in SKILLS:
        src_dir = CANON / "skills" / skill
        dest_dir = GROK_SKILLS / skill
        shutil.copytree(src_dir, dest_dir)
        for path in dest_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
                text = path.read_text(encoding="utf-8")
                path.write_text(rewrite_worker_pointers(text, path), encoding="utf-8")


def grok_agent_frontmatter(name: str, description: str) -> str:
    desc = description.strip() or name
    return (
        "---\n"
        f"name: {name}\n"
        "description: >\n"
        f"  {desc}\n"
        "prompt_mode: full\n"
        "model: inherit\n"
        "permission_mode: default\n"
        "agents_md: true\n"
        "---\n"
    )


def emit_agents() -> None:
    GROK_AGENTS.mkdir(parents=True, exist_ok=True)
    for worker in WORKERS:
        src = CANON / "agents" / f"{worker}.md"
        dest = GROK_AGENTS / f"{worker}.md"
        text = src.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        description = _frontmatter_field(fm, "description")
        dest.write_text(
            grok_agent_frontmatter(worker, description) + body.lstrip("\n"),
            encoding="utf-8",
        )


_CLAUDE_CHROME_TOOL_LINE = re.compile(r"^\s*-\s*mcp__claude-in-chrome__\S+\s*$")


def strip_claude_chrome_tools(text: str) -> str:
    fm, body = split_frontmatter(text)
    if not fm:
        return text
    kept = [line for line in fm.splitlines() if not _CLAUDE_CHROME_TOOL_LINE.match(line)]
    return f"---\n" + "\n".join(kept) + "\n---\n" + body


def adapt_non_claude_markdown_capture_workers() -> None:
    """Cursor/Gemini inherit Claude-in-Chrome tool names from generate; drop them.

    Those hosts must bind capture to their own visible browser, or stop. Codex
    workers are toml without a tools list.
    """
    for rel in (
        ".cursor/agents/capture-worker.md",
        ".gemini/agents/capture-worker.md",
    ):
        path = REPO_ROOT / rel
        if path.is_file():
            path.write_text(strip_claude_chrome_tools(path.read_text(encoding="utf-8")), encoding="utf-8")


def main() -> int:
    if not (CANON / "skills" / "open-geo" / "SKILL.md").is_file():
        print("canonical .agentsmesh/skills/open-geo/SKILL.md is missing", file=sys.stderr)
        return 1
    GROK_ROOT.mkdir(parents=True, exist_ok=True)
    emit_agents()
    emit_skills()
    adapt_non_claude_markdown_capture_workers()
    print(f"wrote {GROK_SKILLS.relative_to(REPO_ROOT)} and {GROK_AGENTS.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
