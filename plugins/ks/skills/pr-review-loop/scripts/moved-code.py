"""Split a diff into code that only moved and code that actually changed.

usage: moved-code.py <base> <head> [--min-lines N] [-- <pathspec>...]

Compares <base>...<head> (from the merge-base, like a PR diff). A run of
added lines whose text, ignoring leading whitespace, also appears as a run of
removed lines is a moved block. Everything else is printed as changed
code, the part a reviewer reads as new.
"""

import argparse
import re
import subprocess
import sys
from collections import defaultdict

HUNK_PREFIX = "@@ -"
SIMPLE_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def run_git(*args):
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "-c", "diff.noprefix=false",
         "-c", "diff.mnemonicPrefix=false", *args],
        capture_output=True,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        sys.exit(show(message) if message else f"git {args[0]} failed")
    # bytes, not text mode: universal newlines would rewrite CRLF and split on a lone CR
    return result.stdout.decode("utf-8", errors="replace")


def unquote(path):
    """Decode a git C-quoted path; unquoted paths pass through."""
    if not (len(path) >= 2 and path.startswith('"') and path.endswith('"')):
        return path
    out = bytearray()
    body = path[1:-1]
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            octal = re.match(r"[0-7]{1,3}", body[i + 1:])
            if octal:
                out.append(int(octal.group(), 8) & 0xFF)
                i += 1 + len(octal.group())
            else:
                out.append(SIMPLE_ESCAPES.get(body[i + 1], ord(body[i + 1]) & 0xFF))
                i += 2
            continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def header_path(spec, prefix):
    # git appends a tab after unquoted paths that contain spaces
    spec = spec.rstrip("\r").removesuffix("\t")
    if spec == "/dev/null":
        return None
    return unquote(spec).removeprefix(prefix)


def parse_diff(diff):
    removed, added, skipped = [], [], []
    old_path = new_path = None
    old_line = new_line = 0
    in_header = False
    # splitlines() would also break on \f, \v and U+2028 inside file content
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            old_path = new_path = None
            in_header = True
        elif in_header and line.startswith("--- "):
            old_path = header_path(line[4:], "a/")
        elif in_header and line.startswith("+++ "):
            new_path = header_path(line[4:], "b/")
        elif line.startswith(HUNK_PREFIX):
            in_header = False
            old_spec, new_spec = line.split(" ")[1:3]
            old_line = int(old_spec[1:].split(",")[0])
            new_line = int(new_spec[1:].split(",")[0])
        elif in_header:
            if line.startswith(("Binary files ", "rename from ", "old mode ")):
                skipped.append(line)
        elif line.startswith("-") and old_path:
            removed.append((old_path, old_line, line[1:]))
            old_line += 1
        elif line.startswith("+") and new_path:
            added.append((new_path, new_line, line[1:]))
            new_line += 1
    return removed, added, skipped


def key(text):
    # interior spacing is code, so only leading whitespace and a trailing CR are ignored
    return text.lstrip().rstrip("\r")


def hidden(ch):
    code = ord(ch)
    return ((code < 32 and ch != "\t") or 0x7F <= code < 0xA0 or 0x202A <= code <= 0x202E
            or 0x2066 <= code <= 0x2069 or code in (0x2028, 0x2029, 0x200B))


def show(text):
    """Make control, bidi and separator characters visible so diff content cannot spoof the output."""
    return "".join(
        (f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}") if hidden(ch) else ch
        for ch in text
    )


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
        exact = all(added[i + k][2] == removed[j + k][2] for k in range(length))
        for k in range(length):
            moved_added[i + k] = True
            source_uses[j + k] += 1
        blocks.append((i, j, length, copy, exact))
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

    for ref in (args.base, args.head):
        if ref.startswith("-"):
            sys.exit(f"invalid ref: {show(ref)}")

    merge_base = run_git("merge-base", args.base, args.head).strip()
    diff = run_git("diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
                   "--text", "--ignore-submodules=all", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/", "--find-renames",
                   f"{args.base}...{args.head}", "--", *pathspec)
    removed, added, skipped = parse_diff(diff)
    for line in skipped:
        if line.startswith("Binary files "):
            print(f"warning: not analysed: {show(line)}", file=sys.stderr)
    if not removed and not added:
        if skipped:
            print(f"warning: no changed lines found: {len(skipped)} renamed, mode-only or binary "
                  "file(s) were skipped", file=sys.stderr)
        else:
            print("warning: no changed lines found: empty diff, or the pathspec matched nothing",
                  file=sys.stderr)
    blocks, moved_added, moved_removed = find_moves(removed, added, args.min_lines)

    print(f"== {show(args.base)}...{show(args.head)}: removed lines numbered at merge-base {merge_base[:10]}, "
          f"added lines at {show(args.head)}")

    moves = [b for b in blocks if not b[3]]
    copies = [b for b in blocks if b[3]]
    for title, group in (("moved blocks: read as pre-existing code", moves),
                         ("copied blocks: the same source appears twice, so this copy is new code", copies)):
        print(f"\n== {title} ({len(group)})")
        for i, j, length, _, exact in group:
            (new_path, new_start, _), (old_path, old_start, _) = added[i], removed[j]
            note = "" if exact else "; indentation or line endings differ, check it"
            print(f"{show(new_path)}:{new_start}-{new_start + length - 1}  <-  "
                  f"{show(old_path)}:{old_start}-{old_start + length - 1}  ({length} lines{note})")

    for title, lines, flags, sign in (("added lines that did not move: review as new code", added, moved_added, "+"),
                                       ("removed lines that did not move: review as deleted code", removed, moved_removed, "-")):
        rows = [line for line, moved in zip(lines, flags) if not moved and line[2].strip()]
        print(f"\n== {title} ({len(rows)})")
        for path, number, text in rows:
            print(f"{show(path)}:{number}\t{sign}{show(text)}")

    print(f"\n== {sum(moved_added)} of {len(added)} added lines moved, "
          f"{sum(moved_removed)} of {len(removed)} removed lines moved")


if __name__ == "__main__":
    main()
