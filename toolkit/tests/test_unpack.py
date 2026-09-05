"""The three ways the bundle can get unpacked have to agree.

The tarball is zstd, and zstd arrives from a different place depending on the
reader's machine: the system tar, Python's own tarfile on 3.14 and later, or
the zstd binary through a pipe. Only the first of those gets
--strip-components for free, which is exactly the kind of difference that
shows up as a working bootstrap on the author's laptop and a missing bin/
directory on a reader's.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from irx import toolchain


def _fixture(root: Path) -> Path:
    """A miniature of the real bundle: one top directory to strip, a nested
    file, and a hard link, whose target is stored archive-relative and so has
    to be cut the same way the member names are."""
    src = root / "src" / "llvmorg-23.1.0"
    (src / "bin").mkdir(parents=True)
    (src / "bin" / "opt").write_text("opt")
    (src / "include").mkdir()
    (src / "include" / "Pass.h").write_text("header")
    (src / "bin" / "clang++").hardlink_to(src / "bin" / "opt")

    archive = root / "min.tar.zst"
    tar = subprocess.run(["tar", "-C", str(src.parent), "-cf", "-", src.name],
                         check=True, capture_output=True,
                         env={"COPYFILE_DISABLE": "1", "PATH": "/usr/bin:/bin"})
    archive.write_bytes(subprocess.run(["zstd", "-q", "-19"], input=tar.stdout,
                                       check=True, capture_output=True).stdout)
    return archive


EXPECTED = ["bin", "bin/clang++", "bin/opt", "include", "include/Pass.h"]


class UnpackTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("zstd"):
            self.skipTest("no zstd binary to build the fixture with")
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.archive = _fixture(self.root)
        self.real_which = shutil.which

    def _laid_out(self, target: Path) -> list[str]:
        return sorted(str(p.relative_to(target)) for p in target.rglob("*"))

    def _unpack_with(self, hide: tuple[str, ...] = (), break_tarfile_zstd: bool = False):
        target = self.root / f"out-{len(list(self.root.iterdir()))}"
        real_open = tarfile.open

        def fake_which(name):
            return None if name in hide else self.real_which(name)

        def fake_open(*args, **kwargs):
            mode = kwargs.get("mode") or (args[1] if len(args) > 1 else "")
            if mode == "r:zst":
                raise tarfile.CompressionError("forced: this Python is older than 3.14")
            return real_open(*args, **kwargs)

        with unittest.mock.patch.object(shutil, "which", fake_which), \
             unittest.mock.patch.object(
                 tarfile, "open", fake_open if break_tarfile_zstd else real_open):
            toolchain._unpack(self.archive, target)
        return target

    def test_the_system_tar_strips_the_top_directory(self):
        self.assertEqual(self._laid_out(self._unpack_with()), EXPECTED)

    def test_python_tarfile_strips_it_too(self):
        target = self._unpack_with(hide=("tar",))
        self.assertEqual(self._laid_out(target), EXPECTED)

    def test_the_zstd_pipe_strips_it_too(self):
        target = self._unpack_with(hide=("tar",), break_tarfile_zstd=True)
        self.assertEqual(self._laid_out(target), EXPECTED)

    def test_the_hard_link_survives_every_route(self):
        # A hard link whose target kept the stripped prefix points at nothing,
        # and the failure only shows when the linked tool is run.
        for kwargs in ({}, {"hide": ("tar",)},
                       {"hide": ("tar",), "break_tarfile_zstd": True}):
            with self.subTest(**kwargs):
                target = self._unpack_with(**kwargs)
                self.assertEqual((target / "bin" / "clang++").read_text(), "opt")

    def test_it_says_so_when_there_is_no_way_to_read_zstd(self):
        with self.assertRaises(RuntimeError) as caught:
            self._unpack_with(hide=("tar", "zstd"), break_tarfile_zstd=True)
        self.assertIn("zstd", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
