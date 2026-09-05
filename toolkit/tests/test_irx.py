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
from irx import env, ir, magic, pipeline, plugin, proc, toolchain

C_SOURCE = """
int square(int x) { return x * x; }
int twice(int x) { return x + x; }
"""

# The smallest pass that is still a real pass. It runs over every function and
# says how many instructions it saw, which is enough to prove the plugin loaded
# and enough to show a reader something change when they put it after mem2reg.
COUNT_PASS = """
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace {
struct CountInstructions : PassInfoMixin<CountInstructions> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &) {
    unsigned n = 0;
    for (BasicBlock &BB : F) n += BB.size();
    errs() << "count: " << F.getName() << " has " << n << " instructions\\n";
    return PreservedAnalyses::all();
  }
};
} // namespace

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "count", LLVM_VERSION_STRING, [](PassBuilder &PB) {
            PB.registerPipelineParsingCallback(
                [](StringRef Name, FunctionPassManager &FPM,
                   ArrayRef<PassBuilder::PipelineElement>) {
                  if (Name == "count") {
                    FPM.addPass(CountInstructions());
                    return true;
                  }
                  return false;
                });
          }};
}
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

    def test_plain_repr_is_a_summary_not_the_whole_module(self):
        # This is what a terminal or a JupyterLite console shows, and the
        # generated dataclass version dumps the entire module as one escaped
        # string, which nobody can read.
        text = repr(self.m)
        self.assertIn("<Module t, 1 function(s)", text)
        self.assertNotIn("ret i32", text)

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


class TestPluginRegistry(unittest.TestCase):
    """The bookkeeping around plugins, with nothing compiled."""

    def setUp(self):
        plugin.forget()

    def tearDown(self):
        plugin.forget()

    def test_suffix_matches_the_platform(self):
        import platform as platform_module

        expected = ".dylib" if platform_module.system() == "Darwin" else ".so"
        self.assertEqual(plugin.suffix(), expected)

    def test_macos_needs_the_undefined_flag_and_linux_does_not(self):
        import platform as platform_module

        flags = plugin.link_flags()
        if platform_module.system() == "Darwin":
            self.assertIn("-Wl,-undefined,dynamic_lookup", flags)
        else:
            self.assertEqual(flags, [])

    def test_load_flags_are_empty_until_something_is_built(self):
        self.assertEqual(plugin.load_flags(), [])

    def test_load_flags_name_every_plugin_built(self):
        plugin._registry["a"] = plugin.Plugin("a", Path("/tmp/a.so"), "", 1.0, False)
        plugin._registry["b"] = plugin.Plugin("b", Path("/tmp/b.so"), "", 1.0, False)
        self.assertEqual(
            sorted(plugin.load_flags()),
            ["-load-pass-plugin=/tmp/a.so", "-load-pass-plugin=/tmp/b.so"],
        )

    def test_asking_for_one_that_was_never_built_says_what_was(self):
        plugin._registry["count"] = plugin.Plugin("count", Path("/tmp/c.so"), "", 1.0, False)
        with self.assertRaises(KeyError) as caught:
            plugin.get("cuont")
        message = str(caught.exception)
        self.assertIn("cuont", message)
        self.assertIn("count", message)
        self.assertIn("restart", message)

    def test_forget_one_leaves_the_others(self):
        plugin._registry["a"] = plugin.Plugin("a", Path("/tmp/a.so"), "", 1.0, False)
        plugin._registry["b"] = plugin.Plugin("b", Path("/tmp/b.so"), "", 1.0, False)
        plugin.forget("a")
        self.assertEqual([p.name for p in plugin.registered()], ["b"])

    def test_a_cached_build_says_so_rather_than_claiming_a_fast_compile(self):
        fresh = plugin.Plugin("x", Path("/tmp/x.so"), "", 9.4, cached=False)
        reused = plugin.Plugin("x", Path("/tmp/x.so"), "", 0.0, cached=True)
        self.assertIn("9.4s", str(fresh))
        self.assertIn("already built", str(reused))


class TestMagicLine(unittest.TestCase):
    """Parsing `%%irxplug ...`, with the compile stubbed out."""

    def setUp(self):
        self.calls: list[tuple] = []
        self.saved = plugin.build
        plugin.build = lambda name, cell, extra=(), force=False, verbose=True: self.record(
            name, cell, extra, force
        )

    def tearDown(self):
        plugin.build = self.saved

    def record(self, name, cell, extra, force):
        self.calls.append((name, cell, extra, force))
        return plugin.Plugin(name, Path(f"/tmp/{name}.so"), cell, 1.0, cached=True)

    def test_name_only(self):
        magic.irxplug("count", "// source")
        self.assertEqual(self.calls, [("count", "// source", (), False)])

    def test_force_is_taken_out_of_the_flags(self):
        magic.irxplug("count --force", "// source")
        name, _, extra, force = self.calls[0]
        self.assertTrue(force)
        self.assertEqual(extra, ())

    def test_other_flags_are_passed_through_to_clang(self):
        magic.irxplug("count -O2 -Wall", "// source")
        self.assertEqual(self.calls[0][2], ("-O2", "-Wall"))

    def test_no_name_is_an_error_that_shows_the_usage(self):
        with self.assertRaises(ValueError) as caught:
            magic.irxplug("", "// source")
        self.assertIn("%%irxplug", str(caught.exception))

    def test_a_flag_where_the_name_should_be_is_caught(self):
        # Easy mistake, and without this the plugin would be called "-O2".
        with self.assertRaises(ValueError) as caught:
            magic.irxplug("-O2", "// source")
        self.assertIn("name", str(caught.exception))

    def test_registering_outside_a_notebook_is_a_quiet_no(self):
        self.assertFalse(magic.register())



# Trimmed from a real `opt -passes=... --print-changed --print-module-scope`
# run. Keeping the real headers matters more than keeping the real IR, because
# the headers are the only thing the parser looks at.
START_IR = """; ModuleID = 'from_c'
define i32 @f(i32 %x) {
  ret i32 %x
}
"""

PRINT_CHANGED = """*** IR Dump At Start ***
; ModuleID = 'from_c'
define i32 @f(i32 %x) {
  %a = add i32 %x, %x
  ret i32 %a
}
*** IR Dump After Annotation2MetadataPass on [module] omitted because no change ***
*** IR Dump After SROAPass on f ***
; ModuleID = 'from_c'
define i32 @f(i32 %x) {
  %a = add i32 %x, %x
  ret i32 %a
}
*** IR Dump After InstCombinePass on f ***
; ModuleID = 'from_c'
define i32 @f(i32 %x) {
  ret i32 %x
}
*** IR Dump After SimplifyCFGPass on f omitted because no change ***
"""


class TestTapeParsing(unittest.TestCase):
    def tape(self) -> pipeline.Tape:
        source = ir.Module.from_ll(START_IR, name="from_c")
        return pipeline._parse(PRINT_CHANGED, "default<O2>", source)

    def test_every_pass_is_kept_not_only_the_ones_that_did_something(self):
        t = self.tape()
        self.assertEqual([s.name for s in t.steps],
                         ["Annotation2MetadataPass", "SROAPass", "InstCombinePass",
                          "SimplifyCFGPass"])

    def test_the_ones_that_changed_something_are_marked(self):
        self.assertEqual([s.short for s in self.tape().changed], ["SROA", "InstCombine"])

    def test_the_index_counts_the_whole_pipeline_not_only_the_changes(self):
        # The point of the tape is that pass 3 of 4 did something and the rest
        # did not, so the numbering has to be over everything.
        self.assertEqual([s.index for s in self.tape().changed], [2, 3])

    def test_a_pass_that_changed_nothing_carries_no_ir(self):
        skipped = [s for s in self.tape().steps if not s.changed]
        self.assertTrue(all(s.ir == "" for s in skipped))

    def test_scope_is_kept_so_a_module_pass_reads_differently(self):
        t = self.tape()
        self.assertEqual(t.steps[0].scope, "[module]")
        self.assertEqual(t.steps[1].scope, "f")

    def test_the_start_dump_is_not_counted_as_a_pass(self):
        self.assertEqual(len(self.tape().steps), 4)

    def test_frames_are_the_start_plus_one_per_change(self):
        self.assertEqual(len(self.tape().frames), 3)

    def test_step_lookup_is_by_substring_and_case_insensitive(self):
        self.assertEqual(self.tape().step("instcombine").name, "InstCombinePass")

    def test_asking_for_a_pass_that_did_not_run_says_how_many_did(self):
        with self.assertRaises(KeyError) as caught:
            self.tape().step("loopunroll")
        self.assertIn("4 passes did", str(caught.exception))

    def test_headline_carries_both_numbers(self):
        self.assertIn("4 passes ran, 2 changed", self.tape().headline)


class TestTapeText(unittest.TestCase):
    """The text form is what a terminal and a stripped down renderer get."""

    def setUp(self):
        source = ir.Module.from_ll(START_IR, name="from_c")
        self.t = pipeline._parse(PRINT_CHANGED, "default<O2>", source)

    def test_it_names_every_pass_that_changed_something(self):
        text = str(self.t)
        self.assertIn("SROA", text)
        self.assertIn("InstCombine", text)

    def test_it_does_not_list_the_passes_that_did_nothing(self):
        self.assertNotIn("Annotation2Metadata", str(self.t))

    def test_one_line_is_singular(self):
        self.assertEqual(pipeline._size(-1), "-1 line")
        self.assertEqual(pipeline._size(-2), "-2 lines")
        self.assertEqual(pipeline._size(0), "same length")

    def test_a_long_loop_scope_is_cut_so_the_columns_hold(self):
        self.t.steps[1].scope = "loop %for.body in function g"
        line = [l for l in str(self.t).split("\n") if "SROA" in l][0]
        self.assertIn("...", line)
        self.assertLess(len(line), 90)

    def test_repr_is_a_summary_not_the_whole_run(self):
        self.assertEqual(repr(self.t), f"<Tape {self.t.headline}>")


class TestTapeWidget(unittest.TestCase):
    def setUp(self):
        source = ir.Module.from_ll(START_IR, name="from_c")
        self.t = pipeline._parse(PRINT_CHANGED, "default<O2>", source)
        self.html = self.t._repr_html_()

    def test_there_is_no_javascript_in_it(self):
        # This is the whole reason for the radio and CSS design. Colab sandboxes
        # output, JupyterLite has no kernel to call back into, and the published
        # site is static. A script tag here would break all three.
        self.assertNotIn("<script", self.html.lower())
        self.assertNotIn("onclick", self.html.lower())

    def test_one_radio_and_one_panel_per_frame(self):
        self.assertEqual(self.html.count('type="radio"'), 3)
        self.assertEqual(self.html.count('class="fr"'), 3)

    def test_the_first_frame_is_the_one_that_shows_with_no_stylesheet(self):
        # Everything after the first carries an inline display:none, so a
        # renderer that drops the <style> shows one module rather than all of
        # them stacked up.
        self.assertIn('<div class="fr">', self.html)
        self.assertEqual(self.html.count('<div class="fr" style="display:none">'), 2)

    def test_the_ids_are_scoped_so_two_tapes_do_not_fight(self):
        other = pipeline._parse(
            PRINT_CHANGED, "default<O1>",
            ir.Module.from_ll("define void @h() {\n  ret void\n}", name="other"),
        )
        self.assertNotEqual(pipeline._ident(self.t), pipeline._ident(other))

    def test_the_same_tape_renders_to_the_same_html_twice(self):
        self.assertEqual(self.html, self.t._repr_html_())

    def test_the_pass_names_survive_into_the_strip(self):
        self.assertIn(">SROA +1<", self.html)

    def test_a_huge_module_is_not_carried_in_every_frame(self):
        big = "\n".join(f"  %v{i} = add i32 1, 1" for i in range(pipeline.FULL_MODULE_LIMIT + 5))
        self.t.steps[1].ir = f"define void @f() {{\n{big}\n}}\n"
        self.assertIn("too much to carry in every frame", self.t._repr_html_())


PRINT_CHANGED_DELETED = """*** IR Dump At Start ***
; ModuleID = 'from_c'
define i32 @g(i32 %n) {
  br label %body
}
*** IR Dump After IndVarSimplifyPass on loop %body in function g ***
; ModuleID = 'from_c'
define i32 @g(i32 %n) {
  br i1 false, label %body, label %out
}
*** IR Pass LoopDeletionPass invalidated ***
*** IR Pass PassManager<Loop, LoopAnalysisManager, LoopStandardAnalysisResults &, LPMUpdater &> invalidated ***
*** IR Dump After GVNPass on g ***
; ModuleID = 'from_c'
define i32 @g(i32 %n) {
  ret i32 0
}
"""


class TestAPassThatDeletedItsLoop(unittest.TestCase):
    """The header shape that has no scope, because there is nothing left to name.

    A loop pass that deletes its loop cannot print the loop afterwards, so opt
    writes one line and no IR. It is the most interesting pass in the run and
    the easiest one to lose, which is what happened here until a lesson went
    looking for it.
    """

    def setUp(self):
        source = ir.Module.from_ll(START_IR, name="from_c")
        self.t = pipeline._parse(PRINT_CHANGED_DELETED, "default<O2>", source)

    def test_it_is_on_the_tape_at_all(self):
        self.assertIn("LoopDeletionPass", [s.name for s in self.t.steps])

    def test_it_counts_as_a_change_because_it_changed_the_module(self):
        step = self.t.step("LoopDeletion")
        self.assertTrue(step.changed)
        self.assertTrue(step.invalidated)

    def test_it_has_no_frame_because_there_was_nothing_left_to_print(self):
        self.assertEqual(self.t.step("LoopDeletion").ir, "")
        self.assertNotIn("LoopDeletionPass", [s.name for s in self.t.shown])

    def test_the_pass_manager_that_went_with_it_is_still_plumbing(self):
        # opt says "ignored" about most plumbing, which is how the rest of it
        # gets left out. It does not say that about one that was invalidated,
        # so that one has to be recognised by name or the count goes up by one.
        self.assertEqual([s.short for s in self.t.steps],
                         ["IndVarSimplify", "LoopDeletion", "GVN"])

    def test_the_scope_reads_as_gone_rather_than_as_blank(self):
        self.assertEqual(self.t.step("LoopDeletion").where, "[gone]")

    def test_the_text_form_says_what_happened_instead_of_a_line_count(self):
        line = [l for l in str(self.t).split("\n") if "LoopDeletion" in l][0]
        self.assertIn("deleted it, no dump", line)

    def test_the_frames_after_it_are_still_the_right_ones(self):
        # This is the bug this whole class is about. There are three changed
        # passes and only two frames, so anything that walks them in step has to
        # know which is which or every panel after the deletion is off by one.
        self.assertEqual(len(self.t.changed), 3)
        self.assertEqual(len(self.t.frames), 3)
        self.assertIn("ret i32 0", self.t.final.text)

    def test_the_widget_gives_it_a_chip_and_an_explanation_not_a_diff(self):
        html = self.t._repr_html_()
        self.assertEqual(html.count('type="radio"'), 4)
        self.assertIn("LoopDeletion gone", html)
        self.assertIn("deleted the thing it was running on", html)

    def test_the_gvn_panel_shows_the_gvn_frame(self):
        # Off by one here would show the IndVarSimplify diff under GVN's chip,
        # which is the kind of wrong that nobody notices.
        html = self.t._repr_html_()
        self.assertIn("pass 3 of 3, GVNPass on g", html)


PRINT_CHANGED_STRANGE = """*** IR Dump At Start ***
; ModuleID = 'from_c'
define i32 @f(i32 %x) {
  ret i32 %x
}
*** IR Dump Sideways WeirdPass on f in reverse ***
; ModuleID = 'from_c'
define i32 @f(i32 %x) {
  ret i32 0
}
"""


class TestAnUnknownBanner(unittest.TestCase):
    """Refuse to carry on rather than glue an unread line onto a frame."""

    STRANGE = PRINT_CHANGED_STRANGE

    def source(self):
        return ir.Module.from_ll(START_IR, name="from_c")

    def test_it_stops_and_quotes_the_line(self):
        with self.assertRaises(ValueError) as caught:
            pipeline._parse(self.STRANGE, "default<O2>", self.source())
        self.assertIn("Dump Sideways WeirdPass", str(caught.exception))

    def test_it_says_how_to_carry_on_anyway(self):
        with self.assertRaises(ValueError) as caught:
            pipeline._parse(self.STRANGE, "default<O2>", self.source())
        self.assertIn("strict=False", str(caught.exception))

    def test_turning_the_check_off_gets_you_the_old_behaviour(self):
        t = pipeline._parse(self.STRANGE, "default<O2>", self.source(), strict=False)
        self.assertEqual(t.steps, [])

    def test_the_shapes_we_do_know_pass_the_check(self):
        for sample in (PRINT_CHANGED, PRINT_CHANGED_DELETED):
            pipeline._parse(sample, "default<O2>", self.source())


class TestHints(unittest.TestCase):
    def make(self, stderr: str, argv: list[str] | None = None) -> proc.Result:
        return proc.Result("opt", argv or ["opt"], 1, "", stderr, 0.0)

    def test_unknown_pass_points_at_the_pass_list(self):
        hint = proc.hint_for(self.make("opt: unknown pass name 'instcombin'"))
        self.assertIn("irx.passes()", hint)

    def test_parse_error_says_it_is_your_ir(self):
        hint = proc.hint_for(self.make("<stdin>:3:5: error: expected instruction opcode"))
        self.assertIn("parse error in your IR", hint)

    def test_the_header_that_moved_gets_named(self):
        hint = proc.hint_for(
            self.make("count.cpp:3:10: fatal error: 'llvm/Passes/PassPlugin.h' file not found")
        )
        self.assertIn("llvm/Plugins/PassPlugin.h", hint)

    def test_headers_missing_is_told_apart_from_the_header_that_moved(self):
        hint = proc.hint_for(
            self.make("count.cpp:2:10: fatal error: 'llvm/IR/PassManager.h' file not found")
        )
        self.assertIn("llvm-N-dev", hint)
        self.assertNotIn("Plugins", hint)

    def test_undefined_symbol_points_at_the_flags(self):
        hint = proc.hint_for(
            self.make("undefined symbol: _ZN4llvm11PassBuilder", ["opt", "-load-pass-plugin=p.so"])
        )
        self.assertIn("cxxflags", hint)

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
        whole = irx.Module.from_c(C_SOURCE)
        self.assertEqual(sorted(whole.functions), ["square", "twice"])
        # Asking what came back rather than matching the text of the `define`
        # line, which carries `dso_local` on Linux and not on macOS.
        one = irx.Module.from_ll(whole.function("square"), name="square")
        self.assertEqual(one.functions, ["square"])

    def test_body_is_the_define_block_and_nothing_else(self):
        whole = irx.Module.from_c(C_SOURCE)
        body = whole.body("square")
        self.assertTrue(body.startswith("define"))
        self.assertTrue(body.endswith("}"))
        # The things function() drags along and body() is for not dragging.
        self.assertNotIn("target triple", body)
        self.assertNotIn("attributes #", body)
        # One function, not the pair, and not the one whose name is a prefix
        # match of nothing in particular.
        self.assertNotIn("@twice", body)

    def test_body_says_which_function_it_could_not_find(self):
        with self.assertRaises(KeyError) as caught:
            irx.Module.from_c(C_SOURCE).body("nosuch")
        self.assertIn("nosuch", str(caught.exception))

    def test_a_declaration_has_no_body(self):
        # `declare` lines match neither the define anchor nor the brace, and a
        # regex that got this wrong would return the next function's body.
        module = irx.Module.from_ll(
            'declare i32 @ext(i32)\ndefine i32 @f() {\n  ret i32 0\n}\n')
        with self.assertRaises(KeyError):
            module.body("ext")
        self.assertIn("ret i32 0", module.body("f"))

    def test_instructions_drops_the_labels_and_counts_a_pass_working(self):
        module = irx.Module.from_c("int add(int a, int b) { return a + b; }")
        before = module.instructions("add")
        self.assertNotIn("entry:", before)
        self.assertTrue(all(not line.endswith(":") for line in before))
        # sroa is the pass that turns those stack slots into registers, so the
        # count has to drop, and the add and the ret are what is left.
        after = module.opt("sroa").instructions("add")
        self.assertLess(len(after), len(before))
        self.assertEqual(len(after), 2)

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


@needs_llvm
class TestPassPlugin(unittest.TestCase):
    """The M0 gate, run as a test.

    Everything in Parts IV and XI assumes a reader can write a pass in a cell
    and have it load a few seconds later. This compiles one and loads it, so if
    that ever stops being true the suite says so rather than a lesson doing it.
    """

    @classmethod
    def setUpClass(cls):
        plugin.forget()
        cls.built = plugin.build("count", COUNT_PASS, verbose=False)

    @classmethod
    def tearDownClass(cls):
        plugin.forget()

    def test_it_compiled_at_all(self):
        self.assertTrue(self.built.path.exists())
        self.assertEqual(self.built.path.suffix, plugin.suffix())

    def test_the_flags_came_from_llvm_config_not_from_us(self):
        flags = plugin.cxxflags()
        self.assertTrue(any(f.startswith("-I") for f in flags), flags)
        self.assertTrue(any(f.startswith("-std=") for f in flags), flags)

    def test_building_the_same_source_again_is_cached(self):
        again = plugin.build("count", COUNT_PASS, verbose=False)
        self.assertTrue(again.cached)
        self.assertEqual(again.path, self.built.path)

    def test_editing_the_source_gets_a_different_file(self):
        edited = plugin.build("count", COUNT_PASS + "\n// a comment\n", verbose=False)
        self.assertNotEqual(edited.path, self.built.path)
        plugin.build("count", COUNT_PASS, verbose=False)

    def test_opt_loads_it_without_being_told_where_it_is(self):
        # The reader typed `count`, not a path into a cache directory they have
        # never seen. This is the whole ergonomic point of the registry.
        module = irx.Module.from_c(C_SOURCE)
        self.assertIn("-load-pass-plugin=", " ".join(plugin.load_flags()))
        module.opt("count", quiet=True)

    def test_the_pass_output_reaches_the_reader(self):
        import contextlib
        import io

        module = irx.Module.from_c("int f(int x) { return x + x; }")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            module.opt("count")
        self.assertIn("count: f has", captured.getvalue())

    def test_it_composes_with_the_real_pipeline(self):
        # Running the same pass before and after mem2reg is the shape of half
        # the lessons in Part IV, so it gets a test rather than a hope.
        import contextlib
        import io

        module = irx.Module.from_c("int f(int x) { int y = x + x; return y; }")
        before, after = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(before):
            module.opt("count")
        with contextlib.redirect_stdout(after):
            module.opt("mem2reg,count")
        self.assertNotEqual(before.getvalue(), after.getvalue())

    def test_an_unknown_pass_name_still_fails_clearly_with_a_plugin_loaded(self):
        with self.assertRaises(proc.ToolError) as caught:
            irx.Module.from_c(C_SOURCE).opt("cuont")
        self.assertIn("irx.passes()", str(caught.exception))


@needs_llvm
class TestTapeAgainstRealLLVM(unittest.TestCase):
    """The parser is written against what opt prints, so it gets tested there."""

    LOOP = """
    int f(int x) { int y = x + x; return y * 2; }
    int g(int n) { int s = 0; for (int i = 0; i < n; i++) s += i * 3; return s; }
    """

    @classmethod
    def setUpClass(cls):
        plugin.forget()
        cls.module = irx.Module.from_c(cls.LOOP)
        cls.tape = cls.module.tape("default<O2>")

    def test_most_passes_do_nothing_which_is_the_entire_point(self):
        self.assertGreater(len(self.tape.steps), 100)
        self.assertLess(len(self.tape.changed), len(self.tape.steps) / 4)

    def test_every_frame_is_a_module_that_actually_parses(self):
        for frame in self.tape.frames:
            self.assertTrue(frame.is_valid(), f"frame after {frame.history[-1:]} is not IR")

    def test_the_last_frame_is_what_opt_gives_you_on_its_own(self):
        direct = self.module.opt("default<O2>", quiet=True)
        self.assertEqual(self.tape.final.functions, direct.functions)
        self.assertEqual(self.tape.final.count("alloca"), direct.count("alloca"))

    def test_the_loop_passes_show_up_with_the_loop_in_their_scope(self):
        rotate = self.tape.step("LoopRotate")
        self.assertIn("loop", rotate.scope)

    def test_pass_managers_and_the_verifier_are_not_counted_as_passes(self):
        names = [s.name for s in self.tape.steps]
        self.assertNotIn("VerifierPass", names)
        self.assertNotIn("ModuleToFunctionPassAdaptor", names)

    def test_o0_runs_passes_and_changes_nothing(self):
        # A good first cell in a lesson, because it is the opposite of what
        # people expect a pipeline to look like.
        t = self.module.tape("default<O0>")
        self.assertGreater(len(t.steps), 0)
        self.assertEqual(t.changed, [])
        self.assertIn("Nothing in this pipeline touched", str(t))

    def test_the_same_pass_on_two_functions_is_two_steps(self):
        t = self.module.tape("mem2reg")
        self.assertEqual([s.scope for s in t.steps], ["f", "g"])

    def test_the_pass_that_deleted_the_loop_is_on_the_tape(self):
        # LoopDeletion is what removes the loop in g once IndVarSimplify has
        # worked out the closed form. It prints one line and no IR, so for a
        # while it was not on the tape at all and the deletion looked like it
        # was GVN's doing.
        step = self.tape.step("LoopDeletion")
        self.assertTrue(step.invalidated)
        self.assertTrue(step.changed)
        self.assertEqual(step.ir, "")

    def test_there_is_one_fewer_frame_than_there_are_changes(self):
        self.assertEqual(len(self.tape.shown), len(self.tape.changed) - 1)
        self.assertEqual(len(self.tape.frames), len(self.tape.shown) + 1)

    def test_the_loop_really_is_gone_by_the_end(self):
        # Asking LLVM rather than looking for a branch in the text, because a
        # fully optimised function still has branches in it.
        report = proc.run("opt", "-passes=print<loops>", "-disable-output", "-",
                          stdin=self.tape.final.text)
        self.assertNotIn("Loop at depth", report.stderr)


@needs_llvm
class TestTapeWithAPrintingPlugin(unittest.TestCase):
    """A teaching pass prints, and opt's dumps and errs() share one stream."""

    @classmethod
    def setUpClass(cls):
        plugin.forget()
        plugin.build("count", COUNT_PASS, verbose=False)

    @classmethod
    def tearDownClass(cls):
        plugin.forget()

    def test_a_pass_that_prints_does_not_corrupt_the_frame_before_it(self):
        t = irx.Module.from_c(C_SOURCE).tape("mem2reg,count,instcombine")
        for frame in t.frames:
            self.assertTrue(frame.is_valid(), "a frame has the pass output stuck to it")

    def test_a_plugin_pass_is_recognised_despite_the_space_in_its_name(self):
        t = irx.Module.from_c(C_SOURCE).tape("mem2reg,count")
        self.assertTrue(any("CountInstructions" in s.name for s in t.steps))


