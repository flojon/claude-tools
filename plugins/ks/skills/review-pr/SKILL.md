---
name: review-pr
description: Use when asked to review a pull request, give a second opinion on someone else's PR before approving it, check whether a PR is ready to merge, review several PRs that ship one change, or keep re-reviewing a PR automatically until it looks good. Triggers on a request naming one or more PR numbers or URLs, or "review this PR" / "review my PR" / "is this PR ready".
---

# Review PR

Take an existing pull request through the same fresh-context review loop implement-ticket runs mid-build, then hand the human a decision: post it, approve it, request changes, or — on their own PR — fix it first.

**Core principle:** same as pr-review-loop's — you do not stop because you are satisfied, you stop when a round earns nothing. But this skill never edits someone else's branch on its own initiative, and it never submits a review without being told to: fixing and posting are always offered, never assumed.

**Flags:** `--rounds N` (default 1; raise it to keep looping even without an intervening fix — useful when the PR keeps getting pushed to while you watch it). It is meant to be paired with something re-invoking this skill on an interval, such as the `loop` skill, rather than run alone: Phase 2's own change-detection already skips a round when nothing has moved since the last one, so `--rounds N` by itself just burns the cap sitting idle in one dispatch. `--no-fix` skips the fix offer even on the human's own PR.

**REQUIRED SUB-SKILLS:** pr-review-loop (running the review), superpowers:requesting-code-review, superpowers:receiving-code-review, superpowers:test-driven-development (only if the fix offer is accepted), superpowers:verification-before-completion (before any green claim).

## Orchestration model

You are the **orchestrator**: dispatch one fresh subagent per phase (Agent tool, `subagent_type: "general-purpose"`, never a fork — these subagents must not inherit your context) and act only on what it reports back. Nothing in Phase 3's posting or fixing action happens until a human has chosen it — that is the one part of this skill that runs in your own context on purpose, because it is the part that has to ask.

## Several PRs that ship one change

This applies when the request names two or more PRs and the human says they ship together, or the linked ticket or the descriptions match; if it's unclear, ask. Run Phase 1 for each PR — sequentially for PRs in the same repo, since they share the recon cache — and Phase 2 for each, each in its own repo, worktree and notes file, with every PR's commands run in its own repo. If any PR's Phase 1 returns `blocked`, stop and tell the human rather than checking an incomplete set.

Then, before Phase 3, dispatch one more fresh subagent. It gets each PR's `worktree_path`, `notes_path` and `round_summary`, each PR body, and the shared ticket text — or, with no ticket, each PR's description. For each concept the PRs share, it checks:

- **Names** match: DTO fields, routes, queue and topic names, environment variables, feature-flag keys.
- **Contracts** agree: what the producer sends, the consumer reads; what the deployment provides, the app reads.
- **Order:** does one have to be deployed before the other, what breaks if it isn't, and does a PR description say so?
- **Flags and config:** a secret, flag or default that one PR needs is provisioned by some PR in the set.
- **Scope:** together, do the PRs cover what the ticket asks — or does each assume another PR handles a part nobody does?

It returns each finding as `{finding, target PR, severity}`, plus a list of checked-and-matching items marked ✓ so the human sees they were checked rather than skipped, and appends to each affected PR's notes file.

A mismatch targets the PR that has to change, or both when either could. Cross-PR findings are verified and triaged like round findings (must-fix, worth-fixing, noise) and merged into the target PR's `must_fix` or worth-fixing, so they gate approve, request-changes and the fix offer. A gap no PR owns is reported at set level, and attached to a PR the human picks.

## Phase 1 — Identify the PR and whether it's yours

**Dispatched as:** one subagent per PR, given whatever identifies the PR (number, URL, or "the PR on the current branch") and the repo.

