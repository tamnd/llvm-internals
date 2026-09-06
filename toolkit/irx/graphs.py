"""LLVM's own graphs, drawn where a reader can see them.

Every graph in here comes out of LLVM. Nothing in this file works out what the
successors of a block are, or which block dominates which. `opt` has printers
for all of it, they are in a release build, and they write Graphviz `.dot` to
the working directory. This module runs one of them, reads what it wrote, and
turns it into a picture. When the graph is wrong it is LLVM that is wrong, which
is the only arrangement worth having in a book that teaches people to go and
look.

Two things are worth saying out loud about the choice of graphs.

The SelectionDAG viewers, `-view-isel-dags` and the rest of that family, are not
here. They only exist in an assertions build: every one of those options is
declared inside `#ifndef NDEBUG`, and the `#else` branch replaces them with
`static const bool ... = false`, so on a release toolchain the flag is not
merely off, it is not a flag
(`llvm/lib/CodeGen/SelectionDAG/SelectionDAGISel.cpp:147-189@llvmorg-23.1.0`).
A reader who installed LLVM from a package manager cannot have them, so a lesson
cannot use them. What a release `opt` will give you is here instead, and the
data dependence graph is the one of these that is genuinely a DAG.

There is no Graphviz here either. `dot` is not installed on every machine this
course has to run on, and shelling out to it would mean a lesson that renders on
the author's laptop and prints a stack trace in Colab. The layout below is
ordinary layered drawing, about eighty lines of it, and the output is one inline
SVG element with no script in it, so it survives being saved into a notebook and
served as static HTML.
"""

from __future__ import annotations

import hashlib
import html
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .ir import COLOUR, KEYWORDS, TOKEN, Module
from .proc import run

# The pass name, and the shape of the file it leaves behind. `opt` prints
# `Writing '<name>'...` as it goes, but matching on a glob is steadier than
# parsing a progress message that has changed wording before.
KINDS = {
    "cfg": ("dot-cfg", "*.dot", "the control flow graph, with each block's instructions"),
    "cfg-only": ("dot-cfg-only", "*.dot", "the control flow graph, blocks named only"),
    "dom": ("dot-dom", "dom.*.dot", "the dominator tree"),
    "post-dom": ("dot-post-dom", "postdom.*.dot", "the post dominator tree"),
    "ddg": ("dot-ddg", "ddg.*.dot", "the data dependence graph"),
    "callgraph": ("dot-callgraph", "*.callgraph.dot", "who calls whom"),
}


# -- reading what LLVM wrote --------------------------------------------------

NODE = re.compile(r"^\s*(Node0x[0-9a-fA-F]+)\s*\[(?P<attrs>.*)\];\s*$")
EDGE = re.compile(
    r"^\s*(Node0x[0-9a-fA-F]+)(?::(?P<port>\w+))?\s*->\s*"
    r"(Node0x[0-9a-fA-F]+)(?::\w+)?\s*(?:\[(?P<attrs>.*)\])?;\s*$"
)
LABEL = re.compile(r'label\s*=\s*"((?:[^"\\]|\\.)*)"')
GRAPH_LABEL = re.compile(r'^\s*label\s*=\s*"((?:[^"\\]|\\.)*)"\s*;\s*$')
PORT = re.compile(r"^<(?P<name>\w+)>(?P<text>.*)$", re.S)


def _unescape(raw: str) -> str:
    """Graphviz label escapes, flattened to plain text.

    `\\l` and `\\n` are both line breaks as far as this is concerned; the
    difference between them is justification, and the boxes here are left
    aligned regardless.
    """
    out: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            following = raw[index + 1]
            out.append("\n" if following in "lnr" else following)
            index += 2
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _split(raw: str) -> list[str]:
    """Split a record label on the bars that are structure, not text.

    A bar inside braces belongs to a nested record, and a backslashed bar is a
    bar somebody wanted to print. Neither is a field separator, which is the
    entire reason this is not `raw.split("|")`.
    """
    fields: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "|" and depth == 0:
            fields.append(raw[start:index])
            start = index + 1
        index += 1
    fields.append(raw[start:])
    return fields


@dataclass
class Node:
    """One box. `title` is the block or function name, `lines` is what is in it."""

    key: str
    title: str
    lines: list[str] = field(default_factory=list)
    ports: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.title or self.key


