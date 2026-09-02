# ---
# id: x03_your_first_fold
# title: Your first fold, and the input that breaks it
# question: My peephole is obviously right, so how would I ever find out it is not?
# part: IV
# env: E0
# minutes: 60
# needs: [t04_the_pass_tape]
# blueprints: [BP-IR-POISON]
# ---

# %% [markdown]
# # Your first fold, and the input that breaks it
#
# Here are two C functions. They are the same shape. Both are an `&&` between two comparisons, and clang at `-O1` turns one of them into a single `and` instruction and refuses to do it to the other.
#
# That refusal is not a missed optimisation. It is LLVM declining to do something that would be wrong, and by the end of this lesson you will have written the wrong version yourself, watched every test you can think of pass, and then had a solver hand you the exact two numbers that break it.

# %% id=two_shapes
FOLDS = "int both(int a, int b) { return a > 0 && b > 0; }"
DOES_NOT = "int both(int a, int b) { return a > 0 && (a << b) > 5; }"

for name, source in [("folds", FOLDS), ("does not fold", DOES_NOT)]:
    ir = irx.compile_c(source, opt="-O1")
    line = [l for l in ir.text.splitlines() if " and i1 " in l or " select i1 " in l]
    print(f"{name:>14}  {line[0].strip()}")

# %% id=gate_why
irx.gate(
    "Same shape, two answers. What is different about the second one?",
    {
        "it is bigger": "It is one instruction longer, and LLVM does not have a size limit here. InstCombine will happily fold much larger things than this.",
        "the shift can produce a value that is not a real number": "Right. A 32 bit shift by 32 or more has no answer, and LLVM's answer for that is a value called poison. Everything below is about what poison does when you move it.",
        "the shift might be slow": "Shifts are one cycle on everything, and cost is not what InstCombine is deciding here anyway.",
        "clang forgot": "It is worth checking before you assume this, and this is one of the cases where the answer is no. There is a specific line in InstCombine that stops it, and we will read that line later on.",
    },
    answer="the shift can produce a value that is not a real number",
)

# %% [markdown]
# ## The fold
#
# The IR for the second function contains this, and it is the thing you are about to try to improve:
#
# ```llvm
# %ok  = icmp sgt i32 %a, 0
# %sh  = shl i32 %a, %b
# %big = icmp sgt i32 %sh, 5
# %r   = select i1 %ok, i1 %big, i1 false
# ```
#
# A `select` with a `false` in the else arm is an `and`. Pick `%big` when `%ok` is true and `false` when `%ok` is false, which is exactly the truth table of `%ok & %big`. One instruction instead of one instruction, but `and` is cheaper to reason about than `select` and every later pass knows more tricks for it, so this is a real and worthwhile canonicalisation. It is also the first fold most people write.
#
# We will work on it as a hand written `.ll` file rather than going through clang each time, so that nothing changes underneath us while we are looking at it.

# %% id=source
BEFORE = """define i32 @both(i32 noundef %a, i32 noundef %b) {
  %ok = icmp sgt i32 %a, 0
  %sh = shl i32 %a, %b
  %big = icmp sgt i32 %sh, 5
  %r = select i1 %ok, i1 %big, i1 false
  %z = zext i1 %r to i32
  ret i32 %z
}
"""
irx.Module(BEFORE)

# %% [markdown]
# ## Twelve lines of C++
#
# The pass below walks every instruction, keeps the `select`s that return an `i1` and have a constant zero in the false arm, and replaces each one with an `and`. The collect-then-rewrite split matters: deleting instructions while iterating over the block you are iterating is how you get a crash that looks like a compiler bug and is not.
#
# The cell compiles it, loads it into `opt`, and gives you a pass named `andsel`. No build tree and no CMake. Two details that are easy to skip past and both cost an hour if you get them wrong. The include is `llvm/Plugins/PassPlugin.h`, which moved from `llvm/Passes/` and still lives in the old place in almost every tutorial online. And the pass sits in an anonymous namespace, which is how every pass in the LLVM tree is written, because you will have a second plugin loaded into this same `opt` before the lesson is over and two exported symbols with one name is a bug you would spend a long time not finding.

# %% id=plugin
%%irxplug andsel
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"

using namespace llvm;

