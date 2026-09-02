# ---
# id: t04_the_pass_tape
# title: Which of two hundred passes actually did anything
# question: I typed -O2 and my function changed, which pass changed it?
# part: I
# env: E0
# minutes: 35
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll]
# blueprints: [BP-AN-PM]
# ---

# %% [markdown]
# # Which of two hundred passes actually did anything
#
# Clang at `-O2` deletes a duplicate load. If you had to name the pass that did it you would probably say GVN, because global value numbering is the pass whose whole job is spotting two computations that are the same.
#
# GVN does run. It runs near the end, and by the time it gets there the duplicate is long gone and GVN has nothing left to find.
#
# The cells below build a tape of every pass that ran and show you who really did it. Then we do it again with a loop, where it gets worse. The pass that removes the loop prints nothing at all, so every tool built on `--print-changed` credits whichever pass runs next, and this notebook will do that in front of you before we fix it.

# %% id=sources
# Two functions. The first has a redundancy you can see. The second has a loop
# whose answer LLVM can work out without running it.
TWICE = """int twice(int *p) {
  int a = *p;
  int b = *p;
  return a + b;
}
"""

GAUSS = """int gauss(int n) {
  int total = 0;
  for (int i = 0; i < n; i++)
    total += i;
  return total;
}
"""

gauss_ir = irx.compile_c(GAUSS)
print(gauss_ir.text.count("\n"), "lines of unoptimised IR")

# %% id=first_tape
# One run of opt, and every pass in the -O2 pipeline on the way past.
gauss = irx.tape(gauss_ir, "default<O2>")
gauss

# %% [markdown]
# ## One command, three answers
#
# That whole widget comes from a single `opt` run:
#
# ```
# opt -passes=default<O2> --print-changed --print-module-scope -S -
# ```
#
# `--print-changed` asks LLVM to say something about every pass, whether or not it did anything, and `--print-module-scope` asks it to print the whole module each time instead of the one function or loop the pass was looking at. One run therefore answers three separate questions at once. Which passes ran, in order. Which ones changed the IR. And what the module looked like after each of the ones that did.
#
# It answers them in a format nobody designed for reading. LLVM writes a banner line before each thing it has to say, and there are five different banner shapes. Count them.

# %% id=banners
import collections
import re

raw = irx.run("opt", "-passes=default<O2>", "--print-changed", "--print-module-scope",
              "-S", "-", stdin=gauss_ir.text).stderr

def shape(line):
    if "At Start" in line:
        return "the module before anything ran"
    if "omitted because no change" in line:
        return "ran, changed nothing"
    if line.endswith("ignored ***"):
        return "not a pass, a pass manager"
    if line.endswith("invalidated ***"):
        return "deleted what it was running on"
    if line.endswith("filtered out ***"):
        return "skipped by -filter-print-funcs"
    return "ran, changed something, module follows"

banners = re.findall(r"^\*\*\* IR .*\*\*\*$", raw, re.M)
for kind, n in collections.Counter(shape(b) for b in banners).most_common():
    print(f"{n:>4}  {kind}")

print()
print(f"{len(banners):>4}  banner lines in total")
print(f"{len(gauss.steps):>4}  passes on the tape")

# %% [markdown]
# The pass manager lines are plumbing. A `PassManager<Function>` is not a pass, it is the thing that runs passes, so `irx` drops those rows and the tape counts only real work. Take them out and the arithmetic closes: every pass on the tape either changed nothing, printed a module, or deleted the thing it was running on.
#
# That last shape is the one this lesson is about, and it is the one almost every tool built on `--print-changed` throws away.
#
# ![Every pass -O2 runs on a five line function, with the sixteen that did anything marked](https://raw.githubusercontent.com/tamnd/llvm-internals/main/docs/diagrams/o2-passes.svg)
#
# The grey ticks are not waste. Most of them are analyses answering a question some later pass asked, or transforms checking a precondition that does not hold here and would hold in the function next to it. The pipeline is fixed and your function is not, so the same list runs over everything and only the applicable parts fire. What the picture is for is scale: the number of passes that touched your code is small enough to hold in your head, which means the question "who changed my function" always has a short answer, once you can see it.