@dataclass
class Edge:
    src: str
    dst: str
    label: str = ""
    back: bool = False


def _node(key: str, attrs: str) -> Node:
    match = LABEL.search(attrs)
    if not match:
        return Node(key=key, title="")
    raw = match.group(1).strip()
    if raw.startswith("{") and raw.endswith("}"):
        raw = raw[1:-1]
    fields = _split(raw)

    ports: dict[str, str] = {}
    tail = fields[-1].strip()
    if len(fields) > 1 and tail.startswith("{") and tail.endswith("}"):
        for piece in _split(tail[1:-1]):
            port = PORT.match(piece.strip())
            if port:
                ports[port.group("name")] = _unescape(port.group("text")).strip()
        fields = fields[:-1]

    title = ""
    if len(fields) > 1:
        title = _unescape(fields[0]).strip().rstrip(":")
        fields = fields[1:]

    lines: list[str] = []
    for piece in fields:
        lines += [line for line in _unescape(piece).split("\n") if line.strip()]
    # A single field graph, the call graph being the one that matters, has the
    # name in the body rather than in a title field. Promote it, so every node
    # has something to be called.
    if not title and len(lines) == 1:
        title, lines = lines[0].strip(), []
    return Node(key=key, title=title, lines=lines, ports=ports)


def parse(dot: str) -> tuple[str, list[Node], list[Edge]]:
    """Graphviz in, a caption and a graph out. Pointer names never leave here.

    LLVM names its nodes after the address of the object they came from, so the
    same function printed twice gives two different files. Everything downstream
    of this function uses `n0`, `n1` and so on, in the order the nodes appear,
    which is stable enough to put in a test.
    """
    caption = ""
    nodes: list[Node] = []
    edges: list[Edge] = []
    keys: dict[str, str] = {}

    def key_for(pointer: str) -> str:
        if pointer not in keys:
            keys[pointer] = f"n{len(keys)}"
        return keys[pointer]

    for line in dot.splitlines():
        if not caption:
            heading = GRAPH_LABEL.match(line)
            if heading:
                caption = _unescape(heading.group(1)).strip()
                continue
        edge = EDGE.match(line)
        if edge:
            label = edge.group("port") or ""
            attrs = edge.group("attrs") or ""
            named = LABEL.search(attrs)
            if named:
                label = _unescape(named.group(1)).strip().strip("[]")
            edges.append(Edge(src=key_for(edge.group(1)), dst=key_for(edge.group(3)), label=label))
            continue
        found = NODE.match(line)
        if found:
            nodes.append(_node(key_for(found.group(1)), found.group("attrs")))
    return caption, nodes, edges


def _label_ports(nodes: list[Node], edges: list[Edge]) -> None:
    """Turn `:s0` and `:s1` into the T and F the record label spelled out."""
    by_key = {node.key: node for node in nodes}
    for edge in edges:
        node = by_key.get(edge.src)
        if node and edge.label in node.ports:
            edge.label = node.ports[edge.label]


# -- getting one --------------------------------------------------------------


class GraphError(RuntimeError):
    """Asked for a graph that this module or this pass did not produce."""


def graph(module: Module | str, kind: str = "cfg", function: str | None = None) -> Graph:
    """Run one of LLVM's graph printers and hand back what it drew.

    `function` picks between the files when the module has more than one, by the
    name in the file `opt` wrote. Leaving it out is fine for a one function
    module and an error otherwise, with the available names in the message,
    because guessing which function the reader meant is how a lesson ends up
    quietly showing the wrong graph.
    """
    if kind not in KINDS:
        raise GraphError(f"{kind!r} is not one of {', '.join(KINDS)}.")
    pass_name, pattern, _ = KINDS[kind]
    text = module.text if isinstance(module, Module) else module

    with tempfile.TemporaryDirectory(prefix="irx-graph-") as tmp:
        work = Path(tmp)
        (work / "in.ll").write_text(text, encoding="utf-8")
        run("opt", f"-passes={pass_name}", "-disable-output", "in.ll", cwd=work)
        written = sorted(work.glob(pattern))
        if not written:
            raise GraphError(
                f"`opt -passes={pass_name}` wrote no graph for this module. "
                "The printers only emit for functions with a body, so a module of "
                "declarations produces nothing."
            )
        chosen = _choose(written, kind, function)
        dot = chosen.read_text(encoding="utf-8")

    caption, nodes, edges = parse(dot)
    # The call graph puts the input file name in its caption, and the input file
    # here is a temporary directory nobody will ever see. Say the module's name
    # instead, which is what the reader called it.
    if isinstance(module, Module):
        caption = caption.replace("in.ll", module.name)
    _label_ports(nodes, edges)
    _mark_back_edges(nodes, edges)
    return Graph(kind=kind, caption=caption, nodes=nodes, edges=edges, dot=dot)


