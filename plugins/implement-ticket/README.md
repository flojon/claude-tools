# implement-ticket

A Claude Code skill that takes a ticket from its tracker to a draft pull request, using fresh-context subagent reviewers as the quality gate instead of stopping once you feel satisfied.

- pulls ticket/issue text and comments from GitHub (other trackers via whatever skill/MCP server you have installed for them), and detects prior or parallel work on the same ticket before scoping anything
- an escalation gate that only spins up a spec-then-plan stage for multi-deliverable or ambiguous work, and implements directly otherwise
- a capped, axis-based review loop (security, correctness, conformance, simplification, "use the output") run by fresh dispatched reviewers, narrowing each round instead of re-running everything
- landing: rebase, re-verify, shape the commit history, and take the PR out of draft only once every exit condition is actually met

## Requirements

This plugin depends on sub-skills from **[superpowers](https://github.com/obra/superpowers)** (or any plugin providing skills of the same name):

- `superpowers:requesting-code-review`
- `superpowers:receiving-code-review`
- `superpowers:test-driven-development`
- `superpowers:verification-before-completion`

Install that plugin first, or provide equivalent skills under those names — `implement-ticket` invokes them by name and will not resolve without them.

## Install

```
/plugin marketplace add jonasfloden/claude-tools
/plugin install implement-ticket@jonasfloden-claude-tools
```

Or copy `skills/implement-ticket/` directly into your `~/.claude/skills/` directory.

## Usage

Ask Claude to implement a ticket by number or URL, e.g.:

> Implement issue #142 and take it to a PR.

Flags: `--spec` / `--no-spec` force the size gate either way. `--max-rounds N` raises the review cap from 3 (default) to up to 5.

See [`skills/implement-ticket/SKILL.md`](skills/implement-ticket/SKILL.md) for the full process.
