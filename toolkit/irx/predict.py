"""Ask the reader to commit to an answer before they are shown one.

A lesson that shows you the result of a pass teaches less than a lesson that
makes you guess first and then shows you that you were wrong. The guess is what
turns reading into a question, and a question is the thing you remember the
answer to.

So a gate is a question, two to four options, and an explanation of every one of
them including the wrong ones. Explaining only the right answer leaves a reader
who picked the second option knowing that they were wrong and not knowing why,
which is the worst of the available outcomes.

Like the pass tape, there is no JavaScript in here. The reveal is a `<details>`
element, which every renderer already understands, and the highlight on the
option you picked is a radio button and a sibling selector. That means the whole
thing still works in a saved notebook, in Colab's sandbox, and in the static
HTML on the site, and it degrades to a question with a list of answers under a
disclosure triangle when a renderer throws the stylesheet away.
"""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass

# Two is not really a prediction, it is a coin toss, and past four the reader is
# reading a menu rather than making a decision.
MIN_OPTIONS = 2
MAX_OPTIONS = 4


@dataclass(repr=False)
class Gate:
    """One prediction gate: a question, the options, and why each one is what it is."""

    question: str
    options: list[tuple[str, str]]
    answer: str
    note: str = ""

    @property
    def labels(self) -> list[str]:
        return [label for label, _ in self.options]

    def why(self, label: str) -> str:
        for name, text in self.options:
            if name == label:
                return text
        raise KeyError(f"{label!r} is not one of {', '.join(self.labels)}")

    def __repr__(self) -> str:
        """Short, and no answer in it.

        A notebook stores a text/plain fallback next to the widget, and the
        default dataclass repr would put every explanation, the answer included,
        into the saved file directly under the question. Anyone reading the
        notebook as text can call print() and get the full version below.
        """
        return f"<Gate {len(self.options)} options: {self.question}>"

    def __str__(self) -> str:
        """The text form, which cannot hide the answer and does not pretend to.

        Anyone reading this is in a terminal or a plain text renderer, where
        there is nowhere to put something that is only revealed on a click.
        Hiding it behind a cipher would be a puzzle rather than a lesson.
        """
        lines = [self.question, ""]
        for index, (label, _) in enumerate(self.options):
            lines.append(f"  {chr(ord('a') + index)}. {label}")
        lines += ["", f"  The answer is {self.answer}.", ""]
        for label, text in self.options:
            mark = "->" if label == self.answer else "  "
            lines.append(f"  {mark} {label}: {text}")
        if self.note:
            lines += ["", f"  {self.note}"]
        return "\n".join(lines) + "\n"

    def _repr_html_(self) -> str:
        return _widget(self)


def gate(question: str, options: dict[str, str], answer: str, note: str = "") -> Gate:
    """Build a prediction gate.

    `options` maps each answer to the sentence explaining it, in the order they
    should appear. `answer` is the key of the right one, and a key that is not
    in `options` is an error here rather than a gate that quietly marks nothing
    as correct, because that would go unnoticed until a reader hit it.
    """
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise ValueError(
            f"A gate takes {MIN_OPTIONS} to {MAX_OPTIONS} options, got {len(options)}. "
            "Fewer is a coin toss and more is a menu."
        )
    if answer not in options:
        raise ValueError(
            f"The answer {answer!r} is not one of the options: {', '.join(options)}."
        )
    empty = [label for label, text in options.items() if not text.strip()]
    if empty:
        raise ValueError(
            f"Every option needs an explanation, including the wrong ones, and "
            f"{', '.join(empty)} has none. A reader who picked a wrong answer and is "
            "not told why learns the least of anybody."
        )
    return Gate(question=question, options=list(options.items()), answer=answer, note=note)


# -- the widget ---------------------------------------------------------------

SHELL = (
    "border:1px solid #d0d7de;border-left:4px solid #0969da;border-radius:6px;"
    "max-width:100%;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;"
    "font-size:13.5px;color:#24292f"
)


def _ident(g: Gate) -> str:
    """A stable id, so the same gate rendered twice gives the same HTML."""
    material = "\x00".join([g.question, g.answer, *g.labels])
    return "irxgate" + hashlib.sha256(material.encode()).hexdigest()[:10]


