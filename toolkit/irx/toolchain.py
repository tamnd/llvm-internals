"""Getting a real, pinned LLVM onto whatever machine this is.

Every claim in this material is written against one tag. A lesson that quietly
ran against whatever compiler happened to be installed would be a lesson that is
wrong in a way nobody notices, so this module would rather fail loudly than run
against the wrong version.

Sources are tried in order and the one that won is printed, because on Colab the
difference between "unpacked a tarball in 20 seconds" and "installed from apt in
four minutes" is the difference between a lesson people finish and one they
close. Anything that measures the bootstrap needs to know which happened.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import env

PIN = json.loads((Path(__file__).parent / "pin.json").read_text(encoding="utf-8"))
TAG: str = PIN["tag"]
MAJOR: str = TAG.removeprefix("llvmorg-").split(".")[0]

RELEASES = "https://github.com/tamnd/llvm-internals/releases/download"
CACHE = Path(os.environ.get("IRX_CACHE", Path.home() / ".cache" / "irx"))

# Tools a lesson is allowed to reach for. Anything outside this list is either
# not in the stripped tarball or not something we have checked behaves the same
# across the three environments, and finding that out from a NameError beats
# finding it out from a subtly different answer.
TOOLS = {
    "clang", "clang++", "opt", "llc", "llvm-as", "llvm-dis", "llvm-link",
    "llvm-extract", "llvm-nm", "llvm-objdump", "llvm-mc", "llvm-mca",
    "llvm-reduce", "llvm-tblgen", "llvm-config", "FileCheck", "lli",
    "llvm-profdata", "llvm-cov", "llvm-readobj", "llvm-symbolizer", "lld",
}


class ToolchainError(RuntimeError):
    pass


@dataclass
class Toolchain:
    bin: Path
    version: str
    source: str
    seconds: float

    @property
    def major(self) -> str:
        return self.version.split(".")[0]

    def __str__(self) -> str:
        return f"LLVM {self.version} from {self.source}, ready in {self.seconds:.1f}s"


_current: Toolchain | None = None


def platform_slug() -> str:
    machine = {"x86_64": "x86_64", "AMD64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(
        platform.machine(), platform.machine()
    )
    return f"{platform.system().lower()}-{machine}"


def _version_of(bindir: Path) -> str | None:
    exe = bindir / "llvm-config"
    if not exe.exists():
        exe = bindir / "opt"
        if not exe.exists():
            return None
        try:
            out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.stdout.split("\n"):
            if "version" in line.lower():
                return line.strip().split()[-1]
        return None
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


# -- the sources, tried in this order ---------------------------------------


def _from_env() -> tuple[Path, str] | None:
    raw = os.environ.get("IRX_LLVM_BIN")
    if raw and (Path(raw) / "opt").exists():
        return Path(raw), "IRX_LLVM_BIN"
    return None


def _from_cache() -> tuple[Path, str] | None:
    bindir = CACHE / TAG / "bin"
    if (bindir / "opt").exists():
        return bindir, "the unpacked tarball in the cache"
    return None


def _from_build_tree() -> tuple[Path, str] | None:
    tree = env.build_tree()
    if tree is not None:
        return tree / "bin", f"the build tree at {tree}"
    return None


def _from_system() -> tuple[Path, str] | None:
    candidates = []
    found = shutil.which("opt")
    if found:
        candidates.append(Path(found).parent)
    candidates += [
        Path(f"/usr/lib/llvm-{MAJOR}/bin"),
        Path("/opt/homebrew/opt/llvm/bin"),
        Path("/usr/local/opt/llvm/bin"),
    ]
    for bindir in candidates:
        if (bindir / "opt").exists():
            return bindir, f"the system LLVM at {bindir}"
    return None


def _from_tarball(verbose: bool) -> tuple[Path, str] | None:
    """The curated build. This is the path the whole E0 story depends on."""
    name = f"llvm-{TAG}-min-{platform_slug()}.tar.xz"
    url = f"{RELEASES}/toolchain-{TAG}/{name}"
    target = CACHE / TAG
    archive = CACHE / name
    CACHE.mkdir(parents=True, exist_ok=True)
    try:
        if verbose:
            print(f"irx: fetching {name}")
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            archive.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    _unpack(archive, target)
    archive.unlink(missing_ok=True)
    bindir = target / "bin"
    return (bindir, "the pinned tarball") if (bindir / "opt").exists() else None


def _unpack(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if shutil.which("tar"):
        # The system tar is several times faster than Python's tarfile on a big
        # archive, and the bootstrap has a wall clock budget.
        subprocess.run(["tar", "-xf", str(archive), "-C", str(target), "--strip-components=1"],
                       check=True)
        return
    with tarfile.open(archive) as tar:
        tar.extractall(target, filter="data")


def _from_apt(verbose: bool) -> tuple[Path, str] | None:
    """The slow fallback, so a lesson still works before the tarball exists.

    This takes minutes, not seconds, and it only exists so that nothing is
    blocked on the packaging work. It prints how long it took because that
    number is the argument for building the tarball.
    """
    if platform.system() != "Linux" or shutil.which("apt-get") is None:
        return None
    if os.geteuid() != 0 and shutil.which("sudo") is None:
        return None
    if verbose:
        print(f"irx: no tarball yet, installing LLVM {MAJOR} from apt.llvm.org. This is slow.")
    sudo = [] if os.geteuid() == 0 else ["sudo"]
    script = Path("/tmp/llvm.sh")
    try:
        with urllib.request.urlopen("https://apt.llvm.org/llvm.sh", timeout=60) as response:  # noqa: S310
            script.write_bytes(response.read())
        script.chmod(0o755)
        subprocess.run([*sudo, "bash", str(script), MAJOR], check=True)
    except (urllib.error.URLError, OSError, subprocess.CalledProcessError):
        return None
    bindir = Path(f"/usr/lib/llvm-{MAJOR}/bin")
    return (bindir, "apt.llvm.org, the slow path") if (bindir / "opt").exists() else None


# -- the entry point ---------------------------------------------------------


def _skew_message(version: str, bindir: Path) -> str:
    return (
        f"Found LLVM {version} at {bindir}, but everything here is written\n"
        f"against {TAG}. Names, defaults and pass behaviour differ between\n"
        "major versions, so a lesson run against the wrong one is not broken,\n"
        "it quietly teaches you something that is not true.\n"
        "\n"
        f"  Point IRX_LLVM_BIN at an LLVM {MAJOR} install, or set\n"
        "  IRX_ALLOW_VERSION_SKEW=1 if you know what you are doing."
    )


def bootstrap(verbose: bool = True, allow_skew: bool | None = None) -> Toolchain:
    """Find or fetch a pinned LLVM, and remember it for the rest of the session.

    Sources are tried cheapest first. A source that turns up the wrong major
    version is passed over rather than treated as a failure, because the common
    case for that is a machine with some other LLVM on PATH, and the right
    answer there is to go and get the pinned one rather than to give up. The one
    exception is IRX_LLVM_BIN: somebody set that on purpose, so being ignored
    would be worse than being told.
    """
    global _current
    if _current is not None:
        return _current

    if allow_skew is None:
        allow_skew = os.environ.get("IRX_ALLOW_VERSION_SKEW") == "1"

    start = time.monotonic()
    finders = [
        ("IRX_LLVM_BIN", _from_env),
        ("cache", _from_cache),
        ("build tree", _from_build_tree),
        ("system", _from_system),
        ("tarball", lambda: _from_tarball(verbose)),
        ("apt", lambda: _from_apt(verbose)),
    ]

    passed_over: list[str] = []
    for label, finder in finders:
        found = finder()
        if found is None:
            continue
        bindir, source = found
        version = _version_of(bindir) or "unknown"
        if version.split(".")[0] != MAJOR and not allow_skew:
            if label == "IRX_LLVM_BIN":
                raise ToolchainError(_skew_message(version, bindir))
            passed_over.append(f"{source} has LLVM {version}")
            if verbose:
                print(f"irx: skipping {source}, that is LLVM {version} and we want {MAJOR}")
            continue

        _current = Toolchain(
            bin=bindir, version=version, source=source, seconds=time.monotonic() - start
        )
        if verbose:
            print(f"irx: {_current}")
            print(f"irx: {env.describe()}")
        return _current

    detail = ""
    if passed_over:
        detail = "\n  Passed over on the way: " + "; ".join(passed_over) + ".\n"
    raise ToolchainError(
        f"Could not find LLVM {MAJOR} anywhere, and could not fetch it.\n"
        f"{detail}"
        "\n"
        "  On a local machine, install it and point at it:\n"
        f"    export IRX_LLVM_BIN=/path/to/llvm-{MAJOR}/bin\n"
        "\n"
        "  In a notebook, this usually means the download was blocked. Try the\n"
        "  cell again, and if it keeps failing open an issue with the output."
    )


def current() -> Toolchain:
    return _current or bootstrap(verbose=False)


def path_to(tool: str) -> Path:
    if tool not in TOOLS:
        known = ", ".join(sorted(TOOLS))
        raise ToolchainError(f"`{tool}` is not one of the tools lessons use. Those are: {known}")
    path = current().bin / tool
    if not path.exists():
        raise ToolchainError(
            f"`{tool}` is not in {current().bin}. The stripped toolchain does not\n"
            "carry every tool. If a lesson needs this one, the tarball recipe has\n"
            "to change, which is a change to the size budget as well."
        )
    return path


def reset() -> None:
    """Forget the current toolchain. Tests use this, lessons do not."""
    global _current
    _current = None
