# ---
# id: t06_who_says_it_is_stale
# title: opt ran four passes for the two you asked for
# question: Who decides that an analysis has to be recomputed?
# part: I
# env: E0
# minutes: 35
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string]
# ---

# %% [markdown]
# # `opt` ran four passes for the two you asked for
#
# T05 left you able to print any pipeline in LLVM, including the one behind `-O2`. That printout is the truth about what was *built*. It is not the truth about what *ran*.
#
# There is a second view, `-debug-pass-manager`, which reports what the pass manager did rather than what the parser made. The two disagree, and the gap between them is where analyses live.
#
# Start with a request for two loop passes.

# %% id=two_passes_four_ran
LOOP = """
int sum_to(int n) {
  int total = 0;
  for (int i = 0; i < n; i++)
    total += i;
  return total;
}
"""

loop = irx.compile_c(LOOP, name="sum_to")


def trace(module, pipeline, *flags):
    """Everything -debug-pass-manager says about one run of one pipeline."""
    r = irx.run("opt", f"-passes={pipeline}", "-debug-pass-manager", "-disable-output",
                *flags, "-", stdin=module.text, check=False)
    return (r.stdout + r.stderr).splitlines()


def started(lines, kind):
    """The names on the 'Running pass:' or 'Running analysis:' lines, in order."""
    return [ln.split(": ", 1)[1].split(" on ")[0]
            for ln in lines if ln.startswith(f"{kind}:")]


lines = trace(loop, "licm,loop-rotate")
print("passes that ran: ", ", ".join(started(lines, "Running pass")))
print("analyses computed:", len(started(lines, "Running analysis")))

# %% [markdown]
# ## Two names in, five passes out
#
# `VerifierPass` you already know about, from T05: `opt` appends it. The other two are new. `LoopSimplifyPass` and `LCSSAPass` ran before either pass you asked for, and nothing you typed mentions them.
#
# Fifteen analyses were computed as well. You typed none of those either.
#
# Before explaining where they came from, look at what the other view says about the same request.

# %% id=the_printed_pipeline_does_not_know
print(irx.run("opt", "-passes=licm,loop-rotate", "-print-pipeline-passes",
              "-disable-output", "-", stdin=loop.text).stdout.strip())

# %% [markdown]
# ## The pipeline that was built says nothing about the two extra passes
#
# `function(loop-mssa(licm<allowspeculation>,loop-rotate<...>)),verify`. There is the `function(...)` adaptor from T05, there are the default parameters, there is the appended `verify`. There is no `LoopSimplify` and no `LCSSA`, and there is one more surprise: the adaptor is `loop-mssa` rather than `loop`, because `licm` wants MemorySSA and the parser picked the variant that maintains it.
#
# Both views are correct. `-print-pipeline-passes` prints the pipeline, and the two extra passes are not in the pipeline. They are inside the adaptor. This is its constructor:
#
# ```cpp
# LoopCanonicalizationFPM.addPass(LoopSimplifyPass());
# LoopCanonicalizationFPM.addPass(LCSSAPass());
# ```
#
# A loop pass is written against a loop in a particular shape: one preheader, one backedge, and values that leave the loop passing through a phi at the exit. Rather than have every loop pass check, the adaptor establishes the shape on the way in. So `loop(...)` in a printed pipeline does not mean "run these passes on the loops". It means "canonicalise, then run these passes on the loops".
#
# That accounts for the passes. The fifteen analyses are the more interesting number.

# %% id=an_analysis_asks_for_an_analysis
for name in started(trace(loop, "require<loops>"), "Running analysis"):
    print("  ", name)

# %% [markdown]
# ## Nobody asked for the dominator tree
#
# `require<loops>` is a pass that does nothing except demand an analysis, which makes it a clean way to watch one being computed. Two of the four lines are scaffolding, the proxy that lets a module level manager reach function analyses and the analysis behind the appended `verify`. The other two are the answer: ask for the loops and you get `LoopAnalysis`, and underneath it `DominatorTreeAnalysis`, because loops are found by looking for back edges in the dominator tree.
#
# Read the order carefully. `LoopAnalysis` is printed *before* the analysis it depends on, which looks backwards until you see where the print comes from: a callback registered to run *before* an analysis starts. So the log is nesting, not sequence. `LoopAnalysis` started, and while it was running it asked the manager for a dominator tree, and that started too.
#
# The word to hold on to is *asked*. Analyses are not scheduled. A pass asks the manager for one, and the manager either has it or computes it.

