"""irx, the small amount of Python that sits between a lesson and real LLVM.

The rule this package follows is that it never does LLVM's job. It does not
parse IR, it does not model a pass, and it does not reimplement anything you
could ask a binary for. It finds a pinned toolchain, runs it, and shows you what
came back in a form that reads well in a notebook. When upstream changes
something, the lesson output changes with it, which is exactly what should
happen.

The usual first cell of a lesson is this:

    import irx
    irx.bootstrap()

and after that:

    m = irx.Module.from_c("int f(int x) { return x + x; }")
    m                                  # renders, coloured
    after = m.opt("instcombine")
    m.diff(after)                      # renders the change, coloured
"""

from __future__ import annotations

from . import env as _env
from .env import Env, cpu_count, describe, detect
from .ir import Diff, Module, has_pass, highlight, passes
from .proc import Result, ToolError, run, version
from .toolchain import Toolchain, ToolchainError, current, path_to
from .toolchain import bootstrap as _bootstrap

__version__ = "0.1.0"

__all__ = [
    "Diff",
    "Env",
    "Module",
    "Result",
    "ToolError",
    "Toolchain",
    "ToolchainError",
    "bootstrap",
    "compile_c",
    "cpu_count",
    "current",
    "describe",
    "detect",
    "has_pass",
    "highlight",
    "passes",
    "path_to",
    "run",
    "version",
    "where",
]


def bootstrap(verbose: bool = True) -> Toolchain:
    """Get a pinned LLVM ready and say where it came from.

    Safe to call twice. The second call is free, so a lesson does not have to be
    careful about which cell a reader ran first.
    """
    return _bootstrap(verbose=verbose)


def compile_c(source: str, **kwargs) -> Module:
    """Shorthand for `Module.from_c`, because lessons type it a lot."""
    return Module.from_c(source, **kwargs)


def where() -> str:
    """One line covering both questions: which environment, and which LLVM."""
    return f"{_env.describe()} {current()}."
