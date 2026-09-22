# Resuming a partly-implemented ticket

Read this when Phase 1 finds any prior attempt — a merged stage, an open PR, or an abandoned branch.

## Find every attempt, in both directions

A title search is not enough. Work that rewrote this ticket's surface may carry no reference to it in its title.

```bash
gh pr list --search 'in:title <n>' --state all      # only finds a repo that titles PRs "(#n)"
gh issue view <n> --json comments                    # stage comments usually name their PR
gh api repos/<owner>/<repo>/issues/<n>/timeline \
  --jq '.[] | select(.event=="cross-referenced") | .source.issue.number'
```

Then follow the arrows **outward**: enumerate the issues earlier stages *filed*. Those are pointed at by the PRs and stage comments, not by the ticket, so nothing in the ticket leads you to them.

**Rejected follow-ups matter as much as shipped ones.** An issue closed as *not planned* is a decision that something should not be built. Rebuilding it wastes exactly as much work as rebuilding a shipped stage.

## Compute the delta from two sources, not one

- **Diffs establish what exists.** Grep the tree. Do not trust a description of what shipped.
- **Prose establishes what the criteria now are.** Departures, falsified acceptance criteria, splits, obligations one stage owes another, and syntax that changed under everyone's feet live in issue comments, PR bodies and design revision notes — nowhere else.

Neither alone is sufficient, and a delta built from diffs only will be confidently wrong about scope.

**Comments supersede the body *and each other*.** The last word on a point wins, not merely the newest comment on the ticket. A comment reporting a departure may itself be corrected by the next one.

**If the stage comments are missing**, reconstruct the delta from diffs and say so in the report — it is materially less reliable, and the human should know which kind of delta they are being handed.

## Which branch — stage boundary wins over branch identity

| Prior state | What to do |
|---|---|
| An open PR for **this** stage (unfinished work) | Continue on its branch and push there. |
| An open PR for the **previous** stage (finished) | **Stack**: branch from that PR's head, open your PR with `--base <that branch>`, and retarget to the default branch when it merges. |
| A **merged** stage | New branch from the fresh default branch. |
| An unpushed or abandoned branch | Adopt it if it rebases cleanly and its tests pass; otherwise restart, and say why. |

Stacking is the correct move when your stage depends on code that has not reached the default branch yet. Pushing into the prior stage's PR instead blows the stage boundary and reopens review rounds that were already settled on a green, mergeable PR.

## Should the open work be finished or merged first?

Before stacking, evaluate the prior PR. Stacking on work that is itself unfinished means building on a base that will change underneath you, and each change costs a rebase and possibly a re-review.

```bash
gh pr view <prior> --json isDraft,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup,comments,reviews
gh pr checks <prior>
```

Decide on `mergeStateStatus`, which is the field that actually says why a PR cannot merge. Green checks alone are not the signal — a PR can have every check passing and still be blocked on a required approval.

| `mergeStateStatus` | Means | Outcome |
|---|---|---|
| `UNSTABLE` | Checks failing | **Finish it first.** Same ticket, and a stage built on a broken stage inherits the breakage. |
| `DIRTY` | Conflicts with the base | **Finish it first** — merge the default branch in and resolve, if it is your work. If it is someone else's, say so and stack. |
| `BEHIND` | Base moved, update required | **Finish it first** — cheap, and it unblocks the merge. |
| `BLOCKED` | Branch protection unsatisfied — usually a required review nobody has submitted | **Stack.** An approval is a human decision, and waiting for one is unbounded. Say what is blocking it. |
| `CLEAN` | Nothing outstanding but the merge itself | **Recommend merging it first**, prominently. Merging is the human's call — never merge, and never make approval a precondition for continuing. |

Read `reviewDecision` alongside it: empty means nobody has reviewed yet, `CHANGES_REQUESTED` means the prior stage has unanswered feedback and belongs in the *finish it first* row whatever its merge state says.

In the check rollup, an **empty or null conclusion is not a success** — it is a check still running, skipped, or neutral. Do not read it as green.

**Never block on the recommendation.** If the human is not there to merge, stack and say you did. Stacking is recoverable — the PR retargets when the base lands — whereas an idle run is just lost time.

## Announce a stacked PR

When you stack, say so explicitly and unmissably, in the run's report *and* in the PR body. A stacked PR that looks like an ordinary one gets reviewed against the wrong base and merged in the wrong order.

State: what it is stacked on and why, that its diff will only read correctly against that base, that it retargets to the default branch when the base merges, and — where it applied — that you recommended merging the base first.

```
Stacked PR: this branches from <base-branch> (PR #<n>), not from <default>.
Reason: <the stage-N code it depends on has not reached the default branch>.
Retarget to <default> once #<n> merges. Review it against <base-branch>.
Recommendation: <#n is green and settled — merging it first would remove this stack.>
```


## Rebasing

- **Never rebase or force-push a branch that is under review.** It detaches review threads from the lines they were written against. Merge the default branch in instead.
- **Your own stacked branch is different.** While it is unreviewed, rebase it freely as the base moves — and it will move if the prior stage gains another review round.

## The diff range for round 1

Base the range on **the prior stage's branch head**, not the merge base with the default branch:

```bash
git diff origin/<prior-stage-branch>..HEAD
```

When the prior stage is merged the two coincide. When it is open they diverge by its entire history, and using the default-branch range silently hands reviewers every finding earlier rounds already settled.

The conformance axis is the exception: it judges the ticket's whole remaining criteria, including any acceptance criterion a prior stage left unadjudicated.

## Before deciding the prior work is finished

An open PR being quiet does not mean it is done. Check how many review rounds it ran, whether CI is green, and whether an automated reviewer is still pending or needs a manual trigger.

## Report, do not rewrite

- **Split-out issues** get reported with their **state and milestone**. A split that carries no milestone while the parent does is real scope that fell off the schedule, and only the human can put it back.
- **A ticket body that is now wrong** — stale syntax, superseded config shapes, a falsified acceptance criterion — gets a correction proposed as a comment. Do not edit someone else's issue body.
