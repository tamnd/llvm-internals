#!/usr/bin/env python3
"""What `irx.bootstrap()` does before a lesson can run a single command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.excalidraw import FONT_SANS, Scene  # noqa: E402

OUT = Path(__file__).resolve().parent / "bootstrap"

# Every source irx will try, in the order it tries them, with the reason it sits
# where it does. The order is the whole design, so it is the whole diagram.
SOURCES = [
    ("env", "IRX_LLVM_BIN", "you pointed at one yourself, so nothing else gets a vote", "source"),
    ("cache", "~/.cache/irx/<tag>/bin", "already unpacked from an earlier cell, so this is free", "output"),
    ("tree", "your llvm-project build tree", "E1 only, and it is the one you just built", "source"),
    ("system", "the LLVM already on PATH", "convenient, and quite often the wrong version", "external"),
    ("tarball", "the pinned tarball we publish", "the Colab path: one download, unpacked in seconds", "tool"),
    ("apt", "apt.llvm.org", "minutes rather than seconds, and only until the tarball exists", "warn"),
]

TOP = 90
STEP = 84
BOX_X, BOX_W, BOX_H = 40, 560, 64
SPINE = 640


def main() -> None:
    s = Scene(padding=40)

    s.label(
        "title",
        BOX_X,
        34,
        "irx.bootstrap() tries these in order and stops at the first one that answers",
        size=14,
    )

    for i, (key, name, why, style) in enumerate(SOURCES):
        y = TOP + i * STEP
        s.box(key, BOX_X, y, BOX_W, BOX_H, f"{name}\n{why}", style, FONT_SANS, 14)
        # The stub each source uses to join the bus. Short on purpose: the point
        # is that all six lead to the same place, not that any one of them is
        # special once it has answered.
        s.arrow(f"{key}-out", (BOX_X + BOX_W + 4, y + BOX_H / 2), (SPINE - 6, y + BOX_H / 2))

    last = TOP + (len(SOURCES) - 1) * STEP + BOX_H
    s.label("order", BOX_X, last + 26, "nothing there? fall through to the next one", size=13)

    # The bus, and then the check that makes all of this worth doing.
    s.path("bus", [(SPINE, TOP + BOX_H / 2), (SPINE, 640), (730, 640)])

    s.label(
        "why-order",
        740,
        TOP + 6,
        "The order is the design, not a preference.\n"
        "\n"
        "Cheap and certain first, slow and uncertain last, so the common case\n"
        "is a cache hit and nobody waits.\n"
        "\n"
        "Wrong major version is not the same as failure. A machine with some\n"
        "other LLVM already on PATH goes back to the list and carries on down\n"
        "it, and ends up downloading the pinned tarball. The one thing that\n"
        "does stop here is IRX_LLVM_BIN pointing at the wrong version, because\n"
        "somebody set that on purpose and deserves to be told.\n"
        "\n"
        "Whichever one answers, its name gets printed. If a bootstrap takes\n"
        "four minutes, the line above the lesson says apt.llvm.org and you\n"
        "know why, rather than guessing that Colab is slow today.",
        size=13,
    )

    s.box(
        "gate", 734, 608, 300, 64,
        "is this the major version\neverything is written against?",
        "tool", FONT_SANS, 14,
    )

    s.arrow("yes", (1038, 640), (1094, 640))
    s.label("yes-label", 1066, 612, "yes", size=12, align="center")
    s.box(
        "ready", 1098, 612, 360, 56,
        "irx: LLVM 23.1.0 from the pinned\ntarball, ready in 21.4s",
        "output", FONT_SANS, 13,
    )

    # "No" is two different situations and they get different answers, which is
    # the part of this that is easy to get wrong.
    s.path("no-keep", [(884, 676), (884, 706), (710, 706), (710, 736)], style="external")
    s.box(
        "keep", 560, 740, 300, 60,
        "back to the list, and try\nthe next source down",
        "external", FONT_SANS, 13,
    )
    s.label("no-keep-label", 590, 682, "no, and nobody asked for this one", size=12)

    s.path("no-stop", [(884, 676), (884, 706), (1050, 706), (1050, 736)], style="warn")
    s.box(
        "stop", 900, 740, 300, 60,
        "ToolchainError naming the version\nit found and how to fix it",
        "warn", FONT_SANS, 13,
    )
    s.label("no-stop-label", 908, 682, "no, but IRX_LLVM_BIN asked for it", size=12)

    s.label(
        "why-stop",
        560,
        820,
        "The split matters. A Colab box with somebody else's LLVM on PATH should go and fetch the right one,\n"
        "not refuse to start. A person who set IRX_LLVM_BIN by hand should hear about it, not be ignored.",
        size=13,
    )

    s.save(OUT, "How irx.bootstrap finds a pinned LLVM, and why it refuses the wrong one")


if __name__ == "__main__":
    main()
