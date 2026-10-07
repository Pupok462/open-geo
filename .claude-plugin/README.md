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

> **Release ritual — bump `version` in `plugin.json` for every release.** It is the
> single source of the plugin version; omit `version` from the marketplace entry.
> Hosted marketplace installs receive a new copy only when the computed version changes,
> so commits pushed without a bump leave users on their cached copy. After the release
> reaches the marketplace, users can run `claude plugin update open-geo@open-geo-marketplace`.
> Plugins loaded in place from a local-path marketplace use the current files at session start.
>
> **Namespacing.** Plugin skills are namespaced: the plugin-installed command is
> `/open-geo:open-geo`. The plain `/open-geo` form exists when working from a repo
> clone (project-level `.claude/skills/`, and the same skills under `.grok/`,
> `.cursor/`, `.gemini/`, `.agents/` for Grok / Cursor / Gemini CLI / Codex).

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
- Versioning and updates: https://code.claude.com/docs/en/plugins/host-marketplace#release-a-new-version
