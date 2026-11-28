"""Split a diff into code that only moved and code that actually changed.

usage: moved-code.py <base> <head> [--min-lines N] [--max-rows N] [-- <pathspec>...]

Compares <base>...<head> (from the merge-base, like a PR diff). A run of
added lines whose text, ignoring leading whitespace, also appears as a run of
removed lines is a moved block. Everything else is printed as changed
code, the part a reviewer reads as new.
"""

import argparse
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict

HUNK_PREFIX = "@@ -"
SKIP_PREFIXES = ("rename from ", "old mode ", "new file mode ", "deleted file mode ")
# identical lines make candidate scanning quadratic, so only the first few sources per line are tried
MAX_CANDIDATES = 100
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
    """Return removed rows, added rows, count of hunkless files skipped, and paths that look binary."""
    removed, added, binary = [], [], []
    skipped = 0
    old_path = new_path = None
    old_line = new_line = 0
    in_header = False
    file_removed, file_added = [], []
    flagged = hunked = False

    def finish():
        nonlocal skipped
        if file_removed or file_added:
            if any("\0" in row[2] for row in file_removed + file_added):
                binary.append(new_path or old_path)
            else:
                removed.extend(file_removed)
                added.extend(file_added)
        elif flagged and not hunked:
            skipped += 1
        file_removed.clear()
        file_added.clear()

    # splitlines() would also break on \f, \v and U+2028 inside file content
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            finish()
            old_path = new_path = None
            in_header = True
            flagged = hunked = False
        elif in_header and line.startswith("--- "):
            old_path = header_path(line[4:], "a/")
        elif in_header and line.startswith("+++ "):
            new_path = header_path(line[4:], "b/")
        elif line.startswith(HUNK_PREFIX):
            in_header = False
            hunked = True
            old_spec, new_spec = line.split(" ")[1:3]
            old_line = int(old_spec[1:].split(",")[0])
            new_line = int(new_spec[1:].split(",")[0])
        elif in_header:
            if line.startswith(SKIP_PREFIXES):
                flagged = True
        elif line.startswith("-") and old_path:
            file_removed.append((old_path, old_line, line[1:]))
            old_line += 1
        elif line.startswith("+") and new_path:
            file_added.append((new_path, new_line, line[1:]))
            new_line += 1
    finish()
    return removed, added, skipped, binary


def key(text):
    # interior spacing is code, so only leading whitespace and a trailing CR are ignored
    return text.lstrip().rstrip("\r")


ESCAPED_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


def hidden(ch, keep_tab):
    if ch == "\t":
        return not keep_tab
    code = ord(ch)
    return (unicodedata.category(ch) in ESCAPED_CATEGORIES
            or 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF)


def show(text, keep_tab=False):
    """Escape invisible characters so diff content cannot spoof the output; keep_tab is for row content only."""
    def escape(ch):
        code = ord(ch)
        if code < 0x100:
            return f"\\x{code:02x}"
        return f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}"
    return "".join(escape(ch) if hidden(ch, keep_tab) else ch for ch in text)


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
            for j in index.get(key(added[i][2]), ())[:MAX_CANDIDATES]:
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


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, show(f"{self.prog}: error: {message}") + "\n")


def non_negative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def cap(rows, limit):
    """Return the rows to print and how many were cut."""
    if limit and len(rows) > limit:
        return rows[:limit], len(rows) - limit
    return rows, 0


def main():
    # before parsing, so an unencodable argument in a usage error cannot crash the console
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    argv = sys.argv[1:]
    pathspec = []
    if "--" in argv:
        split = argv.index("--")
        argv, pathspec = argv[:split], argv[split + 1:]
    parser = SafeParser(usage=__doc__.split("\n\n")[1].removeprefix("usage: "))
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--min-lines", type=int, default=3,
                        help="lines with letters or digits a block needs to count as moved (default 3)")
    parser.add_argument("--max-rows", type=non_negative, default=1000,
                        help="rows printed per section before '... N more' (default 1000, 0 = unlimited)")
    args = parser.parse_args(argv)

    for ref in (args.base, args.head):
        if ref.startswith("-"):
            sys.exit(f"invalid ref: {show(ref)}")

    merge_base = run_git("merge-base", args.base, args.head).strip()
    diff = run_git("diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
                   "--text", "--ignore-submodules=all", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/", "--find-renames",
                   f"{args.base}...{args.head}", "--", *pathspec)
    removed, added, skipped, binary = parse_diff(diff)
    for path in binary:
        print(f"warning: skipped binary-looking file (NUL bytes): {show(path)}", file=sys.stderr)
    if not removed and not added:
        if skipped or binary:
            print(f"warning: no changed lines found: {skipped + len(binary)} renamed, mode-only, empty "
                  "or binary file(s) were skipped", file=sys.stderr)
        else:
            print("warning: no changed lines found: empty diff, or the pathspec matched nothing",
                  file=sys.stderr)
    blocks, moved_added, moved_removed = find_moves(removed, added, args.min_lines)
    rest = "; use --max-rows 0 or a pathspec to see the rest"

    print(f"== {show(args.base)}...{show(args.head)}: removed lines numbered at merge-base {merge_base[:10]}, "
          f"added lines at {show(args.head)}")

    moves = [b for b in blocks if not b[3]]
    copies = [b for b in blocks if b[3]]
    for title, group in (("moved blocks: read as pre-existing code", moves),
                         ("copied blocks: the same source appears twice, so this copy is new code", copies)):
        print(f"\n== {title} ({len(group)})")
        shown, more = cap(group, args.max_rows)
        for i, j, length, _, exact in shown:
            (new_path, new_start, _), (old_path, old_start, _) = added[i], removed[j]
            note = "" if exact else "; indentation or line endings differ, check it"
            print(f"{show(new_path)}:{new_start}-{new_start + length - 1}  <-  "
                  f"{show(old_path)}:{old_start}-{old_start + length - 1}  ({length} lines{note})")
        if more:
            print(f"... {more} more{rest}")

    for title, lines, flags, sign in (("added lines that did not move: review as new code", added, moved_added, "+"),
                                       ("removed lines that did not move: review as deleted code", removed, moved_removed, "-")):
        rows = [line for line, moved in zip(lines, flags) if not moved and line[2].strip()]
        print(f"\n== {title} ({len(rows)})")
        shown, more = cap(rows, args.max_rows)
        for path, number, text in shown:
            print(f"{show(path)}:{number}\t{sign}{show(text, keep_tab=True)}")
        if more:
            print(f"... {more} more{rest}")

    if binary:
        print(f"\n== skipped binary-looking files, NUL bytes ({len(binary)})")
        for path in binary:
            print(show(path))

    totals = (f"{sum(moved_added)} of {len(added)} added lines moved, "
              f"{sum(moved_removed)} of {len(removed)} removed lines moved")
    if skipped or binary:
        totals += (f"; {skipped + len(binary)} file(s) not compared "
                   f"({skipped} rename, mode-only or empty, {len(binary)} binary)")
    print(f"\n== {totals}")


if __name__ == "__main__":
    main()
