# ---
# id: z03_going_and_looking
# title: Every claim in this book has an address
# question: The book says a file and a line number. How do I go and check?
# part: 0
# env: E0
# minutes: 30
# needs: [z01_two_lines_at_the_top, z02_chapter_minus_one]
# ---

# %% [markdown]
# # Every claim in this book has an address
#
# Next to every lesson there is a `claims.yaml`, and in it every factual sentence the lesson makes, with the evidence for it and one of three words: `observed`, `cited`, `inferred`. A cited claim carries something like this:
#
# ```
# llvm/lib/Transforms/Scalar/DCE.cpp:109-116@llvmorg-23.1.0
# ```
#
# This lesson is what to do with that. By the end you will have gone and looked at one, run a piece of LLVM's own test suite, and seen why the part after the `@` is the part that makes the rest of it mean anything.
#
# This is the one lesson in Part 0 that needs a network connection, because going and looking is the entire subject.

# %% id=the_citation
import pathlib
import re
import tempfile
import urllib.request

CITE = re.compile(r"(?P<path>[\w./-]+)"
                  r":(?P<first>\d+)(?:-(?P<last>\d+))?"
                  r"@(?P<tag>llvmorg-[\w.]+)")

RAW = "https://raw.githubusercontent.com/llvm/llvm-project"
BLOB = "https://github.com/llvm/llvm-project/blob"

found = CITE.match("llvm/lib/Transforms/Scalar/DCE.cpp:109-116@llvmorg-23.1.0").groupdict()
print(found)
print()
print("to read: ", f"{BLOB}/{found['tag']}/{found['path']}#L{found['first']}-L{found['last']}")
print("to fetch:", f"{RAW}/{found['tag']}/{found['path']}")

# %% [markdown]
# ## Four things, and the last one is not optional
#
# A path from the root of `llvm-project`, a first line, a last line, and a tag. The first three are what you would expect. The fourth is what makes the other three survive contact with reality.
#
# Line numbers move. Somebody adds an include at the top of a file and every citation into it is off by one; somebody splits a function and it is off by two hundred. A citation with no version attached is a promise that expires quietly and without telling anybody, and a book full of them decays into a book full of confident sentences pointing at the wrong lines.
#
# So the tag is in every citation in this repository, and `tools/refcheck.py` refuses any that disagrees with `docs/pin.json`. That is a script, not a habit, which is the only kind of rule that lasts.
#
# The tag is also what the toolkit fetched your binaries for, so the notebook can build the URL rather than being told it.

# %% id=go_and_look
TAG = irx.toolchain.TAG


def source(path, first, last):
    """The lines a citation names, from the tag this notebook's LLVM was built from."""
    with urllib.request.urlopen(f"{RAW}/{TAG}/{path}", timeout=30) as response:
        lines = response.read().decode("utf-8").splitlines()
    return lines[first - 1:last]


print(f"pinned at {TAG}\n")
for line in source("llvm/lib/Transforms/Scalar/DCE.cpp", 109, 116):
    print(" ", line)

# %% [markdown]
# ## That is the whole procedure
#
# Eight lines, fetched from the tag, and they say what the claim said they say. `DCEPass::run` takes a function and an analysis manager, calls the function Z02 spent an hour on, and returns either `PreservedAnalyses::all()` or a set with the control flow graph in it. You have now checked a citation, and it took one call.
#
# Do this the first time a lesson tells you something that surprises you. It is the difference between a book you believe and a book you have tested, and the second one is worth much more, including when it turns out to be wrong.
#
# ## Where the answers came from
#
# Part I asks a lot of questions and the answers are not spread evenly over the tree.

# %% id=where_part_one_came_from
PART_ONE = [
    "llvm/lib/Passes/PassBuilder.cpp", "llvm/lib/Passes/PassRegistry.def",
    "llvm/lib/Passes/StandardInstrumentations.cpp", "llvm/include/llvm/Passes/PassBuilder.h",
    "llvm/include/llvm/Passes/TargetPassRegistry.inc", "llvm/lib/IR/OptBisect.cpp",
    "llvm/lib/IR/PassManager.cpp", "llvm/lib/Transforms/Scalar/LICM.cpp",
    "llvm/lib/Target/AArch64/AArch64TargetMachine.cpp",
    "llvm/lib/Target/AArch64/AArch64PassRegistry.def",
    "llvm/lib/Target/X86/X86PassRegistry.def", "llvm/docs/LangRef.md",
]

for directory in sorted({path.rsplit("/", 1)[0] for path in PART_ONE}):
    names = [p.rsplit("/", 1)[1] for p in PART_ONE if p.startswith(directory + "/")]
    print(f"  {directory:<42} {', '.join(sorted(names))}")

