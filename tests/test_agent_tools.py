from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

KNOWN_MCP_SERVERS = {"claude-in-chrome"}

BROWSER_DRIVING_AGENTS = {"capture-worker"}

SKILLS = ("open-geo", "semantic-core")
WORKERS = (
    "capture-worker",
    "harvest-worker",
    "harvest-skeptic",
    "core-worker",
)

# Native layout each configured host actually scans.
# Codex skills live under `.agents/skills`; Codex workers live under `.codex/agents`.
HOSTS = {
    "claude": {
        "skill_root": ".claude/skills",
        "agent_pattern": ".claude/agents/{name}.md",
        "roots": (".claude",),
        "claude_chrome_required": True,
    },
    "codex": {
        "skill_root": ".agents/skills",
        "agent_pattern": ".codex/agents/{name}.toml",
        "roots": (".agents", ".codex"),
        "claude_chrome_required": False,
    },
    "cursor": {
        "skill_root": ".cursor/skills",
        "agent_pattern": ".cursor/agents/{name}.md",
        "roots": (".cursor",),
        "claude_chrome_required": False,
    },
    "gemini": {
        "skill_root": ".gemini/skills",
        "agent_pattern": ".gemini/agents/{name}.md",
        "roots": (".gemini",),
        "claude_chrome_required": False,
    },
    "grok": {
        "skill_root": ".grok/skills",
        "agent_pattern": ".grok/agents/{name}.md",
        "roots": (".grok",),
        "claude_chrome_required": False,
    },
}

_MCP_TOOL_RE = re.compile(r"mcp__([A-Za-z0-9_-]+?)__(?:[A-Za-z0-9_]+|\*)")
_FRONTMATTER_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*\s*:")
_WORKER_POINTER_RE = re.compile(
    r"`([^`]*?(?:capture-worker|harvest-worker|harvest-skeptic|core-worker)\.(?:md|toml))`"
)

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
    for line in lines[start + 1 :]:
        if _FRONTMATTER_KEY_RE.match(line):
            break
        region.append(line)
    return "\n".join(region)


def _maybe_tools_region(path: Path) -> str:
    lines = _frontmatter(path)
    start = next((i for i, line in enumerate(lines) if re.match(r"^tools\s*:", line)), None)
    if start is None:
        return ""
    region = [lines[start]]
    for line in lines[start + 1 :]:
        if _FRONTMATTER_KEY_RE.match(line):
            break
        region.append(line)
    return "\n".join(region)


def _mcp_servers_in(text):
    return [match.group(1) for match in _MCP_TOOL_RE.finditer(text)]


def _rel(path):
    return str(path.relative_to(REPO_ROOT))


def _host_skill(host: str, skill: str) -> Path:
    return REPO_ROOT / HOSTS[host]["skill_root"] / skill / "SKILL.md"


def _host_agent(host: str, worker: str) -> Path:
    return REPO_ROOT / HOSTS[host]["agent_pattern"].format(name=worker)


def _resolve_pointer(skill_file: Path, pointer: str) -> Path:
    raw = Path(pointer)
    if raw.is_absolute():
        return raw.resolve()
    return (skill_file.parent / raw).resolve()


def test_agent_directory_is_not_empty():
    assert _agent_files(), "no agent definitions found under .claude/agents/"


@pytest.mark.parametrize("path", _agent_files(), ids=_rel)
def test_agent_frontmatter_mcp_tools_name_a_known_server(path):
    if "tools:" not in "\n".join(_frontmatter(path)):
        pytest.skip(f"{_rel(path)} declares no tools: key")
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
def test_claude_browser_driving_agents_declare_browser_tools(path):
    servers = set(_mcp_servers_in(_tools_region(path)))
    assert "claude-in-chrome" in servers, (
        f"{_rel(path)} is Claude Code's capture-worker and must keep the "
        f"Claude-in-Chrome binding in its tools list"
    )


@pytest.mark.parametrize("path", _executed_files(), ids=_rel)
def test_executed_surfaces_reference_a_known_mcp_server(path):
    unknown = sorted({s for s in _mcp_servers_in(path.read_text(encoding="utf-8")) if s not in KNOWN_MCP_SERVERS})
    assert not unknown, (
        f"{_rel(path)} references MCP server id(s) {unknown}; agents read this file "
        f"as instructions, so a name that does not resolve becomes a runtime failure. "
        f"Known: {sorted(KNOWN_MCP_SERVERS)}."
    )


@pytest.mark.parametrize("host", sorted(HOSTS))
@pytest.mark.parametrize("skill", SKILLS)
def test_host_exposes_skill(host, skill):
    path = _host_skill(host, skill)
    assert path.is_file(), f"{host} is missing skill {_rel(path)}"
    text = path.read_text(encoding="utf-8")
    assert re.search(rf"^name:\s*{re.escape(skill)}\s*$", text, re.MULTILINE), (
        f"{_rel(path)} frontmatter name is not {skill}"
    )


