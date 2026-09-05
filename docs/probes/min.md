# Probe: the min toolchain

A reader opens a badge and waits, and almost everything they wait for is this tarball. This page is the measurement behind it, in the same format as the other probes: the claim as it was originally written, the command that tests it, the result with a date and a machine, and what the design has to change if the answer is the unwelcome one.

The pin is `llvmorg-23.1.0`. The build script is `toolchain/build-min.sh`, and every configuration decision in it carries a comment saying what it costs, because each one is a constraint on what a lesson is allowed to do afterwards.

Every number below was measured on a Linux x86_64 host with 8 cores and 23 GB of RAM. It is a shared box carrying a load average around 27 while these ran, which makes its wall clock figures worth very little and its CPU figures worth quite a lot. That distinction is called out again where it matters. Nothing here was measured on free tier Colab, and the two numbers that decide M0 are Colab numbers.

## 1. Does the configuration build, and how big is it

**Claim as stated.** A curated build of `llvmorg-23.1.0` stripped down to what the lessons actually invoke, targeted at 350 MB. That number is a target, not a measurement. Nobody has built it yet.

**Command.**

```
./toolchain/build-min.sh /root/llvmwork 8
```

**Result, 2026-09-02.** It builds. Four hours and four minutes on eight cores for the first build, which is a number nobody in this project should have to reproduce, because the output is a tarball.

| stage | result |
|---|---|
| install, stripped | 746 MB |
| after the prune | 291 MB |
| tarball | 55 MB |

Five targets are built. X86 because that is what Colab is, AArch64 because that is what half of the readers' laptops are, RISCV for the backend capstone, WebAssembly for the reference types lesson, and NVPTX because its default SM version changed in 23 and one lesson is about noticing that. Each extra target is roughly 30 MB of `libLLVM` and several minutes of build.

The pair of settings that does the real work is `LLVM_BUILD_LLVM_DYLIB=ON` with `LLVM_LINK_LLVM_DYLIB=ON`. Without them every tool statically links its own copy of LLVM, the install runs to several gigabytes, and an out of tree pass plugin has nothing to link against. With them there is one `libLLVM.so`, the tools are small, and `clang++ -shared pass.cpp -lLLVM` works. The whole E0 story rests on that one choice.

Headers stay in the bundle. They are a large share of the 291 MB and they are not negotiable, because compiling a pass plugin in a notebook cell is the point of the environment.

**If the answer had been no.** There is no version of this project where a reader waits for an LLVM build, so a bundle that cannot be made small enough means E0 is not viable and Parts IV and XI move to a local devcontainer.

## 2. What the prune removes, and the bug it hid

**Claim as stated.** Record which targets and tools were dropped and why, because that list becomes a constraint on every lesson written afterwards.

**The list, as of the pin.** Static archives (`lib/*.a`) and `lib/objects-Release`, because every tool and every plugin links the dylib instead. Then `share/man`, `share/doc`, `share/opt-viewer` and `libexec`. Then everything in `bin` that is not one of these:

```
clang clang++ clang-23 opt llc lli
llvm-as llvm-dis llvm-link llvm-extract llvm-nm llvm-objdump
llvm-mc llvm-mca llvm-reduce llvm-tblgen llvm-config llvm-symbolizer
llvm-profdata llvm-cov llvm-readobj
lld FileCheck not count llvm-lit
```

A lesson that wants a tool outside that list has to add it here and watch the size move. The same list lives in `irx/toolchain.py`, which refuses to run a tool that is not on it, so a lesson cannot quietly depend on something the bundle does not ship.

**Result, 2026-09-02, and this is the part worth reading.** The first build of this bundle shipped without `llvm-config`, `llvm-link`, `llvm-extract`, `llvm-tblgen`, `llvm-symbolizer` or `lld`, all six of which are on the keep list above.

The prune was a `case " $KEEP " in *" $f "*)` over a keep list written across four lines. The pattern needs a space on both sides of the name, and the first and last name on every line has a newline on one side instead, so six tools failed to match their own entry and were deleted. Nothing failed. The tarball built, `opt --version` printed 23.1.0, and the timings file looked healthy.

