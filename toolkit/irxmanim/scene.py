"""The timeline, and the CSS it turns into.

A scene holds mobjects and a list of things that happen to them. Rendering
walks each mobject's properties over the whole running time and writes one
`@keyframes` rule per mobject, with a stop wherever that mobject changes.

Three decisions are worth saying out loud, because each one closes off an
option somebody will reasonably ask about.

**No script.** Animation is CSS keyframes on an inline `<svg>`. The output goes
into a saved notebook, into Colab's output sandbox, and into static HTML on the
site, and script survives none of those reliably. It also means the picture
animates when it is loaded as an ordinary image, which script would not.

**The markup is the last frame.** Every element is written out at the position
and opacity it ends on, and the animation walks back to the beginning and
forward again. A renderer that drops the stylesheet, a print stylesheet, and
anybody who has asked their system for less motion all get the finished
picture rather than an empty box, and `prefers-reduced-motion` is honoured
below rather than ignored.

**Easing is sampled here, not asked for.** Each segment is emitted as several
stops with the eased value already worked out, and the CSS between stops is
linear. A keyframe timing function would be shorter to write, but it applies
per stop, and stops belonging to one mobject's motion get interleaved with
stops belonging to another's, which quietly distorts the curve.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .mobject import Arrow, Box, Caption, Code, Group, Head, Line, Mobject, Wash

# The cap from CONTRIBUTING.md. A lesson that wants a longer animation wants
# two animations, and the same argument applies here as applies to lesson
# length: "this one is special" is how caps die.
MAX_SECONDS = 90.0

DEFAULTS = {"opacity": 1.0, "tx": 0.0, "ty": 0.0, "scale": 1.0, "dash": 0.0}
MOVING = ("tx", "ty", "scale")

# How far before a jump the previous value is pinned, so that a property told
# to start somewhere other than where it is jumps rather than drifting there
# across whatever gap came before.
EPS = 0.004

# Samples per segment. Five stops is a smooth enough curve at these durations
# and keeps the stylesheet small enough to read.
SAMPLES = (0.0, 0.25, 0.5, 0.75, 1.0)


class SceneError(ValueError):
    """A scene was asked for something it cannot do."""


def _smooth(u: float) -> float:
    return u * u * (3 - 2 * u)


@dataclass
class Change:
    """One property of one mobject, moving from somewhere to somewhere else."""

    prop: str
    to: float
    start: float | None = None
    relative: bool = False
    at: float = 0.0
    over: float | None = None
    target: Mobject | None = None


@dataclass
class Anim:
    """What the reader asked for. The scene turns it into segments."""

    target: Mobject
    verb: str
    changes: list[Change]
    run_time: float = 0.6

    @property
    def span(self) -> float:
        return max(
            change.at + (self.run_time if change.over is None else change.over)
            for change in self.changes
        )


# -- the animations -----------------------------------------------------------


def fade_in(m: Mobject, run_time: float = 0.5) -> Anim:
    """Arrive. Whatever fades in is not there before it does."""
    return Anim(m, "fade in", [Change("opacity", 1.0, start=0.0)], run_time)


def fade_out(m: Mobject, run_time: float = 0.5) -> Anim:
    """Leave. What a pass does to an instruction it deleted."""
    return Anim(m, "fade out", [Change("opacity", 0.0)], run_time)


def move(m: Mobject, dx: float = 0.0, dy: float = 0.0, run_time: float = 0.6) -> Anim:
    """Shift, relative to wherever it is now."""
    return Anim(
        m,
        "move",
        [Change("tx", dx, relative=True), Change("ty", dy, relative=True)],
        run_time,
    )


def highlight(m: Mobject, run_time: float = 1.0) -> Anim:
    """Wash over it and then take the wash away.

    The mobject has to have a wash, which boxes and lines of code do and arrows
    do not, so this is the one animation that can be asked for of something
    that cannot do it. Saying so here is better than an arrow that shrugs.
    """
    wash = getattr(m, "wash", None)
    if wash is None:
        raise SceneError(
            f"{m.name or type(m).__name__} has nothing to highlight. Boxes and lines "
            "of code carry a highlight, arrows do not. Try fading it in instead."
        )
    edge = min(0.25, run_time / 3)
    return Anim(
        m,
        "highlight",
        [
            Change("opacity", 1.0, start=0.0, over=edge, target=wash),
            Change("opacity", 0.0, at=run_time - edge, over=edge, target=wash),
        ],
        run_time,
    )


def pulse(m: Mobject, size: float = 1.05, run_time: float = 0.6) -> Anim:
    """A small breath, for pointing at something without covering it."""
    half = run_time / 2
    return Anim(
        m,
        "pulse",
        [
            Change("scale", size, start=1.0, over=half),
            Change("scale", 1.0, at=half, over=half),
        ],
        run_time,
    )


def draw(arrow: Arrow, run_time: float = 0.7) -> Anim:
    """Stroke an arrow from its tail to its head, with the head arriving last."""
    if not isinstance(arrow, Arrow):
        raise SceneError("Only an arrow can be drawn. Everything else fades in.")
    return Anim(
        arrow,
        "draw",
        [
            Change("dash", 0.0, start=1.0),
            Change("opacity", 1.0, start=0.0, at=run_time * 0.7, over=run_time * 0.3,
                   target=arrow.head),
        ],
        run_time,
    )


# -- the scene ----------------------------------------------------------------


@dataclass
class Segment:
    a: float
    b: float
    v0: float
    v1: float


SUFFIX = {Wash: "highlight", Head: "head"}


def _derive(m: Mobject, parent: Mobject | None) -> str:
    if isinstance(m, Box | Line | Caption) and m.text:
        return m.text.split("\n")[0].strip()[:40]
    if isinstance(m, Arrow):
        return f"arrow {m.label}".strip()
    if isinstance(m, Code):
        return f"{len(m.rows)} lines"
    if isinstance(m, Group):
        return "group"
    suffix = SUFFIX.get(type(m), type(m).__name__.lower())
    return f"{parent.name} {suffix}" if parent else suffix


class Scene:
    """A drawing that changes over time.

    Build it the way you would read it out loud: put things on the stage with
    `add`, then say what happens with `play`, one beat per call.
    """

    def __init__(
        self,
        width: float = 640,
        height: float = 320,
        caption: str = "",
        *,
        loop: bool = True,
        rest: float = 1.2,
    ) -> None:
        self.width = width
        self.height = height
        self.caption = caption
        self.loop = loop
        self.rest = rest
        self.cursor = 0.0
        self.roots: list[Mobject] = []
        self.known: dict[str, Mobject] = {}
        self.script: list[tuple[float, str, str]] = []
        self.segments: dict[str, dict[str, list[Segment]]] = {}
        self.pins: dict[str, set[float]] = {}
        self.value: dict[tuple[str, str], float] = {}

    # -- building

    def add(self, *mobjects: Mobject) -> Mobject | tuple[Mobject, ...]:
        """Put mobjects on the stage. Returns what it was given, for chaining."""
        for m in mobjects:
            self._register(m, None)
            self.roots.append(m)
        return mobjects[0] if len(mobjects) == 1 else mobjects

    def _register(self, m: Mobject, parent: Mobject | None) -> None:
        if m.key:
            raise SceneError(f"{m.name} is in this scene already, add it once.")
        m.key = f"m{len(self.known)}"
        m.name = m.name or _derive(m, parent)
        self.known[m.key] = m
        for child in m.parts():
            self._register(child, m)

    def play(self, *anims: Anim, run_time: float | None = None) -> None:
        """One beat. Everything passed to a single call happens at once."""
        if not anims:
            raise SceneError("play() with nothing to play. Use wait() for a pause.")
        start = self.cursor
        span = 0.0
        for anim in anims:
            if run_time is not None:
                anim.run_time = run_time
            self._schedule(anim, start)
            self.script.append((start, anim.verb, anim.target.name))
            span = max(span, anim.span)
        self.cursor = start + span
        self._check()

    def wait(self, seconds: float = 0.5) -> None:
        """Hold. What is on the screen stays there."""
        self.cursor += seconds
        self._check()

    def _schedule(self, anim: Anim, start: float) -> None:
        for change in anim.changes:
            target = change.target or anim.target
            if not target.key or self.known.get(target.key) is not target:
                raise SceneError(
                    f"{target.name or _derive(target, None)!r} is not in this scene. "
                    "Everything that moves has to be add()ed first."
                )
            if change.prop not in DEFAULTS:
                raise SceneError(f"{change.prop!r} is not an animatable property.")
            here = self.value.get(
                (target.key, change.prop), self.default(target.key, change.prop)
            )
            first = here if change.start is None else change.start
            last = here + change.to if change.relative else change.to
            a = start + change.at
            b = a + (anim.run_time if change.over is None else change.over)
            track = self.segments.setdefault(target.key, {}).setdefault(change.prop, [])
            track.append(Segment(a, b, first, last))
            if a > EPS:
                self.pins.setdefault(target.key, set()).add(a - EPS)
            self.value[(target.key, change.prop)] = last

    def _check(self) -> None:
        if self.duration > MAX_SECONDS:
            raise SceneError(
                f"This scene runs {self.duration:.1f} seconds and the cap is "
                f"{MAX_SECONDS:.0f}. A longer animation is two animations."
            )

    # -- reading

    @property
    def duration(self) -> float:
        return max(self.cursor, 0.0) + self.rest

    def default(self, key: str, prop: str) -> float:
        """Where a property sits before anything moves it.

        Everything is 1 or 0 except opacity, which the mobject decides. A wash
        is the case that matters: it is drawn with its box and stays invisible
        until a highlight fades it in, and if it were not invisible by default
        every box in the scene would be yellow.
        """
        if prop == "opacity":
            return self.known[key].opacity
        return DEFAULTS[prop]

    def value_at(self, key: str, prop: str, t: float) -> float:
        track = self.segments.get(key, {}).get(prop)
        if not track:
            return self.default(key, prop)
        value = track[0].v0
        for seg in track:
            if t < seg.a:
                break
            if t >= seg.b:
                value = seg.v1
            else:
                u = (t - seg.a) / (seg.b - seg.a) if seg.b > seg.a else 1.0
                value = seg.v0 + (seg.v1 - seg.v0) * _smooth(u)
                break
        return value

    def __str__(self) -> str:
        how = "looping" if self.loop else "once"
        lines = [
            f"Scene {self.width:.0f}x{self.height:.0f}, {self.duration:.1f}s, "
            f"{how}, {len(self.known)} mobjects",
            "",
        ]
        for at, verb, name in self.script:
            lines.append(f"  {at:5.1f}s  {verb:<10} {name}")
        if not self.script:
            lines.append("  nothing happens yet")
        return "\n".join(lines) + "\n"

    def __repr__(self) -> str:
        return f"<Scene {self.duration:.1f}s, {len(self.script)} beats>"

    # -- drawing

    def _body(self, at: float) -> str:
        def wrap(m: Mobject) -> str:
            inner = m.draw(wrap)
            classes = f"{m.key} a" if m.key in self.segments else m.key
            # One frame, written into the markup. Rendering picks the last one,
            # so that a reader without the stylesheet, and anybody who asked
            # for less motion, gets the finished picture rather than a blank.
            final = {prop: self.value_at(m.key, prop, at) for prop in DEFAULTS}
            attrs = ""
            if final["opacity"] != 1.0:
                attrs += f' opacity="{final["opacity"]:.3f}"'
            if any(final[prop] != DEFAULTS[prop] for prop in MOVING):
                attrs += f' transform="{_transform(final, css=False)}"'
            if final["dash"]:
                attrs += f' stroke-dashoffset="{final["dash"] * m.length:.1f}"'
            return f'<g class="{classes}"{attrs}>{inner}</g>'

        return "".join(wrap(m) for m in self.roots)

    def _stops(self, key: str) -> list[float]:
        times = {0.0, self.duration} | self.pins.get(key, set())
        for track in self.segments[key].values():
            for seg in track:
                for u in SAMPLES:
                    times.add(seg.a + u * (seg.b - seg.a))
        return sorted({round(min(max(t, 0.0), self.duration), 4) for t in times})

    def _css(self, ident: str) -> str:
        count = "infinite" if self.loop else "1"
        rules = [
            f"#{ident} .a{{animation-duration:{self.duration:.2f}s;"
            f"animation-timing-function:linear;animation-fill-mode:both;"
            f"animation-iteration-count:{count};"
            "transform-box:fill-box;transform-origin:center}",
            # Somebody who has asked for less motion gets the finished picture,
            # which is the frame the markup already holds.
            f"@media (prefers-reduced-motion:reduce){{#{ident} .a{{animation:none}}}}",
        ]
        for key in self.segments:
            props = set(self.segments[key])
            mobject = self.known[key]
            frames = []
            for t in self._stops(key):
                decls = []
                if "opacity" in props:
                    decls.append(f"opacity:{self.value_at(key, 'opacity', t):.3f}")
                if props & set(MOVING):
                    state = {prop: self.value_at(key, prop, t) for prop in MOVING}
                    decls.append(f"transform:{_transform(state)}")
                if "dash" in props:
                    hidden = self.value_at(key, "dash", t) * mobject.length
                    decls.append(f"stroke-dashoffset:{hidden:.1f}")
                pct = 100 * t / self.duration
                frames.append(f"{pct:.3f}%{{{';'.join(decls)}}}")
            rules.append(f"#{ident} .{key}{{animation-name:{ident}{key}}}")
            rules.append(f"@keyframes {ident}{key}{{{''.join(frames)}}}")
        return "".join(rules)

    def _ident(self, body: str) -> str:
        """A content hash, so the same scene renders the same bytes every time."""
        material = body + str(self) + f"{self.duration}{self.loop}"
        return "irxm" + hashlib.sha256(material.encode()).hexdigest()[:10]

    def svg(self) -> str:
        """The picture on its own, for writing to a file."""
        return self._svg(self.duration, animate=True)

    def frame(self, at: float) -> str:
        """One still, at a moment, with nothing moving.

        For a printed page, which cannot animate, and for looking closely at a
        beat that goes past too quickly to review by eye.
        """
        if not 0 <= at <= self.duration:
            raise SceneError(f"This scene runs {self.duration:.1f} seconds, {at} is outside it.")
        return self._svg(at, animate=False)

    def _svg(self, at: float, animate: bool) -> str:
        body = self._body(at)
        ident = self._ident(body)
        style = f"<style>{self._css(ident)}</style>" if animate else ""
        return (
            f'<svg id="{ident}" xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {self.width:.0f} {self.height:.0f}" '
            f'width="{self.width:.0f}" height="{self.height:.0f}" '
            f'role="img" aria-label="{_attr(self.caption)}">'
            f"{style}"
            f'<rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>'
        )

    def _repr_html_(self) -> str:
        caption = ""
        if self.caption:
            caption = (
                '<p style="margin:0 0 4px 0;color:#57606a;font-size:12px">'
                f"{_attr(self.caption)}</p>"
            )
        return f'<div style="max-width:100%">{caption}{self.svg()}</div>'


def _transform(state: dict[str, float], css: bool = True) -> str:
    """The same transform in the two syntaxes SVG has for it.

    The `transform` attribute is SVG's own, and its lengths are user units with
    no unit written. The `transform` CSS property is CSS's, and a bare number
    there is invalid, so the animation needs `px`. Writing one where the other
    is expected fails silently, which is a long afternoon.
    """
    unit = "px" if css else ""
    out = f"translate({state['tx']:.1f}{unit},{state['ty']:.1f}{unit})"
    if state.get("scale", 1.0) != 1.0:
        out += f" scale({state['scale']:.3f})"
    return out


def _attr(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


__all__ = [
    "MAX_SECONDS",
    "Anim",
    "Change",
    "Scene",
    "SceneError",
    "draw",
    "fade_in",
    "fade_out",
    "highlight",
    "move",
    "pulse",
]
