# claude-tools

A growing collection of Claude Code plugins — skills, and eventually agents/commands/hooks — published as one marketplace repo.

## Install

```
/plugin marketplace add flojon/claude-tools
/plugin install <plugin-name>@flojon-claude-tools
```

Each plugin below is installed independently — installing this marketplace does not install every plugin in it.

## Plugins

| Plugin | Description |
|---|---|
| [`implement-ticket`](plugins/implement-ticket/README.md) | Takes a ticket from its tracker to a draft PR, using fresh-context reviewers as the quality gate. Requires [superpowers](https://github.com/obra/superpowers). |

## Adding a new plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` (only `name` is required; `description`/`version`/`author` recommended).
2. Add its content under `plugins/<name>/skills/`, `plugins/<name>/agents/`, `plugins/<name>/commands/`, and/or `plugins/<name>/hooks/` as needed.
3. Add an entry to `.claude-plugin/marketplace.json` with `"source": "./plugins/<name>"`.
4. Document it in this README.