Losing `lld` also left `ld.lld`, `lld-link`, `ld64.lld` and `wasm-ld` as symlinks pointing at nothing, which is the state in which a bundle unpacks fine and cannot link anything.

The keep list is a bash array now and membership is a loop over it, so a newline is a separator like any other. After the prune the script sweeps for symlinks whose target went and removes those too, naming each one, which is how the `amdgpu-arch` and `nvptx-arch` links turned up: both point into a driver binary that is not on the list.

**What this changes in the design.** The build script ends with a smoke test rather than a version string. A tarball is not finished because it unpacks. It is finished when it does the thing E0 exists to do.

## 3. Does the pruned bundle actually work

**Claim as stated.** Nothing stated this. It exists because of item 2.

**Command.** The `smoke` stage at the end of `toolchain/build-min.sh`. It checks fifteen tools are present and executable, compiles a real pass plugin against the bundle's own headers and its `libLLVM`, loads it into the bundle's `opt` with `-load-pass-plugin`, and runs a module through the bundle's `lli` and checks the exit status.

**Result, 2026-09-02.** All of it passes.

```
plugin compile seconds   54
smoke saw gauss
plugin loaded            yes
lli exit status          7
```

The pass printed its own line from inside `opt`, so the plugin was compiled, linked, loaded and run by the shipped toolchain and nothing else. `lli` returned 7 for `gauss(7)`, so the interpreter the correctness lessons drive their counterexamples through works.

## 4. Does a plugin compile in under 20 seconds

**Claim as stated.** The M0 gate on issue #1: a pass plugin compiles and loads in under 20 seconds on free tier Colab.

**Command.** `clang++ -shared -fPIC` over the smoke pass with the flags `irx` actually uses, which are whatever `llvm-config --cxxflags` returns, three times in a row.

**Result, 2026-09-02, on the shared 8 core host at load average 27.**

| run | wall | user |
|---|---|---|
| 1 | 55.4s | 18.6s |
| 2 | 23.0s | 16.4s |
| 3 | 28.9s | 17.2s |

The wall clock column is noise from a machine carrying three times its core count, and this project's own notes say that host is not a valid place to measure a timing. The user time is the honest figure, and it is 16 to 18 seconds of CPU to parse `PassBuilder.h` and its dependencies and link against the dylib. Against a 20 second gate that is not a pass, it is a coin flip, and the machine that decides is a 2 vCPU Colab runtime.

For comparison the same class of plugin compiles in 1.1 to 1.9 seconds on an M-series laptop against a Homebrew LLVM, which is a useful reminder that the laptop number was never evidence for this gate.

**A precompiled header roughly halves it.** Building a PCH over the five headers a plugin cell includes costs 15 seconds of CPU once and produces a 50 MB file, which is 16 MB compressed. Compiling the pass with `-include-pch` after that costs 8.6 to 9.3 seconds of CPU instead of 16 to 18. The PCH has to be built with the same `-fPIC` as the plugin or clang refuses it outright, with a clear enough message that it took one attempt to find.

Halving the compile is worth nothing if the resulting plugin is not the same plugin, so that was checked rather than assumed. The PCH-built `.so` loads into the bundle's `opt` under `-load-pass-plugin`, and running the same module through both builds produces identical output on stdout and identical diagnostics on stderr. The PCH is a build-time shortcut with no effect on what the pass does.

**What this changes in the design.** Nothing yet, and that is deliberate. The gate is a Colab number and this is not one. If Colab comes in over 20 seconds, the PCH is the first lever and shipping it inside the bundle is the change.

## 5. Does it unpack in under 30 seconds

**Claim as stated.** The `min` tarball is under 350 MB and unpacks in under 30 seconds.

**Result, 2026-09-02.** The size half is comfortable and was the wrong thing to worry about. 291 MB of mostly headers and one large shared object compresses to 55 MB with `xz -T0 -6`, so the download is small.