# %% id=asked_twice_computed_once
lines = trace(loop, "require<domtree>,require<loops>,require<domtree>")

asked = sum("RequireAnalysisPass<llvm::DominatorTreeAnalysis" in ln for ln in lines)
computed = sum(ln.startswith("Running analysis: DominatorTreeAnalysis") for ln in lines)
print(f"passes demanding a dominator tree: {asked}, plus LoopAnalysis, which needs one too")
print(f"times the dominator tree was computed: {computed}")

# %% [markdown]
# ## Computed once, handed out three times
#
# That is the whole design, and the documentation states it in one sentence: querying for an analysis makes the manager check whether it already has a result for that IR, return it if it does and if it is still valid, and otherwise run the analysis, cache it, and return that.
#
# Which leaves exactly one question, and it is the one this lesson is named for. *Still valid* according to whom?
#
# You have a guess available. The dominator tree describes the shape of the control flow graph. `simplifycfg` is a pass whose entire job is changing the shape of the control flow graph. So:

# %% id=gate_stale
irx.gate(
    "`opt` runs `require<domtree>,simplifycfg,require<domtree>` over a function. "
    "When does the second `require` have to compute the tree again?",
    {
        "Always, simplifycfg rewrites blocks": "This is the reasonable answer and it is wrong "
                                               "half the time. Something narrower is going on.",
        "Never, simplifycfg keeps it up to date": "Not by default, though there is a flag, and "
                                                  "you are going to meet it.",
        "Only when simplifycfg changed something": "Right, and the reason is not that LLVM "
                                                   "compared the before and after. Nothing "
                                                   "compares anything.",
        "Only above -O0": "There is no optimisation level here. A pipeline is the passes you "
                          "named, as T05 established.",
    },
    answer="Only when simplifycfg changed something",
    note="Two functions, the same pass over both, and the answer differs. Ask what differs.",
)

# %% id=same_pass_two_answers
TWICE = "int twice(int *p) { int a = *p; int b = *p; return a + b; }"

subjects = {"sum_to": loop.opt("mem2reg"),
            "twice": irx.compile_c(TWICE, name="twice").opt("mem2reg")}


def domtree(name, module, pipeline, *flags):
    """Did the pass change this function, and did the dominator tree survive it?"""
    lines = trace(module, f"require<domtree>,{pipeline},require<domtree>", *flags)
    after = irx.Module.from_ll(
        irx.run("opt", f"-passes={pipeline}", "-S", *flags, "-", stdin=module.text).stdout)
    dropped = sum(ln.startswith("Invalidating analysis: DominatorTreeAnalysis") for ln in lines)
    print(f"{name:<7} {pipeline:<12} changed the IR: "
          f"{after.body(name) != module.body(name)!s:<6} "
          f"dominator tree thrown away: {dropped}")


for name, module in subjects.items():
    for pipeline in ("simplifycfg", "instcombine"):
        domtree(name, module, pipeline)

# %% [markdown]
# ## Four runs, and no rule that fits them
#
# Read the four lines as a table. `simplifycfg` on `sum_to` changed the IR and the tree was thrown away. `simplifycfg` on `twice` changed nothing and the tree survived. So far the rule looks like "changing the IR invalidates the tree".
#
# Then `instcombine` on `twice` changed the IR and the tree survived. And `instcombine` on `sum_to` changed the IR and the tree survived there too.
#
# So it is not a property of the pass, because `simplifycfg` gives two different answers. And it is not a property of the change, because two passes that both changed the same function disagree. Nothing here is being detected. Every one of these four answers was *declared*, by the pass, in what it returned.

