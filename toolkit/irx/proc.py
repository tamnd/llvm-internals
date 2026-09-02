"""Running LLVM's binaries and saying something useful when they fail.

Everything this toolkit does goes through here. Nothing links against LLVM, and
nothing reimplements a piece of it in Python. A lesson that shows you `opt`
output is showing you what `opt` printed, which is the only way the material
stays true when upstream changes something.

The error type exists because the default subprocess failure is useless in a
notebook. `CalledProcessError: returned non-zero exit status 1` tells a reader
nothing, and the reader is a person who has never run this tool before.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import toolchain

DEFAULT_TIMEOUT = 120


class ToolError(RuntimeError):
    """An LLVM tool exited non zero, with the detail a reader needs to act."""

    def __init__(self, result: "Result") -> None:
        self.result = result
        lines = [
            f"{result.tool} exited {result.code}",
            "",
            f"  $ {result.command}",
            "",
        ]
        if result.stderr.strip():
            lines.append(indent(result.stderr.strip(), "  "))
        elif result.stdout.strip():
            lines.append(indent(result.stdout.strip(), "  "))
        else:
            lines.append("  It printed nothing, which usually means it crashed.")
        hint = hint_for(result)
        if hint:
            lines += ["", hint]
        super().__init__("\n".join(lines))


@dataclass
class Result:
    tool: str
    argv: list[str]
    code: int
    stdout: str
    stderr: str
    seconds: float

    @property
    def command(self) -> str:
        return " ".join(shlex.quote(a) for a in self.argv)

    @property
    def ok(self) -> bool:
        return self.code == 0


def indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.split("\n"))


def hint_for(result: Result) -> str:
    """Turn the failures readers actually hit into a sentence they can use."""
    text = (result.stderr + result.stdout).lower()
    if "unknown pass name" in text:
        return (
            "That pass name is not in this build. Pass names are case sensitive and\n"
            "several changed spelling between releases. `irx.passes()` lists what\n"
            "this exact binary accepts."
        )
    if "expected instruction opcode" in text or "expected top-level entity" in text:
        return (
            "This is a parse error in your IR, not a bug in the pass. The line and\n"
            "column above are `llvm-as` reading your text, and it is strict about\n"
            "type annotations in particular."
        )
    if "llvm/passes/passplugin.h" in text and "not found" in text:
        return (
            "That header moved. It is `llvm/Plugins/PassPlugin.h` now, not\n"
            "`llvm/Passes/PassPlugin.h`. Nearly every pass plugin tutorial online\n"
            "predates the move, so this is the first error most people hit."
        )
    if "llvm/ir/passmanager.h" in text and "not found" in text:
        return (
            "This LLVM has the tools but not the headers, so there is nothing to\n"
            "compile a plugin against. On Debian and Ubuntu the headers are in the\n"
            "separate `llvm-N-dev` package. `llvm-config --includedir` will happily\n"
            "name a directory that does not exist, so the flags look right."
        )
    if "undefined symbol" in text and "-load-pass-plugin" in result.command:
        return (
            "The plugin loaded but wants a symbol this `opt` does not have. That\n"
            "is almost always an RTTI or C++ standard mismatch between the plugin\n"
            "and LLVM. `irx.plugin.cxxflags()` shows what llvm-config asked for."
        )
    if "no such file" in text and "-load-pass-plugin" in result.command:
        return (
            "The plugin file is not where the command says it is. `%%irxplug`\n"
            "writes it under the cache directory, so this usually means the compile\n"
            "in an earlier cell failed and you are running a stale command."
        )
    return ""


def run(
    tool: str,
    *args: str | Path,
    stdin: str | None = None,
    check: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> Result:
    """Run one LLVM tool. `tool` is a bare name like `opt`, resolved against the pin."""
    argv = [str(toolchain.path_to(tool)), *(str(a) for a in args)]
    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        result = Result(tool, argv, 124, "", f"timed out after {timeout} seconds", elapsed)
        raise ToolError(result) from None

    result = Result(
        tool=tool,
        argv=argv,
        code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        seconds=time.monotonic() - start,
    )
    if check and not result.ok:
        raise ToolError(result)
    return result


def version() -> str:
    """The version string of the toolchain we are actually using."""
    return run("opt", "--version").stdout.split("\n")[0].strip()
