---
name: review-pr
description: Use when asked to review a pull request, give a second opinion on someone else's PR before approving it, check whether a PR is ready to merge, or keep re-reviewing a PR automatically until it looks good. Triggers on a request naming a PR number or URL, or "review this PR" / "review my PR" / "is this PR ready".
---

# Review PR

Take an existing pull request through the same fresh-context review loop implement-ticket runs mid-build, then hand the human a decision: post it, approve it, request changes, or — on their own PR — fix it first.

**Core principle:** same as pr-review-loop's — you do not stop because you are satisfied, you stop when a round earns nothing. But this skill never edits someone else's branch on its own initiative, and it never submits a review without being told to: fixing and posting are always offered, never assumed.

**Flags:** `--rounds N` (default 1; raise it to keep looping even without an intervening fix — useful when the PR keeps getting pushed to while you watch it). It is meant to be paired with something re-invoking this skill on an interval, such as the `loop` skill, rather than run alone: Phase 2's own change-detection already skips a round when nothing has moved since the last one, so `--rounds N` by itself just burns the cap sitting idle in one dispatch. `--no-fix` skips the fix offer even on the human's own PR.

**REQUIRED SUB-SKILLS:** pr-review-loop (running the review), superpowers:requesting-code-review, superpowers:receiving-code-review, superpowers:test-driven-development (only if the fix offer is accepted), superpowers:verification-before-completion (before any green claim).

## Orchestration model

You are the **orchestrator**: dispatch one fresh subagent per phase (Agent tool, `subagent_type: "general-purpose"`, never a fork — these subagents must not inherit your context) and act only on what it reports back. Nothing in Phase 3's posting or fixing action happens until a human has chosen it — that is the one part of this skill that runs in your own context on purpose, because it is the part that has to ask.

## Phase 1 — Identify the PR and whether it's yours

**Dispatched as:** one subagent, given whatever identifies the PR (number, URL, or "the PR on the current branch") and the repo.

1. **Resolve the PR:**

   ```bash
   gh pr view <n|url> --json number,url,title,body,author,baseRefName,headRefName,isDraft,files,additions,deletions,reviews,comments,mergeable,mergeStateStatus
   ```

   With nothing to identify it, resolve from the current branch (`gh pr view` with no argument). If neither works, return `blocked` — there is nothing to review.

   **A draft PR may be a draft on purpose.** Note `isDraft` and say so in the report; don't assume the author wants a review yet just because a request named the PR.

   **A stacked PR is reviewed against the parent PR's head, not `baseRefName`.** The body or branch name may say the PR builds on another one (`gh pr view <m> --json headRefOid,state,commits` for the parent `<m>`), or `git log origin/<baseRefName>..HEAD` may list commits that are also in the parent's `commits` — that is how you tell `files` includes an earlier PR's changes, including after GitHub retargets the PR to the default branch once its base merges. Use the parent's `headRefOid` rather than its branch name, which is usually deleted after a merge: `git fetch origin pull/<m>/head` if the SHA is not local, and diff from it when it is an ancestor of the head (`git merge-base --is-ancestor`), else from `git merge-base <headRefOid> HEAD` after a rebase. Say which base you used.

   **Size it.** Over about 50 files or 3000 added lines, return `size_warning`, so the human chooses between a full review and a narrowed one before Phase 2 starts — a silent narrowing of a large PR drops exactly what colleague reviews find most: test value, naming, consistency, reuse. Count from the PR JSON's `additions`/`deletions`, not the `files` list (`gh` truncates it near 100 entries), and discount lockfiles and generated files.

2. **Determine ownership** — this decides, at the end, whether fixing is even on the table:

   ```bash
   gh api user --jq .login
   ```

   `is_own_pr` = the PR's author login equals this. Reviewing someone else's PR never edits their branch on its own initiative, `--no-fix` or not.

3. **Pull context.** If the PR body references a ticket or issue, fetch its text too — the same acceptance-criteria reading implement-ticket's Phase 1 does, but **read-only**: this skill never claims a ticket or moves its status. Without a linked ticket, the PR title and body are the only statement of what "right" looks like, and that is what reviewers get as `context`.

