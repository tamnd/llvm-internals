#!/usr/bin/env bash
# Build the `min` toolchain: the LLVM a reader downloads when they open a lesson.
#
# This is the configuration that has to fit in a Colab session. Everything about
# it is a size or time decision, and every one of those decisions is a
# constraint on what a lesson is allowed to do, so they are written down here
# rather than living in somebody's shell history.
#
#   ./build-min.sh /scratch/llvm 8
#
# Takes about an hour and a half on eight cores. Needs roughly 30 GB of disk
# while it runs and produces a tarball a fraction of that.

set -euo pipefail

WORK="${1:-/scratch/llvm}"
JOBS="${2:-$(nproc)}"
TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag"])' \
  "$(dirname "$0")/../docs/pin.json" 2>/dev/null || echo llvmorg-23.1.0)"
VERSION="${TAG#llvmorg-}"
MAJOR="${VERSION%%.*}"
PREFIX="$WORK/install/$TAG"
SLUG="linux-$(uname -m)"
OUT="$WORK/llvm-$TAG-min-$SLUG.tar.zst"
LOG="$WORK/timings.txt"

mkdir -p "$WORK"
: > "$LOG"
say() { printf '\n=== %s (%s) ===\n' "$1" "$(date -u +%H:%M:%S)" | tee -a "$LOG"; }
mark() { printf '%-24s %s\n' "$1" "$2" >> "$LOG"; }

# --- source ----------------------------------------------------------------
say "source"
SRC="$WORK/llvm-project-$VERSION.src"
if [ ! -d "$SRC" ]; then
  t0=$SECONDS
  curl -fsSL -o "$WORK/src.tar.xz" \
    "https://github.com/llvm/llvm-project/releases/download/$TAG/llvm-project-$VERSION.src.tar.xz"
  tar -xf "$WORK/src.tar.xz" -C "$WORK"
  rm -f "$WORK/src.tar.xz"
  mark "source seconds" "$((SECONDS - t0))"
fi

# --- configure -------------------------------------------------------------
say "configure"
# Targets. X86 because that is what Colab is, AArch64 because that is what half
# of the readers' laptops are, RISCV for the backend capstone and the P
# extension lesson, WebAssembly for the reference types lesson, NVPTX because
# its default SM version changed in 23 and one lesson is about noticing that.
# Every extra target is roughly 30 MB of libLLVM and several minutes of build.
#
# The dylib flags are the important pair. Without them every tool statically
# links its own copy of LLVM, the install is several gigabytes, and an out of
# tree pass plugin has nothing to link against. With them, libLLVM.so is one
# shared object, the tools are small, and `clang++ -shared pass.cpp -lLLVM`
# takes about ten seconds. The entire E0 story depends on that.
t0=$SECONDS
cmake -G Ninja -S "$SRC/llvm" -B "$WORK/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" \
  -DCMAKE_C_COMPILER=clang-18 \
  -DCMAKE_CXX_COMPILER=clang++-18 \
  -DLLVM_USE_LINKER=lld-18 \
  -DLLVM_ENABLE_PROJECTS="clang;lld" \
  -DLLVM_TARGETS_TO_BUILD="X86;AArch64;RISCV;WebAssembly;NVPTX" \
  -DLLVM_BUILD_LLVM_DYLIB=ON \
  -DLLVM_LINK_LLVM_DYLIB=ON \
  -DCLANG_LINK_CLANG_DYLIB=ON \
  -DLLVM_ENABLE_ASSERTIONS=OFF \
  -DLLVM_ENABLE_RTTI=OFF \
  -DLLVM_ENABLE_EH=OFF \
  -DLLVM_INSTALL_UTILS=ON \
  -DLLVM_INCLUDE_TESTS=OFF \
  -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DLLVM_INCLUDE_EXAMPLES=OFF \
  -DLLVM_INCLUDE_DOCS=OFF \
  -DLLVM_ENABLE_ZLIB=ON \
  -DLLVM_ENABLE_ZSTD=ON \
  -DLLVM_ENABLE_LIBEDIT=OFF \
  -DLLVM_ENABLE_TERMINFO=OFF \
  -DLLVM_PARALLEL_LINK_JOBS=2
mark "configure seconds" "$((SECONDS - t0))"

# --- build -----------------------------------------------------------------
say "build"
t0=$SECONDS
ninja -C "$WORK/build" -j "$JOBS"
mark "build seconds" "$((SECONDS - t0))"

say "install"
t0=$SECONDS
# install/strip rather than install. Debug info in a release build is most of
# the size and none of the value for somebody reading pass output.
ninja -C "$WORK/build" -j "$JOBS" install/strip
mark "install seconds" "$((SECONDS - t0))"
mark "install MB" "$(du -sm "$PREFIX" | cut -f1)"