The first timing of the other half said 45 seconds, which would have failed the gate outright. That number was wrong, and the way it was wrong is the same trap section 4 spends three paragraphs warning about: it was taken while this host carried a load average of 27. Repeated on the same box at load average 1.4, with `/proc/sys/vm/drop_caches` confirmed writable and the cache dropped before every run:

| | xz -6 | zstd -19 --long | zstd -19 |
|---|---|---|---|
| archive | 55 MB | 57.1 MB | 58.4 MB |
| decompress only, 3 cold runs | 5.7s, 5.6s, 5.6s | 1.3s, 1.3s, 1.2s | 1.2s |
| full unpack to disk, 3 cold runs | 7.4s, 7.1s, 9.0s | 2.0s, 1.7s, 2.2s | 3.2s |
| decompress pinned to one core | 5.7s | 1.5s | not run |
| pack time, once, in CI | 205s | 302s | 132s |

So the gate was never in danger. xz unpacks in 7 to 9 seconds against a 30 second budget, and the earlier 45 was a measurement of the machine, not of the archive.

The claim underneath it was true, though: xz decompression is single threaded. Pinning it to one core changes 5.7 seconds into 5.7 seconds, which is what no threading looks like. The `-T0` in the pack command buys nothing on the reader's side, and a 2 vCPU Colab runtime gets no help from its second core either.

**The bundle ships zstd anyway.** Not because xz misses the gate, but because 4 to 6 seconds of a reader's first ninety is worth 3 MB of download, which is a fraction of a second on any connection that can pull 55 MB in reasonable time.

**Without `--long`, which is the part worth writing down.** The obvious way to pack is `zstd -19 --long`, and it is a trap. `--long` raises the window to 128 MB, and a frame that needs a 128 MB window is one the zstd CLI can refuse unless the reader passes a matching `--long` on their side. That turns the unpack command into `tar -I 'zstd -d --long=27'`, which is a flag that has to survive every tar the readers have.

The measured cost of not doing it is 1.3 MB, or 2.1 percent, and the saving is 170 seconds of packing. In exchange, `tar --zstd -xf` works with no flags at all. That is a good trade at 1.3 MB and it would still be a good trade at five times that.

Worth noting that the `--long` archive did decompress on this host with no flag at all, which is the failure mode this is avoiding: the version of zstd doing the testing was lenient, a reader's might not be, and the bug would land as a broken bootstrap on somebody else's machine.

The 50 MB precompiled header from section 4 compresses to 16 MB, so shipping it inside the bundle if Colab needs it is a 16 MB question, not a 50 MB one.

**What this changed in the code.** `toolchain/build-min.sh` packs with `zstd -q -19 -T0` and unpacks with `tar --zstd -xf`. `irx` has to be more careful, because it runs on whatever the reader has: it tries the system tar first for speed, then Python's `tarfile`, which only learned zstd in 3.14 while this project supports 3.10, then the `zstd` binary through a pipe, and it says which of those is missing when none of them work.

Only the system tar route gets `--strip-components` for free. The two Python routes needed it written by hand, and the first version did not have it, which put `bin/` one level too deep, a bootstrap that works on any machine with GNU tar and fails on one without. `tests/test_unpack.py` now runs all three routes against the same archive and asserts they produce identical trees, hard links included.

## 6. Does the whole bootstrap reach a working LLVM in 90 seconds

**Claim as stated.** The kill criterion for M0.

**Result.** Not measured. It needs a Colab runtime, the published tarball and a real download over a connection that is not a fast office one, and it is the number this milestone exists to find out. Nothing above substitutes for it.

What the probe does establish is where the 90 seconds is likely to go. Unpacking is 2 seconds and is not the problem. The download of 58 MB is bandwidth the project does not control. The plugin compile is 16 to 18 seconds of CPU on a machine with four times Colab's cores, and it is the only figure here that is close to its own gate. If the bootstrap misses 90 seconds, section 4 is where to look, and the precompiled header is the lever that is already built and verified.

There is also a caution this probe earned the hard way. Two of the numbers above were first measured on a host under heavy load and both were wrong in the direction that makes a gate look lost. Any figure that decides M0 gets taken on an idle machine, more than once, or it does not count.
