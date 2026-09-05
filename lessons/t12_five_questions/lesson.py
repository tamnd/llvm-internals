# ---
# id: t12_five_questions
# title: Five questions for a compiler you have never seen
# question: I have an unfamiliar toolchain and a mystery. Where do I start?
# part: I
# env: E0
# minutes: 40
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string, t06_who_says_it_is_stale, t07_which_one_did_it, t08_o2_twice, t09_the_machine_in_the_ir, t10_the_names, t11_not_what_clang_optimised]
# ---

# %% [markdown]
# # Five questions for a compiler you have never seen
#
# Part I ends here, and what it was for was not the eleven facts. It was five questions you can now put to any LLVM based toolchain, in any order, without reading a line of its source, and get answers that are checkable.
#
# Each one is a few lines of code. Together they are a procedure, and the last cells run the whole thing on a program neither of us has looked at yet.
#
# **One. What is this, and what machine is it for?**

# %% id=q1_what_is_this
import re

MYSTERY = """
long sum(long n) { long t = 0; for (long i = 0; i < n; i++) t += i; return t; }
long first(long *a) { return a[0]; }
"""

mystery = irx.compile_c(MYSTERY, name="mystery")

print(irx.run("clang", "--version").stdout.splitlines()[0])
for what in ("triple", "datalayout"):
    head = f"target {what} = "
    print(f"  {what:<11}", next(ln for ln in mystery.lines if ln.startswith(head))[len(head):])

probe = irx.run("opt", "-passes=default<O2>", "-print-pipeline-passes", "-disable-output", "-",
                stdin=mystery.text)
print("  backend    ", "present" if not (probe.stderr or "").strip()
      else (probe.stderr or "").strip().splitlines()[0])

# %% [markdown]
# ## The version alone is not the answer
#
# T09 is why the other three lines are there. The triple decides which passes exist and which pipeline gets built, the data layout decides how wide everything is, and a build without the backend for that triple says so on stderr and quietly gives you the generic pipeline instead. Reading only the version number is how you end up comparing two numbers that were never comparable.
#
# **Two. What would it run?**

# %% id=q2_what_would_it_run
built = probe.stdout.strip()
entries = [n.split("<")[0] for n in re.split(r"[(),]", built) if n]

print(f"{built.count(',') + 1} entries, {len(built)} characters")
for name in ("indvars", "loop-deletion", "simplifycfg", "loop-idiom-vectorize"):
    print(f"  {name:<22} appears {entries.count(name)} times")

# %% [markdown]
# **Three. What did it run?**

# %% id=q3_what_did_run
log = irx.run("opt", "-passes=default<O2>", "-debug-pass-manager", "-disable-output", "-",
              stdin=mystery.text, check=False)
lines = (log.stdout + log.stderr).splitlines()

ran = [ln.split(": ", 1)[1].split(" on ")[0] for ln in lines if ln.startswith("Running pass:")]
skipped = [ln for ln in lines if "due to optnone attribute" in ln]

print(f"{len(ran)} pass runs from {len(set(ran))} distinct passes, {len(skipped)} skipped")
print(f"analyses computed: {sum(ln.startswith('Running analysis:') for ln in lines)}")

# %% [markdown]
# ## What is built and what runs are two different counts
#
# The entry count is what the pipeline *is*. The run count is what happened, and it is larger because an entry runs once per function and once per loop. T05 and T07 between them are the reason to always print both, and T06 is the reason to print the analysis count next to them, because the analyses are where the surprises live.
#
# The skipped count is T11's. If it is not zero, stop and read question five before you conclude anything at all.
#
# **Three questions in, and none of them needed a symptom. Here is the one that does.**
#
# **Four. Which pass did that?**

# %% id=q4_which_one_did_it
def prefix(limit, *flags):
    """The IR -O2 produces when only this many pass runs are allowed."""
    r = irx.run("opt", "-passes=default<O2>", f"-opt-bisect-limit={limit}", *flags, "-S", "-",
                stdin=mystery.text)
    return r.stdout, (r.stderr or "").splitlines()


def has_loop(ir):
    """Ask the loop analysis rather than guessing from the text."""
    r = irx.run("opt", "-passes=print<loops>", "-disable-output", "-", stdin=ir, check=False)
    return "Loop at depth" in (r.stdout + r.stderr)


def blame(done, *flags):
    """The first numbered run whose output satisfies done, by binary search."""
    _, whole = prefix(100000, *flags)
    if not done(prefix(100000, *flags)[0]):
        return f"never, in {len(whole)} runs"
    low, high = 0, len(whole)
    while low < high:
        middle = (low + high) // 2
        if done(prefix(middle, *flags)[0]):
            high = middle
        else:
            low = middle + 1
    return whole[low - 1].split("BISECT: running pass ")[-1]


print(blame(lambda ir: not has_loop(ir)))

# %% [markdown]
# ## `loop-deletion on loop %for.body in function sum`
#
# The counted loop does not survive `-O2`, and eight probes name the run that removed it. The number in front is `(57)` on an aarch64 host and `(56)` on an x86-64 one, which is T09's extra pass shifting everything after it by one. The name is the same on both, and the name is the answer. Note the predicate. Rather than looking for a `br` in the text, it asks the loop analysis, through the printer `print<loops>`, which is the same analysis the loop passes themselves use. Any question you can automate works here; asking the right component is worth the extra second.
#
# `loop-deletion` is a plausible culprit with a plausible name, and T07 said a bisect gives you a suspect rather than a verdict.