# --- prune -----------------------------------------------------------------
say "prune"
# Static archives are the bulk of an LLVM install and nothing here needs them,
# because every tool and every plugin links the dylib instead. Headers stay,
# because compiling a pass plugin in a notebook cell is the whole point.
t0=$SECONDS
rm -rf "$PREFIX"/lib/*.a "$PREFIX"/lib/objects-Release
rm -rf "$PREFIX"/share/man "$PREFIX"/share/doc "$PREFIX"/share/opt-viewer
rm -rf "$PREFIX"/libexec

# Tools a lesson may reach for, and nothing else. This list is duplicated in
# irx/toolchain.py, which asks for a tool by name and refuses anything not on
# it, so a lesson that wants a new tool has to change both and notice the size.
#
# An array rather than one string, because the obvious `case " $KEEP " in` over
# a multi line string silently drops the first and last name on every line: the
# pattern wants a space on both sides and finds a newline. That cost a build.
KEEP=(clang clang++ "clang-$MAJOR" opt llc lli
      llvm-as llvm-dis llvm-link llvm-extract llvm-nm llvm-objdump
      llvm-mc llvm-mca llvm-reduce llvm-tblgen llvm-config llvm-symbolizer
      llvm-profdata llvm-cov llvm-readobj
      lld FileCheck not count llvm-lit)

keep() {
  local name
  for name in "${KEEP[@]}"; do [ "$name" = "$1" ] && return 0; done
  return 1
}

cd "$PREFIX/bin"
for f in *; do
  # Symlinks survive whatever they are. They cost nothing, and the lld ones
  # (ld.lld, wasm-ld, ld64.lld) are how a driver finds the linker, so removing
  # what they point at breaks linking without removing anything named lld.
  keep "$f" || [ -L "$f" ] || rm -f "$f"
done
# A symlink whose target the list above dropped is worth nothing, so it goes
# too. This is a second pass rather than a condition in the first one, because
# the order `for f in *` visits names in decides whether the target is still
# there when the link is looked at, and that is not something to depend on.
for f in *; do
  [ -e "$f" ] || { echo "dropping $f, which pointed at a tool that went"; rm -f "$f"; }
done
cd - >/dev/null
mark "prune seconds" "$((SECONDS - t0))"
mark "pruned MB" "$(du -sm "$PREFIX" | cut -f1)"

# --- package ---------------------------------------------------------------
# zstd over xz, measured in docs/probes/min.md section 5. xz makes an archive
# 4 MB smaller and takes 5.5 seconds longer to unpack, and its decompression is
# single threaded, so Colab's second core does not help. Trading download bytes
# for seconds of a reader's first ninety is the right way round.
#
# No --long, deliberately. It buys 1.3 MB, costs 170 seconds of packing, and
# produces a frame needing a 128 MB decompression window, which some readers'
# zstd will refuse without a matching --long on their side. A default 8 MB
# window means plain `tar --zstd -xf` works with no flags anywhere.
say "package"
t0=$SECONDS
tar -C "$(dirname "$PREFIX")" -cf - "$(basename "$PREFIX")" \
  | zstd -q -19 -T0 > "$OUT"
mark "package seconds" "$((SECONDS - t0))"
mark "tarball MB" "$(du -sm "$OUT" | cut -f1)"
mark "sha256" "$(sha256sum "$OUT" | cut -d' ' -f1)"

# --- unpack, which is the number a reader actually waits for ---------------
say "unpack"
rm -rf "$WORK/unpack" && mkdir -p "$WORK/unpack"
sync; [ -w /proc/sys/vm/drop_caches ] && echo 3 > /proc/sys/vm/drop_caches || true
t0=$SECONDS
tar --zstd -xf "$OUT" -C "$WORK/unpack" --strip-components=1
mark "unpack seconds" "$((SECONDS - t0))"

"$WORK/unpack/bin/opt" --version | head -2 | tee -a "$LOG"

# --- smoke, because a tarball that unpacks is not the same as one that works --
say "smoke"
# The prune above is the step most likely to be quietly wrong, and a missing
# tool shows up as a lesson failing months later rather than as a build error.
# So the bundle has to do the thing E0 is for before it is called finished.
B="$WORK/unpack/bin"
SMOKE="$WORK/smoke"
rm -rf "$SMOKE" && mkdir -p "$SMOKE"

for tool in clang clang++ opt lli llc llvm-as llvm-dis llvm-link llvm-config \
            llvm-nm llvm-objdump llvm-mc llvm-mca llvm-reduce llvm-extract \
            FileCheck; do
  [ -x "$B/$tool" ] || { echo "the prune removed $tool"; exit 1; }
done

cat > "$SMOKE/pass.cpp" <<'CPP'
#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Plugins/PassPlugin.h"
using namespace llvm;
namespace {
struct Smoke : PassInfoMixin<Smoke> {
  PreservedAnalyses run(Function &F, FunctionAnalysisManager &) {
    errs() << "smoke saw " << F.getName() << "\n";
    return PreservedAnalyses::all();
  }
};
}  // namespace
extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
  return {LLVM_PLUGIN_API_VERSION, "smoke", "0.1", [](PassBuilder &PB) {
    PB.registerPipelineParsingCallback(
      [](StringRef N, FunctionPassManager &FPM, ArrayRef<PassBuilder::PipelineElement>) {
        if (N == "smoke") { FPM.addPass(Smoke()); return true; }
        return false;
      });
  }};
}
CPP

t0=$SECONDS
"$B/clang++" -shared -fPIC -O2 -std=c++17 -fno-rtti \
  -I"$WORK/unpack/include" -L"$WORK/unpack/lib" -lLLVM \
  -Wl,-rpath,"$WORK/unpack/lib" \
  -o "$SMOKE/smoke.so" "$SMOKE/pass.cpp"
mark "plugin compile seconds" "$((SECONDS - t0))"

printf 'define i32 @gauss(i32 %%n) {\n  ret i32 %%n\n}\n' > "$SMOKE/in.ll"
"$B/opt" -load-pass-plugin "$SMOKE/smoke.so" -passes=smoke \
  -S "$SMOKE/in.ll" -o /dev/null 2>&1 | tee -a "$LOG" | grep -q "smoke saw gauss"
mark "plugin loaded" "yes"

# lli and llvm-link, which the lessons drive counterexamples through.
"$B/llvm-link" -S "$SMOKE/in.ll" -o "$SMOKE/linked.ll"
printf 'define i32 @main() {\n  %%r = call i32 @gauss(i32 7)\n  ret i32 %%r\n}\n' \
  >> "$SMOKE/linked.ll"
set +e
"$B/lli" "$SMOKE/linked.ll"
mark "lli exit status" "$?"
set -e

say "done"
cat "$LOG"
