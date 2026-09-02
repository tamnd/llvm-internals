# llvm-internals

A complete visual teardown of LLVM 23, taught from zero, where you run the real optimizer and modify it from a notebook cell, and a solver checks whether the optimization you wrote is actually correct.

Pinned to `llvmorg-23.1.0`, released 25 August 2026.

## Why this exists

There are four kinds of LLVM material in the world and none of them get you from "I have typed `-O2` ten thousand times" to "I can add a pass and open a pull request".

`LangRef` is the only real specification of LLVM IR and it is excellent, but it is written for people who already know what a `Value` is, and nothing on the page runs. Kaleidoscope teaches you to emit IR, which is the easy half, and teaches you nothing about what LLVM then does with it. The books are good and are one to three releases behind by the time you buy them, with no way to tell which sentences went stale. And then there is the source, which is tens of millions of lines with two instruction selectors and a thousand TableGen files.

This project is the missing path. Every claim points at a line of LLVM with a version tag on it, every behaviour is something you watch happen rather than something you are told, and every optimization you write gets checked by a solver that will hand you the exact input where you were wrong.

## What is different about this one

**You get a real LLVM, free, in about thirty seconds.** Every lesson is a Jupyter notebook with an Open in Colab badge. Colab is an Ubuntu VM with root, not a sandbox, so you run the actual `opt`, the actual `llc`, the actual `clang`. The official release tarball is about a gigabyte, which is too slow to put in front of a lesson, so we ship a stripped 350 MB toolchain that unpacks fast.

**Modifying LLVM is a beginner activity.** An out of tree pass plugin is one C++ file. Against installed headers and `libLLVM.so` it compiles in about ten seconds, and `opt -load-pass-plugin=./mypass.so` runs it inside the real pipeline. That one flag moves most of the "change the compiler" material out of an environment nobody has and into a notebook cell.

**The Pass Tape.** `opt -passes='default<O2>' --print-changed=diff-quiet` tells you which of the roughly two hundred passes in the default pipeline actually changed anything, which for a small function is usually somewhere between twenty and forty. Nobody has put that on a scrubber before. You drag through the pipeline, watch the IR change at each boundary, delete a pass from the pipeline string, and re-run.

**There is a machine checkable answer to "is my optimization correct".** Alive2 does bounded translation validation of LLVM IR. You sandwich a pass between two `-tv` markers and it either proves the output refines the input or hands you a counterexample with concrete inputs. Run over LLVM's own unit tests it found 47 previously unknown bugs and produced eight patches to `LangRef` itself. This is what makes `poison` teachable instead of merely assertable: you write a fold that looks correct to you and to everyone who reviews it, the solver shows you the input where it is not, you add a `freeze`, and it passes.

**The backends are generated from a machine readable spec, and it already emits JSON.** Over a thousand TableGen files feed roughly forty generators that write the instruction selector, the assembler, the disassembler and the scheduling models before the compiler is built. `llvm-tblgen -dump-json` dumps all of it. So the normative reference for every target level fact is generated rather than transcribed, which is why it can track upstream instead of rotting.

## Shape of the thing

102 lessons in twelve parts, three passes over the whole compiler at increasing depth. Part 0 is orientation including a chapter on the specific dialect of C++ you need in order to read LLVM and nothing more. Parts I through V take you from one line of C to a verified pass you wrote. Parts VI through IX are the backend: SelectionDAG, MIR, register allocation, the MC layer, GlobalISel and TableGen. Part X is the rest of the toolchain and Part XI is changing LLVM in tree and opening a pull request.

Alongside the lessons there is a Blueprint set, which is the normative half. A Blueprint is a specification with nine fixed sections that may not reference the chapter it accompanies, so somebody can implement from it cold. Pass Blueprints carry a refinement obligation in section 4c, and that obligation is a command that runs in CI rather than a sentence, so every pass Blueprint page publishes a dated status line saying whether refinement currently holds over the corpus.

Then three capstones. Track A is a suite of your own passes, every one proved sound by Alive2, and it runs entirely in Colab. Track B is a complete backend for a small RISC target generated from your own TableGen, scored against `llvm/test/CodeGen`. Track C is a mini LLVM in Rust, differentially tested against real `opt` through the textual IR, which exists to find the places where the Blueprints do not say enough.

## Where you can run it

| | Environment | What you get |
|---|---|---|
| E0 | Colab, one badge click | Real LLVM 23.1.0, plus building and loading your own pass plugin in about ten seconds |
| E1 | Local container or your own machine | The above, plus a full build tree, a debugger, honest benchmarks and the backend capstone |
| E2 | Browser, no account at all | Real `opt` and `llc` output through the Compiler Explorer public API, plus every result CI already baked into the page |

Every page on the site is complete on first paint. The output you read was produced by a real run of the pinned toolchain in CI, so there is no runtime to start and no account needed to read anything. The badge is how you go from reading to running.

The honest ceiling is that LLVM does not build inside a Colab session at all. Not slowly, at all. Building LLVM is taught as its own lesson with real numbers, and exactly one capstone track needs a build tree and says so on its first page.

## Status

Specification stage. Nothing is built yet.

The current milestone is M0, which exists to measure the four assumptions this whole design rests on: that a pass plugin really does compile in seconds on a free Colab runtime, that the toolchain tarball fits in 350 MB and unpacks in thirty seconds, that Alive2 fits at the free tier at all, and that the Pass Tape widget survives Colab's output sandbox at realistic data sizes. M0 is allowed to fail. If the plugin number lands north of a minute the architecture is wrong and it is better to know that in week one.

See the [milestone issues](https://github.com/tamnd/llvm-internals/issues?q=is%3Aissue+label%3Akind%2Fmilestone) for the plan and [ROADMAP.md](ROADMAP.md) for the short version.

## Licence

Content is CC BY 4.0. Code is Apache-2.0 with the LLVM exception, deliberately matching upstream, so any pass, lit test or TableGen fragment you write here can go into `llvm-project` or into your proprietary toolchain with no licence analysis. Several boss fights are designed to produce exactly that.

## Related

Part of a series that shares its pedagogy, its Blueprint format and its conformance machinery.

- [cpython-internals](https://github.com/tamnd/cpython-internals), CPython 3.15
- [gcc-internals](https://github.com/tamnd/gcc-internals), GCC 16
- [linux-kernel-internals](https://github.com/tamnd/linux-kernel-internals), Linux 7.2
- [rucc](https://github.com/tamnd/rucc), an optimizing C compiler in Rust with no LLVM, which is the deliberate control
