# Roadmap

Thirteen milestones, about 81 person weeks at 25 focused hours a week. Each milestone has an issue with its tasks, its exit gates and its kill criteria on it, linked below, and that issue is the thing that gets updated. This file is the map.

Three of these are real stopping points, meaning a place where the project could end and still have produced something worth having. They are marked below.

| | Milestone | Weeks | What it produces |
|---|---|---|---|
| [M0](https://github.com/tamnd/llvm-internals/issues/9) | Prove the environment | 5 | The build pipeline, the toolchain tarball, the pass plugin magic, Alive2 wired up, the Pass Tape, and two pilot lessons |
| [M1](https://github.com/tamnd/llvm-internals/issues/10) | Part 0 and the Tourist | 7 | Sixteen lessons, the site, the claim ledger. **Stopping point.** |
| [M2](https://github.com/tamnd/llvm-internals/issues/11) | The IR | 6 | Ten lessons, ten Blueprints, and `bpc` generating attributes and intrinsics from TableGen |
| [M3](https://github.com/tamnd/llvm-internals/issues/12) | Analyses and the pass manager | 5 | Nine lessons, eight Blueprints, the invalidation grader |
| [M4](https://github.com/tamnd/llvm-internals/issues/13) | Transforms | 8 | Fourteen lessons, ten pass Blueprints, and the Alive2 CI job running every refinement obligation. **Stopping point.** |
| [M5](https://github.com/tamnd/llvm-internals/issues/14) | Correctness | 4 | Six lessons on the verifier, reduction, lit and Alive2 |
| [M6](https://github.com/tamnd/llvm-internals/issues/15) | Version bump rehearsal | 4 | No new lessons. Bump to LLVM 24 on purpose and measure what it cost |
| [M7](https://github.com/tamnd/llvm-internals/issues/16) | SelectionDAG | 6 | Nine lessons, three codegen Blueprints, the DAG viewer |
| [M8](https://github.com/tamnd/llvm-internals/issues/17) | MIR and below | 7 | Ten lessons, five Blueprints, register allocation and the MC layer |
| [M9](https://github.com/tamnd/llvm-internals/issues/18) | GlobalISel and TableGen | 7 | Fourteen lessons, and `gen_td` generating target Blueprints from `-dump-json` |
| [M10](https://github.com/tamnd/llvm-internals/issues/19) | The rest of the toolchain | 5 | Eight lessons: Clang, MLIR, lld, LTO, ORC, sanitizers, PGO |
| [M11](https://github.com/tamnd/llvm-internals/issues/20) | The Surgeon | 5 | Six in tree modification lessons, ending in a real pull request. **Stopping point.** |
| [M12](https://github.com/tamnd/llvm-internals/issues/21) | Capstones | 12 | All three tracks with skeletons, graders, scorecards and reference solutions |

## Why the order is what it is

The IR comes before the front end because you do not need to know how Clang produced the `.ll` in order to read the `.ll`, and starting at the IR means the first lesson that matters needs no parsing knowledge at all.

Analyses come before transforms because every interesting transform is gated on an analysis, and somebody who meets LICM before dominance has learned a magic trick rather than a mechanism.

Correctness comes before the backend rather than at the end. Once you have watched a solver hand you a counterexample you stop trusting your own reasoning about `poison`, and that is the correct state of mind for everything after it.

TableGen comes late and is taught backwards. You write a TableGen backend in twenty lines of Python over the JSON dump before you ever read a C++ one, because by Part IX you have already used six things TableGen generated and the question "what produced this table" is one you already have.

M6 is scheduled rather than reactive. LLVM ships twice a year and the 24.x branch is expected in late January 2027, so a major version bump lands mid project no matter when the project starts. The point of doing it deliberately is to measure what it costs while the corpus is still small enough to fix.

## What is deliberately not covered

Flang, LLDB internals, BOLT, Polly, libc++, most of compiler-rt, the full MLIR story, and microarchitecture specific tuning. Each of those is at least a part on its own and several are their own project. The first lesson says so on the first page rather than letting you find out in month three.