def _choose(written: list[Path], kind: str, function: str | None) -> Path:
    """One file out of the several a multi function module produces."""
    def named(path: Path) -> str:
        # `.f.dot`, `dom.f.dot`, `ddg.f..dot`, `in.ll.callgraph.dot`. The name is
        # whatever is left once the prefix and the extensions are taken off.
        stem = path.name.removesuffix(".dot")
        for prefix in ("dom.", "postdom.", "ddg."):
            stem = stem.removeprefix(prefix)
        return stem.strip(".").removesuffix(".callgraph")

    if function is not None:
        for path in written:
            if named(path) == function:
                return path
        raise GraphError(
            f"No {kind} graph for {function!r}. This module has "
            f"{', '.join(repr(named(p)) for p in written)}."
        )
    if len(written) > 1:
        raise GraphError(
            f"This module has more than one {kind} graph, so say which: "
            f"{', '.join(repr(named(p)) for p in written)}."
        )
    return written[0]


def cfg(module: Module | str, function: str | None = None, *, bodies: bool = True) -> Graph:
    """The control flow graph, which is the one Part I wants."""
    return graph(module, "cfg" if bodies else "cfg-only", function)


def dom(module: Module | str, function: str | None = None) -> Graph:
    return graph(module, "dom", function)


def ddg(module: Module | str, function: str | None = None) -> Graph:
    return graph(module, "ddg", function)


def callgraph(module: Module | str) -> Graph:
    return graph(module, "callgraph")


# -- ranking ------------------------------------------------------------------


def _mark_back_edges(nodes: list[Node], edges: list[Edge]) -> None:
    """A depth first walk, and every edge back into the current stack is a loop.

    Done here rather than at drawing time because `back` is a fact about the
    graph and shows up in the text form too. A back edge in a CFG is a loop, and
    a reader who cannot see which edge that is has not been shown the loop.
    """
    out: dict[str, list[Edge]] = {node.key: [] for node in nodes}
    for edge in edges:
        if edge.src in out:
            out[edge.src].append(edge)

    colour: dict[str, int] = dict.fromkeys(out, 0)  # 0 white, 1 on the stack, 2 done
    for start in out:
        if colour[start]:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        colour[start] = 1
        while stack:
            key, index = stack[-1]
            if index == len(out[key]):
                colour[key] = 2
                stack.pop()
                continue
            stack[-1] = (key, index + 1)
            edge = out[key][index]
            if colour.get(edge.dst, 2) == 1:
                edge.back = True
            elif colour.get(edge.dst, 2) == 0:
                colour[edge.dst] = 1
                stack.append((edge.dst, 0))


def _ranks(nodes: list[Node], edges: list[Edge]) -> dict[str, int]:
    """How far down the page each node goes: one past its furthest predecessor.

    Longest path rather than shortest, so an edge never points upward except the
    back edges, which were taken out of the graph before this ran.
    """
    forward = [e for e in edges if not e.back and e.src != e.dst]
    incoming: dict[str, int] = dict.fromkeys((n.key for n in nodes), 0)
    for edge in forward:
        if edge.dst in incoming:
            incoming[edge.dst] += 1

    rank = dict.fromkeys(incoming, 0)
    ready = [n.key for n in nodes if incoming[n.key] == 0]
    seen = 0
    while ready:
        key = ready.pop(0)
        seen += 1
        for edge in forward:
            if edge.src != key or edge.dst not in incoming:
                continue
            rank[edge.dst] = max(rank[edge.dst], rank[key] + 1)
            incoming[edge.dst] -= 1
            if incoming[edge.dst] == 0:
                ready.append(edge.dst)
    # A cycle the back edge walk did not break would leave nodes unplaced. It
    # should not happen, and if it does, putting them at the bottom is better
    # than dropping them off the picture.
    if seen < len(nodes):
        floor = max(rank.values(), default=0) + 1
        for node in nodes:
            if incoming[node.key] > 0:
                rank[node.key] = floor
    return rank


