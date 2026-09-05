"""Tests for tools/refcheck.py.

The ones that matter are the three about rot, because those are the failures
refcheck exists for and all three are silent without it: a claim naming a cell
that has been renamed, a citation still carrying the tag from before a pin
bump, and a citation whose line range runs off the end of the file it names.

The rest are about the parser being strict. A claims file is the evidence for
everything a lesson asserts, and a parser that quietly accepts a shape it does
not understand turns that evidence into decoration.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import refcheck

CLAIMS = """# a comment
claims:
  - id: the-first-one
    claim: Something that is true.
    evidence: cell one
    citation: llvm/lib/IR/Verifier.cpp:10-20@llvmorg-23.1.0
    confidence: cited

  - id: the-second-one
    claim: Something else, whose sentence is long enough that it got folded
      across two lines the way a claims file is allowed to.
    evidence: cells one, two and three
    confidence: observed
"""

LESSON = """# ---
# id: demo
# ---

# %% id=one
print(1)

# %% id=two
print(2)

# %% id=three
print(3)
"""


class ParseClaims(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.yaml"
            path.write_text(text, encoding="utf-8")
            return refcheck.parse_claims(path)

    def test_reads_the_fields(self):
        claims = self.parse(CLAIMS)
        self.assertEqual([c["id"] for c in claims], ["the-first-one", "the-second-one"])
        self.assertEqual(claims[0]["confidence"], "cited")

    def test_folds_a_continuation_onto_one_value(self):
        claims = self.parse(CLAIMS)
        self.assertIn("folded across two lines", claims[1]["claim"])

    def test_a_claim_may_have_no_citation(self):
        # x03 established this shape: observed, evidenced by a cell, no citation.
        self.assertNotIn("citation", self.parse(CLAIMS)[1])

    def test_rejects_a_field_before_the_claims_key(self):
        with self.assertRaises(refcheck.Problem):
            self.parse("id: loose\nclaims:\n  - id: x\n")

    def test_rejects_an_unindented_field(self):
        with self.assertRaises(refcheck.Problem):
            self.parse("claims:\n  - id: x\nclaim: not indented\n")


class ReferencedCells(unittest.TestCase):
    def test_one_cell(self):
        self.assertEqual(refcheck.referenced_cells("cell find_the_note"), {"find_the_note"})

    def test_a_list_of_cells(self):
        self.assertEqual(
            refcheck.referenced_cells("cells one, two and three"),
            {"one", "two", "three"},
        )

    def test_stops_at_prose_rather_than_inventing_a_cell(self):
        # The connecting words in this one are the reason the reader is cautious.
        # "and" and "opt" are not cells, and reading them as cells would fail a
        # lesson that is correct.
        found = refcheck.referenced_cells(
            "cell watch_the_skips, and opt -passes=verify over a hand written define")
        self.assertEqual(found, {"watch_the_skips"})

    def test_finds_a_cell_named_later_in_the_sentence(self):
        self.assertEqual(
            refcheck.referenced_cells("the order of the two passes in cell blame_gvn"),
            {"blame_gvn"},
        )

    def test_two_separate_mentions(self):
        self.assertEqual(
            refcheck.referenced_cells("cell twice_tape, and cell three_alone for the three"),
            {"twice_tape", "three_alone"},
        )


def a_lesson(test, claims=CLAIMS, lesson=LESSON):
    """A directory holding one claims file and one lesson, gone at teardown."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    directory = Path(tmp.name) / "demo"
    directory.mkdir()
    (directory / "claims.yaml").write_text(claims, encoding="utf-8")
    (directory / "lesson.py").write_text(lesson, encoding="utf-8")
    return directory


