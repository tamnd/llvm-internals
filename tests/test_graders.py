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


if __name__ == "__main__":
    unittest.main()
