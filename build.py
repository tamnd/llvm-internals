#!/usr/bin/env python3
"""Turn lesson sources into notebooks, and check they stay in sync.

A lesson lives at lessons/<id>/lesson.py in percent format. This script turns it
into notebooks/<id>/lesson.ipynb, which is what Colab opens. The notebook is
committed because Colab can only open a file that exists at a URL, but it is
build output and it is never edited by hand.

Everything here is standard library on purpose. A tool that needs a virtualenv
before it will tell you your notebook is stale is a tool people stop running.
The one exception is `run`, which needs a Jupyter kernel because executing a
notebook is not something you can fake.

  python3 build.py new x03_wrong_fold   scaffold a new lesson
  python3 build.py list                 what lessons exist
  python3 build.py notebooks            regenerate every notebook
  python3 build.py check                fail if a committed notebook is stale
  python3 build.py run --only t04       execute a notebook from a cold kernel
  python3 build.py diagrams             regenerate the diagrams
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LESSONS = ROOT / "lessons"
NOTEBOOKS = ROOT / "notebooks"
DIAGRAMS = ROOT / "docs" / "diagrams"
PIN_FILE = ROOT / "docs" / "pin.json"

REPO = "tamnd/llvm-internals"
BRANCH = "main"

# nbformat 4.5 is the first version with stable cell ids, which is what lets a
# notebook be byte identical across builds. Anything older regenerates ids and
# every notebook shows up in every diff.
NBFORMAT = (4, 5)

CELL_MARK = re.compile(r"^# %%(?P<rest>.*)$")
HEADER_MARK = "# ---"
OPTION = re.compile(r"(?P<key>[a-z][a-z0-9_]*)=(?P<value>\S+)")

# Keys allowed in a lesson header. Anything else is a typo and gets rejected
# rather than silently ignored, because a header key that does nothing is worse
# than one that errors.
HEADER_KEYS = {
    "id": "str",
    "title": "str",
    "part": "str",
    "env": "str",
    "minutes": "int",
    "needs": "list",
    "blueprints": "list",
    "bootstrap": "str",
}
REQUIRED_KEYS = {"id", "title", "part", "env", "minutes"}
ENVS = {"E0", "E1", "E2"}


class LessonError(Exception):
    """A lesson source that cannot be built. The message names the file."""


@dataclass
class Cell:
    kind: str  # "code" or "markdown"
    source: str
    options: dict[str, str] = field(default_factory=dict)
    line: int = 0


@dataclass
class Lesson:
    path: Path
    header: dict[str, object]
    cells: list[Cell]

    @property
    def id(self) -> str:
        return str(self.header["id"])

    @property
    def env(self) -> str:
        return str(self.header["env"])


def read_pin() -> dict:
    return json.loads(PIN_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Parsing


def parse_header(lines: list[str], path: Path) -> tuple[dict[str, object], int]:
    """Read the YAML style header out of the leading comment block.

    The header is deliberately a tiny subset of YAML: flat keys, scalars, and
    inline lists. That keeps this file free of dependencies and it keeps lesson
    headers boring, which is what you want from metadata.
    """
    if not lines or lines[0].rstrip() != HEADER_MARK:
        raise LessonError(f"{path}: first line must be `{HEADER_MARK}`")

    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == HEADER_MARK:
            end = i
            break
    if end is None:
        raise LessonError(f"{path}: header is never closed with `{HEADER_MARK}`")

    header: dict[str, object] = {}
    for i in range(1, end):
        raw = lines[i]
        if not raw.startswith("#"):
            raise LessonError(f"{path}:{i + 1}: header lines must start with `#`")
        body = raw[1:].strip()
        if not body:
            continue
        if ":" not in body:
            raise LessonError(f"{path}:{i + 1}: expected `key: value`")
        key, _, value = body.partition(":")
        key, value = key.strip(), value.strip()
        if key not in HEADER_KEYS:
            known = ", ".join(sorted(HEADER_KEYS))
            raise LessonError(f"{path}:{i + 1}: unknown header key `{key}`, known keys are {known}")
        if key in header:
            raise LessonError(f"{path}:{i + 1}: duplicate header key `{key}`")
        header[key] = coerce(HEADER_KEYS[key], value, path, i + 1)

    missing = REQUIRED_KEYS - set(header)
    if missing:
        raise LessonError(f"{path}: header is missing {', '.join(sorted(missing))}")
    if header["env"] not in ENVS:
        raise LessonError(f"{path}: env must be one of {', '.join(sorted(ENVS))}")
    return header, end + 1


def coerce(kind: str, value: str, path: Path, line: int) -> object:
    if kind == "int":
        if not value.isdigit():
            raise LessonError(f"{path}:{line}: expected a whole number, got `{value}`")
        return int(value)
    if kind == "list":
        inner = value.strip()
        if not (inner.startswith("[") and inner.endswith("]")):
            raise LessonError(f"{path}:{line}: expected an inline list like [a, b]")
        inner = inner[1:-1].strip()
        return [x.strip() for x in inner.split(",") if x.strip()]
    return value


def parse_cells(lines: list[str], start: int, path: Path) -> list[Cell]:
    cells: list[Cell] = []
    current: Cell | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current, body
        if current is None:
            return
        text = "\n".join(body).strip("\n")
        if current.kind == "markdown":
            text = strip_comment_prefix(text, current.line, path)
        if text.strip():
            current.source = text
            cells.append(current)
        current, body = None, []

    for i in range(start, len(lines)):
        raw = lines[i]
        match = CELL_MARK.match(raw)
        if match:
            flush()
            current = parse_cell_mark(match.group("rest"), path, i + 1)
            continue
        if current is None:
            if raw.strip():
                raise LessonError(f"{path}:{i + 1}: content before the first `# %%` cell")
            continue
        body.append(raw)
    flush()

    if not cells:
        raise LessonError(f"{path}: no cells")
    if cells[0].kind != "markdown":
        raise LessonError(f"{path}: the first cell must be markdown, a lesson opens with a hook")
    return cells


def parse_cell_mark(rest: str, path: Path, line: int) -> Cell:
    rest = rest.strip()
    kind = "code"
    if rest.startswith("[markdown]"):
        kind, rest = "markdown", rest[len("[markdown]") :].strip()
    elif rest.startswith("["):
        raise LessonError(f"{path}:{line}: the only bracketed cell type is [markdown]")

    options: dict[str, str] = {}
    for token in rest.split():
        match = OPTION.fullmatch(token)
        if not match:
            raise LessonError(f"{path}:{line}: cell options look like key=value, got `{token}`")
        options[match.group("key")] = match.group("value")

    unknown = set(options) - {"env", "tags", "id"}
    if unknown:
        raise LessonError(f"{path}:{line}: unknown cell option {', '.join(sorted(unknown))}")
    if "env" in options and options["env"] not in ENVS:
        raise LessonError(f"{path}:{line}: env must be one of {', '.join(sorted(ENVS))}")
    return Cell(kind=kind, source="", options=options, line=line)


def strip_comment_prefix(text: str, line: int, path: Path) -> str:
    out = []
    for offset, raw in enumerate(text.split("\n")):
        if raw.strip() == "":
            out.append("")
        elif raw.startswith("# "):
            out.append(raw[2:])
        elif raw.rstrip() == "#":
            out.append("")
        else:
            raise LessonError(
                f"{path}:{line + offset + 1}: markdown cell lines start with `# `, got `{raw[:20]}`"
            )
    return "\n".join(out).strip("\n")


def load_lesson(path: Path) -> Lesson:
    text = path.read_text(encoding="utf-8")
    if "\t" in text:
        raise LessonError(f"{path}: contains a tab, which renders differently everywhere")
    lines = text.split("\n")
    header, start = parse_header(lines, path)
    cells = parse_cells(lines, start, path)
    stem = path.parent.name
    if header["id"] != stem:
        raise LessonError(f"{path}: header id `{header['id']}` does not match directory `{stem}`")
    return Lesson(path=path, header=header, cells=cells)


def lesson_paths() -> list[Path]:
    if not LESSONS.is_dir():
        return []
    return sorted(p / "lesson.py" for p in LESSONS.iterdir() if (p / "lesson.py").is_file())


# ---------------------------------------------------------------------------
# Emitting


def cell_id(index: int, source: str) -> str:
    """A cell id that depends on position and content, so builds repeat.

    Position is in the hash so that two identical cells in one notebook do not
    collide. Content is in the hash so that a cell keeps its id when something
    above it changes, which keeps diffs small when a notebook does get looked at.
    """
    digest = hashlib.sha256(f"{index}\x00{source}".encode()).hexdigest()
    return digest[:12]


def badge_cell(lesson: Lesson) -> Cell:
    url = f"https://colab.research.google.com/github/{REPO}/blob/{BRANCH}/notebooks/{lesson.id}/lesson.ipynb"
    return Cell(
        kind="markdown",
        source=f"[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)]({url})",
    )


def bootstrap_cell(lesson: Lesson) -> Cell | None:
    """The cell that puts a real LLVM on the machine before anything needs one.

    Injected rather than written out in every lesson, because a preamble that is
    copied 102 times is a preamble that is wrong in 40 of them within a year.
    Set `bootstrap: none` in the header to opt out.
    """
    if lesson.header.get("bootstrap") == "none":
        return None
    pin = read_pin()
    source = "\n".join(
        [
            "# Puts LLVM " + pin["tag"] + " on this machine. Takes about a minute the first",
            "# time and is instant afterwards. Everything below runs against that toolchain,",
            "# not against whatever compiler happens to be installed.",
            "",
            "try:",
            "    import irx",
            "except ImportError:",
            f'    !pip install --quiet "irx @ git+https://github.com/{REPO}@{BRANCH}#subdirectory=toolkit"',
            "    import irx",
            "",
            "irx.bootstrap()",
        ]
    )
    return Cell(kind="code", source=source)


def to_notebook(lesson: Lesson) -> dict:
    cells = [badge_cell(lesson), lesson.cells[0]]
    boot = bootstrap_cell(lesson)
    if boot is not None:
        cells.append(boot)
    cells.extend(lesson.cells[1:])

    out = []
    for index, cell in enumerate(cells):
        node: dict[str, object] = {
            "cell_type": cell.kind,
            "id": cell_id(index, cell.source),
            "metadata": cell_metadata(cell),
            "source": split_source(cell.source),
        }
        if cell.kind == "code":
            # No execution counts and no outputs, ever. A committed notebook that
            # carries execution state is a notebook that lies about what order
            # things ran in, and this material is partly about hidden state.
            node["execution_count"] = None
            node["outputs"] = []
        out.append(node)

    header = lesson.header
    return {
        "cells": out,
        "metadata": {
            "colab": {"provenance": [], "toc_visible": True},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "llvm_internals": {
                "id": header["id"],
                "title": header["title"],
                "part": header["part"],
                "env": header["env"],
                "minutes": header["minutes"],
                "needs": header.get("needs", []),
                "blueprints": header.get("blueprints", []),
                "pin": read_pin()["tag"],
                "generated_by": "build.py, do not edit this file",
            },
        },
        "nbformat": NBFORMAT[0],
        "nbformat_minor": NBFORMAT[1],
    }


def cell_metadata(cell: Cell) -> dict:
    meta: dict[str, object] = {}
    if "env" in cell.options:
        meta["env"] = cell.options["env"]
    if "id" in cell.options:
        meta["name"] = cell.options["id"]
    tags = [t for t in cell.options.get("tags", "").split(",") if t]
    if cell.options.get("env") == "E1":
        tags.append("skip-execution")
    if tags:
        meta["tags"] = sorted(set(tags))
    return meta


def split_source(text: str) -> list[str]:
    """Jupyter stores source as a list of lines, each keeping its newline."""
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + [lines[-1]]


def dump(notebook: dict) -> str:
    """One canonical serialisation, so a rebuild is byte identical or a bug."""
    return json.dumps(notebook, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Commands


def cmd_list(_args: argparse.Namespace) -> int:
    paths = lesson_paths()
    if not paths:
        print("no lessons yet")
        return 0
    rows = []
    for path in paths:
        lesson = load_lesson(path)
        rows.append(
            (
                lesson.id,
                str(lesson.header["part"]),
                lesson.env,
                f"{lesson.header['minutes']}m",
                str(lesson.header["title"]),
            )
        )
    width = max(len(r[0]) for r in rows)
    for row in rows:
        print(f"{row[0]:<{width}}  {row[1]:<4} {row[2]:<3} {row[3]:>4}  {row[4]}")
    return 0


def cmd_notebooks(args: argparse.Namespace) -> int:
    count = 0
    for path in lesson_paths():
        lesson = load_lesson(path)
        if args.only and lesson.id != args.only:
            continue
        target = NOTEBOOKS / lesson.id / "lesson.ipynb"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = dump(to_notebook(lesson))
        if target.exists() and target.read_text(encoding="utf-8") == text:
            continue
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")
        count += 1
    print(f"build: {count} notebook(s) changed")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    problems = []
    seen = set()
    for path in lesson_paths():
        lesson = load_lesson(path)
        seen.add(lesson.id)
        target = NOTEBOOKS / lesson.id / "lesson.ipynb"
        want = dump(to_notebook(lesson))
        if not target.exists():
            problems.append(f"{target.relative_to(ROOT)} is missing, run `build.py notebooks`")
        elif target.read_text(encoding="utf-8") != want:
            problems.append(
                f"{target.relative_to(ROOT)} does not match {path.relative_to(ROOT)}, "
                "run `build.py notebooks`"
            )

    if NOTEBOOKS.is_dir():
        for stray in sorted(NOTEBOOKS.iterdir()):
            if stray.is_dir() and stray.name not in seen:
                problems.append(f"{stray.relative_to(ROOT)} has no lesson source")

    for problem in problems:
        print(f"check: {problem}")
    print(f"check: {len(seen)} lesson(s), {len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_new(args: argparse.Namespace) -> int:
    lesson_id = args.id
    if not re.fullmatch(r"[a-z]\d{2}_[a-z0-9_]+", lesson_id):
        print(f"new: id should look like t04_the_pass_tape, got `{lesson_id}`")
        return 1
    target = LESSONS / lesson_id
    if target.exists():
        print(f"new: {target.relative_to(ROOT)} already exists")
        return 1
    target.mkdir(parents=True)
    title = lesson_id.split("_", 1)[1].replace("_", " ").capitalize()
    (target / "lesson.py").write_text(TEMPLATE.format(id=lesson_id, title=title), encoding="utf-8")
    (target / "claims.yaml").write_text(CLAIMS_TEMPLATE, encoding="utf-8")
    print(f"new: {target.relative_to(ROOT)}")
    print("new: fill in the header, then run `build.py notebooks`")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute notebooks from a cold kernel, which is the only honest test.

    Outputs land in .build/ and are thrown away. Nothing executed here ever gets
    committed, because a committed notebook in this repository has no outputs.
    """
    if shutil.which("jupyter") is None:
        print("run: needs jupyter, try `uv run --with nbconvert --with ipykernel build.py run`")
        return 1
    failures = 0
    for path in lesson_paths():
        lesson = load_lesson(path)
        if args.only and lesson.id != args.only:
            continue
        if lesson.env == "E1" and not args.include_e1:
            print(f"run: {lesson.id} is E1, skipping, pass --include-e1 to run it anyway")
            continue
        notebook = NOTEBOOKS / lesson.id / "lesson.ipynb"
        outdir = ROOT / ".build" / lesson.id
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"run: {lesson.id}")
        command = [
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            f"--ExecutePreprocessor.timeout={args.timeout}",
            # Cells marked env=E1 carry this tag. On E0 they replay from a
            # recording instead, so executing them here would prove nothing.
            "--TagRemovePreprocessor.enabled=True",
            "--TagRemovePreprocessor.remove_cell_tags=skip-execution",
            "--output-dir",
            str(outdir),
            str(notebook),
        ]
        if subprocess.run(command, cwd=ROOT).returncode != 0:
            failures += 1
            print(f"run: {lesson.id} failed")
    print(f"run: {failures} failure(s)")
    return 1 if failures else 0


