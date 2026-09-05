# Contributing

The whole point of this project is that a reader can check everything, so most of the rules below exist to keep that true. Read them before writing a lesson, because a pull request that ignores them gets sent back and that wastes your afternoon as much as ours.

## The pin

Everything is written against `llvmorg-23.1.0`. Every citation looks like this:

```
llvm/lib/Transforms/InstCombine/InstCombineCompares.cpp:1247@llvmorg-23.1.0
```

CI resolves every one of them daily and hashes the surrounding lines, so a citation that stops pointing at what it pointed at opens an issue naming the lesson and every Blueprint section that depended on it.

## Lessons are Python, notebooks are build output

You edit `lessons/<id>/lesson.py`, which is percent format Python with one cell per `# %%`. `build.py` turns it into `notebooks/<id>/lesson.ipynb`. The notebook is committed, because Colab can only open a file that exists at a URL, but it is generated and it is marked as generated so it never shows up in a diff.

This means two things in practice. Notebook JSON is never reviewed, so review stays sane. And hidden execution state is unrepresentable, because cells are emitted in source order with no execution counts, which matters when the material you are teaching is partly about hidden state.

Prototype in Colab as much as you like, that is where you notice the bug, then port the fix back into the `.py`. Editing a generated notebook loses the change on the next build and `build.py check` catches you either way.

```
python build.py new x07_gvn        # scaffold
python build.py notebooks          # regenerate
python build.py run --only x07_gvn # execute headlessly
python build.py check              # what CI runs
```

A pre commit hook rebuilds notebooks so a committed `.ipynb` is never out of sync. The whole format, header keys and cell options included, is in [docs/lesson-format.md](docs/lesson-format.md).

## Prose rules

These are checked by `tools/prosecheck.py` where they can be, and by a human where they cannot. It reads every `.md` file and the markdown cells of every `lessons/<id>/lesson.py`, so the rules apply to lesson prose in exactly the same way they apply to this page. Code cells are code and it leaves them alone.

**No em dashes.** Use a comma, a full stop, or brackets. The checker rejects them.

**No "simply", "just", "obviously", "of course" or "trivially".** <!-- prose-ok --> Somebody will find every single thing in this material hard and each of those words is a small insult to them.

**Never write a number from memory.** If a paragraph says a pass ran forty times, that number is interpolated from generated JSON, not typed.

**Date anything that is in motion.** Any claim about what is default, what is experimental, what is in progress, or what a target supports, carries a date and the command that establishes it. Not "GlobalISel is the default for AArch64 at -O0" but "as of `llvmorg-23.1.0`, checked 2 September 2026, GlobalISel is the default for AArch64 at -O0, and here is the command that tells you what your build does". LLVM's own docs have been burned by this repeatedly and the checker flags status vocabulary in a paragraph with no date.

**Be exact about names.** `InstCombinePass` is not `instcombine` is not `InstCombine`. Getting it wrong costs a reader an hour when they try to grep.

**Quote IR exactly as `llvm-dis` prints it.** Never reformat, never prettify, never renumber. A reader has to be able to copy what they see into a file and run it. Elide with a marker if it is long, do not tidy.

**Never quote a generated `.inc` as if it were source.** Show it next to the TableGen record it came from and say which is which. This is the single most common way LLVM material confuses people.

**Use "they" for people** whose pronouns you do not know.

## Limits

| | Cap |
|---|---|
| Hook | 150 words |
| Tour | 1500 words |
| Whole lesson prose | 2500 words |
| Animation | 90 seconds |
| Cells in the E0 experiment | 25 |
| A single cell | 40 lines |
| Blueprint | no cap |

A lesson that wants to be longer is two lessons. There is no exception for the interesting ones, because "this one is special" is how caps die.

The cell cap is about what a reader has to read. A cell built with `include=` is a grader they call and never read, so it is reviewed as the module it comes from, with tests, and it is not measured against this cap. That is the only carve out, and it is here because the alternative is a grader made worse at its job to fit inside a box nobody was going to open.

## Claims

Every factual claim in a lesson is an entry in `claims.yaml` with an evidence pointer, a citation and a confidence. At most three claims per lesson may be `inferred`, meaning reasoned from the source rather than observed. Every performance claim has to be measured on E1 with the machine and the variance stated, and there are no exceptions to that one. A wall clock number measured on two contended Colab vCPUs is not evidence of anything.

`tools/refcheck.py` is what enforces the parts of that a machine can see, and it runs in CI beside `prosecheck`:

```
python tools/refcheck.py                       # every lesson, no LLVM checkout needed
python tools/refcheck.py --llvm-src ../llvm-project   # and resolve every citation
python tools/refcheck.py --ledger              # regenerate docs/claims.md
```

Without a source tree it checks the shape: every claim has the four required fields, a `cited` claim actually cites something, every cell an evidence pointer names exists in the lesson, every `@llvmorg-` suffix matches `docs/pin.json`, ids are unique, and the `inferred` budget holds. With `--llvm-src` it also opens each cited file and checks the line range is inside it, which is the check that catches a citation drifting after a pin bump.

[docs/claims.md](docs/claims.md) is every claim in the repository in one table, generated by `--ledger`. It is build output. Edit `claims.yaml` and regenerate; a stale ledger fails the test suite.

## Alive2

If a lesson uses Alive2, it says every time that the verification is bounded. Loops are unrolled to a fixed depth, so "no counterexample found" is strong evidence and is not a proof. Describing an Alive2 result as a proof gets a pull request rejected, because overselling the one tool that makes this project's central claim work would be the exact failure the project exists to fix.

## Boss fights

Every boss fight has a grader at `lessons/<id>/grade.py` that exits 0 or 1. The failure message names the input. "Your fold turns f(x=0x80000000) from -2147483648 into poison" teaches something. "Incorrect" does not. Where Alive2 can grade the task it should, because it produces exactly that kind of message for inputs nobody thought to test.

## Review

Every lesson needs two reviewers, one at or below the target reader's level and one at or above LLVM contributor level.

The beginner reviewer answers: where did you get lost, what word was used before it was defined, what did you have to read twice, and could you do the boss fight.

The expert reviewer answers: is anything wrong, is anything true of an older LLVM, is any citation misleading, is any status claim undated, and would this pass code review upstream.

The beginner review is the one that gets skipped under deadline pressure and it must not be.

## Licence

By contributing you agree that code is licensed Apache-2.0 with the LLVM exception and content is CC BY 4.0. The licence matches upstream on purpose so that a pass or a test written here can be sent to `llvm-project` verbatim.
