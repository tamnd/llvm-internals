"""Build a diagram once and get both an editable file and a viewable one.

Diagrams in this repository are written as small Python scripts rather than
drawn by hand. Two reasons. A drawing that lives only as a PNG cannot be
corrected by somebody who spots a mistake in it, and a diagram that is a hundred
lines of layout code can be regenerated when the thing it describes changes.

Every scene writes two files. The `.excalidraw` opens at excalidraw.com so
anybody can move a box and export a new one. The `.svg` is what GitHub and the
site actually render, because neither of them can read an excalidraw file.

Nothing in here is random. Excalidraw normally seeds each element so the hand
drawn wobble differs run to run, which would mean every regeneration produced a
different file. Seeds here are derived from the element id, so a rebuild that
changes nothing produces bytes that change nothing.
"""

from __future__ import annotations

import hashlib
import json
import xml.sax.saxutils as sax
from dataclasses import dataclass, field
from pathlib import Path

# The palette. Every colour is paired with a shape or a label so that the
# diagram still reads with no colour at all, which is the accessibility rule
# from the visual system and also what happens when somebody prints it.
PALETTE = {
    "source": ("#1971c2", "#d0ebff"),  # a thing a human edits
    "tool": ("#6741d9", "#e5dbff"),  # a thing that runs
    "output": ("#2f9e44", "#d3f9d8"),  # a thing that is generated
    "external": ("#495057", "#f1f3f5"),  # a thing we do not control
    "warn": ("#e8590c", "#ffe8cc"),  # a thing that can go wrong
    "plain": ("#1e1e1e", "transparent"),
}

FONT_HAND, FONT_SANS, FONT_CODE = 1, 2, 3
SVG_FONT = {
    FONT_HAND: "Segoe UI, Helvetica, Arial, sans-serif",
    FONT_SANS: "Helvetica, Arial, sans-serif",
    FONT_CODE: "ui-monospace, SFMono-Regular, Menlo, monospace",
}
LINE_HEIGHT = 1.25


def _seed(key: str) -> int:
    """A stable pseudo random number, so rebuilds are byte identical."""
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 2_000_000_000


def _index(n: int) -> str:
    """Excalidraw's fractional index, which just has to sort correctly."""
    return f"a{n:04d}"


