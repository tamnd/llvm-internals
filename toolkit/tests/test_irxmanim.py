"""Tests for irxmanim.

Nothing in here needs LLVM. The library draws and animates, and the only thing
it borrows from the toolkit is the IR colouring, so the whole file runs on a
machine with no compiler on it.

The tests that look at the generated SVG are looking for two things in
particular: that the markup on its own is the last frame, because that is what
a reader without the stylesheet sees, and that the same scene renders the same
bytes, because these files are committed and a picture that churns makes every
diff unreadable.
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from irx.ir import COLOUR
from irxmanim import (
    Arrow,
    Box,
    Caption,
    Code,
    Group,
    Scene,
    SceneError,
    draw,
    fade_in,
    fade_out,
    highlight,
    link,
    move,
    pulse,
)
from irxmanim.mobject import LINE_H, MobjectError

SVG = "{http://www.w3.org/2000/svg}"


def simple() -> tuple[Scene, Box, Box, Arrow]:
    s = Scene(400, 160)
    a = Box(20, 40, text="before")
    b = Box(240, 40, text="after")
    arrow = link(a, b)
    s.add(a, b, arrow)
    return s, a, b, arrow


class TestGeometry(unittest.TestCase):
    def test_a_box_is_wider_than_its_text(self):
        box = Box(0, 0, text="define i32 @f()")
        self.assertGreater(box.w, len("define i32 @f()") * 6)

    def test_a_tone_that_does_not_exist_is_an_error_at_the_point_of_the_typo(self):
        with self.assertRaises(MobjectError) as caught:
            Box(0, 0, text="x", tone="blue")
        self.assertIn("plain", str(caught.exception))

    def test_a_link_between_boxes_side_by_side_goes_sideways(self):
        a, b = Box(0, 0, text="a"), Box(200, 0, text="b")
        arrow = link(a, b)
        self.assertEqual(arrow.start[1], arrow.end[1])
        self.assertGreater(arrow.end[0], arrow.start[0])

    def test_a_link_between_stacked_boxes_goes_down(self):
        a, b = Box(0, 0, text="a"), Box(0, 120, text="b")
        arrow = link(a, b)
        self.assertEqual(arrow.start[0], arrow.end[0])
        self.assertGreater(arrow.end[1], arrow.start[1])

    def test_a_straight_arrow_measures_its_own_length(self):
        # The dash pattern is the length, so a wrong measurement is a stroke
        # that stops short of the head or overshoots it.
        arrow = Arrow(start=(0, 0), end=(30, 40))
        self.assertAlmostEqual(arrow.length, 50.0, places=3)

    def test_a_group_is_as_big_as_the_things_in_it(self):
        group = Group(members=[Box(10, 10, w=50, h=20), Box(100, 40, w=50, h=20)])
        self.assertEqual((group.x, group.y, group.w, group.h), (10, 10, 140, 50))

    def test_an_empty_group_says_so(self):
        with self.assertRaises(MobjectError):
            Group(members=[])

    def test_every_line_of_code_is_its_own_mobject(self):
        code = Code(x=0, y=0, lines=["define i32 @f() {", "  ret i32 1", "}"])
        self.assertEqual(len(code.parts()), 3)
        self.assertEqual(code[1].text, "  ret i32 1")
        self.assertEqual(code[1].y - code[0].y, LINE_H)


class TestBuilding(unittest.TestCase):
    def test_adding_the_same_mobject_twice_is_an_error(self):
        s = Scene()
        box = Box(0, 0, text="a")
        s.add(box)
        with self.assertRaises(SceneError):
            s.add(box)

    def test_animating_something_that_was_never_added_says_which(self):
        s = Scene()
        with self.assertRaises(SceneError) as caught:
            s.play(fade_in(Box(0, 0, text="stray")))
        self.assertIn("stray", str(caught.exception))

    def test_a_beat_with_nothing_in_it_is_an_error(self):
        with self.assertRaises(SceneError):
            Scene().play()

    def test_everything_in_one_call_starts_at_the_same_moment(self):
        s, a, b, _ = simple()
        s.play(fade_in(a), fade_in(b))
        self.assertEqual([at for at, _, _ in s.script], [0.0, 0.0])

    def test_each_call_follows_the_one_before_it(self):
        s, a, b, _ = simple()
        s.play(fade_in(a), run_time=0.5)
        s.wait(0.25)
        s.play(fade_in(b), run_time=0.5)
        self.assertEqual([round(at, 2) for at, _, _ in s.script], [0.0, 0.75])

    def test_a_scene_longer_than_the_cap_is_refused(self):
        # The cap is in CONTRIBUTING.md and applies to animation in lessons.
        s = Scene()
        box = s.add(Box(0, 0, text="a"))
        with self.assertRaises(SceneError) as caught:
            s.play(fade_in(box, run_time=200))
        self.assertIn("two animations", str(caught.exception))

    def test_highlighting_an_arrow_says_what_can_be_highlighted(self):
        s, _, _, arrow = simple()
        with self.assertRaises(SceneError) as caught:
            s.play(highlight(arrow))
        self.assertIn("arrows do not", str(caught.exception))

    def test_only_an_arrow_can_be_drawn(self):
        s, a, _, _ = simple()
        with self.assertRaises(SceneError):
            s.play(draw(a))


class TestTimeline(unittest.TestCase):
    def test_a_fade_in_is_invisible_before_it_starts(self):
        s, a, _, _ = simple()
        s.wait(1.0)
        s.play(fade_in(a, run_time=1.0))
        self.assertEqual(s.value_at(a.key, "opacity", 0.5), 0.0)
        self.assertEqual(s.value_at(a.key, "opacity", 1.0), 0.0)
        self.assertAlmostEqual(s.value_at(a.key, "opacity", 1.5), 0.5)
        self.assertEqual(s.value_at(a.key, "opacity", 2.0), 1.0)

    def test_a_value_holds_between_the_things_that_change_it(self):
        s, a, _, _ = simple()
        s.play(fade_in(a, run_time=0.5))
        s.wait(2.0)
        s.play(fade_out(a, run_time=0.5))
        self.assertEqual(s.value_at(a.key, "opacity", 1.6), 1.0)

    def test_a_move_is_relative_to_wherever_it_is_now(self):
        s, a, _, _ = simple()
        s.play(move(a, dy=-10, run_time=0.5))
        s.play(move(a, dy=-10, run_time=0.5))
        self.assertEqual(s.value_at(a.key, "ty", 2.0), -20.0)

    def test_a_highlight_comes_and_goes(self):
        s, a, _, _ = simple()
        s.play(highlight(a, run_time=1.0))
        self.assertEqual(s.value_at(a.wash.key, "opacity", 0.0), 0.0)
        self.assertEqual(s.value_at(a.wash.key, "opacity", 0.5), 1.0)
        self.assertEqual(s.value_at(a.wash.key, "opacity", 1.0), 0.0)

    def test_the_head_of_an_arrow_arrives_after_the_stroke_starts(self):
        s, _, _, arrow = simple()
        s.play(draw(arrow, run_time=1.0))
        self.assertEqual(s.value_at(arrow.key, "dash", 0.0), 1.0)
        self.assertEqual(s.value_at(arrow.key, "dash", 1.0), 0.0)
        self.assertEqual(s.value_at(arrow.head.key, "opacity", 0.5), 0.0)
        self.assertEqual(s.value_at(arrow.head.key, "opacity", 1.0), 1.0)

    def test_the_storyboard_reads_in_order(self):
        s, a, b, arrow = simple()
        s.play(fade_in(a))
        s.play(draw(arrow))
        s.play(fade_in(b))
        lines = str(s).splitlines()
        self.assertIn("fade in", lines[2])
        self.assertIn("draw", lines[3])
        self.assertIn("before", lines[2])


class TestSvg(unittest.TestCase):
    def setUp(self):
        self.scene, self.a, self.b, self.arrow = simple()
        self.scene.play(fade_in(self.a))
        self.scene.play(draw(self.arrow))
        self.scene.play(fade_in(self.b), pulse(self.b))
        self.scene.play(highlight(self.a))
        self.svg = self.scene.svg()

    def test_it_is_well_formed_xml(self):
        root = ET.fromstring(self.svg)
        self.assertTrue(root.tag.endswith("svg"))

    def test_nothing_in_it_is_a_script(self):
        # It ends up in a saved notebook, in Colab's output sandbox and in
        # static HTML on the site. None of those should be running anything.
        self.assertNotIn("<script", self.svg.lower())
        self.assertNotIn("onload", self.svg.lower())

    def test_the_same_scene_renders_the_same_bytes(self):
        again, a2, b2, arrow2 = simple()
        again.play(fade_in(a2))
        again.play(draw(arrow2))
        again.play(fade_in(b2), pulse(b2))
        again.play(highlight(a2))
        self.assertEqual(self.svg, again.svg())

    def test_there_is_one_keyframes_rule_for_every_mobject_that_moves(self):
        self.assertEqual(self.svg.count("@keyframes"), len(self.scene.segments))

    def test_less_motion_is_honoured(self):
        self.assertIn("prefers-reduced-motion", self.svg)

    def test_the_transform_attribute_has_no_units_and_the_css_one_does(self):
        # SVG's transform attribute takes user units with nothing written after
        # them, and CSS transform needs px. Getting it the wrong way round
        # fails silently, so it is worth a test of its own.
        s = Scene(200, 100)
        box = s.add(Box(10, 10, text="a"))
        s.play(move(box, dy=-17))
        out = s.svg()
        self.assertIn('transform="translate(0.0,-17.0)"', out)
        self.assertIn("transform:translate(0.0px,-17.0px)", out)

    def test_the_markup_on_its_own_is_the_last_frame(self):
        s = Scene(200, 100)
        box = s.add(Box(10, 10, text="gone"))
        s.play(fade_in(box))
        s.play(fade_out(box))
        self.assertIn('opacity="0.000"', s.svg())

    def test_a_highlight_nobody_uses_stays_invisible(self):
        # Every box carries a wash whether or not anything highlights it, and
        # a wash that defaulted to visible would paint the whole scene yellow.
        s = Scene(200, 100)
        s.add(Box(10, 10, text="a"))
        self.assertIn('opacity="0.000"', s.svg())

    def test_the_ir_in_a_line_is_coloured(self):
        s = Scene(300, 60)
        s.add(Code(x=10, y=10, lines=["  %a = add nsw i32 %x, 1"]))
        out = s.svg()
        self.assertIn(COLOUR["keyword"], out)
        self.assertIn(COLOUR["local"], out)

    def test_prose_can_be_drawn_without_being_read_as_ir(self):
        s = Scene(300, 60)
        s.add(Caption(10, 10, text="nothing reads %b"))
        self.assertNotIn(COLOUR["local"], s.svg())


class TestStills(unittest.TestCase):
    def test_a_still_has_nothing_moving_in_it(self):
        s, a, _, _ = simple()
        s.play(fade_in(a))
        still = s.frame(0.0)
        self.assertNotIn("@keyframes", still)
        self.assertIn('opacity="0.000"', still)

    def test_a_still_at_the_end_matches_what_the_animation_leaves(self):
        s, a, _, _ = simple()
        s.play(fade_in(a))
        s.play(fade_out(a))
        ET.fromstring(s.frame(s.duration))
        self.assertIn('opacity="0.000"', s.frame(s.duration))

    def test_asking_for_a_moment_outside_the_scene_says_how_long_it_is(self):
        s, a, _, _ = simple()
        s.play(fade_in(a))
        with self.assertRaises(SceneError) as caught:
            s.frame(60.0)
        self.assertIn("seconds", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
