"""Tests for irx.alive.

The transcripts in here are real. They were captured from alive-tv built against
the pin, and they are pasted rather than generated so that the parser tests run
on a machine with no Alive2 on it. If upstream changes the wording, these are
the tests that should fail first, because the alternative is a lesson that reads
a "wrong" as a "correct" and says nothing.
"""

from __future__ import annotations

import unittest

from irx import verify as A

WRONG = """
----------------------------------------
define i32 @half(i32 %x) {
#0:
  %r = sdiv i32 %x, 2
  ret i32 %r
}
=>
define i32 @half(i32 %x) {
#0:
  %r = ashr i32 %x, 1
  ret i32 %r
}
Transformation doesn't verify!

ERROR: Value mismatch

Example:
i32 %x = #xffffffff (4294967295, -1)

Source:
i32 %r = #x00000000 (0)

Target:
i32 %r = #xffffffff (4294967295, -1)
Source value: #x00000000 (0)
Target value: #xffffffff (4294967295, -1)

Summary:
  0 correct transformations
  1 incorrect transformations
  0 failed-to-prove transformations
  0 Alive2 errors
"""

CORRECT = """
----------------------------------------
define i32 @src(i32 %x) {
#0:
  %r = udiv i32 %x, 2
  ret i32 %r
}
=>
define i32 @tgt(i32 %x) {
#0:
  %r = lshr i32 %x, 1
  ret i32 %r
}
Transformation seems to be correct!

"""

TIMEOUT = """
----------------------------------------
define i32 @src(i32 %x) {
#0:
  %r = sdiv i32 %x, 2
  ret i32 %r
}
=>
define i32 @tgt(i32 %x) {
#0:
  %sign = lshr i32 %x, 31
  %bump = add i32 %x, %sign
  %r = ashr i32 %bump, 1
  ret i32 %r
}
ERROR: Timeout
"""

POISON = """
----------------------------------------
define i32 @src(i32 %x) {
#0:
  %r = add i32 %x, %x
  ret i32 %r
}
=>
define i32 @tgt(i32 %x) {
#0:
  %r = shl nsw i32 %x, 1
  ret i32 %r
}
Transformation doesn't verify!

ERROR: Target is more poisonous than source

Example:
i32 %x = #x40000000 (1073741824)

Source:
i32 %r = #x80000000 (2147483648, -2147483648)

Target:
i32 %r = poison
Source value: #x80000000 (2147483648, -2147483648)
Target value: poison
"""

UNTOUCHED = """
----------------------------------------
define i32 @half(i32 noundef %x) {
entry:
  %div = sdiv i32 noundef %x, 2
  ret i32 %div
}
=>
define i32 @half(i32 noundef %x) {
entry:
  %div = sdiv i32 noundef %x, 2
  ret i32 %div
}
Transformation seems to be correct! (syntactically equal)

Summary:
  1 correct transformations
  0 incorrect transformations
  0 failed-to-prove transformations
  0 Alive2 errors
"""

POISON_UNIQUE = """
----------------------------------------
define i1 @both(i1 %ok, i1 %same) {
#0:
  %r = select i1 %ok, i1 %same, i1 0
  ret i1 %r
}
=>
define i1 @both(i1 %ok, i1 %same) {
#0:
  %r1 = and i1 %ok, %same
  ret i1 %r1
}
Transformation doesn't verify!

ERROR: Target is more poisonous than source

NOTE: The counterexample is unique.

Example:
i1 %ok = #x0 (0)
i1 %same = poison

Source:
i1 %r = #x0 (0)

Target:
i1 %r1 = poison
Source value: #x0 (0)
Target value: poison
"""

TWO = CORRECT.rstrip() + "\n" + WRONG


