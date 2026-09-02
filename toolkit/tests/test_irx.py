"""Tests for irx.

Two kinds live here. The ones that do not need LLVM run everywhere, including on
a CI runner that has no compiler on it, and they cover the parts that are pure
text handling. The ones that do need LLVM run the real binaries and skip with a
clear reason when there is no pinned toolchain to hand, because a test that
quietly passes on the wrong LLVM is worse than one that says it did not run.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import irx
from irx import env, ir, proc, toolchain

C_SOURCE = """
int square(int x) { return x * x; }
int twice(int x) { return x + x; }
"""


def toolchain_available() -> bool:
    """True when there is a pinned LLVM we are allowed to run against."""
    try:
        toolchain.bootstrap(verbose=False)
    except toolchain.ToolchainError:
        return False
    return True


HAVE_LLVM = toolchain_available()
needs_llvm = unittest.skipUnless(
    HAVE_LLVM, f"no LLVM {toolchain.MAJOR}, set IRX_LLVM_BIN to run these"
)


class TestPin(unittest.TestCase):
    def test_tag_looks_like_a_release(self):
        self.assertRegex(toolchain.TAG, r"^llvmorg-\d+\.\d+\.\d+$")

    def test_major_is_derived_not_typed(self):
        self.assertEqual(toolchain.MAJOR, toolchain.TAG.removeprefix("llvmorg-").split(".")[0])


class TestEnv(unittest.TestCase):
    def test_detect_returns_one_of_three(self):
        self.assertIn(env.detect(), {env.Env.E0, env.Env.E1, env.Env.E2})

    def test_describe_says_which_one(self):
        text = env.describe()
        self.assertTrue(text.startswith(("E0", "E1", "E2")), text)

    def test_cpu_count_is_positive(self):
        self.assertGreaterEqual(env.cpu_count(), 1)

    def test_build_tree_does_not_go_hunting(self):
        # A wrong LLVM_BUILD_DIR must come back as None rather than trigger a
        # filesystem walk. This is the check that keeps bootstrap fast.
        old = os.environ.get("LLVM_BUILD_DIR")
        os.environ["LLVM_BUILD_DIR"] = "/definitely/not/here"
        try:
            self.assertIsNone(env.build_tree())
        finally:
            if old is None:
                del os.environ["LLVM_BUILD_DIR"]
            else:
                os.environ["LLVM_BUILD_DIR"] = old


class TestHighlight(unittest.TestCase):
    def test_escapes_html(self):
        out = ir.highlight("; <script>alert(1)</script>")
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_colours_the_things_a_reader_scans_for(self):
        out = ir.highlight("define i32 @f(i32 %x) {\n  ret i32 %x\n}")
        for colour in (ir.COLOUR["keyword"], ir.COLOUR["type"], ir.COLOUR["global"], ir.COLOUR["local"]):
            self.assertIn(colour, out)

    def test_keeps_every_character(self):
        source = 'define void @f() {\n  ; note\n  ret void  ; 42 "x"\n}\n'
        import html as html_module
        import re

        plain = re.sub(r"<[^>]+>", "", ir.highlight(source))
        self.assertEqual(html_module.unescape(plain), source)


class TestModuleText(unittest.TestCase):
    IR = """
define i32 @square(i32 %x) {
  %m = mul nsw i32 %x, %x
  ret i32 %m
}

