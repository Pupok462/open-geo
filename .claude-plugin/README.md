# open-geo — Claude Code plugin manifests

This directory holds the one-command-install path for open-geo as a Claude Code plugin.
The installed skill performs the full run and always returns a portable JSON artifact;
PDF and dashboard outputs are optional.

- `plugin.json` — the plugin manifest (skill at `.claude/skills/open-geo/`, worker
  agents at `.claude/agents/` — both declared via custom paths, since this repo keeps
  them under `.claude/` instead of the default plugin-root `skills/` + `agents/`;
  note the schema wants `skills` as a directory string but `agents` as an array of
  explicit `.md` file paths — a new agent must be appended to that array).
- `marketplace.json` — a single-plugin marketplace listing this repo (`source: "./"`).

Install (from a Claude Code session):

```
/plugin marketplace add <this-repo-url-or-local-path>
/plugin install open-geo@open-geo-marketplace
```

> **Release ritual — bump `version` on every plugin-visible change.** Installed plugins
> only receive updates when `version` changes in BOTH `plugin.json` and the `plugins[0]`
> entry of `marketplace.json`; pushing commits without a bump leaves every installed copy
> stale. Any edit to `SKILL.md`, the agents, or these manifests ⇒ bump both, then users
> pick it up via `/plugin update open-geo`.
>
> **Namespacing.** Plugin skills are namespaced: the plugin-installed command is
> `/open-geo:open-geo`. The plain `/open-geo` form exists only when working from a repo
> clone (project-level `.claude/skills/`).

> **No manual runtime launch.** On first invocation, the skill resolves the plugin/repository
> runtime and runs `scripts/setup.sh --minimal` itself when Python dependencies are missing.
> It installs dashboard dependencies only when the caller explicitly requests `dashboard` or
> `both`. The remaining prerequisite is a **connected visible-browser capability** plus a
> **logged-in browser session** for the target engine; the skill never substitutes API/headless
> data for that rendered surface.

The default `--output data` starts no servers. Every completed run exports
`open-geo.run-artifact.v1`, which lets another agent workflow consume the measurement without
scraping the chat response or reading SQLite directly.

Schema reference (verified against the official Claude Code docs):
- Plugin manifest: https://code.claude.com/docs/en/plugins-reference#plugin-manifest-schema
- Marketplace: https://code.claude.com/docs/en/plugin-marketplaces