class TestACounterexample(unittest.TestCase):
    def setUp(self):
        self.report = A.parse(WRONG)
        self.v = self.report[0]

    def test_the_report_is_false(self):
        self.assertFalse(self.report)
        self.assertFalse(self.report.ok)

    def test_one_function_was_checked(self):
        self.assertEqual(len(self.report), 1)

    def test_the_function_is_named(self):
        self.assertEqual(self.v.function, "half")

    def test_the_status_is_wrong_and_not_merely_false(self):
        self.assertEqual(self.v.status, "wrong")

    def test_the_kind_of_wrongness_is_kept(self):
        self.assertEqual(self.v.kind, "Value mismatch")

    def test_the_input_that_breaks_it_is_pulled_out(self):
        self.assertEqual(self.v.example, [("%x", "#xffffffff (4294967295, -1)")])

    def test_both_answers_are_pulled_out(self):
        self.assertEqual(self.v.source, [("%r", "#x00000000 (0)")])
        self.assertEqual(self.v.target, [("%r", "#xffffffff (4294967295, -1)")])

    def test_the_trailing_summary_lines_are_not_read_as_values(self):
        # alive-tv repeats itself with "Source value:" and "Target value:"
        # lines. Those have no equals sign, so they must not turn into pairs.
        self.assertEqual(len(self.v.target), 1)

    def test_both_versions_of_the_ir_are_kept(self):
        self.assertIn("sdiv", self.v.src_ir)
        self.assertIn("ashr", self.v.tgt_ir)
        self.assertNotIn("ashr", self.v.src_ir)

    def test_the_text_form_names_the_input(self):
        said = str(self.v)
        self.assertIn("It breaks on", said)
        self.assertIn("-1", said)

    def test_the_card_says_wrong(self):
        self.assertIn("Wrong", self.v._repr_html_())


class TestSomethingCorrect(unittest.TestCase):
    def test_the_report_is_true(self):
        self.assertTrue(A.parse(CORRECT))

    def test_the_status_says_so(self):
        self.assertEqual(A.parse(CORRECT)[0].status, "correct")

    def test_there_is_no_counterexample_to_show(self):
        self.assertEqual(A.parse(CORRECT)[0].example, [])


class TestATimeout(unittest.TestCase):
    """The one a reader must not mistake for a pass."""

    def test_it_is_not_correct(self):
        self.assertFalse(A.parse(TIMEOUT))

    def test_it_is_not_wrong_either(self):
        self.assertEqual(A.parse(TIMEOUT)[0].status, "timeout")

    def test_the_text_form_says_the_solver_gave_up(self):
        self.assertIn("ran out of time", str(A.parse(TIMEOUT)))

    def test_the_card_does_not_use_the_word_correct(self):
        html = A.parse(TIMEOUT)[0]._repr_html_()
        self.assertIn("No answer", html)
        self.assertNotIn(">Correct<", html)


class TestPoison(unittest.TestCase):
    def test_the_kind_is_kept_whole(self):
        self.assertEqual(A.parse(POISON)[0].kind, "Target is more poisonous than source")

    def test_poison_survives_as_a_value(self):
        self.assertEqual(A.parse(POISON)[0].target, [("%r", "poison")])

    def test_an_aside_from_the_tool_is_kept(self):
        self.assertEqual(A.parse(POISON_UNIQUE)[0].remarks, ["The counterexample is unique."])

    def test_the_aside_does_not_swallow_the_counterexample(self):
        # The NOTE line sits between the error and the example, so a parser that
        # treated it as the start of a section would lose the inputs.
        v = A.parse(POISON_UNIQUE)[0]
        self.assertEqual(v.example, [("%ok", "#x0 (0)"), ("%same", "poison")])

    def test_the_aside_shows_up_in_both_renderings(self):
        v = A.parse(POISON_UNIQUE)[0]
        self.assertIn("unique", str(v))
        self.assertIn("unique", v._repr_html_())


