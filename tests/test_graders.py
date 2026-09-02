"""Every boss fight grader, against a pipeline that solves it and several that do not.

A grader is the one piece of a lesson that a reader argues with. If it accepts a
wrong answer they learn the wrong thing, and if it rejects a right one they lose
an evening deciding whether they or the notebook is broken. Both failures are
silent, so they get a test.

These need a real LLVM, including lli, so they skip without one. The toolkit CI
job installs the pinned version and turns a skip into a failure, because a
skipped grader test looks exactly like a passing one in a log.
"""

import importlib.util
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toolkit"))

LESSONS = ROOT / "lessons"


def load(lesson_id: str):
    path = LESSONS / lesson_id / "grade.py"
    spec = importlib.util.spec_from_file_location(f"{lesson_id}_grade", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_llvm() -> bool:
    """Everything, including the import, because this runs at collection time.

    The bare build job has no LLVM and gets a skip. The toolkit job has one and
    fails on a skip, so a broken install cannot turn into a quiet green tick.
    """
    try:
        import irx

        bins = irx.current().bin
        return all(
            (bins / tool).exists() or shutil.which(tool) for tool in ("opt", "clang", "lli")
        )
    except Exception:
        return False


GAUSS = """int gauss(int n) {
  int total = 0;
  for (int i = 0; i < n; i++)
    total += i;
  return total;
}
"""


@unittest.skipUnless(has_llvm(), "needs a real LLVM with opt, clang and lli")
class TestT04(unittest.TestCase):
    """The pass tape boss fight: get rid of the loop without default<O2>."""

    @classmethod
    def setUpClass(cls):
        cls.grade = staticmethod(load("t04_the_pass_tape").grade)

    def accepts(self, pipeline):
        self.assertTrue(self.grade(pipeline, GAUSS), f"{pipeline} should have been accepted")

    def rejects(self, pipeline):
        self.assertFalse(self.grade(pipeline, GAUSS), f"{pipeline} should have been rejected")

    def test_the_intended_answer_is_accepted(self):
        self.accepts("sroa,indvars,loop-deletion")

    def test_so_is_a_different_route_to_the_same_place(self):
        # More than one answer is the point. A grader that only knows the one
        # the author had in mind teaches the reader to guess the author.
        self.accepts("mem2reg,indvars,loop-deletion")
        self.accepts("sroa,indvars,simplifycfg")

    def test_a_nested_pipeline_counts_as_one_top_level_pass(self):
        self.accepts("sroa,loop(indvars,loop-deletion)")

    def test_leaving_the_loop_behind_is_rejected(self):
        self.rejects("sroa,indvars")

    def test_deleting_before_the_loop_is_dead_is_rejected(self):
        # loop-deletion runs and finds nothing, because nothing has made the
        # loop pointless yet.
        self.rejects("sroa,loop-deletion")

    def test_the_pipeline_being_taken_apart_is_rejected(self):
        self.rejects("default<O2>")

    def test_too_many_passes_is_rejected(self):
        self.rejects("sroa,instcombine,indvars,simplifycfg,loop-deletion")

    def test_a_pass_that_does_not_exist_is_rejected(self):
        self.rejects("sroa,nosuchpass")

    def test_the_rejection_says_which_rule_was_broken(self):
        import contextlib
        import io

        for pipeline, expected in [
            ("sroa,indvars", "leaves 1 loop"),
            ("default<O2>", "contains default"),
            ("a,b,c,d,e", "is 5 passes"),
            ("sroa,nosuchpass", "would not run"),
        ]:
            said = io.StringIO()
            with contextlib.redirect_stdout(said):
                self.grade(pipeline, GAUSS)
            self.assertIn(expected, said.getvalue())
            self.assertIn(pipeline, said.getvalue())


def cell_source(lesson_id: str, cell_id: str) -> str:
    """The body of one cell of a lesson, straight out of lesson.py.

    The X03 tests build the reader's plugins from the lesson's own cells rather
    than from a copy kept here. A copy would let the lesson stop compiling
    without anything going red, which for the one lesson whose whole point is a
    pass that compiles would be an embarrassing way to find out.
    """
    sys.path.insert(0, str(ROOT))
    import build

    lesson = build.load_lesson(LESSONS / lesson_id / "lesson.py")
    for cell in lesson.cells:
        if cell.options.get("id") == cell_id:
            return cell.source
    raise KeyError(f"{lesson_id} has no cell called {cell_id}")


def plugin_from_cell(lesson_id: str, cell_id: str) -> str:
    """Compile an %%irxplug cell and hand back the pass name it registered."""
    import irx

    magic, _, body = cell_source(lesson_id, cell_id).partition("\n")
    name = magic.split()[1]
    irx.plugin.build(name, body)
    return name


def alive_available() -> bool:
    try:
        import irx

        irx.verify.find(verbose=False)
    except Exception:
        return False
    return True


@unittest.skipUnless(has_llvm(), "needs a real LLVM with opt, clang and lli")
@unittest.skipUnless(alive_available(), "needs alive-tv, set IRX_ALIVE_BIN")
class TestX03(unittest.TestCase):
    """The first fold boss fight: two folds, both sound, and a third left alone."""

    @classmethod
    def setUpClass(cls):
        cls.grade = staticmethod(load("x03_your_first_fold").grade)
        cls.naive = plugin_from_cell("x03_your_first_fold", "plugin")
        cls.half = plugin_from_cell("x03_your_first_fold", "plugin2")

    def said(self, pass_name):
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            passed = self.grade(pass_name)
        return passed, out.getvalue()

    def test_the_lessons_own_naive_pass_is_rejected(self):
        passed, said = self.said(self.naive)
        self.assertFalse(passed)
        self.assertIn("poisonous", said)

    def test_and_the_rejection_names_the_input(self):
        # The whole reason this grader uses a solver instead of a test table.
        _, said = self.said(self.naive)
        self.assertIn("%a = ", said)
        self.assertIn("(32)", said)

    def test_the_lessons_fixed_pass_is_still_only_half_an_answer(self):
        # It folds the and shape soundly and does nothing to the or shape, so it
        # has to fail on structure rather than on correctness.
        passed, said = self.said(self.half)
        self.assertFalse(passed)
        self.assertIn("should end up as an or", said)

    def test_a_pass_that_does_not_exist_is_rejected(self):
        passed, said = self.said("nosuchpass")
        self.assertFalse(passed)
        self.assertIn("would not run", said)

    def test_the_intended_answer_is_accepted(self):
        passed, said = self.said(solution("goodfold"))
        self.assertTrue(passed, said)
        self.assertIn("not a proof", said)

    def test_folding_without_the_freeze_is_rejected_on_both_shapes(self):
        name = solution("nofreeze", drop_freeze=True)
        passed, said = self.said(name)
        self.assertFalse(passed)
        self.assertIn("poisonous", said)

    def test_touching_the_third_shape_is_rejected(self):
        # select %c, %x, %y has a correct rewrite and it is four instructions,
        # so a peephole that reaches for it has stopped being a peephole.
        passed, said = self.said(solution("greedy", greedy=True))
        self.assertFalse(passed)
        self.assertIn("left alone", said)


def solution(name: str, *, drop_freeze: bool = False, greedy: bool = False) -> str:
    """Build one of the boss fight answers under its own pass name.

    Every plugin the tests build ends up loaded into the same `opt`, and the
    first callback that claims a pass name gets it, so each of these has to
    answer to one name and no others.
    """
    import irx

    source = SOLUTION.replace("PASSNAME", name)
    if drop_freeze:
        source = source.replace("B.CreateFreeze(V)", "V")
    if greedy:
        source = source.replace(
            "      if (!R) continue;",
            "      if (!R)\n"
            "        R = B.CreateOr(B.CreateAnd(C, B.CreateFreeze(T)),\n"
            "                       B.CreateAnd(B.CreateNot(C), B.CreateFreeze(E)));",
        )
    irx.plugin.build(name, source)
    return name


# One correct answer to the boss fight, kept here rather than in the lesson so
# that a reader who opens the repository looking for a hint has to look for it.
SOLUTION = """#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"

using namespace llvm;

namespace {
struct PASSNAME : PassInfoMixin<PASSNAME> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &) {
    SmallVector<SelectInst *, 8> hits;
    for (BasicBlock &BB : F)
      for (Instruction &I : BB)
        if (auto *S = dyn_cast<SelectInst>(&I))
          if (S->getType()->isIntegerTy(1))
            hits.push_back(S);

    bool changed = false;
    for (SelectInst *S : hits) {
      IRBuilder<> B(S);
      Value *C = S->getCondition(), *T = S->getTrueValue(), *E = S->getFalseValue();
      Value *V = nullptr, *R = nullptr;
      if (auto *K = dyn_cast<ConstantInt>(E))
        if (K->isZero()) { V = T; R = B.CreateAnd(C, B.CreateFreeze(V), S->getName()); }
      if (!R)
        if (auto *K = dyn_cast<ConstantInt>(T))
          if (K->isOne()) { V = E; R = B.CreateOr(C, B.CreateFreeze(V), S->getName()); }
      if (!R) continue;
      S->replaceAllUsesWith(R);
      S->eraseFromParent();
      changed = true;
    }
    return changed ? PreservedAnalyses::none() : PreservedAnalyses::all();
  }
};
}  // namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "PASSNAME", "0.1", [](PassBuilder &PB) {
    PB.registerPipelineParsingCallback(
      [](StringRef N, FunctionPassManager &FPM, ArrayRef<PassBuilder::PipelineElement>) {
        if (N == "PASSNAME") { FPM.addPass(PASSNAME()); return true; }
        return false;
      });
  }};
}
"""


if __name__ == "__main__":
    unittest.main()
