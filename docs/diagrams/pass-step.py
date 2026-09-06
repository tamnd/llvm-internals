#!/usr/bin/env python3
"""What a pass does to a function, one instruction at a time.

The IR in here is real. It went through `opt -passes=dce -S` from the pinned
toolchain, and what comes out is the four lines the animation ends on. The
transcript is in the comment below so that a reader can run it themselves,
which is cheaper than trusting a picture.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "toolkit"))

from irxmanim import Box, Caption, Code, Scene, fade_in, fade_out, highlight, move  # noqa: E402
from irxmanim.mobject import LINE_H  # noqa: E402

OUT = Path(__file__).resolve().parent / "pass-step.svg"

# $ opt -passes=dce -S <<'EOF'
# define i32 @f(i32 %x) {
#   %a = add nsw i32 %x, 1
#   %b = mul nsw i32 %x, 7
#   ret i32 %a
# }
# EOF
# define i32 @f(i32 %x) {
#   %a = add nsw i32 %x, 1
#   ret i32 %a
# }
BEFORE = [
    "define i32 @f(i32 %x) {",
    "  %a = add nsw i32 %x, 1",
    "  %b = mul nsw i32 %x, 7",
    "  ret i32 %a",
    "}",
]
DEAD = 2


def build() -> Scene:
    s = Scene(430, 208, caption="opt -passes=dce deletes the instruction nothing reads")

    title = Caption(24, 20, text="opt -passes=dce", tone="loud")
    frame = Box(20, 48, w=390, h=100)
    code = Code(x=36, y=58, lines=BEFORE)
    asked = Caption(24, 162, text="nothing reads %b, so nothing needs it")
    done = Caption(24, 162, text="four instructions became three")
    s.add(title, frame, code, asked, done)

    s.play(fade_in(title), fade_in(frame))
    s.play(fade_in(code))
    s.play(highlight(code[DEAD]), fade_in(asked))
    s.play(fade_out(code[DEAD]), run_time=0.4)
    # The lines below the deleted one close up, which is the part of a pass
    # that a printed before and after cannot show you.
    s.play(
        move(code[3], dy=-LINE_H),
        move(code[4], dy=-LINE_H),
        fade_out(asked),
        run_time=0.5,
    )
    s.play(fade_in(done))
    return s


def main() -> None:
    s = build()
    OUT.write_text(s.svg() + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {s.duration:.1f}s, {len(s.script)} beats")


if __name__ == "__main__":
    main()
