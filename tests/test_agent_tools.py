from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

KNOWN_MCP_SERVERS = {"claude-in-chrome"}

BROWSER_DRIVING_AGENTS = {"capture-worker", "harvest-worker"}

_MCP_TOOL_RE = re.compile(r"mcp__([A-Za-z0-9_-]+?)__(?:[A-Za-z0-9_]+|\*)")
_FRONTMATTER_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*\s*:")

_EXECUTED_SURFACES = (
    ".claude/agents/*.md",
    ".claude/skills/*/SKILL.md",
    "engines/*.md",
)


def _agent_files():
    return sorted((REPO_ROOT / ".claude" / "agents").glob("*.md"))


def _executed_files():
    seen = []
    for pattern in _EXECUTED_SURFACES:
        seen.extend(sorted(REPO_ROOT.glob(pattern)))
    return seen


def _frontmatter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{path.name} does not open with a frontmatter fence"
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    assert end is not None, f"{path.name} has an unterminated frontmatter block"
    return lines[1:end]


def _tools_region(path):
    lines = _frontmatter(path)
    start = next((i for i, line in enumerate(lines) if re.match(r"^tools\s*:", line)), None)
    assert start is not None, f"{path.name} frontmatter declares no tools: key"
    region = [lines[start]]
    for line in lines[start + 1:]:
        if _FRONTMATTER_KEY_RE.match(line):
            break
        region.append(line)
    return "\n".join(region)


def _mcp_servers_in(text):
    return [match.group(1) for match in _MCP_TOOL_RE.finditer(text)]


def _rel(path):
    return str(path.relative_to(REPO_ROOT))


def test_agent_directory_is_not_empty():
    assert _agent_files(), "no agent definitions found under .claude/agents/"


@pytest.mark.parametrize("path", _agent_files(), ids=_rel)
def test_agent_frontmatter_mcp_tools_name_a_known_server(path):
    unknown = sorted({s for s in _mcp_servers_in(_tools_region(path)) if s not in KNOWN_MCP_SERVERS})
    assert not unknown, (
        f"{_rel(path)} declares MCP tools for unknown server id(s) {unknown}; "
        f"tool names are matched verbatim against the live server id, so only "
        f"{sorted(KNOWN_MCP_SERVERS)} resolve. An agent whose names do not resolve "
        f"silently starts with none of those tools."
    )


@pytest.mark.parametrize(
    "path",
    [p for p in _agent_files() if p.stem in BROWSER_DRIVING_AGENTS],
    ids=_rel,
)
def test_browser_driving_agents_actually_declare_browser_tools(path):
    servers = set(_mcp_servers_in(_tools_region(path)))
    assert "claude-in-chrome" in servers, (
        f"{_rel(path)} drives a browser but declares no mcp__claude-in-chrome__* tools"
    )


@pytest.mark.parametrize("path", _executed_files(), ids=_rel)
def test_executed_surfaces_reference_a_known_mcp_server(path):
    unknown = sorted({s for s in _mcp_servers_in(path.read_text(encoding="utf-8")) if s not in KNOWN_MCP_SERVERS})
    assert not unknown, (
        f"{_rel(path)} references MCP server id(s) {unknown}; agents read this file "
        f"as instructions, so a name that does not resolve becomes a runtime failure. "
        f"Known: {sorted(KNOWN_MCP_SERVERS)}."
    )
