#!/usr/bin/env python3
"""Check that every claim in every lesson points at evidence that exists.

Standard library only, for the same reason prosecheck.py is: this has to run in
CI on a fresh checkout with nothing installed.

A lesson's claims.yaml is a promise about the lesson. The promise rots in three
ways, and all three are silent:

  a cell gets renamed        and the claim still names the old id
  the pin moves              and a citation still carries the old tag
  a claim gets softened      and its confidence still says observed

None of those break a build, none of them show up in a diff you would notice,
and each one turns a checkable claim into a decorative one. So they get checked.

What is enforced:

  shape        every lesson has a claims.yaml, every claim has id, claim,
               evidence and confidence, and ids are unique and kebab case
  confidence   one of observed, cited, inferred, and at most three inferred in
               a lesson, because a lesson that is mostly inference is an essay
  cells        "cell foo" in an evidence field names a cell that exists
  the pin      every @llvmorg-... suffix in a citation matches docs/pin.json
  pointers     a cited claim has a citation, and it is a pointer rather than a
               sentence. An observed claim may have none, because the cell a
               reader can run is already the evidence.

Two things are reported as notes rather than failures, because both can be
right. A code cell that no claim mentions is usually scene setting. A claim
whose citation names no line range is usually pointing at a whole section.

With --llvm-src DIR the file and line range in every source citation is checked
against a real llvm-project tree, which is the only check here that can tell you
a citation is pointing at the wrong lines rather than merely at a plausible
looking path. CI has no tree, so this is the check you run before you write the
claim, not the one that catches you afterwards.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LESSONS = ROOT / "lessons"
PIN = ROOT / "docs" / "pin.json"
LEDGER = ROOT / "docs" / "claims.md"

# citation is not here on purpose. A claim marked observed is evidenced by a
# cell somebody can run, and x03 established that such a claim may carry no
# citation at all. A cited claim is a different thing and is checked below.
REQUIRED = ("id", "claim", "evidence", "confidence")
CONFIDENCE = ("observed", "cited", "inferred")
MAX_INFERRED = 3

# Cells that exist to run a boss fight rather than to show something, so no
# claim is expected to mention them.
MACHINERY = ("grader", "attempt")
MACHINERY_PREFIX = "gate_"

KEBAB = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*$")
# The word cell or cells. An evidence field is split on it, so a sentence that
# says "cell twice_tape, and cell three_alone" is read as naming both.
CELL_REF = re.compile(r"\bcells?\s+")
BARE = re.compile(r"[a-z0-9_]+$")
SEPARATOR = re.compile(r",\s*|\s+and\s+")
# Words that join a list rather than being in it. "and" survives the split when
# somebody writes ", and", and it is not a cell.
CONNECTORS = {"and", "or", "then", "the"}
# The tag suffix a citation carries, as written in docs/pin.json.
TAG_SUFFIX = re.compile(r"@(llvmorg-[\w.-]+)")
# A source citation we can check against a tree: path, lines, then the tag.
SOURCE_CITE = re.compile(
    r"(?P<path>[\w./-]+\.(?:cpp|h|td|rst|md|py))"
    r"(?::(?P<first>\d+)(?:-(?P<last>\d+))?)?"
    r"@(?P<tag>llvmorg-[\w.-]+)"
)
# A cell marker in a lesson, and the id= option on it if there is one.
CELL_MARK = re.compile(r"^# %%(?P<options>.*)$")
CELL_ID = re.compile(r"\bid=(?P<id>\S+)")


class Problem(Exception):
    pass


# ---------------------------------------------------------------------------
# The claims file


def parse_claims(path: pathlib.Path) -> list[dict[str, str]]:
    """Parse the subset of YAML a claims file is allowed to be.

    A real YAML parser is not in the standard library, and reaching for one
    would be the wrong trade anyway. The subset here is a list of flat string
    fields, it is what every claims file already is, and a parser this small
    means the format cannot quietly grow anchors and nested maps that nothing
    downstream knows how to read.

    Values may be folded across lines by indenting the continuation, because a
    claim is a sentence and a sentence does not fit in eighty columns.
    """
    claims: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    key: str | None = None
    seen_header = False

    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue

        if raw.rstrip() in ("claims:", "claims: []"):
            seen_header = True
            continue
        if not seen_header:
            raise Problem(f"{path}:{number}: expected `claims:` before anything else")

        stripped = raw.strip()
        if stripped.startswith("- "):
            current = {}
            claims.append(current)
            stripped = stripped[2:]
        elif current is None:
            raise Problem(f"{path}:{number}: a field outside any claim")
        elif not raw.startswith("    "):
            raise Problem(f"{path}:{number}: expected an indented field or a new `- ` claim")

        field, sep, value = stripped.partition(": ")
        if sep and KEBAB.match(field.replace("_", "-")):
            key = field
            current[key] = value.strip()
        elif key is not None:
            # A folded continuation of the value above.
            current[key] = f"{current[key]} {stripped}".strip()
        else:
            raise Problem(f"{path}:{number}: cannot read `{stripped}` as `key: value`")

    return claims


def cell_ids(lesson: pathlib.Path) -> set[str]:
    """The explicit id= on every cell of a lesson.

    Read textually rather than through build.py, so refcheck keeps working on a
    lesson build.py rejects. A claim pointing at a cell in a broken lesson is
    still worth reporting, and reporting it is more use than a traceback.
    """
    found: set[str] = set()
    for raw in lesson.read_text(encoding="utf-8").splitlines():
        mark = CELL_MARK.match(raw)
        if mark:
            name = CELL_ID.search(mark.group("options"))
            if name:
                found.add(name.group("id"))
    return found


def referenced_cells(evidence: str) -> set[str]:
    """The cell ids an evidence field names.

    The field is prose with cell ids in it, not a list, because it also has to
    say things like "and the same three run separately". So the reading is
    deliberately cautious: after the word cell, take the first identifier, then
    keep taking comma or "and" separated pieces only while each one is nothing
    but an identifier. The first piece with a space in it ends the list.

    Being cautious in that direction is the right way round. Missing a cell an
    evidence field mentions costs a check nobody notices. Inventing one out of a
    connecting word costs a failure on a lesson that is correct, which is how a
    checker gets switched off.
    """
    out: set[str] = set()
    for segment in CELL_REF.split(evidence)[1:]:
        pieces = SEPARATOR.split(segment.strip())
        first = pieces[0].split(" ")[0]
        if not BARE.match(first) or first in CONNECTORS:
            continue
        out.add(first)
        for piece in pieces[1:]:
            name = piece.strip()
            if not BARE.match(name) or name in CONNECTORS:
                break
            out.add(name)
    return out


# ---------------------------------------------------------------------------
# The checks


def pinned_tag() -> str:
    return str(json.loads(PIN.read_text(encoding="utf-8"))["tag"])


def check_lesson(directory: pathlib.Path, tag: str, src: pathlib.Path | None
                 ) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Problems, notes, and the claims themselves for one lesson."""
    problems: list[str] = []
    notes: list[str] = []
    lesson = directory / "lesson.py"
    path = directory / "claims.yaml"

    if not path.is_file():
        return [f"{directory.name}: no claims.yaml"], [], []

    try:
        claims = parse_claims(path)
    except Problem as bad:
        return [str(bad)], [], []

    if not claims:
        return [f"{path}: no claims, and a lesson that asserts nothing is not a lesson"], [], []

    ids = [c.get("id", "") for c in claims]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"{path}: two claims share the id `{duplicate}`")

    known = cell_ids(lesson) if lesson.is_file() else set()
    inferred = 0

    for claim in claims:
        name = claim.get("id") or "<no id>"
        where = f"{path}: {name}"

        missing = [k for k in REQUIRED if not claim.get(k)]
        if missing:
            problems.append(f"{where}: missing {', '.join(missing)}")
            continue

        if not KEBAB.match(claim["id"]):
            problems.append(f"{where}: id should be kebab-case")

        confidence = claim["confidence"]
        if confidence not in CONFIDENCE:
            problems.append(
                f"{where}: confidence `{confidence}` is not one of {', '.join(CONFIDENCE)}")
        elif confidence == "inferred":
            inferred += 1

        for cell in sorted(referenced_cells(claim["evidence"])):
            if lesson.is_file() and cell not in known:
                problems.append(f"{where}: evidence names cell `{cell}`, which the lesson has not")

        citation = claim.get("citation", "")
        if confidence == "cited" and not citation:
            problems.append(f"{where}: a cited claim has to say what it cites")
        for found in TAG_SUFFIX.findall(citation):
            if found != tag:
                problems.append(
                    f"{where}: citation is pinned to {found}, but docs/pin.json says {tag}")

        if confidence == "cited" and "/" not in citation and "@" not in citation:
            problems.append(f"{where}: a cited claim needs a pointer, not a sentence")

        # The note fires in both modes on purpose. A citation with no path and
        # line range is nothing for --llvm-src to resolve, so without the note
        # the strictest run is the one that says least about it.
        if confidence == "cited" and not SOURCE_CITE.search(citation):
            notes.append(f"{where}: citation names no file and line range")
        if src is not None:
            problems.extend(check_source(where, citation, src))

    if inferred > MAX_INFERRED:
        problems.append(
            f"{path}: {inferred} inferred claims, and at most {MAX_INFERRED} are allowed")

    mentioned = set().union(*(referenced_cells(c.get("evidence", "")) for c in claims))
    for cell in sorted(known - mentioned):
        if cell in MACHINERY or cell.startswith(MACHINERY_PREFIX):
            continue
        notes.append(f"{path}: no claim mentions cell `{cell}`")

    return problems, notes, claims