# %% [markdown]
# ## Act one, the duplicate load
#
# `twice` loads from `p` twice and adds the results. Nothing writes through `p` in between, so one load is enough. Here is who takes the other one out.

# %% id=twice_tape
twice_ir = irx.compile_c(TWICE)
twice = irx.tape(twice_ir, "default<O2>")
twice

# %% id=gate_load
irx.gate(
    "Look at the tape above. Which of the passes that changed twice deleted the second load?",
    {
        "SROA": "SROA is the one that made the loads visible, not the one that removed them. "
                "Clang gives every local variable a stack slot, so before SROA there are four "
                "loads and a store and none of them are obviously the same. SROA promotes the "
                "slots to registers, which is what leaves two identical loads sitting next to "
                "each other where something else can see them.",
        "EarlyCSE": "Right, and the name says when rather than what. It runs a couple of passes "
                    "after SROA, and a second load from a pointer nothing has written to is "
                    "about as cheap a redundancy as there is to find.",
        "InstCombine": "It runs, and the tape says it changed the function, so this is a fair "
                       "guess. It is not the one. Look at the next cell for what it actually did.",
        "GVN": "The reasonable answer and the wrong one. GVN can do this, and the next cell "
               "proves it can. On this function it runs so much later that there is nothing "
               "left for it to find, and the tape marks it as having changed nothing.",
    },
    answer="EarlyCSE",
    note="Check the row numbers in the tape above. The order the passes run in is doing all the work here.",
)

# %% id=three_alone
# Each of the three, run on its own, straight after SROA. All three can do it.
for one in ("early-cse", "instcombine", "gvn"):
    out = irx.run("opt", f"-passes=sroa,{one}", "-S", "-", stdin=twice_ir.text).stdout
    print(f"sroa,{one}")
    print("\n".join(line for line in out.splitlines() if line.startswith("  ")))
    print()

# %% [markdown]
# All three delete the load. Only one of them ever gets the chance, because the pipeline is an order and the first pass to reach a redundancy is the one that removes it. Here is that order, in the file that defines it:
#
# ```cpp
#   // Catch trivial redundancies
#   FPM.addPass(EarlyCSEPass(true /* Enable mem-ssa. */));
#
#   // Hoisting of scalars and load expressions.
#   FPM.addPass(
#       SimplifyCFGPass(SimplifyCFGOptions().convertSwitchRangeToICmp(true)));
#   FPM.addPass(InstCombinePass());
# ```
#
# `llvm/lib/Passes/PassBuilderPipelines.cpp:504-510@llvmorg-23.1.0`
#
# "Catch trivial redundancies" is a job description. EarlyCSE is placed there to sweep up the cheap stuff so that the expensive passes downstream are not handed a function full of obvious duplication. GVN is added hundreds of lines further down the same function, under "Eliminate redundancies" (`llvm/lib/Passes/PassBuilderPipelines.cpp:779-784@llvmorg-23.1.0`), and by then the cheap stuff is gone.
#
# So GVN is not idle by accident, it is idle by design, and the tape saying "no change" next to it is the pipeline working. The pass you would name is doing nothing, and the pass doing the work is one you had not heard of, and both of those facts are on purpose.
#
# InstCombine is worth one more look. It did change `twice`, and it changed it after the load was already gone: `add nsw i32 %0, %0` became `shl nsw i32 %0, 1`. Multiplying by two is a shift. That is a different kind of win from deleting a load, and if you had guessed InstCombine you would have been right that it did something and wrong about what.

# %% [markdown]
# ## Act two, the loop that vanishes
#
# `gauss` adds up the numbers below `n`. There is a closed form for that sum, LLVM knows it, and at `-O2` the loop does not survive.
#
# Look at the first tape again, at the last few rows that changed anything. Two things stand out. IndVarSimplify made the function longer. Then GVN, a few passes later, took ten lines out, and after GVN the loop is gone.