# %% [markdown]
# ## Seven directories, and what each of them is
#
# `llvm/lib/` is the implementation, and it is where you end up whenever the question is what actually happens. `Passes/` is the pass manager and the pipeline; `Transforms/` is the passes themselves, split into `Scalar`, `IPO`, `Utils`, `Vectorize` and a few more; `IR/` is the data structure everything else operates on; `Target/<Name>/` is one backend.
#
# `llvm/include/llvm/` mirrors it, and holds the declarations. The pairing is strict enough to navigate by: for almost any `lib/A/B.cpp` there is an `include/llvm/A/B.h`, and the header is where the comment explaining the design usually lives.
#
# `llvm/docs/` is prose, and two files in it are worth knowing by name. `LangRef` is the language reference for the IR, and it is the last word on what an instruction means. `ProgrammersManual` is the tour of the data structures and the idioms, which is where Z02's material comes from in its full form.
#
# A `.def` file is a list wearing a macro, and T10 took one apart. A `.inc` file is something included more than once, usually with the macros defined differently each time.
#
# One directory is missing from that list, and it is the one that would have answered several of those questions faster.

# %% id=gate_where
irx.gate(
    "You want to know exactly what `dce` does to a call it cannot prove is dead. Where do you look first?",
    {
        "`llvm/test/Transforms/DCE/`": "The tests are executable, small, and each one exists "
                                       "because somebody got it wrong once. A test is usually "
                                       "twelve lines and answers the question exactly.",
        "`llvm/lib/Transforms/Scalar/DCE.cpp`": "Correct and slow. The source says what it does "
                                                "for every input at once, which is more than you "
                                                "asked and harder to read than one example.",
        "`llvm/docs/LangRef.md`": "LangRef defines what the IR means, not what any particular "
                                  "pass does with it. It is the right answer to a different "
                                  "question and Part I asks that question a lot.",
        "The commit history": "Sometimes the only place an answer lives, and never the first "
                              "place to look, because you have to know what you are looking for "
                              "before a log is any use.",
    },
    answer="`llvm/test/Transforms/DCE/`",
    note="Twelve lines, a command to run it and the expected output. Here is one.",
)

# %% id=the_test_is_the_documentation
TEST = "llvm/test/Transforms/DCE/int_sideeffect.ll"

with urllib.request.urlopen(f"{RAW}/{TAG}/{TEST}", timeout=30) as response:
    test = response.read().decode("utf-8")
print(test)

work = pathlib.Path(tempfile.mkdtemp())
(work / "test.ll").write_text(test)


def filecheck(ir):
    """The second half of the RUN line, with %s standing for the test file."""
    (work / "out.ll").write_text(ir)
    return irx.run("FileCheck", work / "test.ll", "--input-file", work / "out.ll",
                   check=False)


after = irx.run("opt", "-S", "-passes=instcombine", stdin=test).stdout
print("FileCheck on what opt produced:", filecheck(after).code)

without = after.replace("  call void @llvm.sideeffect()\n", "")
failed = filecheck(without)
print("FileCheck with that one call taken out:", failed.code)
print(" ", (failed.stdout + failed.stderr).strip().splitlines()[0])

# %% [markdown]
# ## A test is a command, an input and an expected output
#
# The first line is the command. `; RUN:` is a comment as far as the IR parser is concerned and an instruction as far as `lit`, LLVM's test runner, is concerned. `%s` is this file, so the line says: run `opt -S -passes=instcombine` on me, and pipe the result into `FileCheck`, comparing it against the `CHECK` lines in me.
#
# The rest is an input and an assertion sitting next to each other. `CHECK-LABEL: dce` finds the function, and `CHECK: call void @llvm.sideeffect()` says the call is still there afterwards. The comment in the middle says why anybody cared: a call with no arguments and no result, in a function that ignores it, is exactly what dead code elimination exists to remove, and this one must survive because it means "something happens here that I am not telling you about".
#
# The cell ran that RUN line, with the test written to a file so `%s` has something to stand for. `opt` produced the IR, `FileCheck` read the `CHECK` lines out of the test file and the IR out of the other one, found everything it was looking for, and exited 0. That is a passing LLVM test, run by you, with no build tree and no `lit`.
#
# The `<` is not decoration. The testing guide asks for `opt ... < %s` rather than `opt %s` because `opt` emits a `ModuleID` line naming its input file and does not when the input arrives on standard input, and a test that has the path to itself in its output fails as soon as somebody checks the tree out somewhere else. The cell feeds the text in on standard input for the same reason.
#
# Then the same check against the same IR with that one call deleted, which is the state of the world the test exists to rule out. It exits 1 and prints the line it could not find. An assertion that never fails is not an assertion, and this is the two line version of checking that it does.
#
# This is why the test directory is the first place to look. Somebody has already reduced the question to twelve lines and written down the answer, and the answer is executable.
#
# ## What to keep
#
# A citation is a path, a line range and a tag. The tag is the part that stops it rotting, `refcheck` enforces that every one of them matches `docs/pin.json`, and the raw URL for any of them is three strings joined together.
#
# `lib/` implements, `include/llvm/` declares and usually explains, `docs/` has LangRef for what the IR means and the Programmer's Manual for how the code is written, `test/` has small executable examples, and `lib/Target/<Name>/` is one backend, which T09 and T10 both turned out to be about.
#
# A `.def` file is a list of macro invocations, included repeatedly with the macros redefined. That is how pass registries work.
#
# A lit test is a `RUN:` line, an input and `CHECK:` lines, all in one file. You can run the `RUN:` line yourself with the tools you already have, and for a question about one pass on one input it is usually the fastest documentation in the project.
#
# Next: how this book decides what it is allowed to say, which is the last thing before Part I.