class TestAPassThatDidNothing(unittest.TestCase):
    """A tick that means nothing happened, which is not the same as a tick.

    This is the shape most rows in the probe table have, and reading it as
    "verified" would mean a reader looking for their own pass in a pipeline
    concludes it is correct when in fact it never fired.
    """

    def setUp(self):
        self.v = A.parse(UNTOUCHED)[0]

    def test_the_parenthetical_does_not_break_the_verdict(self):
        self.assertEqual(self.v.status, "correct")

    def test_the_parenthetical_is_kept(self):
        self.assertEqual(self.v.note, "syntactically equal")

    def test_it_is_marked_as_untouched(self):
        self.assertTrue(self.v.untouched)

    def test_the_text_form_says_nothing_was_checked(self):
        self.assertIn("nothing to check", str(self.v))

    def test_the_card_does_not_claim_correct(self):
        html = self.v._repr_html_()
        self.assertIn("Unchanged", html)
        self.assertNotIn(">Correct<", html)

    def test_a_real_verdict_is_not_marked_untouched(self):
        self.assertFalse(A.parse(CORRECT)[0].untouched)


class TestSeveralFunctions(unittest.TestCase):
    def test_every_one_is_reported(self):
        self.assertEqual(len(A.parse(TWO)), 2)

    def test_one_failure_makes_the_whole_report_false(self):
        self.assertFalse(A.parse(TWO))

    def test_the_failures_can_be_asked_for_on_their_own(self):
        failed = A.parse(TWO).failed
        self.assertEqual([v.function for v in failed], ["half"])


class TestNothingToCheck(unittest.TestCase):
    def test_an_empty_transcript_parses_to_nothing(self):
        self.assertEqual(len(A.parse("")), 0)

    def test_and_the_report_is_not_quietly_true(self):
        # all() of an empty list is True, which would turn "alive-tv found no
        # functions" into "everything verified". That is the worst available bug
        # in this file.
        self.assertFalse(A.parse(""))


def alive_available() -> bool:
    try:
        A.find(verbose=False)
    except Exception:
        return False
    return True


needs_alive = unittest.skipUnless(
    alive_available(), "no alive-tv, set IRX_ALIVE_BIN to run these"
)

HALF = """define i32 @half(i32 %x) {
  %r = sdiv i32 %x, 2
  ret i32 %r
}
"""

HALF_SHIFTED = """define i32 @half(i32 %x) {
  %r = ashr i32 %x, 1
  ret i32 %r
}
"""

HALF_FIXED_I8 = """define i8 @half(i8 %x) {
  %sign = lshr i8 %x, 7
  %bump = add i8 %x, %sign
  %r = ashr i8 %bump, 1
  ret i8 %r
}
"""

HALF_I8 = """define i8 @half(i8 %x) {
  %r = sdiv i8 %x, 2
  ret i8 %r
}
"""


@needs_alive
class TestAgainstRealAlive(unittest.TestCase):
    def test_the_classic_wrong_fold_gets_caught(self):
        report = A.alive(HALF, HALF_SHIFTED, verbose=False)
        self.assertFalse(report)
        self.assertEqual(report[0].status, "wrong")
        self.assertIn("-1", report[0].example[0][1])

    def test_the_fix_verifies_at_a_width_the_solver_can_manage(self):
        self.assertTrue(A.alive(HALF_I8, HALF_FIXED_I8, verbose=False))

    def test_one_module_holding_src_and_tgt_works_too(self):
        both = HALF.replace("@half", "@src") + "\n" + HALF_SHIFTED.replace("@half", "@tgt")
        self.assertFalse(A.alive(both, verbose=False))

    def test_two_modules_with_no_name_in_common_is_an_error_and_not_a_pass(self):
        with self.assertRaises(A.AliveError) as caught:
            A.alive(HALF, HALF_SHIFTED.replace("@half", "@other"), verbose=False)
        self.assertIn("pairs functions by name", str(caught.exception))

    def test_a_short_budget_produces_a_timeout_and_not_a_verdict(self):
        wide = HALF_FIXED_I8.replace("i8", "i32").replace(", 7", ", 31")
        report = A.alive(HALF.replace("i32", "i32"), wide, smt_seconds=1, verbose=False)
        self.assertEqual(report[0].status, "timeout")


if __name__ == "__main__":
    unittest.main()