WHICH = "Which pass deleted the second load?"
OPTIONS = {
    "EarlyCSE": "It runs first and it catches the cheap redundancies.",
    "GVN": "It can do this and it runs too late to get the chance.",
}


class TestGate(unittest.TestCase):
    """A gate has to work in a renderer with no stylesheet and no kernel."""

    def test_it_refuses_a_single_option(self):
        with self.assertRaises(ValueError) as caught:
            irx.gate(WHICH, {"EarlyCSE": "the only one"}, answer="EarlyCSE")
        self.assertIn("coin toss", str(caught.exception))

    def test_it_refuses_an_answer_that_is_not_an_option(self):
        with self.assertRaises(ValueError) as caught:
            irx.gate(WHICH, OPTIONS, answer="SROA")
        self.assertIn("SROA", str(caught.exception))

    def test_it_refuses_a_wrong_answer_with_no_explanation(self):
        with self.assertRaises(ValueError) as caught:
            irx.gate(WHICH, {**OPTIONS, "GVN": "  "}, answer="EarlyCSE")
        self.assertIn("GVN", str(caught.exception))

    def test_the_repr_does_not_give_the_answer_away(self):
        # It is the text/plain that gets saved into the notebook, right under
        # the question, so a reader scrolling the raw file would see it.
        g = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")
        self.assertNotIn("EarlyCSE", repr(g))
        self.assertIn(WHICH, repr(g))

    def test_printing_it_does(self):
        # Whereas anyone who typed print() asked for the answer.
        g = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")
        self.assertIn("The answer is EarlyCSE.", str(g))
        self.assertIn("It runs first", str(g))

    def test_the_text_form_explains_the_wrong_answers_too(self):
        g = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")
        self.assertIn("runs too late", str(g))

    def test_the_html_has_one_radio_per_option_and_no_script(self):
        html = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")._repr_html_()
        self.assertEqual(html.count('type="radio"'), 2)
        self.assertNotIn("<script", html)
        self.assertNotIn("onclick", html)

    def test_the_answer_is_named_in_a_sentence_not_only_in_a_colour(self):
        html = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")._repr_html_()
        self.assertIn("The answer is <b>EarlyCSE</b>", html)

    def test_the_free_text_box_is_not_an_input(self):
        # The option highlight counts inputs by position, so a second kind of
        # input in the same element would shift every option by one.
        html = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")._repr_html_()
        self.assertIn("<textarea", html)
        self.assertEqual(html.count("<input"), 2)

    def test_rendering_it_twice_gives_the_same_bytes(self):
        first = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")._repr_html_()
        second = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")._repr_html_()
        self.assertEqual(first, second)

    def test_two_gates_do_not_share_an_id(self):
        one = irx.gate(WHICH, OPTIONS, answer="EarlyCSE")._repr_html_()
        two = irx.gate("Something else?", OPTIONS, answer="GVN")._repr_html_()
        self.assertNotEqual(_id_of(one), _id_of(two))

    def test_a_question_with_html_in_it_is_escaped(self):
        g = irx.gate("Does <b>this</b> escape?", OPTIONS, answer="GVN")
        self.assertIn("&lt;b&gt;this&lt;/b&gt;", g._repr_html_())


def _id_of(html: str) -> str:
    return html.split('id="', 1)[1].split('"', 1)[0]



if __name__ == "__main__":
    unittest.main()