def _rules(ident: str, count: int) -> str:
    css = [
        f"#{ident}{{{SHELL}}}",
        f"#{ident} .q{{padding:10px 14px 6px 14px;font-weight:600;line-height:1.45}}",
        f"#{ident} .op{{display:flex;flex-direction:column;gap:4px;padding:2px 14px 8px 14px}}",
        f"#{ident} .op label{{display:block;padding:5px 10px;border:1px solid #d0d7de;"
        "border-radius:6px;background:#fff;cursor:pointer;line-height:1.35}",
        f"#{ident} .ft{{padding:0 14px 10px 14px}}",
        f"#{ident} .ft textarea{{width:100%;box-sizing:border-box;border:1px solid #d0d7de;"
        "border-radius:6px;padding:5px 8px;font:inherit;color:inherit;resize:vertical}",
        f"#{ident} .ft span{{display:block;color:#57606a;font-size:12px;margin-bottom:4px}}",
        f"#{ident} > details{{border-top:1px solid #eaeef2;padding:8px 14px 12px 14px}}",
        f"#{ident} > details summary{{cursor:pointer;color:#0969da;font-size:12.5px}}",
        f"#{ident} .said{{margin:8px 0 6px 0;line-height:1.45}}",
        f"#{ident} .ws{{display:flex;flex-direction:column;gap:6px}}",
        f"#{ident} .why{{padding:6px 10px;border-radius:6px;background:#f6f8fa;line-height:1.45}}",
        f"#{ident} .why.yes{{background:#e6ffec}}",
        f"#{ident} .note{{margin:10px 0 0 0;color:#57606a;font-size:12.5px;line-height:1.45}}",
        f"#{ident} > input{{position:absolute;width:1px;height:1px;opacity:0}}",
    ]
    # The free text box is a <textarea> and not an <input> on purpose. These
    # selectors count inputs by position, so a second kind of input in here
    # would shift every option by one.
    for k in range(1, count + 1):
        checked = f"#{ident} > input:nth-of-type({k}):checked"
        css.append(
            f"{checked} ~ .op > label:nth-child({k})"
            "{border-color:#0969da;box-shadow:inset 0 0 0 1px #0969da}"
        )
        css.append(
            f"{checked} ~ details .ws > .why:nth-child({k})::after"
            '{content:" You picked this.";color:#57606a}'
        )
        css.append(
            f"#{ident} > input:nth-of-type({k}):focus-visible ~ .op > label:nth-child({k})"
            "{outline:2px solid #0969da;outline-offset:2px}"
        )
    return "".join(css)


def _widget(g: Gate) -> str:
    ident = _ident(g)
    inputs, labels, whys = [], [], []
    for k, (label, text) in enumerate(g.options, start=1):
        box = f"{ident}-{k}"
        inputs.append(f'<input type="radio" name="{ident}" id="{box}">')
        labels.append(f'<label for="{box}">{html.escape(label)}</label>')
        # The correct one is named in the sentence above as well as tinted here,
        # so a renderer that drops the stylesheet still tells you which it was.
        klass = "why yes" if label == g.answer else "why"
        whys.append(
            f'<div class="{klass}"><b>{html.escape(label)}</b>. {html.escape(text)}</div>'
        )

    note = f'<p class="note">{html.escape(g.note)}</p>' if g.note else ""
    return (
        f'<div id="{ident}"><style>{_rules(ident, len(g.options))}</style>'
        f'<div class="q">{html.escape(g.question)}</div>'
        f'{"".join(inputs)}'
        f'<div class="op">{"".join(labels)}</div>'
        f'<div class="ft"><span>Or say what you think in your own words first.</span>'
        f'<textarea rows="2" spellcheck="false"></textarea></div>'
        "<details><summary>Show me</summary>"
        f'<p class="said">The answer is <b>{html.escape(g.answer)}</b>.</p>'
        f'<div class="ws">{"".join(whys)}</div>{note}</details></div>'
    )


__all__ = ["Gate", "gate"]