1. **Resolve the PR:**

   ```bash
   gh pr view <n|url> --json number,url,title,body,author,baseRefName,headRefName,isDraft,files,additions,deletions,reviews,comments,mergeable,mergeStateStatus
   ```

   With nothing to identify it, resolve from the current branch (`gh pr view` with no argument). If neither works, return `blocked` — there is nothing to review.

   **A draft PR may be a draft on purpose.** Note `isDraft` and say so in the report; don't assume the author wants a review yet just because a request named the PR.

2. **Determine ownership** — this decides, at the end, whether fixing is even on the table:

   ```bash
   gh api user --jq .login
   ```

   `is_own_pr` = the PR's author login equals this. Reviewing someone else's PR never edits their branch on its own initiative, `--no-fix` or not.

3. **Pull context.** If the PR body references a ticket or issue, fetch its text too — the same acceptance-criteria reading implement-ticket's Phase 1 does, but **read-only**: this skill never claims a ticket or moves its status. Without a linked ticket, the PR title and body are the only statement of what "right" looks like, and that is what reviewers get as `context`.

4. **Get a checkout to build from.** Reuse a local worktree if one already exists for this branch (`git worktree list`); otherwise create one the same collision-proof way implement-ticket's Phase 2 does — a random suffix, not a bare slug, so concurrent runs never collide — built from the PR's actual head, never a stale local copy:

   ```bash
   SLUG=pr<n>-$(od -An -N2 -tx1 /dev/urandom | tr -d ' ')
   git fetch origin "pull/<n>/head:$SLUG"
   git worktree add ".claude/worktrees/$SLUG" "$SLUG"
   ```

5. **Reuse the repo-level verify-leg cache**, keyed exactly as implement-ticket's Phase 2 keys it, so a review benefits from a discovery an implement-ticket run already made on this repo, and vice versa:

   ```bash
   CACHE="$(git rev-parse --path-format=absolute --git-common-dir)/repo-recon-cache.md"
   ```

   Valid under the same rule as implement-ticket's Phase 2 — all of: it exists; every source file it names still exists and hashes the same as recorded; nothing that outranks those sources in the discovery order below exists now but didn't at cache time. Invalid or absent, rediscover — CI config first, then CLAUDE.md/AGENTS.md/CONTRIBUTING, then README, then project files — and write it back.

6. **Write a notes file for this review**, same shape and purpose as implement-ticket's: reviewers and rounds read it, never your context.

   ```bash
   NOTES="$(git rev-parse --absolute-git-dir)/pr-review-notes-<n>.md"
   ```

**Returns to the orchestrator:**

- `pr_number`, `pr_url`, `pr_title`, `is_draft`
- `is_own_pr`: true | false
- `worktree_path`, `notes_path`
- `verify_legs`
- `context`: the ticket text if one is linked, else the PR description
- `blocked`: `null` | `{reason}` — non-null means stop and tell the human rather than dispatching Phase 2

## Phase 2 — Review loop

**Runs as:** you drive it, per **REQUIRED SUB-SKILL pr-review-loop**; each round is its own fresh subagent dispatch, with:

- `fix_mode: report-only` — a round subagent never edits the branch; findings come back untouched, for the human to act on in Phase 3
- `verify_legs` — pass through Phase 1's value; there is no implement-ticket-style size gate here, so `seed_axes` is left unset and pr-review-loop computes round 1 fresh from its own axis table (including its default type-design predicate) against the whole diff
- `cap`: **1 round** by default; `--rounds N` raises it

pr-review-loop never posts anywhere on its own — it hands back each round's `round_summary` and writes it to `notes_path`. That is exactly what this skill needs: nothing touches the PR until Phase 3 asks the human.

A round beyond the first only earns its cost once the diff has actually changed — a new push, or a fix accepted in Phase 3. **If nothing has changed since the last round and the human asks for another anyway, say so and skip the dispatch** rather than re-running an identical review at the same cost for the same answer.

Follow pr-review-loop's "caller's control loop" section as written; when it exits (`decision: stop` or the cap hit), move to Phase 3. With several PRs that ship together, run the cross-PR check first (see "Several PRs that ship one change").