def cmd_diagrams(_args: argparse.Namespace) -> int:
    scripts = sorted(DIAGRAMS.glob("*.py")) if DIAGRAMS.is_dir() else []
    if not scripts:
        print("diagrams: none")
        return 0
    for script in scripts:
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT)
        if result.returncode != 0:
            return 1
    print(f"diagrams: {len(scripts)} script(s)")
    return 0


TEMPLATE = '''# ---
# id: {id}
# title: {title}
# part: TODO
# env: E0
# minutes: 30
# ---

# %% [markdown]
# # {title}
#
# The hook goes here. 150 words at most. Say what the reader is about to see and
# why it is strange, not what they are about to learn.

# %%
# The first thing they run.

# %% [markdown]
# ## What just happened
'''

CLAIMS_TEMPLATE = """# Every factual claim in this lesson, with the evidence for it.
# confidence is one of: observed, cited, inferred. At most three may be inferred.
claims: []
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build.py", description=__doc__.split("\n")[0])
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("list", help="what lessons exist").set_defaults(func=cmd_list)

    p = subs.add_parser("notebooks", help="regenerate every notebook")
    p.add_argument("--only", help="one lesson id")
    p.set_defaults(func=cmd_notebooks)

    subs.add_parser("check", help="fail if a committed notebook is stale").set_defaults(
        func=cmd_check
    )

    p = subs.add_parser("new", help="scaffold a new lesson")
    p.add_argument("id")
    p.set_defaults(func=cmd_new)

    p = subs.add_parser("run", help="execute notebooks from a cold kernel")
    p.add_argument("--only", help="one lesson id")
    p.add_argument("--include-e1", action="store_true", help="also run lessons marked E1")
    p.add_argument("--timeout", type=int, default=600, help="seconds per cell")
    p.set_defaults(func=cmd_run)

    subs.add_parser("diagrams", help="regenerate the diagrams").set_defaults(func=cmd_diagrams)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LessonError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
