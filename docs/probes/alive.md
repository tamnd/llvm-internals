# Probe: Alive2

Everything this project claims to do differently rests on a solver being able to tell a reader that their fold is wrong, in a notebook, before they lose interest. This page is the measurement behind that, in the format the rest of the probes use: the claim as it was originally written, the command that tests it, the result with a date and a machine, and what the design has to change if the answer is the unwelcome one.

The pin is `llvmorg-23.1.0`. Alive2 has no release that matches it, because Alive2 tracks `llvm-project` main and its tags stop at v21.0, so the pin is a commit: `a68009c9e81575bdcc249d3cc534514a76112221`, dated 2026-07-23, the last one before main moved on to 24. That makes it the newest Alive2 that still expects LLVM 23 IR.

Everything below was reproduced with the toolkit in this repository, so anybody can run it again and get a number to argue with.

## 1. Does Alive2 build against the pin at all

**Claim as stated.** Alive2 needs an LLVM built with RTTI and exceptions enabled, which upstream release builds are not, plus Z3.

**Command.**

```
cmake -S llvm -B build -DLLVM_ENABLE_RTTI=ON -DLLVM_ENABLE_EH=ON ...
cmake -S alive2 -B alive-build -DBUILD_LLVM_UTILS=1 -DCMAKE_PREFIX_PATH=build
ninja -C alive-build alive-tv
```

The full recipe is `toolchain/build-alive.sh`.

**Result, 2026-09-02.** Yes, and the RTTI half of the claim is the part that bites. Alive2's `CMakeLists.txt` hard fails configure when `LLVM_ENABLE_RTTI` is off, and it does not check `LLVM_ENABLE_EH` at all. Homebrew's LLVM 23.1.0 on macOS happens to ship `LLVM_ENABLE_RTTI ON` and `LLVM_ENABLE_EH OFF`, which is how alive-tv came to be built on this laptop in about two minutes and how the rest of this page got measured while the Linux builds were still running.

**If the answer had been no.** There is no fallback. Every correctness lesson in Part IV and all of Track A would have had to become a replay recording, and the project's central claim would have been demoted to a video.

## 2. Should `alive` be a separate download or merged into `min`

**Claim as stated.** Separate is smaller for most lessons and adds a second waiting point to the ones that need it, and the answer depends on the sizes you measure.

**Result, 2026-09-02.** Separate, and the sizes turned out not to be the deciding factor.

`min` is built with `LLVM_ENABLE_RTTI=OFF`, because that is how every distribution ships LLVM and therefore what every pass plugin a reader compiles in these lessons is compiled against. Alive2 refuses to configure against that. One LLVM cannot be both, so merging the bundles does not mean a bigger download, it means shipping two LLVMs in one tarball and making every reader who never opens a correctness lesson pay for the second one.

The same reasoning settled `BUILD_LLVM_UTILS=1` rather than `BUILD_TV=1`. `BUILD_TV` also builds `tv.so`, the plugin that validates a real `opt` run, and loading it needs an `opt` from the same RTTI build. Shipping that `opt` would roughly double the bundle and hand the reader two `opt` binaries that disagree about which one a lesson meant. Nothing is lost: `alive-tv before.ll after.ll` covers every use a lesson has.

**If the answer had been merge.** `irx.bootstrap()` would have needed a single download path and the first cell of every lesson would have got slower, including the ones with no solver in them.

## 3. How long does a counterexample take

**Claim as stated.** The Alive2 cell returns a counterexample for a deliberately wrong fold in under 60 seconds on free tier Colab.

**Command.**

```
PYTHONPATH=toolkit python3 toolchain/probe-alive.py
```

**Result, 2026-09-02, macOS 15.8 arm64, LLVM 23.1.0.** Not close to 60 seconds. The wrong fold in the smoke test comes back in 0.03 seconds. Across sixty function and pass pairs, fifteen of which had a real change for Alive2 to look at, the slowest verification was 0.12 seconds and the median 0.04.

