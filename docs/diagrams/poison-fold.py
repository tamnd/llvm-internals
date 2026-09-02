#!/usr/bin/env python3
"""One input, two versions of the same function, and only one of them survives it.

The picture is the counterexample Alive2 finds in lesson X03, drawn as two
columns so the divergence is a place on the page rather than a paragraph.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.excalidraw import FONT_CODE, FONT_SANS, Scene  # noqa: E402

OUT = Path(__file__).resolve().parent / "poison-fold"

BOX_W, BOX_H = 300, 52
LEFT, RIGHT = 60, 460
ROWS = [140, 212, 284, 356]


def column(s, x, tag, head, rows, last_style):
    s.box(f"{tag}-head", x, 84, BOX_W, 40, head, "plain", FONT_SANS, 14)
    for i, (text, style) in enumerate(rows):
        style = last_style if i == len(rows) - 1 else style
        s.box(f"{tag}-{i}", x, ROWS[i], BOX_W, BOX_H, text, style, FONT_CODE, 13)
        if i:
            s.arrow(
                f"{tag}-a{i}",
                (x + BOX_W / 2, ROWS[i - 1] + BOX_H + 2),
                (x + BOX_W / 2, ROWS[i] - 4),
            )


def main() -> None:
    s = Scene(padding=40)

    s.label(
        "title",
        60,
        24,
        "both(a = 0, b = 32). Shifting a 32 bit value by 32 is poison in both versions.\n"
        "The question is what happens next, and the two versions disagree.",
        font=FONT_SANS,
        size=14,
    )

    shared = [
        ("%ok = icmp sgt i32 %a, 0\nfalse", "source"),
        ("%sh = shl i32 %a, %b\npoison", "warn"),
        ("%big = icmp sgt i32 %sh, 5\npoison", "warn"),
    ]

    column(
        s,
        LEFT,
        "src",
        "what you wrote",
        shared + [("%r = select i1 %ok, i1 %big, i1 false\nfalse", "output")],
        "output",
    )
    column(
        s,
        RIGHT,
        "tgt",
        "what your fold produced",
        shared + [("%r = and i1 %ok, %big\npoison", "warn")],
        "warn",
    )

    s.label(
        "src-note",
        60,
        424,
        "select only reads the arm the condition picked.\nThe condition is false, so the poison arm is never read.",
        font=FONT_SANS,
        size=13,
    )
    s.label(
        "tgt-note",
        460,
        424,
        "and reads both operands, every time.\nPoison in either one poisons the result.",
        style="warn",
        font=FONT_SANS,
        size=13,
    )

    # The refinement arrows, which are the point. One direction is a legal
    # rewrite and the other is not, and they are drawn as two separate arrows
    # so that nobody reads the pair as an equals sign.
    middle = (LEFT + RIGHT + BOX_W) / 2
    s.label(
        "ok-lab",
        middle,
        492,
        "replacing the and with the select would be a legal rewrite",
        style="output",
        font=FONT_SANS,
        size=13,
        align="center",
    )
    s.arrow("ok-way", (RIGHT + 40, 516), (LEFT + BOX_W - 40, 516), style="output")
    s.label(
        "bad-lab",
        middle,
        548,
        "replacing the select with the and is the one you did, and it is not",
        style="warn",
        font=FONT_SANS,
        size=13,
        align="center",
    )
    s.arrow(
        "bad-way", (LEFT + BOX_W - 40, 572), (RIGHT + 40, 572), style="warn", dashed=True
    )

    s.label(
        "rule",
        60,
        616,
        "A rewrite is allowed to take a poison result and make it defined. It is never allowed to go the other way.\n"
        "That is the whole rule, and it is why LLVM's own InstCombine refuses this fold unless it can prove the\n"
        "arm it is about to read was never going to be poison.",
        font=FONT_SANS,
        size=13,
    )

    s.save(OUT, "Why folding select into and is wrong when an arm can be poison")


if __name__ == "__main__":
    main()
