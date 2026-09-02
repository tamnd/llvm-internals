#!/usr/bin/env python3
"""Two ways to write an LLVM pass, and why every lesson here uses the second."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.excalidraw import FONT_CODE, FONT_SANS, Scene  # noqa: E402

OUT = Path(__file__).resolve().parent / "pass-plugin"

BOX_W, BOX_H, GAP = 250, 80, 60
COLUMN = [40 + i * (BOX_W + GAP) for i in range(4)]


def row(s, y, items, style):
    for x, (key, text, font) in zip(COLUMN, items):
        s.box(key, x, y, BOX_W, BOX_H, text, style, font, 13)
    for i in range(3):
        s.arrow(f"{items[i][0]}-a", (COLUMN[i] + BOX_W + 4, y + BOX_H / 2), (COLUMN[i + 1] - 6, y + BOX_H / 2))


def main() -> None:
    s = Scene(padding=40)

    s.label(
        "title",
        40,
        24,
        "Both of these compile exactly the same PassInfoMixin class. The only difference is who compiles it.",
        size=14,
    )

    # The way the LLVM documentation describes, which is correct and useless here.
    s.label("in-cap", 40, 74, "in tree, the way you would do it to contribute to LLVM", size=13)
    row(
        s,
        110,
        [
            ("clone", "git clone llvm-project\n1.5 GB of source", FONT_SANS),
            ("edit", "drop your pass in, and edit\nthree CMakeLists files", FONT_SANS),
            ("ninja", "cmake and ninja\nabout an hour, about 30 GB", FONT_SANS),
            ("useit", "build/bin/opt\n-passes=yours", FONT_CODE),
        ],
        "external",
    )
    s.label(
        "in-note",
        40,
        206,
        "Needs a real machine and an afternoon. This is the right way to send a patch upstream, and it does not fit in a notebook.",
        size=13,
    )

    # The way that fits in a cell.
    s.label("out-cap", 40, 288, "out of tree, the way every lesson here does it", size=13)
    row(
        s,
        324,
        [
            ("cell", "%%irxplug count\nyour C++, in one cell", FONT_CODE),
            ("cxx", "clang++ -shared -fPIC\nflags from llvm-config", FONT_CODE),
            ("so", "count-4d46e29.dylib\ncached on the source hash", FONT_CODE),
            ("opt", "opt -load-pass-plugin=...\n-passes=count", FONT_CODE),
        ],
        "tool",
    )

    # The numbers, which are the entire argument, so they sit under the arrows.
    for key, x, text in (
        ("t1", COLUMN[0] + BOX_W + GAP / 2, "2.0 s"),
        ("t2", COLUMN[1] + BOX_W + GAP / 2, "0 s if the\ncell is the same"),
        ("t3", COLUMN[2] + BOX_W + GAP / 2, "0.12 s"),
    ):
        s.label(f"time-{key}", x, 416, text, style="warn", size=12, align="center")

    s.box(
        "out", COLUMN[3], 476, BOX_W, 44,
        "count: f has 13 instructions", "output", FONT_CODE, 13,
    )
    s.arrow("to-out", (COLUMN[3] + BOX_W / 2, 408), (COLUMN[3] + BOX_W / 2, 472))

    s.label(
        "out-note",
        40,
        476,
        "No build tree, no CMake, nothing installed beyond the toolchain that was already there.\n"
        "The plugin does not link against LLVM. Its symbols are already inside opt, and they get\n"
        "resolved when opt opens the file, which is why this is seconds rather than an hour.",
        size=13,
    )

    s.save(OUT, "Building an LLVM pass in tree versus as an out of tree plugin")


if __name__ == "__main__":
    main()