namespace {
struct AndSelect : PassInfoMixin<AndSelect> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &) {
    SmallVector<SelectInst *, 8> hits;
    for (BasicBlock &BB : F)
      for (Instruction &I : BB)
        if (auto *S = dyn_cast<SelectInst>(&I))
          if (S->getType()->isIntegerTy(1))
            if (auto *C = dyn_cast<ConstantInt>(S->getFalseValue()))
              if (C->isZero())
                hits.push_back(S);

    for (SelectInst *S : hits) {
      IRBuilder<> B(S);
      Value *R = B.CreateAnd(S->getCondition(), S->getTrueValue(), S->getName());
      S->replaceAllUsesWith(R);
      S->eraseFromParent();
    }
    return hits.empty() ? PreservedAnalyses::all() : PreservedAnalyses::none();
  }
};
}  // namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "andsel", "0.1", [](PassBuilder &PB) {
    PB.registerPipelineParsingCallback(
      [](StringRef N, FunctionPassManager &FPM, ArrayRef<PassBuilder::PipelineElement>) {
        if (N == "andsel") { FPM.addPass(AndSelect()); return true; }
        return false;
      });
  }};
}

# %% id=run_it
naive = irx.Module(BEFORE).opt("andsel")
irx.Module(BEFORE).diff(naive)

# %% [markdown]
# ## Now test it
#
# Six inputs, chosen to cover a positive `%a`, a negative one, a zero shift, and a shift big enough to be interesting. The original and your version go through `lli` side by side and the answers are compared. This is what testing a peephole looks like when you do it the way everybody does it.

# %% id=tests
CASES = [(1, 1), (5, 2), (0, 32), (-3, 4), (7, 0), (2, 31)]

DRIVER = """@fmt = private constant [4 x i8] c"%d\\0A\\00"
declare i32 @printf(ptr, ...)
define i32 @main() {
"""
for i, (a, b) in enumerate(CASES):
    DRIVER += f"  %r{i} = call i32 @both(i32 {a}, i32 {b})\n"
    DRIVER += f"  %p{i} = call i32 (ptr, ...) @printf(ptr @fmt, i32 %r{i})\n"
DRIVER += "  ret i32 0\n}\n"


def answers(module):
    """Glue main onto the module and interpret the whole thing with lli."""
    return irx.run("lli", "-", stdin=module + DRIVER).stdout.split()


want, got = answers(BEFORE), answers(naive.text)
for (a, b), right, mine in zip(CASES, want, got):
    verdict = "same" if right == mine else f"DIFFERENT, was {right} now {mine}"
    print(f"both({a:>3}, {b:>2}) = {mine:>2}   {verdict}")

# %% [markdown]
# Six for six. Add sixty more and it will still be six hundred for six hundred, because there is no pair of `int`s that makes these two functions print different numbers. The bug in your fold is real, it is already there in the IR above, and running the code cannot find it.
#
# That is not a gap in your test cases. It is the kind of bug that testing is structurally unable to see, and it is the reason the next tool exists.

# %% [markdown]
# ## Ask a solver instead
#
# `irx.alive` hands both versions to [Alive2](https://github.com/AliveToolkit/alive2), which builds a logical formula for each function and asks Z3 whether there is any input at all where they differ. Not a sample of inputs. Every input, including the ones nobody would think to write down.
#
# It answers one of four ways, and only one of them is good news: it verifies, it finds a counterexample, it runs out of time, or it fails. **A timeout is not a pass.** We come back to that at the end and it is the single most important thing to keep hold of from this lesson.

# %% id=check
verdict = irx.alive(BEFORE, naive.text)
verdict

# %% [markdown]
# `a = 0` and `b = 32`. Shifting a 32 bit value by 32 bits has no defined answer, so `%sh` is **poison**, which is LLVM's name for a value that is not a number and instead is a promise that this input was never supposed to happen. Poison spreads through `icmp`, so `%big` is poison too.
#
# In the original that does not matter. `%ok` is false, so the `select` picks the `false` arm and never reads `%big` at all. That is what a `select` is: it reads the arm the condition chose and ignores the other one. `and` is not like that. It reads both operands every time, so poison in either one comes straight out the other side, and your version returns poison where the original returned `0`.
#
# ![The counterexample drawn out, with the poison arm the select ignores and the and does not](https://raw.githubusercontent.com/tamnd/llvm-internals/main/docs/diagrams/poison-fold.svg)
#
# Notice which way round the rule goes. It is not that the two functions have to agree. A rewrite is allowed to take a poison result and turn it into a real one, because poison means "assume this never happens" and any answer is an acceptable answer for an input that never happens. Going the other way is what is forbidden. Alive2 will tell you as much if you ask it the question backwards, and the same two files that failed a moment ago will pass.