# %% [markdown]
# ## The four lines that decide
#
# A pass returns a `PreservedAnalyses`, a set of promises about what is still true. The pass manager hands that to the analysis manager, and everything not covered by it is dropped. There is no inspection of the IR, before or after.
#
# Here is the end of `SimplifyCFGPass::run`, with the parts that fetch its inputs cut:
#
# ```cpp
# PreservedAnalyses SimplifyCFGPass::run(Function &F,
#                                        FunctionAnalysisManager &AM) {
#   ...
#   if (!simplifyFunctionCFG(F, TTI, DT, Options))
#     return PreservedAnalyses::all();
#   // If we removed some blocks, update block numbers to keep dense numbering.
#   F.renumberBlocks();
#   PreservedAnalyses PA;
#   if (RequireAndPreserveDomTree) {
#     DT->updateBlockNumbers();
#     PA.preserve<DominatorTreeAnalysis>();
#   }
#   return PA;
# }
# ```
#
# It returns one of two things. If `simplifyFunctionCFG` reports no change, it returns `PreservedAnalyses::all()`, which promises everything, and nothing at all is dropped. That is the `twice` line in the table. Otherwise it builds a `PreservedAnalyses` and, with `RequireAndPreserveDomTree` off, puts nothing in it, so everything cached for that function goes. That is the `sum_to` line. Hold on to that condition, it comes back in a moment.
#
# `InstCombinePass::run` has the same first half and a different second half:
#
# ```cpp
# // Mark all the analyses that instcombine updates as preserved.
# PreservedAnalyses PA;
# PA.preserve<LastRunTrackingAnalysis>();
# PA.preserveSet<CFGAnalyses>();
# ```
#
# `CFGAnalyses` is a set covering every analysis that depends on nothing but control flow, the dominator tree among them. `instcombine` rewrites instructions and does not move branches around, so it can promise that whole set at once and keep the tree alive for whatever runs next. `EarlyCSE` ends the same way.
#
# Which leaves the obvious question about the pass in the middle of that table. `simplifycfg` clearly knows what it did to the CFG. Why does it promise nothing?
#
# `RequireAndPreserveDomTree` is a command line flag, hidden but settable, so we can answer that by asking for the other branch.

# %% id=the_flag_that_proves_it
domtree("sum_to", subjects["sum_to"], "simplifycfg",
        "-simplifycfg-require-and-preserve-domtree")

# %% [markdown]
# ## Same function, same pass, same edit, and now the tree survives
#
# One hidden flag, and the invalidation is gone. The IR that comes out is byte for byte what came out without it. The only thing that changed is what the pass said on the way home.
#
# The flag's own description says what it is:
#
# ```cpp
# cl::opt<bool> RequireAndPreserveDomTree(
#     "simplifycfg-require-and-preserve-domtree", cl::Hidden,
#
#     cl::desc(
#         "Temporary development switch used to gradually uplift SimplifyCFG "
#         "into preserving DomTree,"));
# ```
#
# Keeping a dominator tree correct through a CFG rewrite is real work, and at the pinned tag that work is partly done, sitting behind a flag that is off, with the rest of the pipeline paying for a rebuilt tree after every `simplifycfg` that changed anything.
#
# That is worth sitting with, because it is the honest shape of the thing. "The dominator tree is invalidated by `simplifycfg`" is not a fact about dominator trees or about control flow. It is the current state of an unfinished piece of work in one file, and it is one flag away from being different.
#
# ## What to keep
#
# `-print-pipeline-passes` shows what was built. `-debug-pass-manager` shows what ran. Ask for `licm,loop-rotate` and four passes run, because `loop(...)` is an adaptor that canonicalises the loop with `LoopSimplify` and `LCSSA` before letting your passes near it.
#
# Analyses are never scheduled. A pass asks the manager, the manager returns a cached result or computes one, and analyses ask each other, which is why `require<loops>` computes a dominator tree.
#
# What gets thrown away is decided by the `PreservedAnalyses` a pass *returns*. Nothing compares the IR. `simplifycfg` returns `all()` when it changed nothing and a promise of nothing otherwise, `instcombine` promises the `CFGAnalyses` set whether or not it changed anything, and `-simplifycfg-require-and-preserve-domtree` changes the answer without changing the output.
#
# So "does this pass invalidate X" is not a question about a pass. It is a question about one function, one input, and one return statement.
#
# Next: a wrong answer out of `-O2`, and how to find which of its hundred and twenty entries produced it, without reading any of them.