def check_source(where: str, citation: str, src: pathlib.Path) -> list[str]:
    """Resolve every file and line range in a citation against a real tree."""
    problems: list[str] = []
    for hit in SOURCE_CITE.finditer(citation):
        target = src / hit.group("path")
        if not target.is_file():
            problems.append(f"{where}: {hit.group('path')} is not in {src}")
            continue
        if hit.group("first") is None:
            continue
        total = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        last = int(hit.group("last") or hit.group("first"))
        if last > total:
            problems.append(
                f"{where}: {hit.group('path')} has {total} lines, citation reaches {last}")
    return problems


# ---------------------------------------------------------------------------
# The ledger


def ledger(everything: list[tuple[str, list[dict[str, str]]]], tag: str) -> str:
    """One table per lesson, every claim with its evidence pointer.

    Generated, and checked in, for the same reason the notebooks are: the thing
    a reader or a reviewer wants to open is a file at a URL, and the thing that
    keeps it honest is CI failing when it does not match its source.
    """
    counts = {level: 0 for level in CONFIDENCE}
    for _, claims in everything:
        for claim in claims:
            if claim.get("confidence") in counts:
                counts[claim["confidence"]] += 1
    total = sum(counts.values())

    out = [
        "<!-- Generated by tools/refcheck.py --ledger. Do not edit. -->",
        "",
        "# The claim ledger",
        "",
        ("Every factual claim every lesson makes, with the evidence for it. "
         f"Written against `{tag}`."),
        "",
        ("`observed` means somebody ran it, on two platforms. `cited` means it is "
         "in the LLVM source or its documentation at the pinned tag, at the line given. "
         "`inferred` means neither, and a lesson is allowed at most three."),
        "",
        (f"{total} claims: {counts['observed']} observed, {counts['cited']} cited, "
         f"{counts['inferred']} inferred."),
        "",
    ]

    for lesson_id, claims in everything:
        out += [f"## {lesson_id}", "", "| Claim | Confidence | Evidence |", "|---|---|---|"]
        for claim in claims:
            out.append(
                f"| {cell(claim.get('claim'))} | {claim.get('confidence', '')} "
                f"| {cell(claim.get('evidence'))}<br>{cell(claim.get('citation'))} |"
            )
        out.append("")

    return "\n".join(out)