# %% id=gate_loop
irx.gate(
    "Between the IndVarSimplify dump and the GVN dump, the loop disappears. Which pass removed it?",
    {
        "GVN": "This is what the dumps say, it is what the diff in this notebook says, and it "
               "is wrong. GVN does run there and it does account for three of those ten lines. "
               "The other seven were already gone before GVN started.",
        "IndVarSimplify": "Close, and worth understanding, because without it nothing else "
                          "could have happened. IndVarSimplify worked out the sum without the "
                          "loop and made the function five lines longer doing it. Making a loop "
                          "pointless is not the same as removing it.",
        "LoopDeletion": "Right. It ran between the two dumps, it deleted the loop it had been "
                        "handed, and then it printed nothing, because the thing it was supposed "
                        "to print no longer existed.",
        "SimplifyCFG": "SimplifyCFG really does delete unreachable blocks and it runs several "
                       "times in this pipeline. None of those runs is where the loop goes, and "
                       "you can check that yourself by looking at where its rows sit on the tape.",
    },
    answer="LoopDeletion",
    note="If you read the first tape carefully you have already seen the answer, in a row that reads `deleted it, no dump`.",
)

# %% id=find_deletion
step = gauss.step("LoopDeletion")
print(step)
print("  changed the module:", step.changed)
print("  printed a dump:    ", bool(step.ir))
print("  running on:        ", step.where)
print()
print("passes that changed the module:", len(gauss.changed))
print("dumps opt actually printed:    ", len(gauss.shown))
print("frames you can look at:        ", len(gauss.frames), "(the start, plus one per dump)")

# %% id=blame_gvn
def loops(text):
    """Ask LLVM how many loops are left. Reading the IR for a branch would find plenty."""
    found = irx.run("opt", "-passes=print<loops>", "-disable-output", "-", stdin=text)
    return found.stderr.count("Loop at depth")

def frame_after(t, name):
    """The module as it stood when the named pass printed it."""
    return t.frames[t.shown.index(t.step(name)) + 1]

# Take the last dump before LoopDeletion ran, then do by hand what the pipeline
# did, one pass at a time, and watch where the loop actually goes.
before = frame_after(gauss, "IndVarSimplify").text
deleted = irx.run("opt", "-passes=loop-mssa(loop-deletion)", "-S", "-", stdin=before).stdout
cleaned = irx.run("opt", "-passes=gvn", "-S", "-", stdin=deleted).stdout

for label, text in [("after IndVarSimplify", before),
                    ("after LoopDeletion", deleted),
                    ("after GVN", cleaned)]:
    print(f"{label:<22} {len(text.splitlines()):>3} lines, {loops(text)} loop(s)")

print()
print("the tape hands GVN a delta of", gauss.deltas()[gauss.shown.index(gauss.step("GVN"))], "lines")

# %% id=remark
# LLVM will tell you it did this, if you ask it in the one place it says so.
said = irx.run("opt", "-passes=loop-mssa(loop-deletion)", "-pass-remarks=loop-delete",
               "-disable-output", "-", stdin=before)
print(said.stderr.strip())

