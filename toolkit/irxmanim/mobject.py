"""The things a scene moves around.

A mobject knows where it is, how big it is, and how to draw itself once. It
knows nothing about time. Everything that changes over time lives in `scene`,
which is the only place that has to think about keyframes, and that split is
the reason this file is readable.

Sizes are worked out from character counts rather than measured, because
measuring text needs a font engine and there is not one here. The numbers below
are the widths of the two fonts the rest of the toolkit already uses at the
sizes it already uses them, so a box is a little wider than its text rather
than a little narrower, which is the direction to be wrong in.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from irx.ir import COLOUR, pieces

MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif"
MONO_SIZE = 11.5
SANS_SIZE = 12.5
MONO_W = 7.0
SANS_W = 6.6
LINE_H = 17.0
PAD_X, PAD_Y = 10.0, 8.0

INK = "#24292f"
QUIET = "#57606a"

# The wash a highlight fades in. One colour, not a palette, because a
# highlighter is one colour: a reader who sees two different washes will look
# for a meaning in the difference and there is not one.
FLASH = "#fff8c5"

# Fill, stroke, and the colour of text sitting on it. `gone` is for something
# the pass is about to delete, and it is deliberately the quietest of them.
TONES = {
    "plain": ("#ffffff", "#d0d7de", INK),
    "flow": ("#ddf4ff", "#0969da", "#0a3069"),
    "loop": ("#fbefff", "#8250df", "#3f1a6b"),
    "warn": ("#fff8c5", "#d4a72c", "#4d2d00"),
    "gone": ("#f6f8fa", "#d8dee4", "#8c959f"),
}


class MobjectError(ValueError):
    """A mobject was asked for something it cannot be."""


Wrap = Callable[["Mobject"], str]


@dataclass
class Mobject:
    """Base class. Position is absolute, in user units, from the top left."""

    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    # Filled in by the scene when the mobject is added. `key` is the CSS class
    # the animation hangs off, `name` is what the storyboard calls it.
    key: str = ""
    name: str = ""

    # Set by whatever can be drawn progressively, which is arrows.
    length: float = 0.0

    # Where the opacity track starts and, if nothing ever animates it, stays.
    # A highlight is the reason this is a field rather than always 1: the wash
    # is part of the box from the moment the box is drawn, and it is invisible
    # until something fades it in.
    opacity: float = 1.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def bottom(self) -> tuple[float, float]:
        return (self.cx, self.y + self.h)

    @property
    def top(self) -> tuple[float, float]:
        return (self.cx, self.y)

    @property
    def left(self) -> tuple[float, float]:
        return (self.x, self.cy)

    @property
    def right(self) -> tuple[float, float]:
        return (self.x + self.w, self.cy)

    def parts(self) -> list[Mobject]:
        """Children that can be animated on their own."""
        return []

    def draw(self, wrap: Wrap) -> str:
        """The SVG for this mobject, calling `wrap` wherever a child belongs.

        The children are placed by the mobject rather than appended by the
        caller because order is paint order, and a highlight that lands on top
        of the text it is highlighting has covered up the thing it points at.
        """
        return ""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name or self.key or ''}>".replace("  ", " ")


@dataclass
class Wash(Mobject):
    """The rectangle a highlight fades in. Invisible until something animates it."""

    radius: float = 4.0

    def __post_init__(self) -> None:
        self.opacity = 0.0

    def draw(self, wrap: Wrap) -> str:
        return (
            f'<rect x="{self.x:.1f}" y="{self.y:.1f}" width="{self.w:.1f}" '
            f'height="{self.h:.1f}" rx="{self.radius}" fill="{FLASH}"/>'
        )


def _text(x: float, y: float, body: str, *, mono: bool, fill: str, anchor: str = "start") -> str:
    font = MONO if mono else SANS
    size = MONO_SIZE if mono else SANS_SIZE
    middle = ' text-anchor="middle"' if anchor == "middle" else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" '
        f'fill="{fill}"{middle} xml:space="preserve">{body}</text>'
    )


@dataclass
class Box(Mobject):
    """A rounded rectangle with a line or two of text in the middle of it."""

    text: str = ""
    tone: str = "plain"
    mono: bool = False

    def __post_init__(self) -> None:
        if self.tone not in TONES:
            raise MobjectError(f"{self.tone!r} is not a tone, try one of {', '.join(TONES)}.")
        lines = self.text.split("\n") if self.text else []
        width = max((len(line) for line in lines), default=0)
        char = MONO_W if self.mono else SANS_W
        self.w = self.w or width * char + 2 * PAD_X
        self.h = self.h or max(len(lines), 1) * LINE_H + 2 * PAD_Y
        self.wash = Wash(self.x, self.y, self.w, self.h)

    def parts(self) -> list[Mobject]:
        return [self.wash]

    def draw(self, wrap: Wrap) -> str:
        fill, stroke, ink = TONES[self.tone]
        out = [
            f'<rect x="{self.x:.1f}" y="{self.y:.1f}" width="{self.w:.1f}" '
            f'height="{self.h:.1f}" rx="6" fill="{fill}" stroke="{stroke}"/>',
            wrap(self.wash),
        ]
        lines = self.text.split("\n") if self.text else []
        first = self.cy - (len(lines) - 1) * LINE_H / 2 + 4
        for index, line in enumerate(lines):
            out.append(
                _text(
                    self.cx,
                    first + index * LINE_H,
                    html.escape(line),
                    mono=self.mono,
                    fill=ink,
                    anchor="middle",
                )
            )
        return "".join(out)


@dataclass
class Line(Mobject):
    """One line of code, coloured as IR, with a wash of its own.

    A line is its own mobject so that a pass can be shown doing what a pass
    does, which is to touch one instruction and leave the rest alone.
    """

    text: str = ""
    ir: bool = True

    def __post_init__(self) -> None:
        self.w = self.w or len(self.text) * MONO_W
        self.h = self.h or LINE_H
        self.wash = Wash(self.x - 4, self.y, self.w + 8, self.h)

    def parts(self) -> list[Mobject]:
        return [self.wash]

    def draw(self, wrap: Wrap) -> str:
        if self.ir:
            spans = []
            for chunk, colour in pieces(self.text):
                fill = f' fill="{colour}"' if colour else ""
                weight = ' font-weight="600"' if colour == COLOUR["keyword"] else ""
                spans.append(f"<tspan{fill}{weight}>{html.escape(chunk)}</tspan>")
            body = "".join(spans)
        else:
            body = html.escape(self.text)
        baseline = self.y + LINE_H - 5
        return wrap(self.wash) + _text(self.x, baseline, body, mono=True, fill=INK)


@dataclass
class Code(Mobject):
    """A block of IR. Every line in it is a mobject, and the block is a group."""

    lines: list[str] = field(default_factory=list)
    ir: bool = True

    def __post_init__(self) -> None:
        self.rows = [
            Line(x=self.x, y=self.y + index * LINE_H, text=text, ir=self.ir)
            for index, text in enumerate(self.lines)
        ]
        self.w = self.w or max((row.w for row in self.rows), default=0)
        self.h = self.h or len(self.rows) * LINE_H

    def __getitem__(self, index: int) -> Line:
        return self.rows[index]

    def parts(self) -> list[Mobject]:
        return list(self.rows)

    def draw(self, wrap: Wrap) -> str:
        return "".join(wrap(row) for row in self.rows)


@dataclass
class Group(Mobject):
    """Several mobjects that move as one. Its own geometry is their extent."""

    members: list[Mobject] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.members:
            raise MobjectError("A group with nothing in it has nothing to move.")
        self.x = min(m.x for m in self.members)
        self.y = min(m.y for m in self.members)
        self.w = max(m.x + m.w for m in self.members) - self.x
        self.h = max(m.y + m.h for m in self.members) - self.y

    def parts(self) -> list[Mobject]:
        return list(self.members)

    def draw(self, wrap: Wrap) -> str:
        return "".join(wrap(m) for m in self.members)


@dataclass
class Head(Mobject):
    """The triangle on the end of an arrow, drawn rather than a marker.

    A `<marker>` cannot be animated separately from the path it sits on, and an
    arrow that is being drawn wants its head to arrive last rather than to hang
    in the air at the destination for the whole of the stroke.
    """

    angle: float = 0.0
    colour: str = QUIET

    def draw(self, wrap: Wrap) -> str:
        size, spread = 8.0, 0.42
        tip = (self.x, self.y)
        wings = [
            (
                self.x - size * math.cos(self.angle + turn),
                self.y - size * math.sin(self.angle + turn),
            )
            for turn in (-spread, spread)
        ]
        points = " ".join(f"{px:.1f},{py:.1f}" for px, py in [tip, *wings])
        return f'<polygon points="{points}" fill="{self.colour}"/>'


@dataclass
class Arrow(Mobject):
    """A line from one point to another, with a head, and a label if it needs one."""

    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)
    label: str = ""
    bend: float = 0.0
    colour: str = QUIET

    def __post_init__(self) -> None:
        (x0, y0), (x1, y1) = self.start, self.end
        # The control point is pushed off the midpoint at a right angle to the
        # line, so `bend` is a distance in user units and a sign, which is
        # easier to think about than a control point.
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        span = math.hypot(x1 - x0, y1 - y0) or 1.0
        self.control = (mx - self.bend * (y1 - y0) / span, my + self.bend * (x1 - x0) / span)
        self.length = self._measure()
        self.x, self.y = min(x0, x1), min(y0, y1)
        self.w, self.h = abs(x1 - x0), abs(y1 - y0)
        self.head = Head(x=x1, y=y1, angle=self._angle(), colour=self.colour)

    def _point(self, t: float) -> tuple[float, float]:
        (x0, y0), (cx, cy), (x1, y1) = self.start, self.control, self.end
        u = 1 - t
        return (
            u * u * x0 + 2 * u * t * cx + t * t * x1,
            u * u * y0 + 2 * u * t * cy + t * t * y1,
        )

    def _measure(self, steps: int = 32) -> float:
        """Length by walking the curve, which is what the dash pattern needs.

        A straight line comes out of this exact, and a curve comes out close
        enough that the stroke finishes where the head is.
        """
        total, previous = 0.0, self._point(0.0)
        for step in range(1, steps + 1):
            current = self._point(step / steps)
            total += math.hypot(current[0] - previous[0], current[1] - previous[1])
            previous = current
        return total

    def _angle(self) -> float:
        near = self._point(0.98)
        return math.atan2(self.end[1] - near[1], self.end[0] - near[0])

    def parts(self) -> list[Mobject]:
        return [self.head]

    def draw(self, wrap: Wrap) -> str:
        (x0, y0), (cx, cy), (x1, y1) = self.start, self.control, self.end
        path = (
            f'<path d="M {x0:.1f} {y0:.1f} Q {cx:.1f} {cy:.1f} {x1:.1f} {y1:.1f}" '
            f'fill="none" stroke="{self.colour}" stroke-width="1.4" '
            f'stroke-dasharray="{self.length:.1f}"/>'
        )
        out = [path, wrap(self.head)]
        if self.label:
            lx, ly = self._point(0.5)
            offset = 6 if self.bend >= 0 else -6
            out.append(
                _text(lx + offset, ly - 4, html.escape(self.label), mono=False, fill=QUIET)
            )
        return "".join(out)


def link(a: Mobject, b: Mobject, label: str = "", bend: float = 0.0, gap: float = 6.0) -> Arrow:
    """An arrow from the edge of one mobject to the edge of another.

    Which edges depends on where they are: side by side gets a horizontal
    arrow, stacked gets a vertical one. `gap` keeps the head off the box it is
    pointing at, because a head touching a border reads as part of the border.
    """
    if abs(b.cy - a.cy) >= abs(b.cx - a.cx):
        if b.cy > a.cy:
            start, end = (a.cx, a.y + a.h + gap), (b.cx, b.y - gap)
        else:
            start, end = (a.cx, a.y - gap), (b.cx, b.y + b.h + gap)
    elif b.cx > a.cx:
        start, end = (a.x + a.w + gap, a.cy), (b.x - gap, b.cy)
    else:
        start, end = (a.x - gap, a.cy), (b.x + b.w + gap, b.cy)
    return Arrow(start=start, end=end, label=label, bend=bend)


@dataclass
class Caption(Mobject):
    """A line of prose inside the picture, for naming what is happening."""

    text: str = ""
    tone: str = "quiet"

    def __post_init__(self) -> None:
        self.w = self.w or len(self.text) * SANS_W
        self.h = self.h or LINE_H

    def draw(self, wrap: Wrap) -> str:
        fill = QUIET if self.tone == "quiet" else INK
        return _text(self.x, self.y + LINE_H - 5, html.escape(self.text), mono=False, fill=fill)


__all__ = [
    "TONES",
    "Arrow",
    "Box",
    "Caption",
    "Code",
    "Group",
    "Head",
    "Line",
    "Mobject",
    "MobjectError",
    "Wash",
    "link",
]