def cell(value: str | None) -> str:
    """A field, made safe to drop in a markdown table cell."""
    return (value or "").replace("|", "\\|").strip()


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ledger", action="store_true",
                        help=f"write {LEDGER.relative_to(ROOT)} from the claims files")
    parser.add_argument("--llvm-src", type=pathlib.Path,
                        help="an llvm-project checkout, to resolve source citations against")
    args = parser.parse_args()

    if args.llvm_src is not None and not (args.llvm_src / "llvm").is_dir():
        print(f"refcheck: {args.llvm_src} does not look like an llvm-project tree",
              file=sys.stderr)
        return 2

    tag = pinned_tag()
    directories = sorted(p for p in LESSONS.iterdir() if (p / "lesson.py").is_file())

    problems: list[str] = []
    notes: list[str] = []
    everything: list[tuple[str, list[dict[str, str]]]] = []

    for directory in directories:
        found, said, claims = check_lesson(directory, tag, args.llvm_src)
        problems += found
        notes += said
        if claims:
            everything.append((directory.name, claims))

    for problem in problems:
        print(problem)
    for note in notes:
        print(f"note, {note}")

    if args.ledger and not problems:
        LEDGER.write_text(ledger(everything, tag) + "\n", encoding="utf-8")
        print(f"refcheck: wrote {LEDGER.relative_to(ROOT)}", file=sys.stderr)

    counted = sum(len(c) for _, c in everything)
    print(f"refcheck: {len(directories)} lesson(s), {counted} claim(s), "
          f"{len(problems)} problem(s), {len(notes)} note(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
