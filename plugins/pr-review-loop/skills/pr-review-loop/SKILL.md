---
name: pr-review-loop
description: Use when a skill needs to run a capped, multi-round, fresh-context review against a diff or pull request and must decide which axes it earns, whether another round is worth dispatching, and when a guard like thrash, whack-a-mole, or diverging fires. A required sub-skill for implement-ticket and review-pr; not invoked directly from a bare human request.
---

# PR Review Loop

Run fresh-context reviewer subagents against a diff, round after round, until a round stops earning its cost — measured, and recorded, not felt.

**Core principle:** the caller is never satisfied into stopping. It stops when a round returns nothing new, or the round cap is hit.

**REQUIRED SUB-SKILLS:** superpowers:requesting-code-review (dispatching reviewers), superpowers:receiving-code-review (triaging what they return).

## What the caller supplies

| Input | Meaning |
|---|---|
| `repo`, `diff_range` (or `pr_number`) | what to review |
| `context` | ticket/acceptance-checklist text, or the PR description if there is no ticket — whatever tells a reviewer what "right" looks like |
| `notes_path` | where round history and verify-leg output live, so reviewers and later rounds can read it without session history |
| `verify_legs` | the build/test commands, and which are cheap vs. expensive |
| `cap` | round limit — the caller decides its own default and its own override flag |
| `fix_mode` | `fix-inline` — the round subagent fixes must-fix/worth-fixing findings itself before deciding whether to continue — or `report-only` — it triages and reports but never edits the branch; fixing, if any, happens outside this loop, and a fresh round only earns its cost after that edit lands. Both modes return `round_summary` to the caller; this loop never posts it anywhere itself |
| `seed_axes` | axes already known to be earned (a size gate, or a prior round's `next_round_recommendation`) — omit to compute round 1 from the table below |

## Returns to the caller, every round

- `round`
- `axes_dispatched`, `axes_reported`, `axes_unreported`: `[{axis, reason}]` — `dispatched == reported ∪ unreported`, and a round cannot return `decision: stop` while `axes_unreported` is non-empty
- `must_fix`: `[{summary, axis, fixed}]` — `fixed` is always `false` under `fix_mode: report-only`
- `rejected`: `[{summary, reason}]`
- `round_summary`: the round's write-up — axes dispatched/reported/unreported (with why), what was found, fixed, and rejected — as markdown text; what the caller does with it (post it, save it, discard it) is entirely the caller's call, never this skill's
- `decision`: `continue | stop`, with `decision_reason`
- `next_round_recommendation`: the live axis list for the next round — meaningful only when `decision == continue` (see "Round 2 onward narrows by default" below; never a bare `full`/`light` label)
- `flags`: `[]` or any of `thrash`, `whack-a-mole`, `diverging`, `out-of-scope-finding`, `unexpected-commit`, `self-referential` — non-empty means the caller stops and asks the human, cap or no cap

## Which axes a change earns

| Axis | Earn it with |
|---|---|
| security | untrusted or configured input reaching a shell, a path, a URL, a query or a deserializer; credentials; a subprocess; a network call; a sandbox or confinement rule |
| correctness | always — this is the floor, and includes swallowed errors, silent fallbacks, and missing error logging |
| conformance | a ticket/PR with several criteria, a staged ticket, or one whose body the comments have rewritten |
| simplification | a diff large enough to have structure worth questioning, or one that touched code it did not need to |
| type design | encapsulation, invariant expression and enforcement, and whether a new type earns its own existence — earned only by the **new public API surface** predicate: anything a consumer outside this repo can call, or that an export/codegen surface publishes; it never fires on its own. A caller may narrow this predicate for its own domain, but state the narrowing rather than restating the predicate itself |
| use the output | a change to anything a human reads: an error message, CLI output, a doc, a public exception — one reviewer builds the real output on a concrete example (a real invocation or run producing it, reusing step 1's build where that already produces it, not a hypothetical) and follows its advice literally |

Round 1 (or the first round this loop runs for a given diff) earns from all six; **security never retires** once earned. Choose by what the change touches, not by the length of this list — five reviewers against a one-function fix spends as much as five against a credential path and buys far less. One axis and one reviewer is a legitimate round 1 for a small change in a quiet corner; say in the report which axes ran and which were not earned, so nobody reads a narrow review as a broad one.

## Running one round

A round subagent's first step is reconstructing round history from disk, not memory: read `notes_path` before anything else — the durable record of what earlier rounds found, fixed, and rejected (each round appends its own `round_summary` there, per step 7 below), and what makes thrash and whack-a-mole detectable without seeing prior transcripts.

1. **Build and test first, once, and hand reviewers the result.** A red diff never goes to reviewers, and a green one does not need proving again by each of them. Put the command and its output in `notes_path`; tell every reviewer the suite is green as of this commit.

   **Reviewers must not re-run the full suite.** N reviewers each running the matrix is N-1 redundant runs of a result already in hand, and on a loaded machine it is what makes timing-sensitive tests flake and builds crawl. What a reviewer should run is small and targeted: a throwaway probe that proves one finding, or a filtered run of the tests their finding touches.

   Write any probe file with a heredoc or the Write tool, never a bare redirect that can block on stdin — one that does not terminate hangs the round with nothing to show for it.

2. **Dispatch fresh reviewers in parallel**, per superpowers:requesting-code-review — each gets `context`, `notes_path`, `diff_range`, and its own `axis` name plus that axis's row (name and earn-condition text) from "Which axes a change earns" above, never any session history — a fresh-context reviewer has no other way to know which of the six lenses it is holding.

   **A reviewer that stops producing output has stopped, whatever its status says.** Stat every reviewer's output file before triaging. Ten minutes with a static output file while its siblings finished means it stopped, whatever its status says — rounds take minutes, not hours. Stop it, then either re-dispatch that axis once or record it in `axes_unreported`; never begin the next round with one still outstanding, and never read its silence as a clean pass.

   **Diagnose before blaming the agent.** Several reviewers stopping within seconds of each other is one external event (an exhausted rate limit, a dropped network, a machine that slept), not several coincidences — check for the shared cause before concluding anything about the work.

   **Watch the load.** Reviewers run builds and test suites; enough of them at once, or alongside other jobs on the same machine, turns a fast build slow and makes timing-sensitive tests flake in code the change never touched. Confirm a suspected flake by running that test alone before believing it.

3. **Collect the inbound comments too.** Findings do not only come from the reviewers just dispatched — read what has arrived since the last round on **both** the PR and the ticket, if there is one:

   ```bash
   gh pr view "$PR" --json comments,reviews
   gh issue view <n> --json comments
   ```

   These go through the same triage as everything else. A bot is a reviewer that is confidently wrong at a higher rate, not a lower one. A passing bot check is not an approval and not a review seat — never block a round waiting for one, and never count its silence as a clean pass; note that it did not report and move on. If the repo has a reviewer that only runs on a manual trigger, say so in the report so the human can fire it — do not trigger it directly, since that spends someone else's quota.

4. **Triage every finding** as must-fix / worth-fixing / noise, per superpowers:receiving-code-review. Verify each claim against the code before accepting it — a wrong finding earns a written rebuttal, not a compliant edit.

5. **Under `fix_mode: fix-inline`, fix must-fix and agreed worth-fixing now**, and log rejections and their reasons in `notes_path`. **Under `fix_mode: report-only`, fix nothing** — hand the triaged findings back to the caller. A later round on the same diff only finds something new once the caller (or a human) has changed the code in between; dispatching one against an unchanged diff just re-reports round 1.

6. **Evaluate whether another round is worth it.** Record `decision`/`decision_reason` either way.

7. **Write `round_summary` and append it to `notes_path`.** Carry the cumulative history: for each round, the axes dispatched/reported/unreported (with why), what was found, fixed, and rejected, so a reader arriving at any moment sees the whole story in one place. **This loop never posts anywhere** — no `gh pr comment`, no `gh issue comment` — a round is a fresh-context subagent with no way to ask a human first, so writing to a PR or ticket is always the caller's decision, made in the caller's own context, not something a round does on its own initiative. Return `round_summary` to the caller; whether and where to post it is entirely up to them.

## Round 2 onward narrows by default

Full fan-out is a round-1 cost, spent because nothing is known yet about which axes this diff earns. Once round 1 has reported, that is no longer true, and **every round after it narrows to the delta and to the axes still live, by default** — a full fan-out again is the exception that needs a reason, not the default that needs an excuse to leave.

Carry axes forward per-axis, not as one round-wide light/full flag:

- an axis that produced a must-fix or worth-fixing finding last round **stays live** — the fix needs checking, and the axis clearly has purchase on this code
- an axis that reported clean last round **retires** for the next round unless the delta plausibly re-triggers it (a fix that added a subprocess call re-earns security even if security was clean before; a fix that only renamed a variable does not re-earn conformance)
- **security never retires once earned** — carry it into every remaining round regardless of what it found
- an axis not earned in round 1 can still be earned mid-loop if a fix's delta newly qualifies it — earning is about the code touched, not the round number

Widen back to a full round — all axes not yet earned re-checked against the whole diff, not just the delta — only when: the fix changed the design rather than staying confined to the reported issue, the delta is broad enough that a retired axis's earlier clean result no longer covers it, or a light round's reviewer flags something outside its scoped delta (the narrowing was wrong; don't trust it, widen instead).

Set `next_round_recommendation` to that live axis list (not a bare `light`/`full` label), so the next round's dispatch is unambiguous about what runs. Say which rounds were light and which axes ran in `round_summary` — "three rounds" and "one full round and two light ones, narrowed to correctness and simplification" are different claims about how hard the work was looked at.

## Guards

**Whack-a-mole:** when successive rounds keep finding the same defect *class* in new instances — another input the parser mishandles, another shape a check misses, another case the pattern does not cover — stop fixing instances; the loop cannot converge on an input space larger than the recogniser. Set `flags: whack-a-mole`, name the class, say why patching it does not terminate, and put the design question to the human: does the thing fail closed when it does not understand its input, and does it need to handle that input at all?

**Diverging vs. converging — test before believing either.** A list of commit subjects that each name a new input case reads identically whether the work is diverging or converging; what tells them apart is not the count but the shape:

| Converging | Diverging |
|---|---|
| The fixes are edge cases of **one grammar** — quoting, separators, empty values | Each fix is **one more dialect**, and the next dialect needs its own code |
| Unhandled input **elides, refuses, or fails safe** | Unhandled input **passes through** |
| The residues are **written down and bounded** | Nobody can say what is still uncovered |

Read the code and run it against inputs it has never seen before concluding anything; diagnosing this from commit subjects alone gets it wrong, and telling someone their design cannot converge when it demonstrably does is an expensive kind of wrong. Set `flags: diverging` only once the shape, not the count, says so.

**Thrash:** if a round reverses a change an earlier round made, stop — set `flags: thrash` and report the disagreement and the reasoning instead of oscillating between two reviewers' preferences.

**Unexpected commit:** a commit on the branch this round did not make and does not recognize is evidence of another round or a human push, not proof of a rogue session — set `flags: unexpected-commit` and let the caller adjudicate rather than concluding anything about who made it.

**Self-referential:** the cap bounds cost, not convergence. If a round's must-fix findings land entirely in scaffolding, harnesses, or documentation the implementation itself invented — never in the production change — the loop is reviewing its own artefacts, not the diff. Set `flags: self-referential` and exit regardless of the cap.

**Out-of-scope finding:** real, but outside what this diff was for. Set `flags: out-of-scope-finding`, name the finding, and report it to the human through the caller — do not build it and do not file it, since filing an issue is a remote write nobody asked for.

## The caller's control loop, after each round's report

Stop that round's subagent now that its report is read; before dispatching the next round, list live agents and stop any left over from a completed one — a round left running can misread a sibling's later commit as a rogue session when it simply started before that round existed.

If `axes_unreported` is non-empty, the round has not completed: re-dispatch the missing axis or accept the record before moving on. If `flags` is non-empty, stop and ask the human before dispatching anything further. Otherwise: if `decision == stop`, or the round just run hit the cap, exit the loop and record why; otherwise dispatch the next round scoped to `next_round_recommendation`'s axis list, passed forward as the next round's `seed_axes`.

**Hitting the cap never means shipping a known defect.** Under `fix_mode: fix-inline`, fix that round's must-fix findings even though the loop is stopping, and say plainly in the report that those fixes were not independently re-reviewed. Under `fix_mode: report-only`, hand the unresolved must-fix findings back to the caller exactly as found — there is nothing here for this skill to fix.

## Common mistakes

| Mistake | Why it bites |
|---|---|
| Running every axis because the list has six | Axes are earned by what the change touches. An unearned axis costs a reviewer and returns nits. |
| Every reviewer re-running the full suite | The loop already ran it and can hand them the output. Reviewers run targeted probes, not the matrix. |
| A full fan-out against a one-function fix | Re-confirms axes that went quiet about code that has not changed. Run a light round instead. |
| Reading "small diff" as "low risk" | A twenty-line change to a confinement check or a credential path is small and dangerous. Judge the neighbourhood, not the line count. |
| Introducing an axis in a late round | Rounds that should be converging start finding worse defects than the rounds before them — a scheduling mistake, not a discovery. |
| Narrowing later rounds in a way that drops security | Security never retires once earned, regardless of what later rounds find. |
| Trusting a stalled reviewer's silence as a clean pass | Ten minutes static while siblings finished means it stopped. Record it in `axes_unreported`, never assume clean. |
| Calling a test failure a finding without re-running it alone | Under heavy parallel load, timing-sensitive tests fail in code the change never touched. Confirm in isolation first. |
| Patching the next instance of a defect already patched twice | The class is the finding. Ask whether it fails closed, and whether it needs to handle that input at all. |
| Treating a bot comment as authoritative | It is a reviewer with a higher false-positive rate. Verify it like any other finding. |
| Implementing a finding that hasn't been verified | Reviewers are confidently wrong at a steady rate. Check first, under either `fix_mode`. |
| Under `report-only`, dispatching another round with nothing changed | Nothing will differ from the last round's findings; a round only earns its cost after a real edit landed. |
| Dispatching the next round without stopping a completed round's leftover subagent | It outlives its own view of the branch and can misdiagnose a later round's commit as a rogue session. |
| Calling a round's findings converging when they live entirely in invented scaffolding | It's reviewing its own harness, not the diff. Exit regardless of the cap. |

## Red flags

- About to add a review axis in a later round — it belonged in round 1
- About to narrow later rounds in a way that drops the security axis
- About to dispatch the next round without stopping a completed round's leftover subagent
- About to write a probe command that could block on stdin instead of using a heredoc
- About to call a round's findings converging when they live entirely in invented scaffolding
- About to begin the next round with a reviewer still outstanding from this one
- About to trigger a repo's manual-only automated reviewer directly instead of naming it in the report
