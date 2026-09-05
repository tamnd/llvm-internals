# ---
# id: z01_two_lines_at_the_top
# title: The two lines the first cell printed
# question: I opened the notebook and it printed something about E0. What am I looking at?
# part: 0
# env: E0
# minutes: 20
# ---

# %% [markdown]
# # The two lines the first cell printed
#
# Every lesson in this book opens with a cell you did not write, and that cell has already run. It printed two lines. They looked like status noise, and they are not: between them they say which LLVM you are about to be taught about, where it came from, and which of the three kinds of machine you are sitting at, which decides what the next hour can and cannot show you.
#
# This lesson is those two lines, and then the smallest thing that can go wrong, on purpose, so that you have seen it once.
#
# Nothing here needs any compiler knowledge. If you have never seen LLVM IR, that is the intended starting point.

# %% id=where_am_i
# The same two facts the bootstrap printed, asked for directly.
print(irx.describe())
print()

box = irx.current()
for field, value in (("LLVM version", box.version), ("came from", box.source),
                     ("ready in", f"{box.seconds:.2f}s")):
    print(f"  {field:<14} {value}")

# %% [markdown]
# ## `E0`, and the two rungs above it
#
# `E0` is a notebook with real LLVM binaries and no build tree. You can run `clang`, `opt`, `llc` and the rest, on any input you like, as many times as you like. What you cannot do is change LLVM itself, because there is nothing to rebuild. Part 0 and Part I are entirely `E0`, and so is a fair amount of what comes after, because you can get a very long way by asking a compiler questions rather than by editing it.
#
# `E1` is a machine with a checkout and a build tree. That is where you write a pass, put a `dbgs()` line in the middle of one, and rebuild. Lessons that need it are marked, and individual cells can be marked, so an `E1` cell inside an otherwise `E0` lesson plays back a recording rather than failing in front of you.
#
# `E2` is a browser with no subprocesses at all, which is a real situation on a locked down machine or a tablet. There the toolkit talks to Compiler Explorer instead of running anything locally, and the lesson says so.
#
# The ladder exists so that a lesson can state its requirements once, in its header, and so that you always know which rung you are on rather than finding out from an error message.

# %% id=the_version_is_the_point
# Two ways to ask what version this is, which agree, and one flag that says more.
print(irx.run("clang", "--version").stdout.strip().splitlines()[0])
print(irx.version())
print()
print("opt is at:", irx.path_to("opt"))

# %% [markdown]
# ## Pinned, and why that is not fussiness
#
# The two version lines agree on the number and disagree on everything in front of it, because whoever built your LLVM got to put their name there. `Homebrew LLVM version 23.1.0` and `LLVM version 23.1.0` are the same release. The number is the part to compare.
#
# This book is pinned to LLVM 23.1.0. Not "LLVM 23 or so", not "whatever your distribution ships": one tag, and every citation in every lesson is a file and a line range in that tag's source, written as `llvm/lib/Passes/PassBuilder.cpp:2707-2749@llvmorg-23.1.0`.
#
# The reason is that almost every interesting fact in this book is a fact about a specific version. Pass pipelines get passes added to them. Error messages get reworded. A pass that fires on your example this year is folded into another pass next year. A book that says "the optimiser will delete that loop" without saying which optimiser is telling you a story; a book that says "run 57 is `loop-deletion`, on this tag, on this target" is telling you something you can check and, later, something you can watch change.
#
# So when a number in front of you does not match a number in the text, the first question is never "what did I do wrong". It is "are we running the same thing", and the cell above is how you find out in five seconds.

# %% id=gate_pin
irx.gate(
    "Your `clang --version` says 24.0.0 and this lesson says 23.1.0. What follows?",
    {
        "The commands still work, some numbers will differ": "Which is the honest answer. The "
                                                             "flags in this book are stable, the "
                                                             "counts and the run numbers are not, "
                                                             "and the lesson tells you which is "
                                                             "which.",
        "Nothing in the book applies": "Far too strong. The method is the point and the method "
                                       "does not move between releases.",
        "Everything applies, versions do not matter for this": "This is the belief the book is "
                                                               "trying to take off you. Half of "
                                                               "Part I is a number that moved.",
        "You must install 23.1.0 before continuing": "You do not. The bootstrap fetches the "
                                                     "pinned toolchain when it can, and when it "
                                                     "cannot the lesson still runs.",
    },
    answer="The commands still work, some numbers will differ",
    note="Every claim in this book carries the tag it was measured against, for exactly this.",
)

# %% id=end_to_end
# C in, IR out, and the IR actually executed, in three calls.
SOURCE = "int main(void) { return 6 * 7; }\n"

module = irx.compile_c(SOURCE, name="answer")
print(module.body("main"))

exit_code = irx.run("lli", "-", stdin=module.text, check=False).code
print("running the IR gives:", exit_code)

# %% [markdown]
# ## That was the whole toolchain
#
# `irx.compile_c` ran the pinned `clang` on that string and handed back the LLVM IR as text. `lli` is an interpreter for that text, so the last line ran the program without any machine code ever existing, and `main` returning `42` came back as the process exit status.
#
# The IR is longer than the C and says less. That is normal and it is the subject of T02 and T03. For now the only claim being made is that the three shapes on your screen are a real chain: source, IR, behaviour.
#
# Two things in that output are worth noticing now. There is no multiply. Nothing has optimised this file yet, and `6 * 7` still arrived as `ret i32 42`, because folding constants is something clang's front end does while it is building the IR rather than something the optimiser is asked for later. And there is an `alloca` and a `store` for a variable that does not exist in the source, holding a `0` nobody reads. Dead on arrival, and still there. Which of those two habits belongs to which program is what T01 is about.

# %% id=when_it_breaks
# The smallest failure in the book, produced on purpose.
broken = irx.run("clang", "-x", "c", "-S", "-emit-llvm", "-o", "-", "-",
                 stdin="int f(void) { return q; }\n", check=False)

print("exit code:", broken.code)
print("stdout is empty:", broken.stdout == "")
for line in (broken.stderr or "").strip().splitlines()[:3]:
    print(" ", line)

# %% [markdown]
# ## Read the first line of the error, not the last
#
# `check=False` is the toolkit saying "this is expected to fail, hand me the result anyway". Without it a failing tool raises, which is what you want almost all the time and not what you want when the failure is the experiment.
#
# Three things are worth taking from that output. The exit code is not zero. The output is empty rather than partial, so there is no half compiled file to be confused by. And the message names a line, a column and a symbol, which between them is usually the whole diagnosis.
#
# You will produce a lot of failures in this book deliberately. A tool that refuses to do something tells you where a boundary is, and boundaries are most of what there is to learn about a compiler.
#
# ## What to keep
#
# The bootstrap cell prints which LLVM you have and which rung of the ladder you are on. Both matter and both are one call away: `irx.current()` and `irx.describe()`.
#
# `E0` is real binaries and no build tree, `E1` adds a build tree, `E2` is a browser with no subprocesses. A lesson declares what it needs in its header, and a single cell can declare it too.
#
# The book is pinned to LLVM 23.1.0 and every citation carries that tag. A different version means the commands still work and some of the numbers move. That is a fact about compilers, not a defect in the book.
#
# `clang` produces IR, `lli` runs it, `opt` transforms it. You have now used two of the three.
#
# A tool that fails gives you an exit code, an empty stdout and a message with a line and column in it. Failures are evidence, and this book asks for them on purpose.
#
# Next: the C++ chapter, which exists so that you can read LLVM's source later. If you already write C++, it is ninety seconds and a self test.
