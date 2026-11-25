"""Split a diff into code that only moved and code that actually changed.

usage: moved-code.py <base> <head> [--min-lines N] [-- <pathspec>...]

Compares <base>...<head> (from the merge-base, like a PR diff). A run of
added lines whose text, ignoring indentation, also appears as a run of
removed lines is a moved block. Everything else is printed as changed
code, the part a reviewer reads as new.
"""

import argparse
import subprocess
import sys
from collections import defaultdict

HUNK_PREFIX = "@@ -"


def run_git(*args):
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        sys.exit(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def parse_diff(diff):
    removed, added = [], []
    old_path = new_path = None
    old_line = new_line = 0
    for line in diff.splitlines():
        line = line.rstrip("\r")
        if line.startswith("diff --git "):
            old_path = new_path = None
        elif line.startswith("--- "):
            old_path = None if line[4:] == "/dev/null" else line[6:]
        elif line.startswith("+++ "):
            new_path = None if line[4:] == "/dev/null" else line[6:]
        elif line.startswith(HUNK_PREFIX):
            old_spec, new_spec = line.split(" ")[1:3]
            old_line = int(old_spec[1:].split(",")[0])
            new_line = int(new_spec[1:].split(",")[0])
        elif line.startswith("-") and old_path:
            removed.append((old_path, old_line, line[1:]))
            old_line += 1
        elif line.startswith("+") and new_path:
            added.append((new_path, new_line, line[1:]))
            new_line += 1
    return removed, added


def key(text):
    return " ".join(text.split())


def substantive(text):
    return any(ch.isalnum() for ch in text)


def adjacent(lines, i):
    """True when lines[i] directly follows lines[i - 1] in the same file."""
    return i > 0 and lines[i][0] == lines[i - 1][0] and lines[i][1] == lines[i - 1][1] + 1


def find_moves(removed, added, min_lines):
    index = defaultdict(list)
    for j, (_, _, text) in enumerate(removed):
        if substantive(text):
            index[key(text)].append(j)

    blocks = []
    moved_added = [False] * len(added)
    source_uses = defaultdict(int)
    i = 0
    while i < len(added):
        best = None
        if substantive(added[i][2]):
            for j in index.get(key(added[i][2]), ()):
                length = 1
                while (i + length < len(added) and j + length < len(removed)
                       and adjacent(added, i + length) and adjacent(removed, j + length)
                       and key(added[i + length][2]) == key(removed[j + length][2])):
                    length += 1
                weight = sum(substantive(added[i + k][2]) for k in range(length))
                if weight >= min_lines and (best is None or length > best[1]):
                    best = (j, length)
        if best is None:
            i += 1
            continue
        j, length = best
        copy = any(source_uses[j + k] for k in range(length))
        for k in range(length):
            moved_added[i + k] = True
            source_uses[j + k] += 1
        blocks.append((i, j, length, copy))
        i += length

    moved_removed = [source_uses[j] > 0 for j in range(len(removed))]
    return blocks, moved_added, moved_removed


def main():
    argv = sys.argv[1:]
    pathspec = []
    if "--" in argv:
        split = argv.index("--")
        argv, pathspec = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(usage=__doc__.split("\n\n")[1].removeprefix("usage: "))
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--min-lines", type=int, default=3,
                        help="lines with letters or digits a block needs to count as moved (default 3)")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    merge_base = run_git("merge-base", args.base, args.head).strip()
    diff = run_git("diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
                   "--find-renames", f"{args.base}...{args.head}", "--", *pathspec)
    removed, added = parse_diff(diff)
    blocks, moved_added, moved_removed = find_moves(removed, added, args.min_lines)

    print(f"== {args.base}...{args.head}: removed lines numbered at merge-base {merge_base[:10]}, "
          f"added lines at {args.head}")

    moves = [b for b in blocks if not b[3]]
    copies = [b for b in blocks if b[3]]
    for title, group in (("moved blocks: read as pre-existing code", moves),
                         ("copied blocks: the same source appears twice, so this copy is new code", copies)):
        print(f"\n== {title} ({len(group)})")
        for i, j, length, _ in group:
            (new_path, new_start, _), (old_path, old_start, _) = added[i], removed[j]
            print(f"{new_path}:{new_start}-{new_start + length - 1}  <-  "
                  f"{old_path}:{old_start}-{old_start + length - 1}  ({length} lines)")

    for title, lines, flags, sign in (("added lines that did not move: review as new code", added, moved_added, "+"),
                                       ("removed lines that did not move: review as deleted code", removed, moved_removed, "-")):
        rows = [line for line, moved in zip(lines, flags) if not moved and line[2].strip()]
        print(f"\n== {title} ({len(rows)})")
        for path, number, text in rows:
            print(f"{path}:{number}\t{sign}{text}")

    print(f"\n== {sum(moved_added)} of {len(added)} added lines moved, "
          f"{sum(moved_removed)} of {len(removed)} removed lines moved")


if __name__ == "__main__":
    main()
