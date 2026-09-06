# claude-tools

A growing collection of Claude Code plugins — skills, and eventually agents/commands/hooks — published as one marketplace repo.

## Install

```
/plugin marketplace add jonasfloden/claude-tools
/plugin install <plugin-name>@jonasfloden-claude-tools
```

Each plugin below is installed independently — installing this marketplace does not install every plugin in it.

## Plugins

### implement-ticket

Takes a ticket from its tracker to a draft pull request, using fresh-context subagent reviewers as the quality gate instead of stopping once you feel satisfied.

- pulls ticket/issue text and comments from GitHub (other trackers via whatever skill/MCP server you have installed for them), and detects prior or parallel work on the same ticket before scoping anything
- an escalation gate that only spins up a spec-then-plan stage for multi-deliverable or ambiguous work, and implements directly otherwise
- a capped, axis-based review loop (security, correctness, conformance, simplification, "use the output") run by fresh dispatched reviewers, narrowing each round instead of re-running everything
- landing: rebase, re-verify, shape the commit history, and take the PR out of draft only once every exit condition is actually met

**Requires** sub-skills from **[superpowers](https://github.com/obra/superpowers)** (or any plugin providing skills of the same name): `superpowers:requesting-code-review`, `superpowers:receiving-code-review`, `superpowers:test-driven-development`, `superpowers:verification-before-completion`. Install that plugin first — `implement-ticket` invokes them by name and will not resolve without them.

Usage:

> Implement issue #142 and take it to a PR.

Flags: `--spec` / `--no-spec` force the size gate either way. `--max-rounds N` raises the review cap from 3 (default) to up to 5.

See [`plugins/implement-ticket/skills/implement-ticket/SKILL.md`](plugins/implement-ticket/skills/implement-ticket/SKILL.md) for the full process.

## Adding a new plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json` (only `name` is required; `description`/`version`/`author` recommended).
2. Add its content under `plugins/<name>/skills/`, `plugins/<name>/agents/`, `plugins/<name>/commands/`, and/or `plugins/<name>/hooks/` as needed.
3. Add an entry to `.claude-plugin/marketplace.json` with `"source": "./plugins/<name>"`.
4. Document it in this README.