class CheckLesson(unittest.TestCase):
    def build(self, claims=CLAIMS, lesson=LESSON):
        return a_lesson(self, claims, lesson)

    def test_a_good_lesson_has_no_problems(self):
        problems, _, claims = refcheck.check_lesson(self.build(), "llvmorg-23.1.0", None)
        self.assertEqual(problems, [])
        self.assertEqual(len(claims), 2)

    def test_catches_a_cell_that_has_been_renamed(self):
        directory = self.build(lesson=LESSON.replace("id=one", "id=uno"))
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertTrue(any("cell `one`" in p for p in problems), problems)

    def test_catches_a_citation_left_on_the_old_pin(self):
        directory = self.build()
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-24.1.0", None)
        self.assertTrue(any("pinned to llvmorg-23.1.0" in p for p in problems), problems)

    def test_catches_a_cited_claim_with_nothing_cited(self):
        directory = self.build(claims=CLAIMS.replace(
            "    citation: llvm/lib/IR/Verifier.cpp:10-20@llvmorg-23.1.0\n", ""))
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertTrue(any("has to say what it cites" in p for p in problems), problems)

    def test_catches_an_unknown_confidence(self):
        directory = self.build(claims=CLAIMS.replace("confidence: observed",
                                                     "confidence: probably"))
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertTrue(any("`probably`" in p for p in problems), problems)

    def test_catches_too_much_inference(self):
        one = ("  - id: guess-{n}\n    claim: A guess.\n"
               "    evidence: cell one\n    confidence: inferred\n")
        directory = self.build(claims="claims:\n" + "".join(
            one.format(n=n) for n in range(refcheck.MAX_INFERRED + 1)))
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertTrue(any("inferred claims" in p for p in problems), problems)

    def test_catches_a_duplicate_id(self):
        directory = self.build(claims=CLAIMS.replace("the-second-one", "the-first-one"))
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertTrue(any("share the id" in p for p in problems), problems)

    def test_a_missing_claims_file_is_a_problem(self):
        directory = self.build()
        (directory / "claims.yaml").unlink()
        problems, _, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertEqual(problems, ["demo: no claims.yaml"])

    def test_an_unmentioned_cell_is_a_note_and_not_a_problem(self):
        directory = self.build(lesson=LESSON + "\n# %% id=scene_setting\nprint(4)\n")
        problems, notes, _ = refcheck.check_lesson(directory, "llvmorg-23.1.0", None)
        self.assertEqual(problems, [])
        self.assertTrue(any("scene_setting" in n for n in notes), notes)

    def test_boss_fight_machinery_is_not_even_a_note(self):
        extra = "\n# %% id=grader\npass\n\n# %% id=gate_one\npass\n"
        _, notes, _ = refcheck.check_lesson(self.build(lesson=LESSON + extra),
                                            "llvmorg-23.1.0", None)
        self.assertEqual([n for n in notes if "grader" in n or "gate_one" in n], [])


class AgainstASourceTree(unittest.TestCase):
    """The --llvm-src checks, against a tree standing in for llvm-project."""

    def tree(self, lines=30):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        target = root / "llvm" / "lib" / "IR"
        target.mkdir(parents=True)
        (target / "Verifier.cpp").write_text("x\n" * lines, encoding="utf-8")
        return root

    def test_a_citation_that_resolves(self):
        problems = refcheck.check_source(
            "where", "llvm/lib/IR/Verifier.cpp:10-20@llvmorg-23.1.0", self.tree())
        self.assertEqual(problems, [])

    def test_catches_a_line_range_off_the_end_of_the_file(self):
        problems = refcheck.check_source(
            "where", "llvm/lib/IR/Verifier.cpp:10-9000@llvmorg-23.1.0", self.tree())
        self.assertTrue(any("reaches 9000" in p for p in problems), problems)

    def test_a_shapeless_citation_is_still_a_note_here(self):
        # There is nothing for this mode to resolve, which is the reason to say
        # so rather than the reason to go quiet.
        _, notes, _ = refcheck.check_lesson(
            a_lesson(self, claims=CLAIMS.replace(
                "llvm/lib/IR/Verifier.cpp:10-20@llvmorg-23.1.0",
                "the section of LangRef about phi")),
            "llvmorg-23.1.0", self.tree())
        self.assertTrue(any("names no file and line range" in n for n in notes), notes)

    def test_catches_a_path_that_is_not_there(self):
        problems = refcheck.check_source(
            "where", "llvm/lib/IR/Verifer.cpp:10-20@llvmorg-23.1.0", self.tree())
        self.assertTrue(any("is not in" in p for p in problems), problems)


class TheRepository(unittest.TestCase):
    """refcheck against the lessons that are actually in this repository.

    Not a test of refcheck so much as a test of the claims files, which is the
    point of having it run in CI at all.
    """

    def test_every_claim_in_every_lesson_checks_out(self):
        tag = refcheck.pinned_tag()
        problems = []
        for directory in sorted(refcheck.LESSONS.iterdir()):
            if (directory / "lesson.py").is_file():
                problems += refcheck.check_lesson(directory, tag, None)[0]
        self.assertEqual(problems, [])

    def test_the_ledger_is_not_stale(self):
        tag = refcheck.pinned_tag()
        everything = []
        for directory in sorted(refcheck.LESSONS.iterdir()):
            if (directory / "lesson.py").is_file():
                claims = refcheck.check_lesson(directory, tag, None)[2]
                if claims:
                    everything.append((directory.name, claims))
        expected = refcheck.ledger(everything, tag) + "\n"
        self.assertEqual(
            refcheck.LEDGER.read_text(encoding="utf-8"),
            expected,
            "docs/claims.md is out of date, run tools/refcheck.py --ledger",
        )


if __name__ == "__main__":
    unittest.main()
