#!/usr/bin/env bash
# Build the `alive` toolchain: the extra download for lessons that ask whether a
# transformation is correct rather than what it did.
#
#   ./build-alive.sh /scratch/alive 5
#
# This is a second bundle and not an addition to `min`, and that is the whole
# design decision in this file. Alive2 refuses to configure against an LLVM
# built without RTTI, `min` is built without RTTI because that is how every
# distribution ships it and how every plugin in these lessons is compiled, and
# an LLVM cannot be both. So `alive` carries its own LLVM, statically linked
# into one binary, and a reader who never opens a correctness lesson never
# downloads it.
#
# Takes about three hours on six cores and needs roughly 20 GB of disk while it
# runs.

set -euo pipefail

WORK="${1:-/scratch/alive}"
JOBS="${2:-$(nproc)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag"])' \
  "$HERE/../docs/pin.json")"
VERSION="${TAG#llvmorg-}"

# Alive2 has no release for this LLVM. It tracks llvm-project main, so a commit
# is only good against the LLVM that was main when it landed, and picking one is
# picking a date. This is the last commit before main moved on to 24, which
# makes it the newest Alive2 that still expects the 23 IR.
ALIVE_COMMIT="a68009c9e81575bdcc249d3cc534514a76112221"

PREFIX="$WORK/install/alive-$TAG"
SLUG="linux-$(uname -m)"
OUT="$WORK/alive-$TAG-$SLUG.tar.xz"
LOG="$WORK/timings.txt"

mkdir -p "$WORK"
: > "$LOG"
say() { printf '\n=== %s (%s) ===\n' "$1" "$(date -u +%H:%M:%S)" | tee -a "$LOG"; }
mark() { printf '%-24s %s\n' "$1" "$2" >> "$LOG"; }

# --- prerequisites ---------------------------------------------------------
say "prerequisites"
# re2c builds Alive2's IR parser and z3 is the solver that finds the
# counterexample. Both come from the distribution, because Alive2 asks for Z3
# 4.8.5 and every distribution anybody would run this on is well past that.
for tool in cmake ninja re2c git; do
  command -v "$tool" >/dev/null || { echo "need $tool" >&2; exit 1; }
done
[ -f /usr/include/z3.h ] || { echo "need the Z3 headers, apt install libz3-dev" >&2; exit 1; }

# --- source ----------------------------------------------------------------
say "source"
SRC="$WORK/llvm-project-$VERSION.src"
if [ ! -d "$SRC" ]; then
  t0=$SECONDS
  curl -fsSL -o "$WORK/src.tar.xz" \
    "https://github.com/llvm/llvm-project/releases/download/$TAG/llvm-project-$VERSION.src.tar.xz"
  tar -xf "$WORK/src.tar.xz" -C "$WORK"
  rm -f "$WORK/src.tar.xz"
  mark "llvm source seconds" "$((SECONDS - t0))"
fi

if [ ! -d "$WORK/alive2/.git" ]; then
  # Fetch the one commit rather than cloning. It is a repository we only ever
  # read one revision of, and Alive2's build asks git what version this is, so
  # it has to be a real checkout and not an unpacked tarball.
  t0=$SECONDS
  rm -rf "$WORK/alive2" && mkdir -p "$WORK/alive2"
  git -C "$WORK/alive2" init -q .
  git -C "$WORK/alive2" remote add origin https://github.com/AliveToolkit/alive2.git
  git -C "$WORK/alive2" fetch -q --depth 1 origin "$ALIVE_COMMIT"
  git -C "$WORK/alive2" checkout -q FETCH_HEAD
  mark "alive source seconds" "$((SECONDS - t0))"
fi
mark "alive commit" "$(git -C "$WORK/alive2" rev-parse HEAD)"

# --- llvm ------------------------------------------------------------------
say "configure llvm"
# X86 only. `min` carries five targets because lessons compile for them, and
# this one carries the host because Alive2 only needs enough of a backend to
# have a data layout and a triple.
#
# RTTI and EH are the reason this build exists. Everything else is off, static
# and small, because nothing here ships except one executable.
t0=$SECONDS
cmake -G Ninja -S "$SRC/llvm" -B "$WORK/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$WORK/llvm-install" \
  -DLLVM_ENABLE_PROJECTS="" \
  -DLLVM_TARGETS_TO_BUILD="X86" \
  -DLLVM_ENABLE_RTTI=ON \
  -DLLVM_ENABLE_EH=ON \
  -DLLVM_ENABLE_ASSERTIONS=OFF \
  -DLLVM_BUILD_LLVM_DYLIB=OFF \
  -DLLVM_LINK_LLVM_DYLIB=OFF \
  -DLLVM_INCLUDE_TESTS=OFF \
  -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DLLVM_INCLUDE_EXAMPLES=OFF \
  -DLLVM_INCLUDE_DOCS=OFF \
  -DLLVM_INCLUDE_UTILS=OFF \
  -DLLVM_ENABLE_ZLIB=ON \
  -DLLVM_ENABLE_ZSTD=OFF \
  -DLLVM_ENABLE_LIBEDIT=OFF \
  -DLLVM_ENABLE_TERMINFO=OFF \
  -DLLVM_ENABLE_LIBXML2=OFF \
  -DLLVM_PARALLEL_LINK_JOBS=1