# %% id=backwards
irx.alive(naive.text, BEFORE)

# %% [markdown]
# That one word, refinement, is most of what separates a compiler writer from somebody who breaks compilers. The relation is one way, `alive-tv` checks it in the direction you give it, and getting the arguments the wrong way round is a mistake you will make at least once.
#
# The fix is an instruction whose entire job is stopping poison. `freeze` takes a value and returns it unchanged if it was a real value, or some arbitrary but fixed value of that type if it was poison. It is the one place in LLVM where "I do not care what this is, as long as it is something" is spelled out in the IR. The [LangRef entry](https://llvm.org/docs/LangRef.html#freeze-instruction) is worth reading once.

# %% id=gate_fix
irx.gate(
    "You are about to add a freeze. Which value needs it?",
    {
        "the condition, %ok": "The condition is read by both versions, so if it were poison both of them would be poisoned and there would be no difference to find.",
        "the true arm, %big": "Right. It is the value the select was allowed to ignore and the and is not, so it is the one that has to be made safe before the and reads it.",
        "the result": "Too late. By the time the and has produced its result the poison is already in it, and freezing it there would only hide which input caused it.",
        "both operands": "This works and it verifies, and it is one instruction more than you need. Only one of the two was protected by the select in the first place.",
    },
    answer="the true arm, %big",
    note="Freeze the value that the original was allowed to look away from.",
)

# %% [markdown]
# One extra line in the pass. `CreateFreeze` on the true arm, and the `and` reads the frozen copy. The struct has a different name from the one above because both plugins are loaded into the same `opt`, which is the situation the anonymous namespace exists for.

# %% id=plugin2
%%irxplug andsel2
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"

using namespace llvm;

namespace {
struct AndSelectSafe : PassInfoMixin<AndSelectSafe> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &) {
    SmallVector<SelectInst *, 8> hits;
    for (BasicBlock &BB : F)
      for (Instruction &I : BB)
        if (auto *S = dyn_cast<SelectInst>(&I))
          if (S->getType()->isIntegerTy(1))
            if (auto *C = dyn_cast<ConstantInt>(S->getFalseValue()))
              if (C->isZero())
                hits.push_back(S);

    for (SelectInst *S : hits) {
      IRBuilder<> B(S);
      Value *Safe = B.CreateFreeze(S->getTrueValue());
      Value *R = B.CreateAnd(S->getCondition(), Safe, S->getName());
      S->replaceAllUsesWith(R);
      S->eraseFromParent();
    }
    return hits.empty() ? PreservedAnalyses::all() : PreservedAnalyses::none();
  }
};
}  // namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "andsel2", "0.1", [](PassBuilder &PB) {
    PB.registerPipelineParsingCallback(
      [](StringRef N, FunctionPassManager &FPM, ArrayRef<PassBuilder::PipelineElement>) {
        if (N == "andsel2") { FPM.addPass(AndSelectSafe()); return true; }
        return false;
      });
  }};
}

# %% id=check2
fixed = irx.Module(BEFORE).opt("andsel2")
for line in fixed.text.splitlines():
    if "freeze" in line or " and " in line:
        print(line.strip())

irx.alive(BEFORE, fixed.text)

# %% [markdown]
# ## What LLVM does about the same problem
#
# Your first version was wrong, and so far the only reason to believe that is a solver you met ten minutes ago. So go and look at the pass that does this fold for real. It is in `llvm/lib/Transforms/InstCombine/InstCombineSelect.cpp`, and the comment above the check says the thing you found out for yourself:
#
# > Folding select to and/or i1 isn't poison safe in general. impliesPoison checks whether folding it does not convert a well-defined value into poison.
#
# Two folds sit under that comment, and they are the two you are being asked for in the boss fight. `select B, true, C` becomes `or B, C` and `select B, C, false` becomes `and B, C`, and both are wrapped in the same guard, a call to `impliesPoisonOrCond`. If InstCombine can prove the arm was never going to be poison it does the fold, and if it cannot, it leaves the `select` alone. It does not reach for `freeze` here, because a `freeze` costs a real instruction and this fold is not worth one.
#
# Which means the two C functions at the top of this lesson are the two sides of that check, and you can watch InstCombine take each branch.

# %% id=instcombine
SAFE = BEFORE.replace("%sh = shl i32 %a, %b", "%sh = add i32 %a, 1")