# %% [markdown]
# ## Why the dump is missing
#
# LoopDeletion is a loop pass, so the pass manager hands it one loop and expects to print that loop afterwards. When the pass deletes the loop there is nothing left to hand back:
#
# ```cpp
#     PreservedAnalyses PassPA = Pass->run(*L, LAM, LAR, Updater);
#
#     // Do not pass deleted Loop into the instrumentation.
#     if (Updater.skipCurrentLoop())
#       PI.runAfterPassInvalidated<Loop>(*Pass, PassPA);
#     else
#       PI.runAfterPass<Loop>(*Pass, *L, PassPA);
# ```
#
# `llvm/lib/Transforms/Scalar/LoopPassManager.cpp:289-295@llvmorg-23.1.0`
#
# That `runAfterPassInvalidated` call is a different callback from the usual one, and it takes no IR, because there is no IR to give it. What comes out the other end is a banner with no module under it and no scope on it:
#
# ```cpp
# template <typename T>
# void TextChangeReporter<T>::handleInvalidated(StringRef PassID) {
#   Out << formatv("*** IR Pass {0} invalidated ***\n", PassID);
# }
# ```
#
# `llvm/lib/Passes/StandardInstrumentations.cpp:490-493@llvmorg-23.1.0`
#
# So the record of the most consequential thing that happened to this function is one line saying a pass ran, with no name for what it ran on and no picture of the result. Anything that builds its view of the pipeline out of the dumps cannot see it, and will attribute those seven lines to the next pass that prints. That is not a bug in LLVM. LLVM is reporting exactly what it knows, which is that it cannot print something that has been freed.
#
# It is a trap for the reader, though, and it is the reason `irx` reads all five banner shapes rather than only the ones with a module attached. The row on the tape saying `deleted it, no dump` is that banner, kept instead of discarded. `tape.changed` counts it and `tape.shown` does not, so the two lists have different lengths in this pipeline and the same length in almost every other one. That gap is the whole bug, in one number.
#
# The remark you printed above comes from the pass itself:
#
# ```cpp
#   LLVM_DEBUG(dbgs() << "Loop is invariant, delete it!\n");
#   ORE.emit([&]() {
#     return OptimizationRemark(DEBUG_TYPE, "Invariant", L->getStartLoc(),
#                               L->getHeader())
#            << "Loop deleted because it is invariant";
#   });
# ```
#
# `llvm/lib/Transforms/Scalar/LoopDeletion.cpp:504-509@llvmorg-23.1.0`
#
# "Invariant" here means the loop computes nothing anybody needs. IndVarSimplify is what made that true, by rewriting the value the loop was accumulating into arithmetic on `n` that does not need the loop to run. Look back at the diff for IndVarSimplify and you will see it introduce `i33` values: it needs one extra bit so the multiply in the closed form cannot overflow before the shift takes the bit back off. It paid five lines for that, which looks like a loss right up until the pass three rows later collects on it.
#
# That is the shape of a pipeline. Passes are not each individually an improvement. They set each other up, and a pass that makes your function bigger may be the only reason the next one can make it smaller.

# %% [markdown]
# ## Boss fight
#
# Build a pipeline that gets rid of the loop in `gauss` without using `default<O2>`.
#
# The rules the grader enforces: at most four top level passes, the word `default` does not appear, `gauss` has no loop left in it afterwards, and it still returns the same answers for `n` of 0, 1, 2, 10, 1000 and -5. That last one is the rule that matters. It is not hard to delete a loop, it is hard to delete a loop and still be right.
#
# You have been given everything you need. You know a pass that makes the loop pointless, you know a pass that deletes pointless loops, and you know from act one that neither of them can see anything at all until the local variables are out of their stack slots. `irx.passes()` lists every name `opt` accepts if you want to go looking for a different route. There is more than one answer.

# %% include=grade.py id=grader

# %% id=attempt
# Change the pipeline and run the cell. The grader names the part that is wrong.
passed = grade("sroa", GAUSS)

# %% [markdown]
# ## What you now know
#
# - You can take any function and any pipeline and get an ordered list of every pass that ran, which ones changed the IR, and the module after each one, from a single `opt` invocation.
# - You can tell the difference between a pass that did nothing and a pass that did something and could not print it, which is a distinction most tooling built on `--print-changed` gets wrong.
# - You can find out which pass is responsible for a change by bisecting the pipeline by hand, rather than reading the diff and trusting the name at the top of it.
# - You can read `PassBuilderPipelines.cpp` to find out why a pass runs where it runs, and use that to predict which of two passes that could do a job will be the one that does.
# - You know that a pass making your function longer is not a pass failing, and you have seen a case where the growth is exactly what makes the next removal legal.
#
# The blueprint for this is [BP-AN-PM](../../blueprints/BP-AN-PM.md), which is the pass manager end to end: analysis invalidation, the adaptors that let a function pass run inside a module pipeline, and where the instrumentation callbacks used above are hooked in.
