"""The pin exists twice, so something has to check the two copies agree.

`docs/pin.json` is the one a human reads and edits. `toolkit/irx/pin.json` is the
one that ships inside the pip package, because a wheel cannot reach back up into
the repository to read a file that is not in it. Two copies means they can drift,
and drift here means the toolkit fetches a different LLVM than the docs describe,
which is the exact failure the pin was introduced to prevent.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_PIN = ROOT / "docs" / "pin.json"
PACKAGE_PIN = ROOT / "toolkit" / "irx" / "pin.json"


class TestPinCopies(unittest.TestCase):
    def test_both_copies_exist(self):
        self.assertTrue(DOCS_PIN.exists(), f"{DOCS_PIN} is missing")
        self.assertTrue(PACKAGE_PIN.exists(), f"{PACKAGE_PIN} is missing")

    def test_the_two_copies_are_byte_identical(self):
        self.assertEqual(
            DOCS_PIN.read_bytes(),
            PACKAGE_PIN.read_bytes(),
            "docs/pin.json and toolkit/irx/pin.json have drifted. "
            "Edit docs/pin.json and copy it over the other one.",
        )

    def test_the_tag_looks_like_an_llvm_release(self):
        pin = json.loads(DOCS_PIN.read_text(encoding="utf-8"))
        self.assertRegex(pin["tag"], r"^llvmorg-\d+\.\d+\.\d+$")
        self.assertEqual(pin["citation_suffix"], "@" + pin["tag"])