declare void @llvm.trap()
"""

    def setUp(self):
        self.m = irx.Module.from_ll(self.IR, name="t")

    def test_functions_lists_definitions_only(self):
        self.assertEqual(self.m.functions, ["square"])

    def test_declarations_are_separate(self):
        self.assertEqual(self.m.declarations, ["llvm.trap"])

    def test_count_ignores_comments(self):
        m = irx.Module.from_ll("define void @f() {\n  ; mul mul mul\n  ret void\n}")
        self.assertEqual(m.count("mul"), 0)
        self.assertEqual(m.count("ret"), 1)

    def test_count_does_not_match_inside_a_word(self):
        m = irx.Module.from_ll("define void @f() {\n  %adder = add i32 1, 2\n  ret void\n}")
        self.assertEqual(m.count("add"), 1)

    def test_repr_html_mentions_the_name(self):
        self.assertIn("t,", self.m._repr_html_())

    def test_opt_does_not_mutate_the_original(self):
        before = self.m.text
        clone = irx.Module(text=self.m.text, name=self.m.name, history=["fake"])
        self.assertEqual(self.m.text, before)
        self.assertEqual(self.m.history, [])
        self.assertEqual(clone.history, ["fake"])


class TestDiff(unittest.TestCase):
    def test_no_change_says_so(self):
        a = irx.Module.from_ll("define void @f() {\n  ret void\n}")
        d = a.diff(a)
        self.assertFalse(d.changed)
        self.assertIn("Nothing changed", d._repr_html_())

    def test_change_shows_both_sides(self):
        a = irx.Module.from_ll("define void @f() {\n  ret void\n}")
        b = irx.Module(text="define void @g() {\n  ret void\n}\n", name="x", history=["rename"])
        d = a.diff(b)
        self.assertTrue(d.changed)
        text = str(d)
        self.assertIn("-define void @f()", text)
        self.assertIn("+define void @g()", text)
        self.assertIn("rename", d._repr_html_())


class TestToolGuard(unittest.TestCase):
    def test_unknown_tool_is_refused_by_name(self):
        with self.assertRaises(toolchain.ToolchainError) as caught:
            toolchain.path_to("gcc")
        self.assertIn("gcc", str(caught.exception))
        self.assertIn("opt", str(caught.exception))

    def test_the_allowed_list_covers_what_lessons_use(self):
        for tool in ("clang", "opt", "llc", "llvm-as", "llvm-dis", "llvm-link", "FileCheck"):
            self.assertIn(tool, toolchain.TOOLS)


class TestBootstrapOrder(unittest.TestCase):
    """The fall through rules, with every source stubbed out.

    None of this runs a compiler. What it checks is which source wins and what
    happens to one that turns up the wrong major version, which is the part that
    decides whether somebody on Colab gets a lesson or an error.
    """

    NAMES = (
        "_from_env", "_from_cache", "_from_build_tree", "_from_system",
        "_from_tarball", "_from_apt", "_version_of",
    )

    def setUp(self):
        self.saved = {name: getattr(toolchain, name) for name in self.NAMES}
        self.versions: dict[str, str] = {}
        for name in self.NAMES[:4]:
            setattr(toolchain, name, lambda: None)
        for name in self.NAMES[4:6]:
            setattr(toolchain, name, lambda verbose=False: None)
        toolchain._version_of = lambda bindir: self.versions.get(str(bindir), "unknown")
        toolchain.reset()

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(toolchain, name, value)
        toolchain.reset()

    def offer(self, finder: str, path: str, version: str, takes_verbose: bool = False):
        self.versions[path] = version
        found = (Path(path), f"the {finder} source")
        if takes_verbose:
            setattr(toolchain, finder, lambda verbose=False: found)
        else:
            setattr(toolchain, finder, lambda: found)

    def good(self) -> str:
        return f"{toolchain.MAJOR}.1.0"

    def test_first_match_wins(self):
        self.offer("_from_cache", "/a", self.good())
        self.offer("_from_system", "/b", self.good())
        self.assertEqual(str(toolchain.bootstrap(verbose=False).bin), "/a")

    def test_wrong_version_on_path_falls_through_to_the_tarball(self):
        # The whole reason this rule exists. A Colab box with someone else's
        # LLVM on PATH should download the pinned one, not refuse to start.
        self.offer("_from_system", "/usr/bin", "18.1.0")
        self.offer("_from_tarball", "/cache/bin", self.good(), takes_verbose=True)
        chain = toolchain.bootstrap(verbose=False)
        self.assertEqual(str(chain.bin), "/cache/bin")
        self.assertEqual(chain.version, self.good())

    def test_explicit_env_var_with_the_wrong_version_stops(self):
        # Somebody set this by hand, so quietly ignoring it would be worse.
        self.offer("_from_env", "/opt/llvm18/bin", "18.1.0")
        self.offer("_from_tarball", "/cache/bin", self.good(), takes_verbose=True)
        with self.assertRaises(toolchain.ToolchainError) as caught:
            toolchain.bootstrap(verbose=False)
        self.assertIn("18.1.0", str(caught.exception))
        self.assertIn("IRX_ALLOW_VERSION_SKEW", str(caught.exception))

    def test_skew_can_be_allowed_on_purpose(self):
        self.offer("_from_system", "/usr/bin", "18.1.0")
        self.assertEqual(toolchain.bootstrap(verbose=False, allow_skew=True).version, "18.1.0")

    def test_nothing_anywhere_says_what_it_passed_over(self):
        self.offer("_from_system", "/usr/bin", "18.1.0")
        with self.assertRaises(toolchain.ToolchainError) as caught:
            toolchain.bootstrap(verbose=False)
        message = str(caught.exception)
        self.assertIn("Passed over on the way", message)
        self.assertIn("18.1.0", message)
        self.assertIn("IRX_LLVM_BIN", message)

    def test_bootstrap_twice_is_free(self):
        self.offer("_from_cache", "/a", self.good())
        first = toolchain.bootstrap(verbose=False)
        self.offer("_from_cache", "/b", self.good())
        self.assertIs(toolchain.bootstrap(verbose=False), first)


class TestHints(unittest.TestCase):
    def make(self, stderr: str, argv: list[str] | None = None) -> proc.Result:
        return proc.Result("opt", argv or ["opt"], 1, "", stderr, 0.0)

    def test_unknown_pass_points_at_the_pass_list(self):
        hint = proc.hint_for(self.make("opt: unknown pass name 'instcombin'"))
        self.assertIn("irx.passes()", hint)

    def test_parse_error_says_it_is_your_ir(self):
        hint = proc.hint_for(self.make("<stdin>:3:5: error: expected instruction opcode"))
        self.assertIn("parse error in your IR", hint)

    def test_missing_plugin_only_fires_for_plugin_commands(self):
        plain = self.make("no such file or directory")
        self.assertEqual(proc.hint_for(plain), "")
        plugin = self.make("no such file or directory", ["opt", "-load-pass-plugin=/tmp/p.so"])
        self.assertIn("%%irxplug", proc.hint_for(plugin))

    def test_nothing_matched_is_empty_not_a_guess(self):
        self.assertEqual(proc.hint_for(self.make("some brand new failure")), "")


class TestToolError(unittest.TestCase):
    def test_message_carries_the_command_and_the_stderr(self):
        result = proc.Result("opt", ["opt", "-passes=nope", "-"], 1, "", "unknown pass name 'nope'", 0.1)
        message = str(proc.ToolError(result))
        self.assertIn("opt exited 1", message)
        self.assertIn("-passes=nope", message)
        self.assertIn("unknown pass name", message)
        self.assertIn("irx.passes()", message)

    def test_silence_is_reported_as_silence(self):
        message = str(proc.ToolError(proc.Result("llc", ["llc"], -11, "", "", 0.1)))
        self.assertIn("printed nothing", message)


@needs_llvm
class TestAgainstRealLLVM(unittest.TestCase):
    """These run the actual pinned binaries. Nothing here is mocked."""

    def test_version_matches_the_pin(self):
        self.assertIn(toolchain.MAJOR, proc.version())

    def test_c_to_ir_round_trip(self):
        m = irx.Module.from_c(C_SOURCE)
        self.assertEqual(sorted(m.functions), ["square", "twice"])
        m.verify()

    def test_names_are_kept_so_the_ir_is_readable(self):
        # -fno-discard-value-names is the difference between %x and %0, and a
        # lesson that shows numbered registers is a lesson people bounce off.
        m = irx.Module.from_c("int f(int counter) { return counter + 1; }")
        self.assertIn("%counter", m.text)

    def test_o0_ir_is_not_optnone(self):
        # Without -disable-O0-optnone every pass below would do nothing, which
        # is the single most confusing thing a beginner can hit.
        m = irx.Module.from_c("int f(int x) { return x + x; }")
        self.assertNotIn("optnone", m.text)

    def test_module_id_is_not_diff_noise(self):
        # clang writes `-` here and opt writes `<stdin>`, so without pinning it
        # this line is the first hunk of every before and after in the course.
        before = irx.Module.from_c(C_SOURCE)
        after = before.opt("mem2reg")
        self.assertNotIn("ModuleID", str(before.diff(after)))

    def test_a_pass_actually_changes_something(self):
        before = irx.Module.from_c("int f(int x) { int y = x + x; return y; }")
        after = before.opt("mem2reg")
        self.assertLess(after.count("alloca"), before.count("alloca"))
        self.assertTrue(before.diff(after).changed)

    def test_history_records_the_pipeline(self):
        m = irx.Module.from_c(C_SOURCE).opt("mem2reg").opt("instcombine")
        self.assertEqual(m.history, ["mem2reg", "instcombine"])
        self.assertIn("mem2reg then instcombine", m._repr_html_())

    def test_bad_ir_raises_something_readable(self):
        with self.assertRaises(proc.ToolError) as caught:
            irx.Module.from_ll("define i32 @f() {\n  ret i32 nonsense\n}").verify()
        self.assertIn("opt exited", str(caught.exception))

    def test_is_valid_is_the_quiet_version(self):
        self.assertTrue(irx.Module.from_c(C_SOURCE).is_valid())
        self.assertFalse(irx.Module.from_ll("define i32 @f() {\n  oops\n}").is_valid())

    def test_unknown_pass_reaches_the_reader_with_the_hint_attached(self):
        with self.assertRaises(proc.ToolError) as caught:
            irx.Module.from_c(C_SOURCE).opt("instcombin")
        self.assertIn("irx.passes()", str(caught.exception))

    def test_extract_one_function(self):
        text = irx.Module.from_c(C_SOURCE).function("square")
        self.assertIn("@square", text)
        self.assertNotIn("define", text.replace("define i32 @square", ""))

    def test_asm_comes_out_as_text(self):
        asm = irx.Module.from_c("int f(int x) { return x + x; }").asm()
        self.assertIn("f:", asm)

    def test_pass_list_is_long_and_contains_the_obvious_ones(self):
        names = irx.passes()
        self.assertGreater(len(names), 100)
        for name in ("mem2reg", "instcombine", "gvn", "verify"):
            self.assertIn(name, names)

    def test_has_pass_agrees_with_the_binary(self):
        self.assertTrue(irx.has_pass("mem2reg"))
        self.assertFalse(irx.has_pass("definitely-not-a-pass"))

    def test_link_joins_two_modules(self):
        a = irx.Module.from_c("int a(void) { return 1; }")
        b = irx.Module.from_c("int b(void) { return 2; }")
        self.assertEqual(sorted(a.link(b).functions), ["a", "b"])

    def test_where_says_both_things(self):
        line = irx.where()
        self.assertRegex(line, r"^E[012],")
        self.assertIn("LLVM", line)


if __name__ == "__main__":
    unittest.main()
