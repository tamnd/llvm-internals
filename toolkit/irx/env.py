"""Which of the three environments this code is running in.

E0  A notebook on somebody else's machine, almost always Colab. Root, two vCPUs,
    a pinned LLVM that arrived as a tarball, and no build tree. Most lessons.
E1  A local machine with a full llvm-project checkout and a build directory.
    Six lessons need this and they say so.
E2  A browser, meaning JupyterLite or Pyodide. No subprocesses at all, so this
    environment talks to Compiler Explorer's public API instead.

Lessons ask which one they are in so they can pick a strategy, not so they can
apologise. A lesson that cannot do the real thing here plays back a recording of
somebody doing it, and says that is what it is doing.
"""

from __future__ import annotations

import os
import shutil
import sys
from enum import Enum
from pathlib import Path


class Env(str, Enum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"

    def __str__(self) -> str:
        return self.value


def in_browser() -> bool:
    return sys.platform == "emscripten" or "pyodide" in sys.modules


def in_colab() -> bool:
    return "google.colab" in sys.modules or os.environ.get("COLAB_RELEASE_TAG") is not None


def build_tree() -> Path | None:
    """A full llvm-project build directory, if there is one.

    Checked in order: an explicit environment variable, then the two layouts
    people actually use. Nothing here searches the filesystem, because a tool
    that goes hunting for a 60 GB directory tree is a tool that hangs.
    """
    explicit = os.environ.get("LLVM_BUILD_DIR")
    if explicit:
        candidate = Path(explicit)
        return candidate if (candidate / "bin" / "opt").exists() else None

    for candidate in (
        Path.home() / "llvm-project" / "build",
        Path.home() / "src" / "llvm-project" / "build",
    ):
        if (candidate / "bin" / "opt").exists():
            return candidate
    return None


def detect() -> Env:
    if in_browser():
        return Env.E2
    if build_tree() is not None and not in_colab():
        return Env.E1
    return Env.E0


def describe() -> str:
    """One line a lesson can print so the reader knows where they are."""
    env = detect()
    if env is Env.E2:
        return "E2, a browser. No subprocesses here, so this runs against Compiler Explorer."
    if env is Env.E1:
        return f"E1, a local machine with a build tree at {build_tree()}."
    where = "Colab" if in_colab() else "a notebook without a build tree"
    return f"E0, {where}. Real LLVM binaries, no build tree, so no in tree modification."


def cpu_count() -> int:
    """How many cores we can actually use, which on Colab is not what os says."""
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        return os.cpu_count() or 1


def have(tool: str) -> bool:
    return shutil.which(tool) is not None
