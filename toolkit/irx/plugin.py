"""Compiling a real LLVM pass, in a notebook cell, in a few seconds.

This is the piece that decides how much of this project is possible. Building
LLVM from source is an hour and 30 GB, so if writing a pass meant doing that,
then every lesson about writing passes would need a machine nobody reading in a
browser tab has. An out of tree plugin needs neither. It is one C++ file
compiled against installed headers, and `opt` loads it at run time with
`-load-pass-plugin`.

On this laptop that compile is a shade over two seconds. That number is the
whole argument, and it is why the toolchain we ship keeps its headers and builds
LLVM as one shared library rather than statically linking every tool.

What this module adds on top of a compiler call is caching and error messages. A
reader edits a cell and runs it again perhaps thirty times in a lesson, and only
the runs where the source actually changed should cost anything.
"""

from __future__ import annotations

import hashlib
import platform
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from . import toolchain
from .proc import run

# Beside the toolchain rather than in the working directory, so that a reader
# who reruns a notebook from the top does not recompile everything, and so that
# nothing ends up committed by accident.
DIRECTORY = toolchain.CACHE / "plugins"


@dataclass
class Plugin:
    name: str
    path: Path
    source: str
    seconds: float
    cached: bool

    def __str__(self) -> str:
        if self.cached:
            return f"plugin '{self.name}' was already built, so this was free"
        return f"plugin '{self.name}' compiled in {self.seconds:.1f}s"


_registry: dict[str, Plugin] = {}


def suffix() -> str:
    """What a loadable module is called here. macOS cares, Linux does not."""
    return ".dylib" if platform.system() == "Darwin" else ".so"


def link_flags() -> list[str]:
    """Extra flags needed to leave LLVM's symbols undefined until load time.

    A plugin does not link against LLVM. The symbols it needs are already in
    `opt`, and they get resolved when `opt` dlopens the file. ELF is happy with
    that by default. Mach-O is not, and needs to be told.
    """
    if platform.system() == "Darwin":
        return ["-Wl,-undefined,dynamic_lookup"]
    return []


def cxxflags() -> list[str]:
    """The compile flags for this exact LLVM, asked for rather than guessed.

    This matters more than it looks. A plugin has to agree with the LLVM that
    loads it about RTTI, exceptions and the C++ standard, and getting one of
    those wrong produces a link error or, worse, a crash on load. `llvm-config`
    knows how its own LLVM was built, so it gets asked.
    """
    return shlex.split(run("llvm-config", "--cxxflags").stdout.strip())


def _key(source: str, flags: list[str]) -> str:
    material = "\x00".join([source, toolchain.current().version, *flags])
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def build(
    name: str,
    source: str,
    extra: tuple[str, ...] = (),
    verbose: bool = True,
    force: bool = False,
) -> Plugin:
    """Compile one C++ file into a loadable pass plugin, and remember it.

    The cache key covers the source, the LLVM version and the flags, so editing
    a cell rebuilds and rerunning an unchanged cell does not.
    """
    flags = [*cxxflags(), *extra]
    path = DIRECTORY / f"{name}-{_key(source, flags)}{suffix()}"
    DIRECTORY.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        plugin = Plugin(name, path, source, 0.0, cached=True)
    else:
        cpp = path.with_suffix(".cpp")
        cpp.write_text(source, encoding="utf-8")
        start = time.monotonic()
        run("clang++", "-shared", "-fPIC", "-o", path, cpp, *flags, *link_flags(), timeout=300)
        plugin = Plugin(name, path, source, time.monotonic() - start, cached=False)

    _registry[name] = plugin
    if verbose:
        print(f"irx: {plugin}")
    return plugin


def registered() -> list[Plugin]:
    return list(_registry.values())


def load_flags() -> list[str]:
    """What to hand `opt` so every plugin built in this session is available."""
    return [f"-load-pass-plugin={p.path}" for p in _registry.values()]


def get(name: str) -> Plugin:
    if name not in _registry:
        known = ", ".join(sorted(_registry)) or "none yet"
        raise KeyError(
            f"No plugin called {name!r} has been built in this session. Built so far: {known}. "
            "A kernel restart clears this, and the cell with %%irxplug in it has to run again."
        )
    return _registry[name]


def forget(name: str | None = None) -> None:
    """Drop one plugin or all of them. Tests use this, lessons do not."""
    if name is None:
        _registry.clear()
    else:
        _registry.pop(name, None)
