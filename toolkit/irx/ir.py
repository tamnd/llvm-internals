"""A piece of LLVM IR you can hold onto, run passes over, and look at.

This is the object almost every lesson passes around. It is a thin wrapper over
a string of textual IR, on purpose. There is no object model here and no attempt
to parse anything, because the moment this file starts modelling IR it starts
being wrong in ways that survive an upgrade, and the whole point of the material
is that what you see is what the real tools printed.

So a `Module` holds text, and every method shells out to a real binary and hands
back the text that came out. What the class adds is the part that a raw
subprocess call does not give you in a notebook: it renders readably, it can
show you what a pass changed rather than just the after picture, and when
something fails it says which tool failed and why.
"""

from __future__ import annotations

import difflib
import html
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import plugin
from .proc import ToolError, run

# Keywords worth colouring. This is not the full grammar and does not try to be.
# It is the set of words that show up in the IR a reader looks at in the first
# few lessons, plus the ones that carry meaning people miss, like `nsw` and
# `poison`.
KEYWORDS = {
    "define", "declare", "ret", "br", "switch", "call", "tail", "musttail",
    "invoke", "unreachable", "alloca", "load", "store", "getelementptr",
    "inbounds", "phi", "select", "icmp", "fcmp", "zext", "sext", "trunc",
    "bitcast", "inttoptr", "ptrtoint", "add", "sub", "mul", "udiv", "sdiv",
    "urem", "srem", "shl", "lshr", "ashr", "and", "or", "xor", "fadd", "fsub",
    "fmul", "fdiv", "nsw", "nuw", "exact", "fast", "nnan", "ninf", "nsz",
    "poison", "undef", "null", "zeroinitializer", "true", "false", "global",
    "constant", "internal", "private", "external", "linkonce_odr", "weak",
    "dso_local", "nocapture", "noundef", "readonly", "writeonly", "nounwind",
    "willreturn", "speculatable", "memory", "align", "to", "eq", "ne", "sgt",
    "sge", "slt", "sle", "ugt", "uge", "ult", "ule", "attributes", "source_filename",
    "target", "datalayout", "triple", "type", "label", "freeze", "extractvalue",
    "insertvalue", "landingpad", "resume", "atomicrmw", "cmpxchg", "fence",
}

COLOUR = {
    "comment": "#6a737d",
    "local": "#005cc5",
    "global": "#6f42c1",
    "meta": "#8a8a8a",
    "type": "#0e7490",
    "keyword": "#b31d28",
    "number": "#b45309",
    "string": "#0a7d37",
}

TOKEN = re.compile(
    r"(?P<comment>;[^\n]*)"
    r"|(?P<string>c?\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<meta>![A-Za-z_.$][\w.$]*|![0-9]+)"
    r"|(?P<local>%[\w.$-]+|%\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<global>@[\w.$-]+|@\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<type>\b(?:i1|i8|i16|i32|i64|i128|half|bfloat|float|double|fp128|ptr|void|token|x86_fp80)\b)"
    r"|(?P<word>[A-Za-z_][\w.]*)"
    r"|(?P<number>\b-?(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?(?:e[-+]?\d+)?)\b)"
)


def highlight(text: str) -> str:
    """LLVM IR to coloured HTML. Small on purpose, see the module docstring."""
    out: list[str] = []
    position = 0
    for match in TOKEN.finditer(text):
        out.append(html.escape(text[position : match.start()]))
        kind = match.lastgroup or ""
        value = match.group()
        if kind == "word":
            kind = "keyword" if value in KEYWORDS else ""
        if kind and kind in COLOUR:
            weight = ";font-weight:600" if kind == "keyword" else ""
            out.append(f'<span style="color:{COLOUR[kind]}{weight}">{html.escape(value)}</span>')
        else:
            out.append(html.escape(value))
        position = match.end()
    out.append(html.escape(text[position:]))
    return "".join(out)


PRE = (
    "margin:0;padding:10px 12px;background:#fbfbfb;border:1px solid #e3e3e3;"
    "border-radius:6px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,"
    "Menlo,monospace;font-size:12.5px;line-height:1.45"
)
CAPTION = "margin:0 0 4px 0;color:#57606a;font-size:12px"

MODULE_ID = re.compile(r"^; ModuleID = '.*'$", re.M)


def _block(body: str, caption: str = "") -> str:
    head = f'<p style="{CAPTION}">{html.escape(caption)}</p>' if caption else ""
    return f'<div>{head}<pre style="{PRE}">{body}</pre></div>'


