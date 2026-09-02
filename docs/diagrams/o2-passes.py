#!/usr/bin/env python3
"""Every pass `-O2` runs on a five line function, and the sixteen that did anything.

The numbers are not typed in. They come from `o2-passes.json`, which is written
by this same script on a machine that has the pinned LLVM:

    python3 docs/diagrams/o2-passes.py --measure

Rerunning that on a different host gives a slightly different total, because the
pipeline depends on the target, so the file records which machine and which
LLVM produced it and the caption says so too.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.excalidraw import FONT_CODE, FONT_SANS, Scene  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "o2-passes"
DATA = HERE / "o2-passes.json"

SOURCE = """int gauss(int n) {
  int total = 0;
  for (int i = 0; i < n; i++)
    total += i;
  return total;
}
"""

# The same function with the loop taken out, so the caption can say what the
# loop is worth in passes rather than asserting that loops cost something.
PLAIN = """int twice(int *p) {
  int a = *p;
  int b = *p;
  return a + b;
}
"""

# One tick per pass. Narrow enough that a hundred of them fit on a line and you
# read the row as a quantity rather than counting it.
PITCH, TICK_W, TICK_H = 9.0, 5.0, 26.0
# A pass that did something gets a taller tick as well as a different colour, so
# the sixteen are still findable in a printout with no colour in it.
LIFT = 10.0
LEFT, TOP = 40.0, 118.0


def measure() -> dict:
    """Run the pipeline for real and write down what happened."""
    import irx

    irx.bootstrap(verbose=False)
    loop = irx.compile_c(SOURCE).tape("default<O2>")
    plain = irx.compile_c(PLAIN).tape("default<O2>")

    changed = []
    seen = 0
    for step in loop.changed:
        # A pass that deleted what it was running on changed the module and left
        # no dump, so there is no line count to report for it and the deltas
        # list is shorter than this one.
        if step.invalidated:
            changed.append({"index": step.index, "name": step.short, "delta": None})
        else:
            changed.append(
                {"index": step.index, "name": step.short, "delta": loop.deltas()[seen]}
            )
            seen += 1

    return {
        "llvm": irx.version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "pipeline": loop.pipeline,
        "loop": {"total": len(loop.steps), "changed": changed},
        "plain": {"total": len(plain.steps), "changed": len(plain.changed)},
    }


def draw(data: dict) -> None:
    loop = data["loop"]
    total = loop["total"]
    hits = {entry["index"]: entry for entry in loop["changed"]}

    s = Scene(padding=40)
    width = total * PITCH

    s.label(
        "title",
        LEFT,
        24,
        f"{total} passes run when you type -O2 on a five line loop. "
        f"{len(hits)} of them change the IR.",
        size=15,
        font=FONT_SANS,
    )
    s.label(
        "sub",
        LEFT,
        52,
        "One tick per pass, left to right, in the order they ran.",
        size=13,
        font=FONT_SANS,
    )

    for i in range(1, total + 1):
        x = LEFT + (i - 1) * PITCH
        entry = hits.get(i)
        if entry is None:
            s.box(f"p{i}", x, TOP, TICK_W, TICK_H, "", "external", radius=0)
        elif entry["delta"] is None:
            # The one that changed the module and printed nothing. It gets its
            # own colour because the whole second half of the lesson is about it.
            s.box(f"p{i}", x, TOP - LIFT, TICK_W, TICK_H + LIFT, "", "warn", radius=0)
        else:
            s.box(f"p{i}", x, TOP - LIFT, TICK_W, TICK_H + LIFT, "", "tool", radius=0)

    # The sixteen get a number above the tick and a line in the legend, because
    # labelling them in place would put sixteen captions inside 1000 pixels.
    # Neighbours like 44 and 45 are 9 pixels apart, so every other one sits a
    # line higher rather than running into the one before it.
    previous = -99
    high = False
    for entry in loop["changed"]:
        index = entry["index"]
        x = LEFT + (index - 1) * PITCH + TICK_W / 2
        high = not high if index - previous < 2 else False
        previous = index
        y = TOP - LIFT - (30 if high else 16)
        s.label(f"n{index}", x, y, str(index), size=11, align="center")

    s.label("axis-a", LEFT, TOP + TICK_H + 8, "first pass", size=12)
    s.label("axis-b", LEFT + width, TOP + TICK_H + 8, "last pass", size=12, align="right")

    legend_top = TOP + TICK_H + 62
    s.label("legend-h", LEFT, legend_top - 24, "the ones that did something", size=13, font=FONT_SANS)
    for row, entry in enumerate(loop["changed"]):
        delta = entry["delta"]
        if delta is None:
            change = "deleted the loop, no dump"
        elif delta == 0:
            change = "same length"
        else:
            change = f"{delta:+d} line" if abs(delta) == 1 else f"{delta:+d} lines"
        s.label(
            f"l{entry['index']}",
            LEFT,
            legend_top + row * 20,
            f"{entry['index']:>4}  {entry['name']:<26} {change}",
            size=13,
            font=FONT_CODE,
            style="warn" if delta is None else "plain",
        )

    tail = legend_top + len(loop["changed"]) * 20 + 18
    s.label(
        "note",
        LEFT,
        tail,
        "The orange one is the pass that removed the loop, and it is the only one with nothing to\n"
        "show you. opt prints the IR after a pass by asking the loop it just ran on to print itself,\n"
        "and by then there was no loop. It writes one line instead and no IR at all.",
        size=13,
        font=FONT_SANS,
    )
    s.label(
        "note2",
        LEFT,
        tail + 66,
        "Look at the pass before it. IndVarSimplify made the function five lines longer, which is\n"
        "the opposite of what an optimiser is supposed to do, and it is what made the deletion\n"
        "possible. Getting shorter is not the same thing as making progress.",
        size=13,
        font=FONT_SANS,
    )
    s.label(
        "note3",
        LEFT,
        tail + 132,
        "The grey ticks are not wasted work either. Most of them are a pass looking for a pattern\n"
        "that is not in this function, and the same pipeline has to be right for five lines and for\n"
        f"five thousand. Take the loop out and it drops to {data['plain']['total']} passes with "
        f"{data['plain']['changed']} changes.",
        size=13,
        font=FONT_SANS,
    )
    s.label(
        "prov",
        LEFT,
        tail + 198,
        f"Measured with {data['llvm']} on {data['machine']}, pipeline {data['pipeline']}.",
        size=12,
        style="warn",
    )

    s.save(OUT, f"A row of {total} ticks, one per pass, with {len(hits)} of them highlighted")


def main() -> None:
    if "--measure" in sys.argv:
        DATA.write_text(json.dumps(measure(), indent=2) + "\n", encoding="utf-8")
        print(f"diagram: measured, wrote {DATA.name}")
    draw(json.loads(DATA.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
