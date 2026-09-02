#!/usr/bin/env python3
"""Where a lesson goes from the file you edit to the thing a reader opens."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.excalidraw import FONT_CODE, Scene  # noqa: E402

OUT = Path(__file__).resolve().parent / "build-pipeline"


def main() -> None:
    s = Scene(padding=40)

    # The main flow, left to right, one row.
    s.label("cap-a", 0, 46, "you edit this", size=12)
    s.box("src", 0, 100, 230, 78, "lessons/t04/\nlesson.py", "source", FONT_CODE, 15)

    s.box("build", 300, 100, 180, 78, "build.py\nnotebooks", "tool", FONT_CODE, 15)

    s.label("cap-c", 550, 46, "generated, never edited by hand", size=12)
    s.box("nb", 550, 100, 250, 78, "notebooks/t04/\nlesson.ipynb", "output", FONT_CODE, 15)

    s.label("cap-d", 870, 46, "what a reader clicks", size=12)
    s.box("colab", 870, 100, 200, 78, "Colab, from the\nbadge in the README", "external", size=15)

    s.arrow("a1", (230, 139), (295, 139))
    s.arrow("a2", (480, 139), (545, 139))
    s.arrow("a3", (800, 139), (865, 139))

    # The check, which is the whole reason the notebook can be committed safely.
    s.box("check", 300, 300, 180, 70, "build.py check", "tool", FONT_CODE, 15)
    s.path("c1", [(115, 178), (115, 335), (295, 335)])
    s.path("c2", [(675, 178), (675, 335), (485, 335)])
    s.label(
        "check-note",
        300,
        390,
        "Rebuilds the notebook in memory and compares bytes.\n"
        "Different means somebody edited the generated file, and CI fails.",
        size=13,
    )

    # The loop that makes prototyping in Colab safe.
    s.path(
        "loop",
        [(1030, 100), (1030, 10), (115, 10), (115, 96)],
        style="warn",
        dashed=True,
        label="found a bug in Colab? fix it in the .py, not in the notebook",
        label_at=(542, -18),
    )

    s.save(OUT, "How a lesson becomes a notebook a reader can open in Colab")


if __name__ == "__main__":
    main()