@dataclass(repr=False)
class Module:
    """Textual LLVM IR, plus the operations a lesson wants to do to it."""

    text: str
    name: str = "module"
    history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # The `; ModuleID` line is the name of the file the tool read, so it says
        # `-` coming out of clang and `<stdin>` coming out of opt. Left alone it
        # is the first line of every single before and after diff in the whole
        # course, and it means nothing. Pin it to this module's name instead, so
        # a diff only shows things a pass actually did.
        self.text = MODULE_ID.sub(f"; ModuleID = '{self.name}'", self.text, count=1)

    # -- getting one ---------------------------------------------------------

    @classmethod
    def from_ll(cls, text: str, name: str = "module") -> "Module":
        return cls(text=text.strip() + "\n", name=name)

    @classmethod
    def from_file(cls, path: str | Path) -> "Module":
        path = Path(path)
        return cls.from_ll(path.read_text(encoding="utf-8"), name=path.stem)

    @classmethod
    def from_c(
        cls,
        source: str,
        opt: str = "-O0",
        std: str = "c17",
        target: str | None = None,
        extra: tuple[str, ...] = (),
        name: str = "from_c",
    ) -> "Module":
        """Compile C to IR with the pinned clang.

        `-O0` by default because the first thing most lessons want to show is
        what the front end emits before anything has cleaned it up, and at `-O1`
        and above the interesting mess is already gone. `-Xclang
        -disable-O0-optnone` is passed for you, because without it clang marks
        every function `optnone` at `-O0` and then every pass you run does
        nothing, which is a confusing half hour for a lot of people.
        """
        args = [
            "-x", "c", f"-std={std}", opt, "-S", "-emit-llvm",
            "-Xclang", "-disable-O0-optnone",
            "-fno-discard-value-names", "-o", "-", "-",
        ]
        if target:
            args = ["-target", target, *args]
        result = run("clang", *args, *extra, stdin=source)
        return cls(text=result.stdout, name=name)

    @classmethod
    def from_cpp(
        cls,
        source: str,
        opt: str = "-O0",
        std: str = "c++20",
        target: str | None = None,
        extra: tuple[str, ...] = (),
        name: str = "from_cpp",
    ) -> "Module":
        args = [
            "-x", "c++", f"-std={std}", opt, "-S", "-emit-llvm",
            "-Xclang", "-disable-O0-optnone",
            "-fno-discard-value-names", "-o", "-", "-",
        ]
        if target:
            args = ["-target", target, *args]
        result = run("clang++", *args, *extra, stdin=source)
        return cls(text=result.stdout, name=name)

    # -- looking at it -------------------------------------------------------

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    @property
    def functions(self) -> list[str]:
        """Names of functions with a body. Declarations are not included."""
        return re.findall(r"^define[^@]*@\"?([\w.$-]+)", self.text, re.M)

    @property
    def declarations(self) -> list[str]:
        return re.findall(r"^declare[^@]*@\"?([\w.$-]+)", self.text, re.M)

    def function(self, name: str) -> str:
        """A module containing just this function, which is what you want once a
        module grows.

        Note that this is a whole module, header and attribute groups included,
        not the function on its own, because llvm-extract is what produces it
        and a bare function is not something LLVM will read back. Use `body`
        when you want the define block by itself.
        """
        result = run("llvm-extract", "-func", name, "-S", "-", stdin=self.text)
        return result.stdout

    def body(self, name: str) -> str:
        """The define block on its own, from `define` to the closing brace.

        Printing a function is the single most common thing a lesson does, and
        `function` buries a two line body under a target triple and a screen of
        target features that differ per machine and teach nobody anything.
        """
        match = re.search(rf"^define[^@\n]*@\"?{re.escape(name)}\"?\b.*?^}}",
                          self.text, re.MULTILINE | re.DOTALL)
        if match is None:
            raise KeyError(f"no function {name!r} with a body in {self.name}")
        return match.group(0)

    def instructions(self, name: str) -> list[str]:
        """Body lines of a function, without the define, the brace or the block
        labels. Rough, and good enough to watch a pass do its work."""
        return [line.strip() for line in self.body(name).splitlines()[1:-1]
                if line.strip() and not line.strip().endswith(":")]

    def count(self, opcode: str) -> int:
        """How many times an instruction appears. Rough, and good enough to watch a pass work."""
        return len(re.findall(rf"(?<![\w.]){re.escape(opcode)}(?![\w.])", self.strip_comments()))

    def strip_comments(self) -> str:
        return "\n".join(line.split(";")[0].rstrip() for line in self.lines)

    def __str__(self) -> str:
        return self.text

    def __len__(self) -> int:
        return len(self.text)

    def _caption(self) -> str:
        caption = f"{self.name}, {len(self.functions)} function(s)"
        if self.history:
            caption += ", after " + " then ".join(self.history)
        return caption

    def __repr__(self) -> str:
        # Not the generated dataclass repr, which prints the entire module as
        # one escaped string. That happens in a terminal, in a JupyterLite
        # console, and anywhere else without HTML, and it is unreadable.
        return f"<Module {self._caption()}, {len(self.lines)} lines>"

    def _repr_html_(self) -> str:
        return _block(highlight(self.text), self._caption())

    def show(self, first: int | None = None) -> None:
        """Print the IR. `first` trims it, because some modules are long."""
        text = self.text if first is None else "\n".join(self.lines[:first])
        print(text)

    # -- doing something to it -----------------------------------------------

    def verify(self) -> "Module":
        """Ask LLVM whether this IR is well formed. Raises with the real message if not."""
        run("opt", "-passes=verify", "-disable-output", "-", stdin=self.text)
        return self

    def is_valid(self) -> bool:
        try:
            self.verify()
        except ToolError:
            return False
        return True

    def opt(
        self, passes: str, *extra: str, name: str | None = None, quiet: bool = False
    ) -> "Module":
        """Run a pass pipeline and hand back the result as a new Module.

        The original is untouched, so `before` and `after` can both be on screen
        at once, which is the shape almost every lesson wants.

        Any plugin built with `%%irxplug` in this session is loaded for you. A
        reader who has just written a pass called `count` should be able to type
        `m.opt("count")` and have it work, rather than repeat a path they did
        not choose and cannot see.
        """
        result = run(
            "opt", *plugin.load_flags(), f"-passes={passes}", "-S", *extra, "-", stdin=self.text
        )
        # A pass that prints is printing for somebody, and that somebody is the
        # reader. Half the passes in this course exist to say something on the
        # way past, and swallowing it because it arrived on stderr rather than
        # stdout would make those lessons show nothing at all.
        if not quiet and result.stderr.strip():
            print(result.stderr.rstrip("\n"))
        return Module(
            text=result.stdout,
            name=name or self.name,
            history=[*self.history, passes],
        )

    def asm(self, *extra: str, target: str | None = None, opt: str = "-O2") -> str:
        """Machine code for this IR, as text, from llc."""
        args = [opt, "-o", "-", "-"]
        if target:
            args = [f"-mtriple={target}", *args]
        return run("llc", *args, *extra, stdin=self.text).stdout

    def link(self, *others: "Module", name: str | None = None) -> "Module":
        """Join modules the way a real link does, with llvm-link.

        Files rather than stdin, because llvm-link takes several inputs and
        there is only one standard input to give it. Concatenating the text
        instead would look like it works and then fail on the second module
        header, which is a confusing error to hand somebody.
        """
        modules = [self, *others]
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index, module in enumerate(modules):
                path = Path(tmp) / f"{index}.ll"
                path.write_text(module.text, encoding="utf-8")
                paths.append(path)
            result = run("llvm-link", "-S", "-o", "-", *paths)
        joined = "+".join(m.name for m in modules)
        return Module(text=result.stdout, name=name or joined)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.text, encoding="utf-8")
        return path

    def tape(self, passes: str, *extra: str):
        """Run a pipeline and keep every step, rather than only the answer.

        Render it in a cell to scrub through the run. See `irx.pipeline`.
        """
        from .pipeline import tape

        return tape(self, passes, *extra)

    # -- comparing two of them -----------------------------------------------

    def diff(self, other: "Module", context: int = 3) -> "Diff":
        """What changed between two modules. Render it in a cell to see it in colour."""
        return Diff(self, other, context=context)