for label, module in [("shl, can be poison", BEFORE), ("add, cannot", SAFE)]:
    out = irx.Module(module).opt("instcombine")
    kept = "select" if "select" in out.text else "and"
    print(f"{label:>20}  instcombine left a {kept}")

# %% [markdown]
# `add i32 %a, 1` with no `nsw` on it wraps rather than producing poison, so `impliesPoison` succeeds and the fold happens. Put the `shl` back and it does not. Same pass, same fold, and the deciding question is the one you spent this lesson on.
#
# ## The size of the guarantee you now have
#
# Alive2 proved something real about the fixed version, and it is important to know exactly how much. The solver is bounded. It reasons about the function at the width it is written, and the work it has to do grows fast with that width, so it can and will run out of time. Here is that happening, in this notebook, right now.
#
# The example is a different fold: replacing a signed divide by two with a shift, which is wrong, and the three instruction version that rounds towards zero, which is right. Watch what happens to each one as the type gets wider.

# %% id=bound
import time

SDIV = "define i{w} @half(i{w} %x) {{\n  %r = sdiv i{w} %x, 2\n  ret i{w} %r\n}}\n"
SHIFT = "define i{w} @half(i{w} %x) {{\n  %r = ashr i{w} %x, 1\n  ret i{w} %r\n}}\n"
ROUND = ("define i{w} @half(i{w} %x) {{\n"
         "  %s = lshr i{w} %x, {top}\n"
         "  %b = add i{w} %x, %s\n"
         "  %r = ashr i{w} %b, 1\n"
         "  ret i{w} %r\n}}\n")

for width in (8, 32):
    for label, after in [("plain shift, wrong", SHIFT), ("rounded shift, right", ROUND)]:
        start = time.monotonic()
        report = irx.alive(SDIV.format(w=width), after.format(w=width, top=width - 1),
                           smt_seconds=5, verbose=False)
        print(f"i{width:<3} {label:>22}  {report[0].status:>8}  {time.monotonic() - start:5.2f}s")

# %% [markdown]
# Finding the counterexample stays fast at every width, because the solver only has to produce one number and `-1` breaks the plain shift immediately. Proving there is no counterexample is the expensive direction, and somewhere between `i8` and `i32` it stops being possible in the time you gave it.
#
# So read the results honestly. A red card means your transformation is wrong and here is why, and that is a fact. A green card means no counterexample exists for that function at that width, which is a strong and useful thing to know and is not a proof that your pass is correct in general. An amber card means the solver gave up and you learned nothing at all, which is worth saying out loud because an amber card next to a green one looks like a near miss and it is not.
#
# The fold you fixed above verifies in hundredths of a second, because it is four instructions of `i1`. Most peepholes are like that. Reach for anything wider or with a divide in it and you will meet the amber card soon enough.

# %% [markdown]
# ## Boss fight
#
# Write one pass that does two folds, both of them soundly.
#
# 1. `select i1 %c, i1 %x, i1 false` becomes an `and`.
# 2. `select i1 %c, i1 true, i1 %x` becomes an `or`. This is the mirror of the first one, and it needs the same protection for the same reason.
# 3. A `select` with neither arm constant is left alone. There is a correct rewrite for that shape and it takes four instructions to say what one instruction already said, so a peephole should not do it.
#
# The grader runs your pass on all three, checks the right thing happened to each, and puts every result through Alive2. If it finds a counterexample it will print the input.

# %% include=grade.py id=grader

# %% id=attempt
# Build your pass in a %%irxplug cell above this one, then name it here.
grade("andsel2")

# %% [markdown]
# ## What you now know
#
# - A `select` reads one arm, an `and` reads both, and that is a difference you cannot see by running the code.
# - Poison is what LLVM produces when an operation has no right answer, and it spreads through everything that reads it.
# - A rewrite may turn poison into a real value and may never turn a real value into poison. That is refinement, it only runs one way, and it is the rule Alive2 is checking.
# - `freeze` converts poison into some fixed value, which is how you make a fold like this legal when you cannot prove the poison was not there.
# - Real InstCombine guards this exact fold with `impliesPoison` and gives up rather than folding when it cannot prove the arm is safe.
# - Alive2 is bounded. Wrong is a fact, correct is correct at that width, and a timeout tells you nothing.
#
# The Blueprint for all of it is [BP-IR-POISON](../../blueprints/BP-IR-POISON.md), which is the one to read before you write a pass that anybody else will run.
