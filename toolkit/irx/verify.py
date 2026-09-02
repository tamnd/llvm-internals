"""Asking a solver whether a transformation is correct, and showing what it said.

This is the one place where a lesson can stop saying "this looks right" and get
an answer. Alive2 takes two versions of a function, asks Z3 whether there is any
input where they disagree, and if there is, hands back that input. A reader who
has written a wrong fold gets the exact number that breaks it instead of a
review comment.

Two things about it are worth knowing before reading any further, because
overselling this tool would be worse than not having it:

Alive2 is bounded. It can come back with "correct", "here is a counterexample",
or "I ran out of time", and the third answer is common on anything wider than a
byte once division is involved. A timeout is not a pass. Every place this
module can tell the difference, it says which one happened rather than folding
the two into a boolean.

Alive2 also lives in its own toolchain. It refuses to build against an LLVM
without RTTI, and the `min` bundle has RTTI off because that is how everybody
ships LLVM and what every plugin in these lessons compiles against. So `alive`
is a second, smaller download that only the lessons needing it ever pull, and
`irx.alive` fetches it the first time somebody calls it.

The module is `irx.verify` and the function is `irx.alive`. The question is
verification and the tool that answers it is Alive2, and naming both of them the
same thing would mean `irx.alive` could not be the function a lesson calls.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .toolchain import CACHE, RELEASES, TAG, ToolchainError, platform_slug

# Alive2's own default, in milliseconds. Kept rather than raised, because a
# lesson that sits for two minutes and then times out anyway has spent the
# reader's attention on nothing.
SMT_MS = 10_000

SEPARATOR = re.compile(r"^-{10,}$")
ASSIGNMENT = re.compile(r"^(?P<decl>.+?) = (?P<value>.+)$")
DEFINE = re.compile(r"^define .*?@(?P<name>[\w.$-]+)\s*\(")

# Both of these can carry a parenthetical after them, and the one that matters
# is "(syntactically equal)", which means the pass left this function alone and
# the solver never had to think about it. Matched as a prefix so a new
# parenthetical upstream does not turn a verdict into an unparsed error.
CORRECT = "Transformation seems to be correct!"
WRONG = "Transformation doesn't verify!"
ASIDE = re.compile(r"\((?P<note>[^)]*)\)\s*$")

_bin: Path | None = None


class AliveError(RuntimeError):
    pass


# -- finding alive-tv --------------------------------------------------------


def _from_env() -> tuple[Path, str] | None:
    raw = os.environ.get("IRX_ALIVE_BIN")
    if raw and (Path(raw) / "alive-tv").exists():
        return Path(raw) / "alive-tv", "IRX_ALIVE_BIN"
    return None


def _from_cache() -> tuple[Path, str] | None:
    exe = CACHE / TAG / "alive" / "bin" / "alive-tv"
    return (exe, "the unpacked bundle in the cache") if exe.exists() else None


def _from_path() -> tuple[Path, str] | None:
    found = shutil.which("alive-tv")
    return (Path(found), f"alive-tv on PATH at {found}") if found else None


def _from_bundle(verbose: bool) -> tuple[Path, str] | None:
    name = f"alive-{TAG}-{platform_slug()}.tar.xz"
    url = f"{RELEASES}/toolchain-{TAG}/{name}"
    target = CACHE / TAG / "alive"
    archive = CACHE / name
    target.mkdir(parents=True, exist_ok=True)
    try:
        if verbose:
            print(f"irx: fetching {name}, the correctness bundle. This happens once.")
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
            archive.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    subprocess.run(
        ["tar", "-xf", str(archive), "-C", str(target), "--strip-components=1"], check=True
    )
    archive.unlink(missing_ok=True)
    exe = target / "bin" / "alive-tv"
    return (exe, "the pinned bundle") if exe.exists() else None


def find(verbose: bool = True) -> Path:
    """Where alive-tv is, fetching the bundle if this is the first time."""
    global _bin
    if _bin is not None:
        return _bin
    for finder in (_from_env, _from_cache, _from_path, lambda: _from_bundle(verbose)):
        found = finder()
        if found is None:
            continue
        _bin, source = found
        if verbose:
            print(f"irx: alive-tv from {source}")
        return _bin
    raise ToolchainError(
        "Could not find alive-tv and could not fetch the correctness bundle.\n"
        "\n"
        "  This is a separate download from the LLVM one, so a working `opt` does\n"
        "  not mean this will work. If you built Alive2 yourself, point at it:\n"
        "    export IRX_ALIVE_BIN=/path/to/alive2/build\n"
    )


def reset() -> None:
    """Forget where alive-tv was. Tests use this, lessons do not."""
    global _bin
    _bin = None


# -- what came back ----------------------------------------------------------


@dataclass
class Verdict:
    """One function, checked. `status` is the whole point of this class.

    It is one of `correct`, `wrong`, `timeout` or `error`, and only the first of
    those is good news. `timeout` in particular is not a quiet `correct`, it is
    the solver saying it does not know, and a reader who reads it as a pass has
    learned something false.
    """

    status: str
    function: str = ""
    kind: str = ""
    note: str = ""
    remarks: list[str] = field(default_factory=list)
    example: list[tuple[str, str]] = field(default_factory=list)
    source: list[tuple[str, str]] = field(default_factory=list)
    target: list[tuple[str, str]] = field(default_factory=list)
    src_ir: str = ""
    tgt_ir: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "correct"

    @property
    def untouched(self) -> bool:
        """The two versions are the same text, so nothing was proved about anything.

        Worth asking about before reading a tick as good news. A pass that did
        not fire always verifies, and a reader looking for their own pass in a
        pipeline needs to know the difference between "it is right" and "it did
        not run".
        """
        return self.note == "syntactically equal"

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.untouched:
            return f"{self.function}: unchanged, so there was nothing to check."
        head = {
            "correct": f"{self.function}: correct.",
            "wrong": f"{self.function}: wrong. {self.kind}.",
            "timeout": f"{self.function}: no answer, the solver ran out of time.",
            "error": f"{self.function}: Alive2 could not check this. {self.kind}",
        }[self.status]
        if self.status != "wrong":
            return head
        lines = [head, "", "  It breaks on:"]
        lines += [f"    {name} = {value}" for name, value in self.example]
        if self.source or self.target:
            lines += ["", "  Yours gives:"]
            lines += [f"    {name} = {value}" for name, value in self.target]
            lines += ["", "  It should give:"]
            lines += [f"    {name} = {value}" for name, value in self.source]
        lines += ["", *(f"  {remark}" for remark in self.remarks)]
        return "\n".join(lines).rstrip()

    def _repr_html_(self) -> str:
        return _card(self)


@dataclass
class Report:
    """Every function alive-tv looked at, plus the transcript it printed.

    A report is truthy when every function checked out. Index it to get one
    function back, because the lessons that use this mostly check one and want
    to reach straight for the counterexample.
    """

    verdicts: list[Verdict]
    raw: str
    seconds: float

    @property
    def ok(self) -> bool:
        return bool(self.verdicts) and all(v.ok for v in self.verdicts)

    @property
    def failed(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.ok]

    def __bool__(self) -> bool:
        return self.ok

    def __len__(self) -> int:
        return len(self.verdicts)

    def __iter__(self):
        return iter(self.verdicts)

    def __getitem__(self, index) -> Verdict:
        return self.verdicts[index]

    def __str__(self) -> str:
        if not self.verdicts:
            return f"alive-tv checked nothing in {self.seconds:.1f}s.\n\n{self.raw}"
        return "\n\n".join(str(v) for v in self.verdicts)

    def _repr_html_(self) -> str:
        if not self.verdicts:
            return f"<pre>{_escape(self.raw)}</pre>"
        return "".join(_card(v) for v in self.verdicts)


# -- reading the transcript --------------------------------------------------


def _pairs(lines: list[str]) -> list[tuple[str, str]]:
    """Turn `i32 %x = #xffffffff (4294967295, -1)` into a name and a value."""
    out = []
    for line in lines:
        hit = ASSIGNMENT.match(line.strip())
        if not hit:
            continue
        decl = hit.group("decl").split()
        out.append((decl[-1], hit.group("value").strip()))
    return out


def _blocks(raw: str) -> list[list[str]]:
    """Split the transcript into one chunk per transformation.

    alive-tv prints a rule of dashes before each one, so the first chunk is
    whatever it said before it started and the rest are the answers.
    """
    chunks: list[list[str]] = [[]]
    for line in raw.split("\n"):
        if SEPARATOR.match(line.strip()):
            chunks.append([])
            continue
        if line.startswith("Summary:"):
            break
        chunks[-1].append(line)
    return [chunk for chunk in chunks[1:] if any(line.strip() for line in chunk)]


def _one(chunk: list[str]) -> Verdict:
    src, tgt, verdict = [], [], None
    where = "src"
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in chunk:
        stripped = line.strip()
        if stripped == "=>" and where == "src":
            where = "tgt"
            continue
        if stripped.startswith(CORRECT) or stripped.startswith(WRONG):
            verdict = "correct" if stripped.startswith(CORRECT) else "wrong"
            aside = ASIDE.search(stripped)
            if aside:
                sections.setdefault("note", []).append(aside.group("note"))
            where = "after"
            continue
        if stripped.startswith("NOTE:"):
            # Asides alive-tv volunteers, the useful one being that the
            # counterexample it found is the only one there is.
            sections.setdefault("remark", []).append(stripped[len("NOTE:") :].strip())
            continue
        if stripped.startswith("ERROR:"):
            detail = stripped[len("ERROR:") :].strip()
            if verdict is None:
                verdict = "timeout" if detail.lower() == "timeout" else "error"
            sections.setdefault("kind", []).append(detail)
            where = "after"
            continue

        if where == "src":
            src.append(line)
        elif where == "tgt":
            tgt.append(line)
        elif stripped.endswith(":") and stripped[:-1] in ("Example", "Source", "Target"):
            current = stripped[:-1].lower()
            sections.setdefault(current, [])
        elif current and stripped:
            sections[current].append(line)
        elif not stripped:
            current = None

    name = ""
    for line in src:
        hit = DEFINE.match(line.strip())
        if hit:
            name = hit.group("name")
            break

    kinds = sections.get("kind", [])
    notes = sections.get("note", [])
    return Verdict(
        status=verdict or "error",
        function=name,
        kind=kinds[0] if kinds else "",
        note=notes[0] if notes else "",
        remarks=sections.get("remark", []),
        example=_pairs(sections.get("example", [])),
        source=_pairs(sections.get("source", [])),
        target=_pairs(sections.get("target", [])),
        src_ir="\n".join(src).strip(),
        tgt_ir="\n".join(tgt).strip(),
    )


def parse(raw: str, seconds: float = 0.0) -> Report:
    return Report([_one(chunk) for chunk in _blocks(raw)], raw, seconds)


# -- the call ----------------------------------------------------------------


def alive(
    before: str,
    after: str | None = None,
    *,
    smt_seconds: float = SMT_MS / 1000,
    timeout: int = 300,
    verbose: bool = True,
) -> Report:
    """Ask whether `after` does the same thing as `before`, for every input.

        irx.alive(before, after)     two modules, matched up by function name
        irx.alive(text)              one module holding @src and @tgt

    The first form is the one a lesson uses after running its own pass, because
    the two modules are exactly what went into `opt` and what came out. The
    second is the older Alive style and is handy for trying a fold out before
    writing any C++ at all.

    A `Report` that is false means either a counterexample or a timeout, and
    those are different things. Print it and it says which.
    """
    exe = find(verbose=verbose)
    with tempfile.TemporaryDirectory(prefix="irx-alive-") as work:
        root = Path(work)
        src = root / "before.ll"
        src.write_text(before, encoding="utf-8")
        argv = [str(exe), f"--smt-to={int(smt_seconds * 1000)}", str(src)]
        if after is not None:
            tgt = root / "after.ll"
            tgt.write_text(after, encoding="utf-8")
            argv.append(str(tgt))

        start = time.monotonic()
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AliveError(
                f"alive-tv did not come back within {timeout} seconds, which is longer\n"
                f"than the {smt_seconds:g} second budget it was given for the solver.\n"
                "That usually means the module is much bigger than one function."
            ) from None
        elapsed = time.monotonic() - start

    if done.returncode < 0:
        raise AliveError(
            f"alive-tv was killed by signal {-done.returncode}.\n"
            "\n"
            "  This is a crash in the tool, not a verdict about your IR. If the IR\n"
            "  parses under `opt`, it is worth reporting.\n"
        )
    report = parse(done.stdout + done.stderr, elapsed)
    if not report.verdicts:
        raise AliveError(
            "alive-tv did not check anything.\n"
            "\n"
            "  It pairs functions by name, so two modules with no name in common\n"
            "  give it nothing to do. Its output was:\n"
            "\n" + "\n".join("  " + line for line in (done.stdout + done.stderr).split("\n"))
        )
    return report


# -- the card ----------------------------------------------------------------

TINT = {
    "correct": ("#1a7f37", "#e6ffec", "Correct"),
    "wrong": ("#cf222e", "#ffebe9", "Wrong"),
    "timeout": ("#9a6700", "#fff8c5", "No answer"),
    "error": ("#57606a", "#f6f8fa", "Could not check"),
}

HEAD = {
    "correct": "No input makes these two disagree.",
    "wrong": "There is an input where these two disagree.",
    "timeout": "The solver ran out of time. This is not a pass, it is a shrug.",
    "error": "Alive2 could not check this one.",
}


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rows(pairs: list[tuple[str, str]]) -> str:
    return "".join(
        f'<tr><td style="padding:1px 10px 1px 0;color:#57606a">{_escape(name)}</td>'
        f'<td style="padding:1px 0"><code>{_escape(value)}</code></td></tr>'
        for name, value in pairs
    )


def _card(v: Verdict) -> str:
    colour, wash, word = TINT[v.status]
    head = HEAD[v.status]
    if v.kind and v.status in ("wrong", "error"):
        head += f" {_escape(v.kind)}."
    if v.untouched:
        colour, wash, word = "#57606a", "#f6f8fa", "Unchanged"
        head = "The two versions are the same text, so nothing was checked."

    body = ""
    if v.example:
        body += (
            '<div style="padding:8px 14px 0 14px">'
            '<div style="color:#57606a;font-size:12px;margin-bottom:3px">It breaks on</div>'
            f'<table style="border-collapse:collapse;font-size:12.5px">{_rows(v.example)}</table>'
            "</div>"
        )
    if v.target or v.source:
        body += (
            '<div style="display:flex;gap:22px;padding:8px 14px 0 14px;flex-wrap:wrap">'
            '<div><div style="color:#57606a;font-size:12px;margin-bottom:3px">'
            "Your version gives</div>"
            f'<table style="border-collapse:collapse;font-size:12.5px">{_rows(v.target)}</table>'
            "</div>"
            '<div><div style="color:#57606a;font-size:12px;margin-bottom:3px">'
            "It should give</div>"
            f'<table style="border-collapse:collapse;font-size:12.5px">{_rows(v.source)}</table>'
            "</div></div>"
        )

    for remark in v.remarks:
        body += (
            '<div style="padding:8px 14px 0 14px;color:#57606a;font-size:12px">'
            f"{_escape(remark)}</div>"
        )

    return (
        f'<div style="border:1px solid #d0d7de;border-left:4px solid {colour};border-radius:6px;'
        "margin:6px 0;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;"
        'font-size:13.5px;color:#24292f;max-width:100%">'
        f'<div style="background:{wash};padding:7px 14px;border-radius:2px 6px 0 0">'
        f'<b style="color:{colour}">{word}</b>'
        f'<span style="color:#57606a"> &nbsp;{_escape(v.function)}</span>'
        f'<div style="margin-top:2px;line-height:1.4">{head}</div></div>'
        f"{body}"
        '<div style="height:10px"></div></div>'
    )


__all__ = ["AliveError", "Report", "Verdict", "alive", "find", "parse", "reset"]