4. **Get a checkout to build from.** Reuse a local worktree if one already exists for this branch (`git worktree list`); otherwise create one the same collision-proof way implement-ticket's Phase 2 does — a random suffix, not a bare slug, so concurrent runs never collide — built from the PR's actual head, never a stale local copy:

   ```bash
   SLUG=pr<n>-$(od -An -N2 -tx1 /dev/urandom | tr -d ' ')
   git fetch origin "pull/<n>/head"
   git worktree add --detach ".claude/worktrees/$SLUG" FETCH_HEAD
   ```

   A reused worktree is refreshed the same way, inside it, with no named branch to collide with a force-push: `git -C <worktree_path> fetch origin "pull/<n>/head"` then `git -C <worktree_path> checkout --detach FETCH_HEAD`.

   Then check it still merges into `baseRefName` — the branch GitHub will merge into, not a stack base. `mergeStateStatus` alone can lag a base that moved minutes ago, so fetch it first (`--write-tree` needs git 2.38+):

   ```bash
   git fetch origin <baseRefName>
   OUT=$(git -C <worktree_path> merge-tree --write-tree origin/<baseRefName> HEAD 2>&1); RC=$?
   ```

   `merge_conflict` is `true` only for `RC=1` with `CONFLICT` in `$OUT`, `false` for `RC=0`, and `unknown` for anything else — an old git, a missing ref (also exit 1, without `CONFLICT`), unrelated histories (128). A conflict is a finding for the author whatever the rounds say; it warns rather than blocks, so Phase 2 still runs.

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
- `diff_range`: `<base>...<head>`, with the stack base when the PR is stacked
- `merge_conflict`: true | false | unknown
- `size_warning`: `null` | `{files, added_lines}` — non-null means ask the human for a full review or a narrowed one before dispatching Phase 2
- `blocked`: `null` | `{reason}` — non-null means stop and tell the human rather than dispatching Phase 2

## Phase 2 — Review loop

**Runs as:** you drive it, per **REQUIRED SUB-SKILL pr-review-loop**; each round is its own fresh subagent dispatch, with:

- `fix_mode: report-only` — a round subagent never edits the branch; findings come back untouched, for the human to act on in Phase 3
- `diff_range` — Phase 1's value for round 1; later rounds, see below
- `verify_legs` — pass through Phase 1's value
- `seed_axes` — unset by default, so pr-review-loop computes round 1 fresh from its own axis table (including its default type-design predicate) against the whole diff. When Phase 1 returned `size_warning`, ask the human which they want: **full** leaves it unset; **narrowed** sets `seed_axes` to correctness and security and, if they name the files or directories that matter most, limits `diff_range` to those paths (`-- <paths>`). Say in the report which paths and axes were not reviewed
- `cap`: **1 round** by default; `--rounds N` raises it

pr-review-loop never posts anywhere on its own — it hands back each round's `round_summary` and writes it to `notes_path`. That is exactly what this skill needs: nothing touches the PR until Phase 3 asks the human.

A round beyond the first only earns its cost once the diff has actually changed — a new push, or a fix accepted in Phase 3. **If nothing has changed since the last round and the human asks for another anyway, say so and skip the dispatch** rather than re-running an identical review at the same cost for the same answer.

**Scope a later round to what the author changed, not to what the base brought in.** Record the head each round reviewed in `notes_path`. Once the branch has merged its base or been rebased, a plain diff from that SHA carries everyone else's commits too:

- While the last reviewed SHA is still an ancestor of the head (`git merge-base --is-ancestor <last> <head>`; `--remerge-diff` needs git 2.36+): `git log -p --first-parent --remerge-diff <last>..<head>` — each new commit, and of a merge commit only what its author changed beyond the automatic merge. A merge of `origin/<base>` then shows nothing, as it should; a merge of any other branch also shows only its conflict resolution, so review that branch's own commits too: `git log -p --no-merges <merge>^1..<merge>^2 --not origin/<base>`.
- After a rebase or force-push: `git range-diff origin/<base>..<last> origin/<base>..<head>`, then `git show` each commit it marks new or changed.

That output is patch text, not a range: write it to a file beside `notes_path` (`pr-review-delta-<n>-r<round>.patch`) and pass the reviewers a `diff_range` that names the file, the SHAs it covers and the command that produced it, so they can regenerate it. What the new base brought in is reviewed only where it meets the branch's own changes — a renamed API the branch calls, a test the branch's code now breaks.

Follow pr-review-loop's "caller's control loop" section as written; when it exits (`decision: stop` or the cap hit), move to Phase 3.

## Phase 3 — Offer next actions

**Runs in your own context** — nothing here is a remote write until the human says so.

