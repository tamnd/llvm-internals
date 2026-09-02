# irx

The small amount of Python that sits between a lesson and a real LLVM.

Every lesson in this repository starts the same way. A cell installs this package, calls `irx.bootstrap()`, and prints one line saying which LLVM it got and where from. After that the lesson is free to compile things, run passes and look at the output, and none of it has to care whether it is running on Colab, on your laptop, or in a browser tab.

## What it does and does not do

`irx` never does LLVM's job. It does not parse IR, it does not model a pass, and it does not reimplement anything you could ask a binary for. It finds a pinned toolchain, runs it, and renders what came back in a form that reads well in a notebook.

That restraint is the whole point. When upstream changes a pass, the lesson output changes with it and the material stays true. A helper that reimplemented `instcombine` in Python would be a helper that is confidently wrong two releases from now, and nobody would notice until a reader learned something false.

So the list of things in here is short:

- find a pinned LLVM, or fetch one, and refuse the wrong version
- run a tool and turn a failure into a message a person can act on
- hold IR as text, and show a before and after so the change is the thing you notice

## The pin

Everything is written against one tag, which lives in [`irx/pin.json`](irx/pin.json) and is a copy of [`docs/pin.json`](../docs/pin.json) at the top of the repository. A test keeps the two in sync.

Names, defaults and pass behaviour differ between LLVM major versions. A lesson run against the wrong one is not broken in any way you would see, it quietly teaches you something that is not true, so `irx` would rather stop than let that happen.

## Getting a toolchain

`irx.bootstrap()` tries a list of sources in order and stops at the first one that answers with the right major version.

![How irx.bootstrap finds a pinned LLVM](../docs/diagrams/bootstrap.svg)

The interesting rule is what happens on a version mismatch. If the LLVM already on your PATH is the wrong one, that is not treated as a failure, it goes back to the list and keeps going down, and usually ends up downloading the pinned tarball. The one case that does stop is `IRX_LLVM_BIN` pointing at the wrong version, because somebody set that by hand and being ignored would be worse than being told.

Two environment variables are worth knowing:

| Variable | What it does |
| --- | --- |
| `IRX_LLVM_BIN` | Use this `bin` directory and nothing else. Wins over every other source. |
| `IRX_ALLOW_VERSION_SKEW` | Set to `1` to run against a different major version anyway. Expect some lessons to disagree with what you see. |
| `IRX_CACHE` | Where the fetched tarball is unpacked. Defaults to `~/.cache/irx`. |

## Using it

```python
import irx
irx.bootstrap()
```

```
irx: LLVM 23.1.0 from the pinned tarball, ready in 21.4s
irx: E0, Colab. Real LLVM binaries, no build tree, so no in tree modification.
```

A module comes from C, from C++, from a file, or from IR you typed yourself:

```python
m = irx.Module.from_c("int f(int x) { int y = x + x; return y * 2; }")
m          # renders as coloured IR in the cell
```

Running a pipeline gives you a new module and leaves the original alone, so both can be on screen at once:

```python
after = m.opt("mem2reg,instcombine")
m.diff(after)
```

```diff
@@ -6,15 +6,7 @@
 define i32 @f(i32 noundef %x) #0 {
 entry:
-  %x.addr = alloca i32, align 4
-  %y = alloca i32, align 4
-  store i32 %x, ptr %x.addr, align 4
-  %0 = load i32, ptr %x.addr, align 4
-  %1 = load i32, ptr %x.addr, align 4
-  %add = add nsw i32 %0, %1
-  store i32 %add, ptr %y, align 4
-  %2 = load i32, ptr %y, align 4
-  %mul = mul nsw i32 %2, 2
+  %mul = shl nsw i32 %x, 2
   ret i32 %mul
 }
```

That diff is nine instructions turning into one, and it is the reason `diff` exists at all. An after picture on its own does not show you that.

## When a tool fails

The default subprocess failure is `CalledProcessError: returned non-zero exit status 1`, which tells a reader who has never run `opt` before absolutely nothing. `irx` raises `ToolError` instead, with the command, the real stderr, and where possible a sentence about what to do:

```
opt exited 1

  $ /usr/lib/llvm-23/bin/opt -passes=instcombin -S -

  opt: unknown pass name 'instcombin'

That pass name is not in this build. Pass names are case sensitive and
several changed spelling between releases. `irx.passes()` lists what
this exact binary accepts.
```

Three failures get a hint like that, chosen because they are the three that people actually hit: a pass name that does not exist, a parse error in hand written IR, and a pass plugin path that points at nothing.

## Notes on some choices

**No runtime dependencies.** This gets pip installed inside a Colab cell before anything else happens, so every dependency is time a reader spends watching a progress bar, and every version pin is a chance to argue with whatever Colab already has.

**`-fno-discard-value-names` and `-Xclang -disable-O0-optnone` are passed for you.** The first is the difference between reading `%counter` and reading `%7`. The second matters more: without it clang marks every function `optnone` at `-O0`, so every pass you run does nothing at all, and working out why is a bad first hour.

**The `; ModuleID` line is rewritten.** It holds the name of the file the tool read, so clang writes `-` and `opt` writes `<stdin>`. Left alone it would be the first hunk of every before and after in the whole course, and it means nothing.

**Only known tools can be run.** `irx.run` takes a bare name like `opt` and resolves it against the pinned toolchain, and a name that is not on the allowed list is refused. The stripped tarball does not carry every LLVM binary, and finding that out from a clear error beats finding it out from a subtly different answer.

## Tests

```
cd toolkit
python3 -m unittest discover -s tests -t .
```

Two kinds of test live there. The ones that do not need a compiler run anywhere, including on a CI runner with no LLVM on it. The ones that do run the real binaries and skip with a reason when there is no pinned toolchain, because a test that quietly passes against the wrong LLVM is worse than one that says it did not run.

## Licence

Apache-2.0 WITH LLVM-exception, matching upstream.