# -- drawing ------------------------------------------------------------------

CHAR_W = 7.0          # ui-monospace at 11.5px, near enough for a box width
LINE_H = 15.0
TITLE_H = 19.0
PAD_X, PAD_Y = 9.0, 7.0
GAP_X, GAP_Y = 34.0, 44.0
MARGIN = 12.0
FRAME = "#d0d7de"
INK = "#24292f"
QUIET = "#57606a"
FLOW = "#0969da"
LOOP = "#8250df"


@dataclass
class Box:
    node: Node
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def _boxes(nodes: list[Node], rank: dict[str, int]) -> list[Box]:
    boxes = []
    for node in nodes:
        width = max([len(line) for line in node.lines] + [len(node.title) + 2])
        boxes.append(
            Box(
                node=node,
                w=width * CHAR_W + 2 * PAD_X,
                h=(TITLE_H if node.title else 0) + len(node.lines) * LINE_H + 2 * PAD_Y,
            )
        )

    rows: dict[int, list[Box]] = {}
    for box in boxes:
        rows.setdefault(rank[box.node.key], []).append(box)

    top = MARGIN
    for index in sorted(rows):
        row = rows[index]
        span = sum(b.w for b in row) + GAP_X * (len(row) - 1)
        left = -span / 2
        for box in row:
            box.x, box.y = left, top
            left += box.w + GAP_X
        top += max(b.h for b in row) + GAP_Y

    shift = MARGIN - min(b.x for b in boxes)
    for box in boxes:
        box.x += shift
    return boxes


def _tspans(line: str, x: float, y: float) -> str:
    """One line of IR as coloured SVG, using the same palette as the diff view."""
    pieces = []
    position = 0
    for match in TOKEN.finditer(line):
        pieces.append((line[position : match.start()], ""))
        kind = match.lastgroup or ""
        value = match.group()
        if kind == "word":
            kind = "keyword" if value in KEYWORDS else ""
        pieces.append((value, COLOUR.get(kind, "")))
        position = match.end()
    pieces.append((line[position:], ""))

    spans = []
    for text, colour in pieces:
        if not text:
            continue
        fill = f' fill="{colour}"' if colour else ""
        weight = ' font-weight="600"' if colour == COLOUR["keyword"] else ""
        spans.append(f'<tspan{fill}{weight}>{html.escape(text)}</tspan>')
    return f'<text x="{x:.1f}" y="{y:.1f}" xml:space="preserve">{"".join(spans)}</text>'


def _curve(a: tuple[float, float], b: tuple[float, float]) -> str:
    lift = min(28.0, max(10.0, (b[1] - a[1]) / 2))
    return (
        f"M {a[0]:.1f} {a[1]:.1f} C {a[0]:.1f} {a[1] + lift:.1f}, "
        f"{b[0]:.1f} {b[1] - lift:.1f}, {b[0]:.1f} {b[1]:.1f}"
    )


def _side(box_a: Box, box_b: Box, lane: float, side: int) -> str:
    """Out of one side, along a lane in the margin, and back in at the same side.

    For the two edges that cannot be a short hop between neighbouring rows: a
    back edge, which goes up, and a forward edge that skips a row, which would
    otherwise be drawn straight through whatever box is sitting in between.
    """
    edge_a = box_a.x + box_a.w if side > 0 else box_a.x
    edge_b = box_b.x + box_b.w if side > 0 else box_b.x
    corner = 8 * side
    up = -8 if box_b.cy < box_a.cy else 8
    return (
        f"M {edge_a:.1f} {box_a.cy:.1f} H {lane - corner:.1f} "
        f"Q {lane:.1f} {box_a.cy:.1f} {lane:.1f} {box_a.cy + up:.1f} "
        f"V {box_b.cy - up:.1f} Q {lane:.1f} {box_b.cy:.1f} {lane - corner:.1f} {box_b.cy:.1f} "
        f"H {edge_b:.1f}"
    )


