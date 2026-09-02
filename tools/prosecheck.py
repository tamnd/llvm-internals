#!/usr/bin/env python3
"""Check the prose rules from CONTRIBUTING.md that a machine can check.

Standard library only and no configuration file, because the whole value of this
thing is that it runs in CI on a fresh checkout without anyone installing
anything first.

Four rules:

  em-dash     No em dashes. Use a comma, a full stop or brackets.
  banned      No "simply", "just", "obviously", "of course" or "trivially".
  wrap        One paragraph is one line. A sentence never gets broken across
              two lines, because a hard wrapped paragraph produces a diff where
              one word change rewraps six lines and the review is unreadable.
  whitespace  No trailing whitespace and no tabs.

A line ending in the comment <!-- prose-ok --> is exempt from em-dash and
banned, which is how a document quotes a rule in order to state it.

Markdown files are the obvious target and they are not the important one. Most
of the prose in this repository is going to live in the markdown cells of
lessons/<id>/lesson.py, so those get read too. The rules only apply to the
markdown cells; code cells are code.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

EM_DASH = "—"
ALLOW = "<!-- prose-ok -->"

BANNED = re.compile(
    r"(?<![\w-])(simply|just|obviously|trivially)(?![\w-])|of course",
    re.IGNORECASE,
)

# Lines that are not prose, so the one-paragraph-one-line rule does not apply.
# Lists, tables, headings, quotes, footnotes and anything indented as a code
# block wrap for their own reasons.
NOT_PROSE = re.compile(r"^(\s*$|#{1,6} |\s*[-*+] |\s*\d+\. |\s*>|\||\s{4,}|\[\^)")

# A cell marker in a lesson, and whether the cell it opens is markdown.
CELL = re.compile(r"^# %%(?P<options>.*)$")

NOISE = {
    ".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", "node_modules", "build", "site",
}


def scan(path: pathlib.Path, lines: list[tuple[int, str]]) -> list[str]:
    """Apply the four rules to numbered lines of markdown.

    The lines carry their own numbers rather than being enumerated here, because
    the prose in a lesson is a handful of stretches of a bigger file and a
    problem has to point at the line somebody has to go and edit.
    """
    problems: list[str] = []
    fenced = False
    for position, (number, line) in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced:
            continue

        exempt = ALLOW in line

        if EM_DASH in line and not exempt:
            problems.append(f"{path}:{number}: em dash")
        if not exempt:
            hit = BANNED.search(line)
            if hit:
                problems.append(f"{path}:{number}: banned word {hit.group(0)!r}")
        if line != line.rstrip():
            problems.append(f"{path}:{number}: trailing whitespace")
        if "\t" in line:
            problems.append(f"{path}:{number}: tab")

        # The wrap rule. A prose line followed by another prose line means the
        # paragraph got hard wrapped, so the sentence is broken across a
        # newline. Checked forwards rather than backwards so the reported line
        # is the one somebody has to go and join.
        if NOT_PROSE.match(line):
            continue
        nxt = lines[position + 1][1] if position + 1 < len(lines) else ""
        if nxt.strip().startswith("```") or nxt.strip().startswith("~~~"):
            continue
        if not NOT_PROSE.match(nxt):
            problems.append(f"{path}:{number}: hard wrapped paragraph, join it onto one line")

    return problems


def markdown_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def lesson_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """The markdown cells of a lesson, with their line numbers in the lesson.

    Read textually instead of through build.py. The parser strips the comment
    prefix and trims blank lines, and a prose error that points two lines away
    from the sentence it is about is an error people learn to ignore.
    """
    out: list[tuple[int, str]] = []
    inside = False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        mark = CELL.match(raw)
        if mark:
            inside = mark.group("options").strip().startswith("[markdown]")
            # A blank between cells, so the wrap rule does not read the first
            # line of one cell as a continuation of the last line of the one
            # before it. Line 0 never gets reported, because blank is not prose.
            out.append((0, ""))
            continue
        if not inside:
            continue
        if raw.startswith("# "):
            out.append((number, raw[2:]))
        elif raw.rstrip() in ("", "#"):
            out.append((number, ""))
        else:
            out.append((number, raw))
    return out


def check(path: pathlib.Path) -> list[str]:
    read = lesson_lines if path.suffix == ".py" else markdown_lines
    return scan(path, read(path))


def ours(path: pathlib.Path) -> bool:
    """Skip machine generated directories.

    Named one by one rather than skipping every dot directory, because .github
    holds the pull request template and that is prose somebody wrote.
    """
    return not (NOISE & set(path.parts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["."], help="files or directories")
    args = parser.parse_args()

    targets: list[pathlib.Path] = []
    for raw in args.paths:
        p = pathlib.Path(raw)
        if p.is_dir():
            found = [q for q in p.rglob("*.md") if ours(q)]
            found += [q for q in p.rglob("lesson.py") if ours(q)]
            targets.extend(sorted(set(found)))
        elif p.suffix == ".md" or p.name == "lesson.py":
            targets.append(p)

    problems: list[str] = []
    for path in targets:
        problems.extend(check(path))

    for problem in problems:
        print(problem)

    print(f"prosecheck: {len(targets)} files, {len(problems)} problems", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