Once the loop exits, you hold the final round's `must_fix`, `rejected`, `round_summary`, and the cumulative round history pr-review-loop wrote to `notes_path`.

1. **Summarize for the human:** what ran (axes, rounds, and anything a `size_warning` narrowed out), what's still outstanding (`must_fix` unresolved), what was rejected and why, and the `merge_conflict` result — `true` means the PR cannot merge as it stands; `unknown` says the check could not run. Write this summary to `SUMMARY="$(git rev-parse --absolute-git-dir)/pr-review-summary-<n>.md"` — the `$SUMMARY` the posting commands below read from.
2. **Offer to post it**, asking which of:
   - **comment only** — `gh pr review <n> --comment --body-file "$SUMMARY"`
   - **approve** — offer this only when `must_fix` is empty and `merge_conflict` is `false`; `gh pr review <n> --approve --body-file "$SUMMARY"`
   - **request changes** — the natural default when `must_fix` is non-empty or `merge_conflict` is `true`; `gh pr review <n> --request-changes --body-file "$SUMMARY"`
   - **nothing** — some reviews are just for the human's own eyes

   Never default to posting without being told. Submitting a review on a pull request is visible to everyone on it, and is exactly the kind of action this skill waits on rather than assumes.
3. **If `is_own_pr` and `must_fix` is non-empty or `merge_conflict` is `true`, and `--no-fix` was not passed, offer to fix it too — but only offer.** If the human accepts:
   1. dispatch one subagent, per superpowers:test-driven-development, to fix the outstanding `must_fix` (and any accepted `worth-fixing`, and the merge conflict if there is one) on the PR's actual branch, and push it
   2. per superpowers:verification-before-completion, re-run the verify legs and paste the real output into `notes_path` — no green claim without it
   3. dispatch another pr-review-loop round, still `fix_mode: report-only`, scoped to the delta per Phase 2's delta rule, so the fix gets checked rather than trusted
   4. return to step 2's posting offer with the updated result
4. **Clean up the worktree you created**, if any, once the human's chosen action is taken — same as implement-ticket's Phase 6 — and name anything deliberately left behind.

This phase ends the run once an action is taken or the human declines all of them; there is nothing further to return.

## Common mistakes

| Mistake | Why it bites |
|---|---|
| Posting a review or fixing code without the human choosing to | Visible, hard-to-reverse actions on a pull request. This skill only offers; the human decides. |
| Offering to fix a PR that isn't the human's own | Editing someone else's branch on your own initiative isn't a review, it's an unrequested contribution. |
| Approving with an open `must_fix` | The entire point of request-changes is that it's still there. |
| Approving with `merge_conflict` true or unknown | The PR cannot merge as it stands, or nobody checked. |
| Diffing a stacked PR against `baseRefName` | The parent's commits flood the review; use the parent's `headRefOid`. |
| Dispatching a large PR with `size_warning` set without asking | The human picks full or narrowed; a silent narrowing drops what colleague reviews find. |
| Re-diffing from the last reviewed SHA after a rebase or base merge | It carries everyone else's commits; use the delta rule in Phase 2. |
| Fetching a PR into a named local branch | A force-push is rejected, or git refuses to touch a branch checked out in a worktree; fetch to `FETCH_HEAD` and detach. |
| Setting `merge_conflict` from any non-zero `merge-tree` exit | A missing ref also exits 1; only `CONFLICT` output means conflict. |
| Re-running a round against a diff nothing has touched since the last one | It will just restate the same findings at the same cost. |
| Rediscovering verify legs from scratch | implement-ticket's Recon cache already has them for this repo — read it, don't redo it. |
| Treating a draft PR as ready for review | The author may have left it a draft specifically because it isn't ready — ask before assuming otherwise. |
| Reading pr-review-loop's `report-only` findings as already fixed | Nothing was edited. `fixed` is `false` on every one of them until Phase 3 says otherwise. |

## Red flags

- About to offer approve while `merge_conflict` is not `false`
- About to dispatch Phase 2 with `size_warning` set before the human chose full or narrowed
- About to diff a stacked PR against `baseRefName`, or a later round from the last SHA after a rebase
- About to call `gh pr review --approve` or `--request-changes` without having asked which action the human wants
- About to fix a finding on a PR that belongs to someone else
- About to offer to fix without first checking `is_own_pr`
- About to dispatch another round against a diff nothing has touched since the last one
- About to treat a `report-only` round's findings as fixed
