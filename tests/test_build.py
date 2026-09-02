"""Tests for build.py.

The one that matters is test_rebuild_is_byte_identical. Everything else in this
repository's review process assumes that a committed notebook is exactly what
the lesson source produces, and if that stops being true nobody notices until
somebody has been editing generated files for a month.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build  # noqa: E402

LESSON = """# ---
# id: t04_the_pass_tape
# title: The pass tape
# part: I
# env: E0
# minutes: 35
# needs: [t01_hello, t03_opt]
# blueprints: [BP-AN-PM]
# ---

# %% [markdown]
# # The pass tape
#
# Two hundred passes run when you type -O2. Most of them do nothing.

# %%
print("hello")

# %% env=E1
# This one needs a full build tree.
print("big")

# %% [markdown]
# ## What just happened
"""


class Harness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.lessons = root / "lessons"
        self.notebooks = root / "notebooks"
        self.lessons.mkdir()
        self._saved = (build.LESSONS, build.NOTEBOOKS, build.ROOT)
        build.LESSONS, build.NOTEBOOKS, build.ROOT = self.lessons, self.notebooks, root
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        build.LESSONS, build.NOTEBOOKS, build.ROOT = self._saved
        self.tmp.cleanup()

    def write(self, lesson_id: str, text: str) -> Path:
        d = self.lessons / lesson_id
        d.mkdir(exist_ok=True)
        path = d / "lesson.py"
        path.write_text(text, encoding="utf-8")
        return path


class TestParsing(Harness):
    def test_header_and_cells(self) -> None:
        lesson = build.load_lesson(self.write("t04_the_pass_tape", LESSON))
        self.assertEqual(lesson.header["title"], "The pass tape")
        self.assertEqual(lesson.header["minutes"], 35)
        self.assertEqual(lesson.header["needs"], ["t01_hello", "t03_opt"])
        self.assertEqual([c.kind for c in lesson.cells], ["markdown", "code", "code", "markdown"])

    def test_markdown_comment_prefix_is_stripped(self) -> None:
        lesson = build.load_lesson(self.write("t04_the_pass_tape", LESSON))
        first = lesson.cells[0].source
        self.assertTrue(first.startswith("# The pass tape"))
        self.assertIn("\n\nTwo hundred passes", first)

    def test_id_must_match_directory(self) -> None:
        path = self.write("t05_elsewhere", LESSON)
        with self.assertRaisesRegex(build.LessonError, "does not match directory"):
            build.load_lesson(path)

    def test_unknown_header_key_is_rejected(self) -> None:
        path = self.write("t04_the_pass_tape", LESSON.replace("# part: I", "# parts: I"))
        with self.assertRaisesRegex(build.LessonError, "unknown header key"):
            build.load_lesson(path)

    def test_missing_required_key_is_rejected(self) -> None:
        path = self.write("t04_the_pass_tape", LESSON.replace("# minutes: 35\n", ""))
        with self.assertRaisesRegex(build.LessonError, "missing minutes"):
            build.load_lesson(path)

    def test_bad_env_is_rejected(self) -> None:
        path = self.write("t04_the_pass_tape", LESSON.replace("# env: E0", "# env: colab"))
        with self.assertRaisesRegex(build.LessonError, "env must be one of"):
            build.load_lesson(path)

    def test_unknown_cell_option_is_rejected(self) -> None:
        path = self.write("t04_the_pass_tape", LESSON.replace("# %% env=E1", "# %% enviroment=E1"))
        with self.assertRaisesRegex(build.LessonError, "unknown cell option"):
            build.load_lesson(path)

    def test_first_cell_must_be_markdown(self) -> None:
        broken = LESSON.replace("# %% [markdown]\n# # The pass tape", "# %%\nx = 1\n\n# %% [markdown]\n# # T", 1)
        path = self.write("t04_the_pass_tape", broken)
        with self.assertRaisesRegex(build.LessonError, "first cell must be markdown"):
            build.load_lesson(path)

    def test_tabs_are_rejected(self) -> None:
        path = self.write("t04_the_pass_tape", LESSON.replace('print("hello")', '\tprint("x")'))
        with self.assertRaisesRegex(build.LessonError, "contains a tab"):
            build.load_lesson(path)


class TestNotebook(Harness):
    def notebook(self) -> dict:
        lesson = build.load_lesson(self.write("t04_the_pass_tape", LESSON))
        return build.to_notebook(lesson)

    def test_badge_is_first_and_bootstrap_is_third(self) -> None:
        cells = self.notebook()["cells"]
        self.assertIn("colab-badge.svg", "".join(cells[0]["source"]))
        self.assertIn("The pass tape", "".join(cells[1]["source"]))
        self.assertIn("irx.bootstrap()", "".join(cells[2]["source"]))

    def test_no_outputs_and_no_execution_counts(self) -> None:
        for cell in self.notebook()["cells"]:
            if cell["cell_type"] == "code":
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])

    def test_e1_cells_are_tagged_so_ci_skips_them(self) -> None:
        cells = self.notebook()["cells"]
        tagged = [c for c in cells if "skip-execution" in c["metadata"].get("tags", [])]
        self.assertEqual(len(tagged), 1)
        self.assertIn("big", "".join(tagged[0]["source"]))

    def test_cell_ids_are_unique(self) -> None:
        ids = [c["id"] for c in self.notebook()["cells"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_source_lines_keep_their_newlines(self) -> None:
        # Jupyter's own convention. Get it wrong and every notebook renders as
        # one long line in some viewers and correctly in others.
        for cell in self.notebook()["cells"]:
            for line in cell["source"][:-1]:
                self.assertTrue(line.endswith("\n"), line)
            self.assertFalse(cell["source"][-1].endswith("\n"))

    def test_metadata_records_the_pin(self) -> None:
        meta = self.notebook()["metadata"]["llvm_internals"]
        self.assertEqual(meta["pin"], build.read_pin()["tag"])
        self.assertEqual(meta["env"], "E0")

    def test_bootstrap_can_be_turned_off(self) -> None:
        source = LESSON.replace("# minutes: 35", "# minutes: 35\n# bootstrap: none")
        lesson = build.load_lesson(self.write("t04_the_pass_tape", source))
        joined = json.dumps(build.to_notebook(lesson))
        self.assertNotIn("irx.bootstrap", joined)


class TestByteStability(Harness):
    def test_rebuild_is_byte_identical(self) -> None:
        self.write("t04_the_pass_tape", LESSON)
        args = build.argparse.Namespace(only=None)
        build.cmd_notebooks(args)
        target = self.notebooks / "t04_the_pass_tape" / "lesson.ipynb"
        first = target.read_bytes()
        for _ in range(3):
            build.cmd_notebooks(args)
            self.assertEqual(target.read_bytes(), first)

    def test_check_passes_on_a_clean_tree(self) -> None:
        self.write("t04_the_pass_tape", LESSON)
        build.cmd_notebooks(build.argparse.Namespace(only=None))
        self.assertEqual(build.cmd_check(None), 0)

    def test_check_catches_a_one_character_edit(self) -> None:
        self.write("t04_the_pass_tape", LESSON)
        build.cmd_notebooks(build.argparse.Namespace(only=None))
        target = self.notebooks / "t04_the_pass_tape" / "lesson.ipynb"
        target.write_text(target.read_text(encoding="utf-8").replace("hello", "hellp"), "utf-8")
        self.assertEqual(build.cmd_check(None), 1)

    def test_check_catches_a_missing_notebook(self) -> None:
        self.write("t04_the_pass_tape", LESSON)
        self.assertEqual(build.cmd_check(None), 1)

    def test_check_catches_a_notebook_with_no_source(self) -> None:
        orphan = self.notebooks / "t99_gone"
        orphan.mkdir(parents=True)
        (orphan / "lesson.ipynb").write_text("{}", encoding="utf-8")
        self.assertEqual(build.cmd_check(None), 1)

    def test_notebook_is_valid_json_and_declares_nbformat_45(self) -> None:
        self.write("t04_the_pass_tape", LESSON)
        build.cmd_notebooks(build.argparse.Namespace(only=None))
        target = self.notebooks / "t04_the_pass_tape" / "lesson.ipynb"
        doc = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual((doc["nbformat"], doc["nbformat_minor"]), (4, 5))


class TestRun(Harness):
    """Covers the execute path when a kernel is available, and skips when not.

    Skipping is the right call here rather than making jupyter a hard
    dependency. Somebody fixing a typo in a header should not need a kernel to
    find out whether they broke the parser.
    """

    @unittest.skipIf(build.shutil.which("jupyter") is None, "no jupyter on this machine")
    def test_a_notebook_executes_and_e1_cells_do_not(self) -> None:
        source = LESSON.replace('print("big")', 'raise SystemExit("must not run")')
        source = source.replace("# minutes: 35", "# minutes: 35\n# bootstrap: none")
        self.write("t04_the_pass_tape", source)
        build.cmd_notebooks(build.argparse.Namespace(only=None))
        code = build.cmd_run(
            build.argparse.Namespace(only=None, include_e1=False, timeout=120)
        )
        self.assertEqual(code, 0)
        out = build.ROOT / ".build" / "t04_the_pass_tape" / "lesson.ipynb"
        doc = json.loads(out.read_text(encoding="utf-8"))
        joined = json.dumps(doc)
        self.assertNotIn("must not run", joined)
        self.assertIn("hello", joined)


class TestScaffold(Harness):
    def test_new_produces_something_that_builds(self) -> None:
        self.assertEqual(build.cmd_new(build.argparse.Namespace(id="t09_dominators")), 0)
        source = (self.lessons / "t09_dominators" / "lesson.py").read_text(encoding="utf-8")
        source = source.replace("# part: TODO", "# part: I")
        (self.lessons / "t09_dominators" / "lesson.py").write_text(source, encoding="utf-8")
        lesson = build.load_lesson(self.lessons / "t09_dominators" / "lesson.py")
        self.assertEqual(lesson.header["title"], "Dominators")

    def test_new_rejects_a_bad_id(self) -> None:
        self.assertEqual(build.cmd_new(build.argparse.Namespace(id="The Pass Tape")), 1)

    def test_new_refuses_to_clobber(self) -> None:
        build.cmd_new(build.argparse.Namespace(id="t09_dominators"))
        self.assertEqual(build.cmd_new(build.argparse.Namespace(id="t09_dominators")), 1)


if __name__ == "__main__":
    unittest.main()