| function | passes with a change to check | slowest |
|---|---|---|
| half | sccp | 0.04s |
| twice | instcombine, reassociate, early-cse, gvn | 0.07s |
| abs | sccp, simplifycfg | 0.05s |
| clamp | sccp, simplifycfg | 0.03s |
| sum | instcombine, reassociate, gvn, simplifycfg, licm, indvars | 0.12s |
| swap | none | |

The other forty five pairs are passes that ran and changed nothing, which alive-tv reports as `correct (syntactically equal)`. That is not a verification and `irx.verify` marks it as `untouched` rather than as a tick, because a reader looking for their own pass in a pipeline needs to know the difference between "it is right" and "it did not run".

**Still outstanding.** The number that matters for the exit criterion is the one from free tier Colab, not from an M-series laptop, and that run needs the Linux bundle from item 5. Colab's CPU is slower but the work here is a fraction of a second, so the risk is the download and unpack rather than the solving.

## 4. Where the solver gives up

**Claim as stated.** Nothing stated this. It came out of the probe, and it is the reason lesson X03 has a section called "the size of the guarantee you now have".

**Command.** The second table printed by `toolchain/probe-alive.py`. The pair is `sdiv i{w} %x, 2` against a plain `ashr`, which is wrong, and against the three instruction version that rounds towards zero, which is right.

**Result, 2026-09-02, macOS 15.8 arm64, default 10 second SMT budget, median of 3.**

| width | plain shift, which is wrong | rounded shift, which is right |
|---|---|---|
| i8 | wrong, 0.19s | correct, 0.21s |
| i16 | wrong, 0.11s | timeout, 10.11s |
| i32 | wrong, 0.06s | timeout, 10.09s |
| i64 | wrong, 0.21s | timeout, 10.22s |

Finding a counterexample is cheap at every width, because the solver only has to produce one number and `-1` breaks the plain shift immediately. Proving that no counterexample exists is the expensive direction and it falls off a cliff between `i8` and `i16`. Raising the budget to 120 seconds did not change the `i16` answer.

**What this changes in the design.** A lesson may not describe a green result as a proof. `irx.verify` reports four statuses rather than a boolean, renders a timeout in amber with the words "no answer" and never the word correct, and `Report.ok` is false for a timeout and false for an empty report. Lessons state the bound every time they show a green card. X03 makes the reader watch the cliff happen rather than reading a disclaimer about it.

## 5. Bundle size and unpack time

**Claim as stated.** Two bundles is more download, and the question is whether the combination still fits inside a Colab session and inside a reader's patience.

**Command.** `toolchain/build-alive.sh /root/alivework 6`, which measures the install size, the tarball size, the unpack time after dropping the page cache, and finishes with a smoke test on a fold that is wrong.

**Result.** Not measured yet. The Linux build was started on the x86_64 host on 2026-09-02 at 11:04 UTC and was 589 of 2701 targets in at the time of writing. This row gets filled in from `timings.txt` when it finishes, and this page is not done until it is.

As an indication and nothing more, the macOS build of `alive-tv` against a shared Homebrew LLVM is 2.2 MB of binary plus a `libz3` it does not carry. The Linux bundle statically links LLVM into that binary and does carry `libz3`, so it will be very much larger, and the whole point of measuring rather than guessing is that neither of those numbers predicts the other.

## 6. Does `alive-tv -passes=<pass>` work

**Claim as stated.** Nothing stated this either. It is an alternative to the two file mode that would let a lesson verify a real pass run in one process.

**Result, 2026-09-02, macOS 15.8 arm64.** It segfaults on this build, in `llvm::AnalysisManager<llvm::Module>::getResultImpl`, against the shared Homebrew dylib. Not retested on the static Linux build.

**What this changes in the design.** `irx.alive` does not take a `passes=` argument, and will not until the mode is known to work on the bundle that actually ships. This costs nothing. The two file form is what a reader does anyway, and it is more honest about what is being compared, because both sides are on the screen.