mark "llvm configure seconds" "$((SECONDS - t0))"

say "build llvm"
t0=$SECONDS
ninja -C "$WORK/build" -j "$JOBS"
mark "llvm build seconds" "$((SECONDS - t0))"

# --- alive2 ----------------------------------------------------------------
say "configure alive2"
# BUILD_LLVM_UTILS rather than BUILD_TV. BUILD_TV also builds tv.so, the plugin
# that validates a real `opt` run, and loading it needs an `opt` from this same
# RTTI build. Shipping that opt would double the bundle and give a reader two
# opts that disagree about which one a lesson meant.
#
# Nothing is lost by leaving it out. `alive-tv -passes=instcombine f.ll` runs
# the pass and checks it in one process, which is the same answer `opt -tv`
# gives, and `alive-tv f.ll` on a file holding @src and @tgt checks a fold a
# reader wrote by hand. Those two are every use a lesson has.
t0=$SECONDS
cmake -G Ninja -S "$WORK/alive2" -B "$WORK/alive-build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_LLVM_UTILS=1 \
  -DCMAKE_PREFIX_PATH="$WORK/build"
mark "alive configure seconds" "$((SECONDS - t0))"

say "build alive2"
t0=$SECONDS
ninja -C "$WORK/alive-build" -j "$JOBS" alive-tv
mark "alive build seconds" "$((SECONDS - t0))"

# --- package ---------------------------------------------------------------
say "package"
rm -rf "$PREFIX"
mkdir -p "$PREFIX/bin" "$PREFIX/lib"
cp "$WORK/alive-build/alive-tv" "$PREFIX/bin/"
strip "$PREFIX/bin/alive-tv"

# libz3 travels with the binary. It is the one thing alive-tv needs that a
# Colab image does not already have, and asking a reader to apt install
# anything is asking them to have sudo.
Z3="$(ldd "$PREFIX/bin/alive-tv" | awk '/libz3/ {print $3}')"
[ -n "$Z3" ] && cp -L "$Z3" "$PREFIX/lib/"
patchelf --set-rpath '$ORIGIN/../lib' "$PREFIX/bin/alive-tv" 2>/dev/null \
  || echo "no patchelf, irx will set LD_LIBRARY_PATH instead" | tee -a "$LOG"
mark "install MB" "$(du -sm "$PREFIX" | cut -f1)"

t0=$SECONDS
tar -C "$(dirname "$PREFIX")" -cf - "$(basename "$PREFIX")" | xz -T0 -6 > "$OUT"
mark "package seconds" "$((SECONDS - t0))"
mark "tarball MB" "$(du -sm "$OUT" | cut -f1)"
mark "sha256" "$(sha256sum "$OUT" | cut -d' ' -f1)"

# --- unpack and prove it works ---------------------------------------------
say "unpack"
rm -rf "$WORK/unpack" && mkdir -p "$WORK/unpack"
sync; [ -w /proc/sys/vm/drop_caches ] && echo 3 > /proc/sys/vm/drop_caches || true
t0=$SECONDS
tar -xf "$OUT" -C "$WORK/unpack" --strip-components=1
mark "unpack seconds" "$((SECONDS - t0))"

say "smoke test"
# A fold that is wrong, so the answer has to be a counterexample and not a tick.
# `x + x` is `x << 1`, and it is still `x << 1` when that overflows, so claiming
# nsw is claiming something the source never said.
cat > "$WORK/smoke.ll" <<'LL'
define i32 @src(i32 %x) {
  %r = add i32 %x, %x
  ret i32 %r
}

define i32 @tgt(i32 %x) {
  %r = shl nsw i32 %x, 1
  ret i32 %r
}
LL
t0=$SECONDS
"$WORK/unpack/bin/alive-tv" "$WORK/smoke.ll" 2>&1 | tee -a "$LOG" | tail -20
mark "smoke seconds" "$((SECONDS - t0))"

say "done"
cat "$LOG"
