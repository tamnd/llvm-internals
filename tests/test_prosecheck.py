"""Tests for tools/prosecheck.py.

The lesson reading is what these are mostly about. Almost all the prose in this
repository will live in the markdown cells of lesson files rather than in .md
files, so a prose checker that only reads .md is a prose checker that does not
read the prose.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import prosecheck  # noqa: E402

LESSON = '''# ---
# id: t04_the_pass_tape
# title: The pass tape
# ---

# %% [markdown]
# # The pass tape
#
# Two hundred passes run and almost none of them touch your function.

# %%
# This comment is code, so the rules do not apply to it. It is obviously fine.
print("hello")

# %% [markdown]
# One more paragraph, on one line, the way every paragraph here has to be.
'''


def write(text, name="lesson.py"):
    directory = Path(tempfile.mkdtemp())
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class TestReadingALesson(unittest.TestCase):
    def test_a_clean_lesson_passes(self):
        self.assertEqual(prosecheck.check(write(LESSON)), [])

    def test_the_comment_prefix_is_stripped_before_the_rules_run(self):
        lines = dict(prosecheck.lesson_lines(write(LESSON)))
        self.assertEqual(lines[7], "# The pass tape")

    def test_the_header_is_not_prose(self):
        lines = dict(prosecheck.lesson_lines(write(LESSON)))
        self.assertNotIn(3, lines)

    def test_code_cells_are_not_prose(self):
        body = " ".join(text for _, text in prosecheck.lesson_lines(write(LESSON)))
        self.assertNotIn("This comment is code", body)

    def test_a_banned_word_in_a_markdown_cell_is_caught(self):
        bad = LESSON.replace("almost none of them", "just none of them")
        problems = prosecheck.check(write(bad))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("banned word 'just'", problems[0])

    def test_a_banned_word_in_a_code_cell_is_not(self):
        bad = LESSON.replace('print("hello")', 'print("just testing")')
        self.assertEqual(prosecheck.check(write(bad)), [])

    def test_an_em_dash_in_a_markdown_cell_is_caught(self):
        bad = LESSON.replace("run and almost", "run — almost")
        problems = prosecheck.check(write(bad))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("em dash", problems[0])

    def test_a_hard_wrapped_paragraph_is_caught(self):
        bad = LESSON.replace(
            "# Two hundred passes run and almost none of them touch your function.",
            "# Two hundred passes run and almost none\n# of them touch your function.",
        )
        problems = prosecheck.check(write(bad))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("hard wrapped", problems[0])

    def test_the_line_number_is_the_line_in_the_lesson(self):
        bad = LESSON.replace("almost none of them", "just none of them")
        # Line 9 of LESSON, counting the header and the cell marker.
        self.assertIn(":9:", prosecheck.check(write(bad))[0])

    def test_the_last_line_of_a_cell_does_not_wrap_into_the_next_cell(self):
        # Both cells end in a sentence. Without a break between them the wrap
        # rule would read the second cell as a continuation of the first.
        self.assertEqual(prosecheck.check(write(LESSON)), [])

    def test_a_fence_inside_a_markdown_cell_is_skipped(self):
        fenced = LESSON.replace(
            "# %%\n# This comment is code",
            "# %% [markdown]\n# ```\n# just obviously simply\n# ```\n\n# %%\n# This comment is code",
        )
        self.assertEqual(prosecheck.check(write(fenced)), [])


class TestReadingMarkdown(unittest.TestCase):
    def test_a_clean_file_passes(self):
        path = write("# Title\n\nOne sentence on one line.\n", name="doc.md")
        self.assertEqual(prosecheck.check(path), [])

    def test_a_banned_word_is_caught(self):
        path = write("# Title\n\nThis is just fine.\n", name="doc.md")
        self.assertIn("banned word", prosecheck.check(path)[0])

    def test_prose_ok_exempts_a_line(self):
        path = write("Do not write just here. <!-- prose-ok -->\n", name="doc.md")
        self.assertEqual(prosecheck.check(path), [])


class TestWhichFilesGetRead(unittest.TestCase):
    def test_a_tool_cache_is_skipped(self):
        self.assertFalse(prosecheck.ours(Path("toolkit/.pytest_cache/README.md")))

    def test_the_pull_request_template_is_not(self):
        self.assertTrue(prosecheck.ours(Path(".github/pull_request_template.md")))


if __name__ == "__main__":
    unittest.main()