def _self(box: Box, lane: float) -> str:
    """A block that branches to itself, which is the tightest loop there is."""
    top, bottom = box.y + box.h / 3, box.y + 2 * box.h / 3
    right = box.x + box.w
    return (
        f"M {right:.1f} {bottom:.1f} H {lane - 8:.1f} Q {lane:.1f} {bottom:.1f} "
        f"{lane:.1f} {bottom - 8:.1f} V {top + 8:.1f} Q {lane:.1f} {top:.1f} "
        f"{lane - 8:.1f} {top:.1f} H {right:.1f}"
    )


# How far apart two edges leaving the same box are pulled, so that a T and an F
# out of one terminator are two arrows rather than one arrow with two labels
# printed on top of each other.
SPREAD = 26.0
LANE = 15.0


def _spread(box: Box, count: int) -> float:
    """How far apart to put them, without walking off the edge of the box."""
    if count < 2:
        return 0.0
    return min(SPREAD, max(10.0, (box.w - 20) / (count - 1)))


def _fan(edges: list[Edge], pick: str) -> dict[int, tuple[int, int]]:
    """Which of its siblings each edge is, at whichever end `pick` names."""
    groups: dict[str, list[Edge]] = {}
    for edge in edges:
        groups.setdefault(getattr(edge, pick), []).append(edge)
    spot = {}
    for group in groups.values():
        for index, edge in enumerate(group):
            spot[id(edge)] = (index, len(group))
    return spot


def _svg(g: Graph) -> str:
    rank = _ranks(g.nodes, g.edges)
    boxes = _boxes(g.nodes, rank)
    at = {box.node.key: box for box in boxes}

    loops, skips, short = [], [], []
    for edge in g.edges:
        if edge.back:
            loops.append(edge)
        elif rank[edge.dst] - rank[edge.src] > 1:
            skips.append(edge)
        else:
            short.append(edge)
    # The fan is over the short edges only. The long ones leave from the side of
    # the box rather than the bottom, so counting them here would push the short
    # ones off centre to make room for an arrow that is not there.
    from_source = _fan(short, "src")
    to_target = _fan(short, "dst")

    # Lanes live outside the boxes, so the drawing has to make room for them
    # before anything is placed. Skipping edges go down the left, loops up the
    # right, which keeps the two kinds of long edge from sharing a corridor.
    left_pad = LANE * (len(skips) + 1) if skips else 0.0
    for box in boxes:
        box.x += left_pad
    right = max(box.x + box.w for box in boxes)
    # The extra 24 is where the T or the F on a back edge goes. Without it the
    # label sits on top of the dashed line it belongs to.
    width = right + MARGIN + (LANE * len(loops) + 24 if loops else 0.0)
    height = max(box.y + box.h for box in boxes) + MARGIN

    # A content hash, not id() or hash(), so the same graph gives the same
    # marker id every time. A notebook that is rebuilt should have a byte
    # identical diff or none at all.
    ident = "irxg" + hashlib.sha256(g.dot.encode()).hexdigest()[:8]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{min(width, 900):.0f}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" '
        f'font-size="11.5" fill="{INK}">',
        f'<defs><marker id="{ident}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" '
        f'markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="{QUIET}"/>'
        f'</marker><marker id="{ident}l" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" '
        f'markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="{LOOP}"/>'
        "</marker></defs>",
    ]

    def label_at(
        edge: Edge, x: float, y: float, colour: str = FLOW, anchor: str = "middle"
    ) -> None:
        if edge.label:
            parts.append(
                f'<text x="{x:.1f}" y="{y:.1f}" fill="{colour}" font-size="10.5" '
                f'text-anchor="{anchor}">{html.escape(edge.label)}</text>'
            )

    for index, edge in enumerate(loops):
        lane = right + LANE * (index + 1)
        source, target = at[edge.src], at[edge.dst]
        path = _self(source, lane) if edge.src == edge.dst else _side(source, target, lane, 1)
        parts.append(
            f'<path d="{path}" fill="none" stroke="{LOOP}" stroke-width="1.2" '
            f'stroke-dasharray="4 3" marker-end="url(#{ident}l)"/>'
        )
        middle = source.cy if edge.src == edge.dst else (source.cy + target.cy) / 2
        label_at(edge, lane + 5, middle + 3, LOOP, "start")

    for index, edge in enumerate(skips):
        lane = left_pad - LANE * (index + 1)
        source, target = at[edge.src], at[edge.dst]
        parts.append(
            f'<path d="{_side(source, target, lane, -1)}" fill="none" stroke="{FRAME}" '
            f'stroke-width="1.2" marker-end="url(#{ident})"/>'
        )
        label_at(edge, lane + 5, (source.cy + target.cy) / 2 + 3, FLOW, "start")

    for edge in short:
        a, b = at[edge.src], at[edge.dst]
        out_of, out_count = from_source[id(edge)]
        into, in_count = to_target[id(edge)]
        start = (a.cx + (out_of - (out_count - 1) / 2) * _spread(a, out_count), a.y + a.h)
        end = (b.cx + (into - (in_count - 1) / 2) * _spread(b, in_count), b.y - 3)
        parts.append(
            f'<path d="{_curve(start, end)}" fill="none" stroke="{FRAME}" '
            f'stroke-width="1.2" marker-end="url(#{ident})"/>'
        )
        # Two rows of labels, alternating. A block with four successors has its
        # arrows a couple of dozen pixels apart and the word `def-use` is wider
        # than that, so on one row they would sit on top of each other.
        label_at(edge, start[0], start[1] + 13 + (out_of % 2) * 12)

    for box in boxes:
        node = box.node
        parts.append(
            f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
            f'rx="6" fill="#fbfbfb" stroke="{FRAME}"/>'
        )
        top = box.y + PAD_Y
        if node.title:
            parts.append(
                f'<text x="{box.x + PAD_X:.1f}" y="{top + 11:.1f}" fill="{QUIET}" '
                f'font-weight="600">{html.escape(node.title)}</text>'
            )
            top += TITLE_H
        for offset, line in enumerate(node.lines):
            parts.append(_tspans(line, box.x + PAD_X, top + 11 + offset * LINE_H))

    parts.append("</svg>")
    return "".join(parts)


