"""Tests for irx.graphs.

Split the same way as the rest of the toolkit tests. The parser and the layout
run against a fixture and need nothing installed, because they are text handling
and should be covered on a machine with no compiler. The rest run `opt` and skip
with a reason when there is no pinned toolchain.

The fixture below is verbatim `opt -passes=dot-cfg` output, addresses and all.
It has been left exactly as LLVM wrote it, because the point of these tests is
that this module reads what LLVM actually produces rather than what would have
been convenient.
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

import irx
from irx import graphs, toolchain

DOT = r"""digraph "CFG for 'f' function" {
	label="CFG for 'f' function";

	Node0x600002f880a0 [shape=record,color="#3d50c3ff", style=filled, fillcolor="#d24b4070", fontname="Courier",label="{1:\l|  %2 = icmp sgt i32 %0, 0\l  br i1 %2, label %5, label %3\l|{<s0>T|<s1>F}}"];
	Node0x600002f880a0:s0 -> Node0x600002f88140;
	Node0x600002f880a0:s1 -> Node0x600002f88190;
	Node0x600002f88190 [shape=record,label="{3:\l|  %4 = phi i32 [ 0, %1 ], [ %12, %5 ]\l  ret i32 %4\l}"];
	Node0x600002f88140 [shape=record,label="{5:\l|  %6 = phi i32 [ %13, %5 ], [ 0, %1 ]\l  br i1 %14, label %3, label %5\l|{<s0>T|<s1>F}}"];
	Node0x600002f88140:s0 -> Node0x600002f88190;
	Node0x600002f88140:s1 -> Node0x600002f88140;
}
"""


def toolchain_available() -> bool:
    try:
        toolchain.bootstrap(verbose=False)
    except toolchain.ToolchainError:
        return False
    return True


needs_llvm = unittest.skipUnless(
    toolchain_available(), f"no LLVM {toolchain.MAJOR}, set IRX_LLVM_BIN to run these"
)


class TestLabelEscapes(unittest.TestCase):
    def test_both_kinds_of_line_break_are_a_line_break(self):
        self.assertEqual(graphs._unescape(r"a\lb\nc"), "a\nb\nc")

    def test_an_escaped_angle_bracket_is_an_angle_bracket(self):
        # The DDG printer writes <kind:root> this way, and a reader who sees
        # \<kind:root\> in a picture has been shown the escaping, not the graph.
        self.assertEqual(graphs._unescape(r"\<kind:root\>"), "<kind:root>")

    def test_a_bar_inside_braces_is_not_a_field(self):
        self.assertEqual(graphs._split("a|{b|c}|d"), ["a", "{b|c}", "d"])

    def test_an_escaped_bar_is_not_a_field_either(self):
        # `or` disassembles as a bar in some dumps, and splitting on it would
        # cut an instruction in half.
        self.assertEqual(graphs._split(r"a\|b|c"), [r"a\|b", "c"])


class TestParse(unittest.TestCase):
    def setUp(self):
        self.caption, self.nodes, self.edges = graphs.parse(DOT)
        graphs._label_ports(self.nodes, self.edges)
        graphs._mark_back_edges(self.nodes, self.edges)

    def test_the_caption_is_the_graph_label(self):
        self.assertEqual(self.caption, "CFG for 'f' function")

    def test_every_node_arrives_with_its_block_number_and_its_instructions(self):
        self.assertEqual([n.title for n in self.nodes], ["1", "3", "5"])
        self.assertEqual(self.nodes[1].lines[-1], "  ret i32 %4")

    def test_no_pointer_survives_the_parse(self):
        # LLVM names nodes after addresses, so the same function printed twice
        # gives two different files. Nothing downstream may depend on that.
        keys = {n.key for n in self.nodes}
        self.assertEqual(keys, {"n0", "n1", "n2"})
        self.assertNotIn("Node0x", str(self.edges))

    def test_the_ports_become_the_true_and_false_arms(self):
        labels = sorted(e.label for e in self.edges if e.src == "n0")
        self.assertEqual(labels, ["F", "T"])

    def test_the_edge_that_goes_back_into_the_loop_is_marked(self):
        back = [(e.src, e.dst) for e in self.edges if e.back]
        self.assertEqual(back, [("n1", "n1")])

    def test_the_text_form_names_blocks_and_draws_back_edges_differently(self):
        text = str(graphs.Graph("cfg", self.caption, self.nodes, self.edges, DOT))
        self.assertIn("F => 5", text)
        self.assertIn("T -> 3", text)
        self.assertIn("1 back edge(s)", text)


class TestRanks(unittest.TestCase):
    def test_a_node_sits_one_below_its_furthest_predecessor(self):
        # Longest path, not shortest. n2 has an edge straight from n0 as well as
        # one through n1, and putting it on row one would draw an arrow upward.
        nodes = [graphs.Node(key=f"n{i}", title=str(i)) for i in range(3)]
        edges = [graphs.Edge("n0", "n1"), graphs.Edge("n1", "n2"), graphs.Edge("n0", "n2")]
        self.assertEqual(graphs._ranks(nodes, edges), {"n0": 0, "n1": 1, "n2": 2})

    def test_a_back_edge_does_not_count_towards_the_ranking(self):
        nodes = [graphs.Node(key=f"n{i}", title=str(i)) for i in range(2)]
        edges = [graphs.Edge("n0", "n1"), graphs.Edge("n1", "n0", back=True)]
        self.assertEqual(graphs._ranks(nodes, edges), {"n0": 0, "n1": 1})


class TestSvg(unittest.TestCase):
    def setUp(self):
        caption, nodes, edges = graphs.parse(DOT)
        graphs._label_ports(nodes, edges)
        graphs._mark_back_edges(nodes, edges)
        self.graph = graphs.Graph("cfg", caption, nodes, edges, DOT)
        self.svg = self.graph.svg()

    def test_it_is_well_formed_xml(self):
        root = ET.fromstring(self.svg)
        self.assertTrue(root.tag.endswith("svg"))

    def test_there_is_a_box_for_every_block_and_a_path_for_every_edge(self):
        root = ET.fromstring(self.svg)
        rects = root.findall(".//{http://www.w3.org/2000/svg}rect")
        paths = root.findall(".//{http://www.w3.org/2000/svg}path")
        self.assertEqual(len(rects), 3)
        # Four edges, plus the two arrowhead markers in the defs block.
        self.assertEqual(len(paths), 6)

    def test_nothing_in_it_is_a_script(self):
        # This ends up inside a saved notebook and inside static HTML on the
        # site. Colab strips script, and the site should not be serving any.
        self.assertNotIn("<script", self.svg.lower())
        self.assertNotIn("onclick", self.svg.lower())

    def test_the_same_graph_renders_the_same_bytes_twice(self):
        # The marker id is a content hash rather than id() or hash(), so that
        # rebuilding a notebook does not produce a diff every time.
        self.assertEqual(self.svg, self.graph.svg())

    def test_the_html_says_which_pass_drew_it(self):
        self.assertIn("opt -passes=dot-cfg", self.graph._repr_html_())


class TestArgumentErrors(unittest.TestCase):
    def test_an_unknown_kind_says_what_the_kinds_are(self):
        with self.assertRaises(graphs.GraphError) as caught:
            graphs.graph("", kind="dominators")
        self.assertIn("post-dom", str(caught.exception))


@needs_llvm
class TestAgainstRealLLVM(unittest.TestCase):
    LOOP = """
    int f(int n) {
      int s = 0;
      for (int i = 0; i < n; i++) { if (i & 1) s += i; else s -= i; }
      return s;
    }
    """

    def test_a_loop_has_exactly_one_back_edge(self):
        graph = irx.cfg(irx.compile_c(self.LOOP, opt="-O1", name="loop"))
        self.assertEqual(len(graph.loops), 1)
        self.assertIn("CFG for 'f' function", graph.caption)

    def test_the_successors_are_the_ones_the_terminator_names(self):
        graph = irx.cfg(irx.compile_c(self.LOOP, opt="-O1", name="loop"))
        entry = next(n for n in graph.nodes if graph.successors(n.name))
        self.assertEqual(len(graph.successors(entry.name)), 2)

    def test_a_switch_gets_one_arrow_per_case(self):
        source = """
        int g(int x) {
          switch (x) { case 1: return 10; case 2: return 20; default: return 0; }
        }
        """
        graph = irx.cfg(irx.compile_c(source, name="switch"), "g")
        out = [e.label for e in graph.edges if e.src == graph.nodes[0].key]
        self.assertEqual(sorted(out), ["1", "2", "def"])

    def test_two_functions_is_an_error_that_names_both(self):
        source = "int a(void) { return 1; }\nint b(void) { return 2; }\n"
        with self.assertRaises(graphs.GraphError) as caught:
            irx.cfg(irx.compile_c(source, name="two"))
        self.assertIn("'a'", str(caught.exception))
        self.assertIn("'b'", str(caught.exception))

    def test_asking_for_a_function_that_is_not_there_says_what_is(self):
        source = "int a(void) { return 1; }\n"
        with self.assertRaises(graphs.GraphError) as caught:
            irx.cfg(irx.compile_c(source, name="one"), "nosuch")
        self.assertIn("'a'", str(caught.exception))

    def test_the_dominator_tree_has_no_back_edge_because_it_is_a_tree(self):
        graph = irx.dom(irx.compile_c(self.LOOP, opt="-O1", name="loop"))
        self.assertEqual(graph.loops, [])
        self.assertEqual(len(graph.edges), len(graph.nodes) - 1)

    def test_the_call_graph_is_named_after_the_module_not_the_temporary_file(self):
        source = "static int h(int x) { return x * 3; }\nint c(int x) { return h(x); }\n"
        graph = irx.callgraph(irx.compile_c(source, name="calls"))
        self.assertIn("calls", graph.caption)
        self.assertNotIn("in.ll", graph.caption)
        self.assertIn("h", graph.successors("c"))

    def test_the_picture_of_a_real_function_is_well_formed_xml(self):
        graph = irx.cfg(irx.compile_c(self.LOOP, opt="-O1", name="loop"))
        ET.fromstring(graph.svg())


if __name__ == "__main__":
    unittest.main()