@pytest.mark.parametrize("host", sorted(HOSTS))
@pytest.mark.parametrize("worker", WORKERS)
def test_host_exposes_worker(host, worker):
    path = _host_agent(host, worker)
    assert path.is_file(), f"{host} is missing worker {_rel(path)}"
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        assert re.search(rf'^name\s*=\s*"{re.escape(worker)}"', text, re.MULTILINE), (
            f"{_rel(path)} toml name is not {worker}"
        )
    else:
        assert re.search(rf"^name:\s*{re.escape(worker)}\s*$", text, re.MULTILINE), (
            f"{_rel(path)} frontmatter name is not {worker}"
        )


@pytest.mark.parametrize("host", sorted(HOSTS))
@pytest.mark.parametrize("skill", SKILLS)
def test_generated_skill_worker_pointers_resolve_inside_that_host(host, skill):
    skill_file = _host_skill(host, skill)
    text = skill_file.read_text(encoding="utf-8")
    extra = []
    harvest = skill_file.parent / "references" / "harvest.md"
    files = [skill_file]
    if harvest.is_file():
        files.append(harvest)
    pointers = []
    for src in files:
        for match in _WORKER_POINTER_RE.finditer(src.read_text(encoding="utf-8")):
            pointers.append((src, match.group(1)))
    assert pointers, f"{_rel(skill_file)} (and harvest.md) cite no worker contract path"
    host_roots = tuple((REPO_ROOT / root).resolve() for root in HOSTS[host]["roots"])
    for src, pointer in pointers:
        resolved = _resolve_pointer(src, pointer)
        assert resolved.is_file(), (
            f"{_rel(src)} points at `{pointer}` → {resolved} which does not exist"
        )
        if not any(_is_relative_to(resolved, root) for root in host_roots):
            extra.append(f"{_rel(src)} → {pointer} resolves outside {HOSTS[host]['roots']}")
    assert not extra, (
        f"{host}/{skill} worker-contract pointer(s) escape this host:\n" + "\n".join(extra)
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@pytest.mark.parametrize(
    "host",
    [name for name, spec in HOSTS.items() if not spec["claude_chrome_required"]],
)
def test_non_claude_capture_worker_does_not_require_claude_in_chrome(host):
    path = _host_agent(host, "capture-worker")
    if path.suffix == ".toml":
        tools_region = ""
    else:
        tools_region = _maybe_tools_region(path)
    servers = set(_mcp_servers_in(tools_region))
    assert "claude-in-chrome" not in servers, (
        f"{_rel(path)} is not Claude Code; capture-worker must not require "
        f"mcp__claude-in-chrome__* in its tools list"
    )


@pytest.mark.parametrize("host", sorted(HOSTS))
def test_capture_worker_body_is_host_portable(host):
    path = _host_agent(host, "capture-worker")
    text = path.read_text(encoding="utf-8")
    assert "QueryCapture" in text
    assert re.search(r"stop and report the prerequisite", text, re.IGNORECASE)
    assert re.search(r"API|headless", text, re.IGNORECASE)
    if not HOSTS[host]["claude_chrome_required"]:
        assert re.search(r"Other hosts", text), (
            f"{_rel(path)} must describe a non-Claude browser binding, not only Claude-in-Chrome"
        )


def test_grok_skill_does_not_point_at_codex_workers():
    skill = _host_skill("grok", "open-geo")
    text = skill.read_text(encoding="utf-8")
    harvest = skill.parent / "references" / "harvest.md"
    blob = text + harvest.read_text(encoding="utf-8")
    assert ".codex/agents" not in blob, (
        f"{_rel(skill)} still points at Codex workers; Grok must load `.grok/agents`"
    )


def test_emit_grok_adapters_rewrite_points_inside_grok():
    import importlib.util

    script = REPO_ROOT / "scripts" / "emit_grok_adapters.py"
    spec = importlib.util.spec_from_file_location("emit_grok_adapters", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    src = REPO_ROOT / ".grok" / "skills" / "open-geo" / "SKILL.md"
    rewritten = mod.rewrite_worker_pointers(
        "contract in `.agentsmesh/agents/capture-worker.md`", src
    )
    assert rewritten == "contract in `../../agents/capture-worker.md`"
    resolved = (src.parent / "../../agents/capture-worker.md").resolve()
    assert resolved == (REPO_ROOT / ".grok" / "agents" / "capture-worker.md").resolve()
    assert resolved.is_file()


def test_canonical_ask_and_spawn_are_not_claude_only():
    skill = (REPO_ROOT / ".agentsmesh" / "skills" / "open-geo" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Host primitives" in skill
    assert "AskUserQuestion" in skill
    assert "spawn_subagent" in skill
    capture = (REPO_ROOT / ".agentsmesh" / "agents" / "capture-worker.md").read_text(
        encoding="utf-8"
    )
    assert "Other hosts" in capture
    assert "mcp__claude-in-chrome" in capture
