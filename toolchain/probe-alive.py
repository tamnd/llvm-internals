#!/usr/bin/env python3
"""Time Alive2 over the passes the lessons are going to verify.

The question this answers is not "does Alive2 work". It is "does Alive2 come
back inside a reader's patience, for the passes and the sizes of function the
lessons actually use". Those are different questions and the second one is the
one that decides which lessons can exist.

    PYTHONPATH=toolkit python3 toolchain/probe-alive.py

Prints a markdown table, so the output goes straight into docs/probes/alive.md
without anybody retyping a number.
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from datetime import date

import irx
from irx import verify

# Small on purpose. A lesson shows a function that fits on a screen, so timing
# something bigger would answer a question nobody in a lesson is asking.
SOURCES = {
    "half": "int half(int x) { return x / 2; }",
    "twice": "int twice(int *p) { int a = *p; int b = *p; return a + b; }",
    "abs": "int myabs(int x) { return x < 0 ? -x : x; }",
    "clamp": "int clamp(int x) { if (x < 0) return 0; if (x > 255) return 255; return x; }",
    "sum": "int sum(int n) { int t = 0; for (int i = 0; i < n; i++) t += i; return t; }",
    "swap": "void swap(int *a, int *b) { int t = *a; *a = *b; *b = t; }",
}

PASSES = [
    "instcombine",
    "instsimplify",
    "reassociate",
    "early-cse",
    "gvn",
    "sccp",
    "simplifycfg",
    "adce",
    "licm",
    "indvars",
]

# The pass that has to run first, so the baseline is SSA rather than a pile of
# allocas. Verifying stack traffic is a different and much slower question.
BASELINE = "mem2reg"

REPEATS = 3

# The second half of the probe. Halving a signed number by shifting is the fold
# everybody writes on their first day, and the fix for it is three instructions,
# so the pair is small enough that any difference in timing is the solver's
# opinion of the problem rather than the size of the input.
WIDTHS = [8, 16, 32, 64]

SDIV = "define i{w} @half(i{w} %x) {{\n  %r = sdiv i{w} %x, 2\n  ret i{w} %r\n}}\n"
SHIFT = "define i{w} @half(i{w} %x) {{\n  %r = ashr i{w} %x, 1\n  ret i{w} %r\n}}\n"
ROUNDED = (
    "define i{w} @half(i{w} %x) {{\n"
    "  %sign = lshr i{w} %x, {top}\n"
    "  %bump = add i{w} %x, %sign\n"
    "  %r = ashr i{w} %bump, 1\n"
    "  ret i{w} %r\n"
    "}}\n"
)


def baseline(source: str) -> str:
    return irx.Module.from_c(source).opt(BASELINE, quiet=True).text


def timed(before: str, after: str) -> tuple[str, float]:
    runs, verdict = [], "nothing checked"
    for _ in range(REPEATS):
        start = time.monotonic()
        report = verify.alive(before, after, verbose=False)
        runs.append(time.monotonic() - start)
        if len(report):
            verdict = "unchanged" if report[0].untouched else report[0].status
    return verdict, statistics.median(runs)


def main() -> int:
    irx.bootstrap(verbose=False)
    verify.find(verbose=False)

    rows = []
    for name, source in SOURCES.items():
        before = baseline(source)
        for pass_name in PASSES:
            # Whether the pass did anything is alive-tv's call and not a text
            # comparison here. opt rewrites the module header either way, so the
            # two files differ even when the function does not.
            after = irx.run("opt", f"-passes={pass_name}", "-S", "-", stdin=before).stdout
            rows.append((name, pass_name, *timed(before, after)))

    print(f"Measured {date.today().isoformat()} on {platform.platform()},")
    print(f"LLVM {irx.current().version}, alive-tv at {verify.find(verbose=False)}.")
    print()
    print("| function | pass | verdict | median of 3 |")
    print("|---|---|---|---|")
    for name, pass_name, verdict, seconds in rows:
        shown = "" if verdict == "unchanged" else f"{seconds:.2f}s"
        print(f"| {name} | {pass_name} | {verdict} | {shown} |")

    checked = [seconds for _, _, verdict, seconds in rows if verdict != "unchanged"]
    print()
    print(f"{len(checked)} of {len(rows)} pairs had a change to check.")
    if checked:
        print(f"Slowest {max(checked):.2f}s, median {statistics.median(checked):.2f}s.")

    print()
    print("| width | fold | verdict | median of 3 |")
    print("|---|---|---|---|")
    for width in WIDTHS:
        before = SDIV.format(w=width)
        for label, template in [("shift", SHIFT), ("shift with rounding", ROUNDED)]:
            after = template.format(w=width, top=width - 1)
            verdict, seconds = timed(before, after)
            print(f"| i{width} | {label} | {verdict} | {seconds:.2f}s |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