@dataclass(repr=False)
class Graph:
    """What one of LLVM's graph printers produced, as text or as a picture."""

    kind: str
    caption: str
    nodes: list[Node]
    edges: list[Edge]
    dot: str

    @property
    def loops(self) -> list[Edge]:
        """The back edges. In a CFG, one of these is one loop."""
        return [edge for edge in self.edges if edge.back]

    def successors(self, name: str) -> list[str]:
        by_key = {node.key: node for node in self.nodes}
        return [
            by_key[edge.dst].name
            for edge in self.edges
            if by_key.get(edge.src) is not None and by_key[edge.src].name == name
        ]

    def __str__(self) -> str:
        lines = [self.caption or f"{self.kind} graph", ""]
        by_key = {node.key: node for node in self.nodes}
        for node in self.nodes:
            lines.append(f"  {node.name}")
            lines += [f"      {line}" for line in node.lines]
            for edge in self.edges:
                if edge.src != node.key:
                    continue
                arrow = "=>" if edge.back else "->"
                tag = f"{edge.label} " if edge.label else ""
                lines.append(f"    {tag}{arrow} {by_key[edge.dst].name}")
            lines.append("")
        if self.loops:
            lines.append(f"  {len(self.loops)} back edge(s), drawn with =>")
        return "\n".join(lines).rstrip() + "\n"

    def __repr__(self) -> str:
        return str(self)

    def svg(self) -> str:
        """The picture on its own, for writing to a file."""
        return _svg(self)

    def _repr_html_(self) -> str:
        caption = html.escape(self.caption or f"{self.kind} graph")
        return (
            f'<div><p style="margin:0 0 4px 0;color:{QUIET};font-size:12px">{caption}, '
            f"as <code>opt -passes={KINDS[self.kind][0]}</code> drew it</p>"
            f'<div style="overflow-x:auto">{_svg(self)}</div></div>'
        )


__all__ = ["Edge", "Graph", "GraphError", "Node", "callgraph", "cfg", "ddg", "dom", "graph"]
