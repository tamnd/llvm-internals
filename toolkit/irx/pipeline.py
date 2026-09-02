"""Run a pipeline and keep every step, so a reader can scrub through it.

At `-O2` LLVM runs a couple of hundred passes over a small function and about
twenty of them change anything. That ratio is the single most useful fact about
the middle end and it is invisible from a before and after picture, so this
module keeps the whole run and the widget puts it on screen.

The work is done by one `opt` invocation:

    opt -passes=... --print-changed --print-module-scope -S -

`--print-changed` dumps the IR after a pass that changed something, and prints a
one line "omitted because no change" for every pass that did not, which is how
we get both the full ordered pass list and the frames from a single run.
`--print-module-scope` makes every dump the whole module rather than just the
function a function pass ran on, so consecutive frames are comparable and the
diff between them is honest.

None of this parses IR. It splits `opt`'s own output on `opt`'s own headers, and
everything below that line is `difflib` on text.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
from dataclasses import dataclass, field

from .ir import Diff, Module, highlight
from .proc import run

# opt writes one of these before every dump. The trailing note is what tells a
# pass that did nothing apart from one that did. Three shapes show up in
# practice and all three have to be recognised, because a header that is not
# recognised does not end the frame before it, it gets swallowed into that
# frame's IR:
#
#   *** IR Dump At Start ***
#   *** IR Dump After SROAPass on f ***
#   *** IR Dump After SROAPass on f omitted because no change ***
#   *** IR Pass PassManager<Function> on f ignored ***
#
# The pass name is `.+?` rather than `\S+` on purpose. An out of tree plugin
# reports itself as `(anonymous namespace)::CountInstructions`, with a space in
# it, which is exactly the case a lesson in Part IV will hit.
HEADER = re.compile(
    r"^\*\*\* IR (?:Dump At (?P<start>Start)"
    r"|(?:Dump After|Pass) (?P<name>.+?) on (?P<scope>.+?)"
    r"(?P<note> omitted because no change| filtered out| ignored)?)"
    r" \*\*\*$",
    re.M,
)

# llvm-as says where it stopped understanding, and that is how we find the end
# of a dump that has a pass's own output stuck to the back of it.
# Not anchored, because llvm-as puts its own path in front of the location.
PARSE_ERROR = re.compile(r"<stdin>:(\d+):\d+: error:")

# Every pass in LLVM is called SomethingPass. The suffix is noise on a chip that
# has to fit on a phone, so the strip drops it and the panel keeps it.
SUFFIX = re.compile(r"Pass$")

# Above this the whole module stops being something a person reads in a
# disclosure triangle and starts being a reason the notebook is 40 MB.
FULL_MODULE_LIMIT = 400


def _size(delta: int) -> str:
    if delta == 0:
        return "same length"
    return f"{delta:+d} line" if abs(delta) == 1 else f"{delta:+d} lines"


@dataclass
class Step:
    """One pass in the pipeline, whether or not it did anything."""

    index: int  # position in the pipeline, 1 based, counting every pass
    name: str  # "SROAPass"
    scope: str  # "f" for a function pass, "[module]" for a module pass
    changed: bool
    ir: str = ""  # the whole module after this pass, empty when nothing changed

    @property
    def short(self) -> str:
        return SUFFIX.sub("", self.name) or self.name

    def __str__(self) -> str:
        did = "changed" if self.changed else "no change"
        return f"{self.index:>4}  {self.name} on {self.scope}, {did}"


@dataclass(repr=False)
class Tape:
    """Every pass that ran, and the module after each one that changed it."""

    pipeline: str
    source: Module
    steps: list[Step] = field(default_factory=list)

    # -- what happened --------------------------------------------------------

    @property
    def changed(self) -> list[Step]:
        return [s for s in self.steps if s.changed]

    @property
    def frames(self) -> list[Module]:
        """The starting module, then one per pass that changed it."""
        out = [self.source]
        for step in self.changed:
            out.append(Module(text=step.ir, name=self.source.name,
                              history=[*self.source.history, step.name]))
        return out

    @property
    def final(self) -> Module:
        return self.frames[-1]

    def diffs(self) -> list[Diff]:
        frames = self.frames
        return [frames[i].diff(frames[i + 1]) for i in range(len(frames) - 1)]

    def deltas(self) -> list[int]:
        """Lines added minus lines removed, per changed pass."""
        frames = self.frames
        counts = [len(f.text.splitlines()) for f in frames]
        return [counts[i + 1] - counts[i] for i in range(len(counts) - 1)]

    def step(self, name: str) -> Step:
        """The first pass whose name contains `name`, case insensitive."""
        wanted = name.lower()
        for step in self.steps:
            if wanted in step.name.lower():
                return step
        raise KeyError(
            f"No pass matching {name!r} ran in this pipeline. "
            f"{len(self.steps)} passes did, and `[s.name for s in tape.steps]` lists them."
        )

    # -- showing it -----------------------------------------------------------

    @property
    def headline(self) -> str:
        n, k = len(self.steps), len(self.changed)
        return f"{self.pipeline} on {self.source.name}: {n} passes ran, {k} changed the IR"

    def __repr__(self) -> str:
        return f"<Tape {self.headline}>"

    def __str__(self) -> str:
        """The text fallback, which has to teach the same thing the widget does."""
        lines = [self.headline, ""]
        for step, delta in zip(self.changed, self.deltas()):
            # A loop pass names the loop and the function it is in, which is
            # long enough to wreck the column, so it gets cut here and kept in
            # full in the panel.
            scope = step.scope if len(step.scope) <= 22 else step.scope[:19] + "..."
            lines.append(f"  {step.index:>4}  {step.short:<26} {scope:<23} {_size(delta)}")
        if not self.changed:
            lines.append("  Nothing in this pipeline touched the module.")
        return "\n".join(lines) + "\n"

    def _repr_html_(self) -> str:
        return _widget(self)


def tape(module: Module, passes: str, *extra: str) -> Tape:
    """Run `passes` over `module` and keep every step of it."""
    flags = _plugin_flags()
    result = run(
        "opt",
        *flags,
        f"-passes={passes}",
        "--print-changed",
        "--print-module-scope",
        "-S",
        *extra,
        "-",
        stdin=module.text,
    )
    # Only pay for the tidy up when there is a plugin loaded that could have
    # printed something. A stock pipeline writes nothing but dumps.
    return _parse(result.stderr, passes, module, tidy=bool(flags))


def _plugin_flags() -> list[str]:
    # Imported here rather than at the top because plugin imports proc, and this
    # keeps the import graph a line instead of a loop.
    from . import plugin

    return plugin.load_flags()


def _parse(stderr: str, passes: str, source: Module, tidy: bool = False) -> Tape:
    """Split opt's output on opt's own headers. The bodies are never inspected."""
    marks = list(HEADER.finditer(stderr))
    steps: list[Step] = []
    index = 0
    for i, mark in enumerate(marks):
        if mark.group("start"):
            continue
        # "ignored" is what opt says about the plumbing: pass managers, the
        # adaptors that run a function pass over a module, the verifier, the
        # print at the end. They have to be matched, or they end up inside the
        # frame before them, but counting them as passes would inflate the one
        # number this whole thing exists to report.
        if mark.group("note") == " ignored":
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(stderr)
        changed = mark.group("note") is None
        body = stderr[mark.end() : end].strip("\n")
        ir = body + "\n" if changed else ""
        if changed and tidy:
            ir = _trim(ir)
        index += 1
        steps.append(
            Step(
                index=index,
                name=mark.group("name"),
                scope=mark.group("scope"),
                changed=changed,
                ir=ir,
            )
        )
    return Tape(pipeline=passes, source=source, steps=steps)


def _trim(body: str) -> str:
    """Cut anything a pass printed for itself off the end of a dump.

    opt writes the dumps to stderr and a pass that calls `errs()` writes to the
    same place, so a printing pass lands at the bottom of the frame before it.
    A teaching pass is usually a printing pass, so this is not a corner case,
    it is the normal case in Part IV.

    Rather than guess where the IR stops, ask llvm-as. It reports the line it
    stopped understanding on, which is exactly the first line of the junk.
    """
    result = run("llvm-as", "-o", os.devnull, "-", stdin=body, check=False)
    if result.ok:
        return body
    match = PARSE_ERROR.search(result.stderr)
    if not match:
        return body
    kept = "\n".join(body.split("\n")[: int(match.group(1)) - 1]).rstrip("\n") + "\n"
    second = run("llvm-as", "-o", os.devnull, "-", stdin=kept, check=False)
    # If cutting there did not produce a module either, the problem is not a
    # printing pass and quietly handing back a truncated module would be worse
    # than handing back what opt actually said.
    return kept if second.ok else body


# -- the widget ---------------------------------------------------------------
#
# There is no JavaScript in here and that is deliberate. Colab renders cell
# output inside a sandboxed iframe, JupyterLite runs the whole kernel in the
# browser, and the published site is static HTML with no kernel at all. A
# hidden radio button per frame plus sibling selectors is the one mechanism all
# four of those agree on, and it keeps working in a saved notebook that nobody
# will ever rerun.
#
# The panels also carry an inline `display:none`, so if a renderer strips the
# `<style>` block, which GitHub does, what is left is the first frame and a list
# of pass names rather than twenty modules stacked on top of each other.

CHIP = (
    "display:inline-block;padding:3px 8px;border:1px solid #d0d7de;border-radius:12px;"
    "background:#fff;color:#24292f;font-size:11.5px;cursor:pointer;user-select:none;"
    "white-space:nowrap"
)
SHELL = (
    "border:1px solid #e3e3e3;border-radius:6px;overflow:hidden;max-width:100%;"
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace"
)


def _ident(t: Tape) -> str:
    """A stable id, so the same tape rendered twice gives the same HTML."""
    material = f"{t.pipeline}\x00{t.source.name}\x00{len(t.steps)}\x00{t.source.text[:400]}"
    return "irxtape" + hashlib.sha256(material.encode()).hexdigest()[:10]


def _rules(ident: str, count: int) -> str:
    css = [
        f"#{ident}{{{SHELL}}}",
        f"#{ident} .hd{{padding:8px 12px;background:#f6f8fa;border-bottom:1px solid #e3e3e3;"
        "font-size:12px;color:#24292f}",
        f"#{ident} .st{{display:flex;flex-wrap:wrap;gap:5px;padding:8px 12px;"
        "border-bottom:1px solid #eee}",
        f"#{ident} .st label{{{CHIP}}}",
        f"#{ident} .fr{{display:none;padding:10px 12px}}",
        f"#{ident} .cap{{margin:0 0 6px 0;color:#57606a;font-size:12px}}",
        f"#{ident} .ir{{margin:0;padding:8px 10px;background:#fbfbfb;border:1px solid #e3e3e3;"
        "border-radius:6px;overflow-x:auto;font-size:12px;line-height:1.45}",
        f"#{ident} details{{margin-top:8px;font-size:12px;color:#57606a}}",
        f"#{ident} > input{{position:absolute;width:1px;height:1px;opacity:0}}",
    ]
    # nth-of-type counts by element name, and the chrome around the panels is
    # made of divs too, so the panels get their own container and are picked out
    # with nth-child inside it. The inputs are the only <input> here, so
    # nth-of-type is exactly right for them.
    for k in range(1, count + 1):
        checked = f"#{ident} > input:nth-of-type({k}):checked"
        css.append(f"{checked} ~ .pn > .fr:nth-child({k}){{display:block !important}}")
        css.append(
            f"{checked} ~ .st > label:nth-child({k})"
            "{background:#0969da;border-color:#0969da;color:#fff}"
        )
        css.append(
            f"#{ident} > input:nth-of-type({k}):focus-visible ~ .st > label:nth-child({k})"
            "{outline:2px solid #0969da;outline-offset:2px}"
        )
    return "".join(css)


def _widget(t: Tape) -> str:
    ident = _ident(t)
    frames, diffs, deltas = t.frames, t.diffs(), t.deltas()
    chips = ["start"]
    for step, delta in zip(t.changed, deltas):
        chips.append(f"{step.short} {delta:+d}" if delta else step.short)

    inputs, strip, panels = [], [], []
    for k, chip in enumerate(chips, start=1):
        box = f"{ident}-{k}"
        state = " checked" if k == 1 else ""
        inputs.append(f'<input type="radio" name="{ident}" id="{box}"{state}>')
        strip.append(f'<label for="{box}">{html.escape(chip)}</label>')
        hide = "" if k == 1 else ' style="display:none"'
        panels.append(f'<div class="fr"{hide}>{_panel(t, k, frames, diffs, deltas)}</div>')

    return (
        f'<div id="{ident}"><style>{_rules(ident, len(chips))}</style>'
        f'<div class="hd">{html.escape(t.headline)}</div>'
        f'{"".join(inputs)}<div class="st">{"".join(strip)}</div>'
        f'<div class="pn">{"".join(panels)}</div></div>'
    )


def _panel(t: Tape, k: int, frames, diffs, deltas) -> str:
    if k == 1:
        caption = f"before anything ran, {len(frames[0].text.splitlines())} lines"
        return (
            f'<p class="cap">{html.escape(caption)}</p>'
            f'<pre class="ir">{highlight(frames[0].text)}</pre>'
        )
    step, delta, diff = t.changed[k - 2], deltas[k - 2], diffs[k - 2]
    caption = f"pass {step.index} of {len(t.steps)}, {step.name} on {step.scope}, {_size(delta)}"
    rows = []
    for line in diff.unified().split("\n"):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            style = "color:#8250df;background:#f6f0ff"
        elif line.startswith("+"):
            style = "background:#e6ffec"
        elif line.startswith("-"):
            style = "background:#ffebe9"
        else:
            style = ""
        rows.append(f'<div style="{style}">{highlight(line) or "&nbsp;"}</div>')
    whole = frames[k - 1].text
    if len(whole.splitlines()) <= FULL_MODULE_LIMIT:
        details = (
            "<details><summary>the whole module after this pass</summary>"
            f'<pre class="ir">{highlight(whole)}</pre></details>'
        )
    else:
        details = (
            "<details><summary>the whole module after this pass</summary>"
            f'<p class="cap">{len(whole.splitlines())} lines, too much to carry in every '
            f"frame. `tape.frames[{k - 1}]` has it.</p></details>"
        )
    return (
        f'<p class="cap">{html.escape(caption)}</p>'
        f'<pre class="ir">{"".join(rows)}</pre>{details}'
    )


__all__ = ["Step", "Tape", "tape"]