## Phase 3 — Offer next actions

**Runs in your own context** — nothing here is a remote write until the human says so.

Once the loop exits, you hold the final round's `must_fix`, `rejected`, `round_summary`, and the cumulative round history pr-review-loop wrote to `notes_path`.

1. **Summarize for the human:** what ran (axes, rounds), what's still outstanding (`must_fix` unresolved), what was rejected and why. With several PRs, ownership, `must_fix`, the post offer and the fix offer are per PR: each PR's `$SUMMARY` carries the cross-PR findings naming it plus the ✓ list. Write this summary to `SUMMARY="$(git rev-parse --absolute-git-dir)/pr-review-summary-<n>.md"` — the `$SUMMARY` the posting commands below read from.
2. **Offer to post it**, asking which of:
   - **comment only** — `gh pr review <n> --comment --body-file "$SUMMARY"`
   - **approve** — offer this only when `must_fix` is empty; `gh pr review <n> --approve --body-file "$SUMMARY"`
   - **request changes** — the natural default when `must_fix` is non-empty; `gh pr review <n> --request-changes --body-file "$SUMMARY"`
   - **nothing** — some reviews are just for the human's own eyes

   Never default to posting without being told. Submitting a review on a pull request is visible to everyone on it, and is exactly the kind of action this skill waits on rather than assumes.
3. **If `is_own_pr` and `must_fix` is non-empty and `--no-fix` was not passed, offer to fix it too — but only offer.** If the human accepts:
   1. dispatch one subagent, per superpowers:test-driven-development, to fix the outstanding `must_fix` (and any accepted `worth-fixing`) on the PR's actual branch, and push it
   2. per superpowers:verification-before-completion, re-run the verify legs and paste the real output into `notes_path` — no green claim without it
   3. dispatch another pr-review-loop round, still `fix_mode: report-only`, scoped to the delta, so the fix gets checked rather than trusted; with several PRs, re-run the cross-PR check against the delta too, and skip it when no PR in the set changed since last time
   4. return to step 2's posting offer with the updated result
4. **Clean up every worktree you created**, if any, once the human's chosen action is taken — same as implement-ticket's Phase 6 — and name anything deliberately left behind.

This phase ends the run once an action is taken or the human declines all of them; there is nothing further to return.

## Common mistakes

| Mistake | Why it bites |
|---|---|
| Posting a review or fixing code without the human choosing to | Visible, hard-to-reverse actions on a pull request. This skill only offers; the human decides. |
| Offering to fix a PR that isn't the human's own | Editing someone else's branch on your own initiative isn't a review, it's an unrequested contribution. |
| Approving with an open `must_fix` | The entire point of request-changes is that it's still there. |
| Re-running a round against a diff nothing has touched since the last one | It will just restate the same findings at the same cost. |
| Rediscovering verify legs from scratch | implement-ticket's Recon cache already has them for this repo — read it, don't redo it. |
| Treating a draft PR as ready for review | The author may have left it a draft specifically because it isn't ready — ask before assuming otherwise. |
| Reviewing PRs that ship together one at a time and stopping there | Each can be correct alone while the pair is broken: a renamed field on one side only, a frontend that ships before the backend it needs. |
| Cross-PR findings left out of a PR's `must_fix` | The PR's own review is clean, so it gets approved while the pair is still broken. |
| Reading pr-review-loop's `report-only` findings as already fixed | Nothing was edited. `fixed` is `false` on every one of them until Phase 3 says otherwise. |

## Red flags

- About to call `gh pr review --approve` or `--request-changes` without having asked which action the human wants
- About to fix a finding on a PR that belongs to someone else
- About to offer to fix without first checking `is_own_pr`
- About to dispatch another round against a diff nothing has touched since the last one
- About to treat a `report-only` round's findings as fixed
- About to approve one PR of a set without its cross-PR findings