@dataclass
class Scene:
    """A diagram. Add boxes and arrows, then save."""

    padding: int = 32
    elements: list[dict] = field(default_factory=list)
    _svg: list[str] = field(default_factory=list)

    # -- building ----------------------------------------------------------

    def box(
        self,
        key: str,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        style: str = "source",
        font: int = FONT_HAND,
        size: int = 16,
        shape: str = "rectangle",
        radius: float | None = None,
    ) -> tuple[float, float, float, float]:
        stroke, fill = PALETTE[style]
        text_id = f"{key}-text"
        # A corner radius of 8 on a box 5 pixels wide is a circle, and a row of
        # those reads as a string of zeroes rather than as a row of ticks.
        if radius is None:
            radius = 8 if shape == "rectangle" else min(w, h) / 2
        rounded = shape == "rectangle" and radius > 0
        self._element(
            {
                "id": key,
                "type": shape,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "strokeColor": stroke,
                "backgroundColor": fill,
                "fillStyle": "solid",
                "roundness": {"type": 3} if rounded else None,
                "boundElements": [{"id": text_id, "type": "text"}],
            }
        )
        self._element(
            {
                "id": text_id,
                "type": "text",
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "strokeColor": stroke,
                "text": label,
                "originalText": label,
                "fontSize": size,
                "fontFamily": font,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": key,
                "lineHeight": LINE_HEIGHT,
                "autoResize": False,
            }
        )

        svg_fill = "none" if fill == "transparent" else fill
        if shape == "ellipse":
            self._svg.append(
                f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" '
                f'fill="{svg_fill}" stroke="{stroke}" stroke-width="2"/>'
            )
        else:
            self._svg.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
                f'fill="{svg_fill}" stroke="{stroke}" stroke-width="2"/>'
            )
        self._svg_text(label, x + w / 2, y + h / 2, size, font, stroke, "middle", centred=True)
        return (x, y, w, h)

    def label(
        self,
        key: str,
        x: float,
        y: float,
        text: str,
        style: str = "plain",
        font: int = FONT_CODE,
        size: int = 13,
        align: str = "left",
    ) -> None:
        stroke, _ = PALETTE[style]
        lines = text.split("\n")
        width = max(len(line) for line in lines) * size * 0.6
        height = len(lines) * size * LINE_HEIGHT
        self._element(
            {
                "id": key,
                "type": "text",
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "strokeColor": stroke,
                "text": text,
                "originalText": text,
                "fontSize": size,
                "fontFamily": font,
                "textAlign": align,
                "verticalAlign": "top",
                "containerId": None,
                "lineHeight": LINE_HEIGHT,
            }
        )
        anchor = {"left": "start", "center": "middle", "right": "end"}[align]
        self._svg_text(text, x, y, size, font, stroke, anchor, centred=False)

    def arrow(
        self,
        key: str,
        start: tuple[float, float],
        end: tuple[float, float],
        style: str = "plain",
        dashed: bool = False,
        label: str | None = None,
    ) -> None:
        stroke, _ = PALETTE[style]
        x1, y1 = start
        x2, y2 = end
        self._element(
            {
                "id": key,
                "type": "arrow",
                "x": x1,
                "y": y1,
                "width": abs(x2 - x1),
                "height": abs(y2 - y1),
                "strokeColor": stroke,
                "strokeStyle": "dashed" if dashed else "solid",
                "points": [[0, 0], [x2 - x1, y2 - y1]],
                "startArrowhead": None,
                "endArrowhead": "arrow",
                "roundness": {"type": 2},
            }
        )
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        self._svg.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
            f'stroke-width="2"{dash} marker-end="url(#head-{style})"/>'
        )
        if label:
            self._svg_text(
                label,
                (x1 + x2) / 2,
                (y1 + y2) / 2 - 8,
                12,
                FONT_CODE,
                stroke,
                "middle",
                centred=False,
            )

    def path(
        self,
        key: str,
        points: list[tuple[float, float]],
        style: str = "plain",
        dashed: bool = False,
        label: str | None = None,
        label_at: tuple[float, float] | None = None,
    ) -> None:
        """An arrow with corners, for a route that would otherwise cross a box."""
        stroke, _ = PALETTE[style]
        x0, y0 = points[0]
        rel = [[x - x0, y - y0] for x, y in points]
        self._element(
            {
                "id": key,
                "type": "arrow",
                "x": x0,
                "y": y0,
                "width": max(p[0] for p in rel) - min(p[0] for p in rel),
                "height": max(p[1] for p in rel) - min(p[1] for p in rel),
                "strokeColor": stroke,
                "strokeStyle": "dashed" if dashed else "solid",
                "points": rel,
                "startArrowhead": None,
                "endArrowhead": "arrow",
                "roundness": {"type": 2},
            }
        )
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        pts = " ".join(f"{x},{y}" for x, y in points)
        self._svg.append(
            f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="2"{dash} '
            f'stroke-linejoin="round" marker-end="url(#head-{style})"/>'
        )
        if label and label_at:
            self._svg_text(label, label_at[0], label_at[1], 12, FONT_CODE, stroke, "middle", False)

    # -- internals ---------------------------------------------------------

    def _element(self, partial: dict) -> None:
        seed = _seed(partial["id"])
        base = {
            "angle": 0,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": "solid",
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "index": _index(len(self.elements)),
            "roundness": None,
            "seed": seed,
            "version": 1,
            "versionNonce": seed,
            "isDeleted": False,
            "boundElements": None,
            # A fixed timestamp. A wall clock here would make every rebuild a diff.
            "updated": 1,
            "link": None,
            "locked": False,
        }
        base.update(partial)
        self.elements.append(base)

    def _svg_text(
        self,
        text: str,
        x: float,
        y: float,
        size: int,
        font: int,
        colour: str,
        anchor: str,
        centred: bool,
    ) -> None:
        lines = text.split("\n")
        step = size * LINE_HEIGHT
        top = y - (len(lines) - 1) * step / 2 + size * 0.35 if centred else y + size
        parts = []
        for i, line in enumerate(lines):
            parts.append(
                f'<text x="{x}" y="{top + i * step:.1f}" font-family="{SVG_FONT[font]}" '
                f'font-size="{size}" fill="{colour}" text-anchor="{anchor}" '
                f'xml:space="preserve">{sax.escape(line)}</text>'
            )
        self._svg.extend(parts)

    def _bounds(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for el in self.elements:
            if el["type"] == "arrow":
                for dx, dy in el["points"]:
                    xs.append(el["x"] + dx)
                    ys.append(el["y"] + dy)
            else:
                xs += [el["x"], el["x"] + el["width"]]
                ys += [el["y"], el["y"] + el["height"]]
        return min(xs), min(ys), max(xs), max(ys)

    # -- output ------------------------------------------------------------

    def save(self, stem: Path, title: str) -> None:
        stem.parent.mkdir(parents=True, exist_ok=True)
        stem.with_suffix(".excalidraw").write_text(self.to_excalidraw(), encoding="utf-8")
        stem.with_suffix(".svg").write_text(self.to_svg(title), encoding="utf-8")
        print(f"diagram: {stem.name}.excalidraw and {stem.name}.svg")

    def to_excalidraw(self) -> str:
        doc = {
            "type": "excalidraw",
            "version": 2,
            "source": "https://github.com/tamnd/llvm-internals",
            "elements": self.elements,
            "appState": {"gridSize": 20, "viewBackgroundColor": "#ffffff"},
            "files": {},
        }
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

    def to_svg(self, title: str) -> str:
        x0, y0, x1, y1 = self._bounds()
        pad = self.padding
        width = x1 - x0 + 2 * pad
        height = y1 - y0 + 2 * pad
        markers = "".join(
            f'<marker id="head-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{stroke}"/></marker>'
            for name, (stroke, _) in PALETTE.items()
        )
        body = "\n  ".join(self._svg)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="{x0 - pad:.0f} {y0 - pad:.0f} {width:.0f} {height:.0f}" '
            f'role="img" aria-label="{sax.escape(title)}">\n'
            f"  <title>{sax.escape(title)}</title>\n"
            f"  <defs>{markers}</defs>\n"
            f'  <rect x="{x0 - pad:.0f}" y="{y0 - pad:.0f}" width="{width:.0f}" '
            f'height="{height:.0f}" fill="#ffffff"/>\n'
            f"  {body}\n"
            f"</svg>\n"
        )
