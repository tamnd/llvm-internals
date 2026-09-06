"""Short animations for the lessons, with no dependencies and no script.

The name is borrowed from manim, and so is the vocabulary: mobjects, a scene,
and `play` for one beat of it. None of the implementation is borrowed. manim
renders video, which wants cairo, ffmpeg and usually a LaTeX install, and none
of that fits in the first cell of a Colab notebook or survives being saved into
one. What comes out of here is a single inline `<svg>` with a stylesheet in it,
which animates in a notebook, in Colab's output sandbox, on the site, and as an
ordinary `<img>`.

    from irxmanim import Scene, Box, link, fade_in, draw, highlight

    s = Scene(420, 150, caption="A pass reads a function and writes one back")
    ir = s.add(Box(20, 40, text="the function", tone="plain"))
    pass_ = s.add(Box(230, 40, text="InstCombinePass", tone="flow"))
    arrow = s.add(link(ir, pass_))
    s.play(fade_in(ir))
    s.play(draw(arrow))
    s.play(fade_in(pass_))
    s.play(highlight(pass_))

Print the scene and you get the storyboard, which is what a review reads. Show
it in a notebook and you get the picture. Call `svg()` and you get a file.

Everything about how it is drawn is in `mobject`, and everything about how it
moves is in `scene`.
"""

from __future__ import annotations

from . import mobject, scene
from .mobject import (
    TONES,
    Arrow,
    Box,
    Caption,
    Code,
    Group,
    Head,
    Line,
    Mobject,
    MobjectError,
    Wash,
    link,
)
from .scene import (
    MAX_SECONDS,
    Anim,
    Change,
    Scene,
    SceneError,
    draw,
    fade_in,
    fade_out,
    highlight,
    move,
    pulse,
)

__all__ = [
    "MAX_SECONDS",
    "TONES",
    "Anim",
    "Arrow",
    "Box",
    "Caption",
    "Change",
    "Code",
    "Group",
    "Head",
    "Line",
    "Mobject",
    "MobjectError",
    "Scene",
    "SceneError",
    "Wash",
    "draw",
    "fade_in",
    "fade_out",
    "highlight",
    "link",
    "mobject",
    "move",
    "pulse",
    "scene",
]