# %% id=gate_suspect
irx.gate(
    "The bisect names one run, `loop-deletion`. What has been established?",
    {
        "That by that run the loop was gone": "And nothing about why. It is the first run after "
                                              "which the property holds, which is not the same "
                                              "as the cause.",
        "That loop-deletion removed the loop": "It is the pass that was running when the "
                                               "property became true, which is weaker. The "
                                               "next cell takes it away and the loop still "
                                               "goes.",
        "That without loop-deletion the loop survives": "That is the claim to test, and it is "
                                                        "false here. Two other passes are "
                                                        "willing to finish the job.",
        "That loop-deletion is why -O2 is faster here": "Nothing measured time. Every number in "
                                                        "this lesson is a count or a name.",
    },
    answer="That by that run the loop was gone",
    note="Necessity is a separate experiment, and this is the one where it disagrees.",
)

# %% id=q4b_from_both_sides
for off in ("loop-deletion", "indvars", "loop-deletion,loop-unroll-full",
            "loop-deletion,indvars"):
    ir = irx.run("opt", "-passes=default<O2>", f"-opt-disable={off}", "-S", "-",
                 stdin=mystery.text).stdout
    print(f"  without {off:<32} loop survives -O2: {has_loop(ir)}")

print()
for off in ("loop-deletion", "loop-deletion,loop-unroll-full"):
    print(f"  with {off} off, the bisect says: {blame(lambda ir: not has_loop(ir), f'-opt-disable={off}')}")

# %% [markdown]
# ## Three passes were willing, and none of them was the cause
#
# Take `loop-deletion` out and the loop still goes, at `loop-unroll-full`. Take that out too and it still goes, at `sccp`. Take out `indvars` and the loop survives the entire pipeline, with or without any of the other three.
#
# So the answer to "which pass removed the loop" is that three of them would have, and the question worth asking was a different one. `indvars` is the pass that replaced the loop's result with a closed form, which is T08's cell running in a new context. After that the loop computes nothing anybody reads, and removing a dead loop is something several passes know how to do. The bisect found the first one that got there.
#
# This is the honest limit of the T07 procedure, and it is why the confirmation step is not optional. A bisect finds the run after which a property holds. `-opt-disable` asks whether a pass was needed. When the two answers differ, the difference is the interesting part, and here it separates the pass that did the work from the pass that swept up.
#
# **Five. Is what I am holding what it optimised?**

# %% id=q5_provenance
def provenance(module):
    """What the file says about how it was produced, which is not always what you assume."""
    group = next((ln for ln in module.lines if ln.startswith("attributes #0")), "")
    return {
        "optnone": "optnone" in group,
        "noinline": "noinline" in group,
        "tbaa": module.text.count("!tbaa") > 0,
        "triple": any(ln.startswith("target triple") for ln in module.lines),
    }


for label, module in (("irx.compile_c at -O0", mystery),
                      ("plain clang -O0", irx.Module.from_ll(
                          irx.run("clang", "-x", "c", "-std=c17", "-O0", "-S", "-emit-llvm",
                                  "-o", "-", "-", stdin=MYSTERY).stdout)),
                      ("clang -O2", irx.Module.from_ll(
                          irx.run("clang", "-x", "c", "-std=c17", "-O2", "-S", "-emit-llvm",
                                  "-o", "-", "-", stdin=MYSTERY).stdout))):
    print(f"  {label:<22} {provenance(module)}")

# %% [markdown]
# ## Four bits that decide whether your experiment means anything
#
# `optnone` means nearly nothing will run, and it is the difference between the two `-O0` rows: `irx.compile_c` passes `-Xclang -disable-O0-optnone` and plain `clang -O0` does not. `noinline` means the inliner will not run, which is invisible until your test has two functions in it, and both `-O0` rows have it. No `!tbaa` means alias analysis is working with less than a real `-O2` compile has; the one `!tbaa` in the last row is the load in `first`, and neither `-O0` file has it. No triple means the generic pipeline.
#
# All four are in the file, and all four are things you can check before you spend an afternoon. Nothing here needed a second machine or a second compiler.
#
# ## What to keep
#
# **What is this, and for what machine.** The version, the triple, the data layout, and whether the backend for that triple is in the build. A missing backend is a warning on stderr and a different pipeline.
#
# **What would it run.** `-print-pipeline-passes` for the entries, and count the ones you care about rather than reading all of them.
#
# **What did run.** `-debug-pass-manager` for the pass runs, the distinct passes, the analyses and the skips. Runs outnumber entries; analyses are computed on demand and thrown away on a pass's say so.
#
# **Which pass did that.** `-opt-bisect-limit` and a binary search over any predicate you can automate, then `-opt-disable` to ask whether that pass was needed. The two questions have different answers more often than is comfortable, and the gap between them is where the real cause is.
#
# **Is this what it optimised.** `optnone`, `noinline`, `!tbaa` and the triple, four things in the file that change what the pipeline can do to it.
#
# That is Part I. You have not read a pass, written one, or built LLVM, and you can already take an unfamiliar compiler apart far enough to say what it did and which part of it did it, with evidence somebody else can reproduce.
#
# Part II builds one.
