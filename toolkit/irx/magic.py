"""`%%irxplug`, the cell magic that turns a cell of C++ into a working pass.

A lesson about writing a pass should look like writing a pass. Not like writing
a pass, then a CMakeLists, then a shell command with eleven flags in it, then
remembering where the shared object landed. So the cell is the source, the magic
is the build, and the pass is available to `opt` on the next line:

    %%irxplug count
    #include "llvm/IR/PassManager.h"
    ...

    m.opt("count")

Registration is quiet and optional. Importing `irx` outside IPython does nothing
here, which matters because the same package runs under plain `python3` in tests
and in CI.
"""

from __future__ import annotations

import shlex

from . import plugin

USAGE = "usage: %%irxplug <name> [--force] [extra clang++ flags]"


def irxplug(line: str, cell: str) -> None:
    """Compile the cell as an out of tree pass plugin called <name>."""
    args = shlex.split(line)
    if not args:
        raise ValueError(USAGE)

    name, *rest = args
    if name.startswith("-"):
        raise ValueError(f"The first thing after %%irxplug is the plugin's name. {USAGE}")

    force = "--force" in rest
    extra = tuple(a for a in rest if a != "--force")

    built = plugin.build(name, cell, extra=extra, force=force)
    if not built.cached:
        # Said once, after the build that cost something, because this is the
        # number the whole design rests on and a reader should see it rather
        # than take our word for it.
        print(f"irx: `opt` will load it as {built.path.name}, and `{name}` is now a pass name")


def register(shell=None) -> bool:
    """Make the magic available. Returns whether there was a shell to register with."""
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    shell = shell or get_ipython()
    if shell is None:
        return False
    shell.register_magic_function(irxplug, magic_kind="cell", magic_name="irxplug")
    return True


def load_ipython_extension(shell) -> None:
    """So that `%load_ext irx` works for anybody who prefers to be explicit."""
    register(shell)