@dataclass(repr=False)
class Diff:
    """A before and after, rendered so the change is the thing you notice first."""

    before: Module
    after: Module
    context: int = 3

    @property
    def label(self) -> str:
        added = self.after.history[len(self.before.history) :]
        return " then ".join(added) if added else "before to after"

    def unified(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.text.splitlines(keepends=True),
                self.after.text.splitlines(keepends=True),
                fromfile="before",
                tofile="after",
                n=self.context,
            )
        )

    @property
    def changed(self) -> bool:
        return self.before.text != self.after.text

    def __str__(self) -> str:
        return self.unified() or "no change\n"

    def __repr__(self) -> str:
        # Without HTML the diff itself is the useful thing, so print it rather
        # than a summary of it.
        return str(self)

    def _repr_html_(self) -> str:
        if not self.changed:
            return _block(
                '<span style="color:#57606a">Nothing changed.</span>',
                f"{self.label}, and the IR is identical",
            )
        rows = []
        for line in self.unified().split("\n"):
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
            body = highlight(line)
            rows.append(f'<div style="{style}">{body or "&nbsp;"}</div>')
        return _block("".join(rows), f"{self.label}, and here is what moved")


# -- things about the toolchain rather than about one module -----------------


def passes() -> list[str]:
    """Every pass name this exact binary accepts.

    Worth having because pass names change between releases and the error you
    get for a wrong one is `unknown pass name`, which does not suggest a fix.
    """
    out = run("opt", "--print-passes").stdout
    found = set()
    for line in out.split("\n"):
        line = line.strip()
        if not line or line.endswith(":") or " " in line:
            continue
        found.add(line.split("<")[0])
    return sorted(found)


def has_pass(name: str) -> bool:
    return name in set(passes())
