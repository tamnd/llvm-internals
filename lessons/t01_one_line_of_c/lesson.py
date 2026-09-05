# ---
# id: t01_one_line_of_c
# title: The optimiser is a separate program, and it can be told no
# question: I compiled with -O0 and then ran the optimiser on it, so why is my code still slow?
# part: I
# env: E0
# minutes: 30
# ---

# %% [markdown]
# # The optimiser is a separate program, and it can be told no
#
# One line of C. Add two integers and return the answer.
#
# At `-O0` clang turns it into eight instructions that spend most of their time putting the arguments in memory and taking them out again. At `-O2` it is two. That much is not surprising, and most people have a rough mental model that covers it: the optimiser was switched off, then it was switched on.
#
# So take the eight instruction version, hand it to the optimiser on its own, and ask for the whole `-O2` pipeline. It comes back with eight instructions.
#
# The IR is carrying a note that says do not touch this function, clang wrote the note, and until you find it nothing you do to that file will change anything.

# %% id=source
# One line of C, and the pinned clang, with no help from the toolkit.
SOURCE = "int add(int a, int b) { return a + b; }\n"

def straight_from_clang(level):
    """No irx.compile_c here on purpose. This lesson is about what clang does
    when nobody has arranged anything for you, and compile_c arranges one
    thing. We get to it at the end."""
    text = irx.run("clang", "-x", "c", level, "-S", "-emit-llvm", "-o", "-", "-",
                   stdin=SOURCE).stdout
    return irx.Module.from_ll(text, name=f"clang {level}")


o0 = straight_from_clang("-O0")
o2 = straight_from_clang("-O2")

for module in (o0, o2):
    print(f"===== {module.name} " + "=" * 30)
    print(module.body("add"))
    print()

# %% [markdown]
# ## The front end is not trying to be clever
#
# The `-O0` version stores both arguments into stack slots it allocated a line earlier, loads them straight back out, and only then adds them. Nothing in between could have changed them. Every one of those six memory instructions is dead on arrival.
#
# This is not clang being bad at its job. It is clang doing the simplest correct thing, on purpose, because the simplest correct thing is the one you can write a front end for without also writing an optimiser inside it. Locals become stack slots, reads become loads, writes become stores, and the result is IR that is plainly right and plainly wasteful.
#
# Making it fast is somebody else's job. That somebody is a different program.

# %% id=two_programs
# clang emitted the IR. opt is what transforms it, and llc is what turns it into
# machine code. Three programs, and the file passed between them is the point.
for tool in ("clang", "opt", "llc"):
    print(f"{tool:>6}  {irx.path_to(tool)}")

# %% [markdown]
# ## Run the optimiser on it by hand
#
# We have the `-O0` IR as text. `opt` is the optimiser as a standalone program, `-passes=default<O2>` asks for the exact pipeline `clang -O2` would have run, and `-S` says keep it readable.
#
# The prediction almost everybody makes here is that this reproduces the two instruction version, because it is the same pipeline over the same code.

# %% id=opt_does_nothing
after = o0.opt("default<O2>", name="after opt -O2")

print("instructions before:", len(o0.instructions("add")))
print("       after -O2   :", len(after.instructions("add")))
print()
print(after.body("add"))

# %% [markdown]
# ## Nothing happened
#
# Same eight instructions. The pipeline ran, every pass in it got its turn, and the function came out the other side untouched.
#
# It is worth being clear that `opt` did not fail and did not quietly do nothing. It walked the whole `-O2` pipeline, in order, the same one `clang -O2` uses. Something stopped every pass in it from touching this function.
#
# The reason is written in the file, a little way below the code.

# %% id=find_the_note
# Attributes hang off the function by number. `#0` on the define line points at
# an attribute group at the bottom of the module.
for line in o0.lines:
    if line.startswith("define") or line.startswith("attributes #0"):
        print(line[:110] + ("..." if len(line) > 110 else ""))

print()
print("optnone present at -O0:", "optnone" in o0.text)
print("optnone present at -O2:", "optnone" in o2.text)

# %% [markdown]
# ## `optnone`
#
# `optnone` is an instruction to the optimiser, stored in the IR, and it means exactly what it looks like.
#
# It is worth being precise about who obeys it, because the obvious guess is wrong. Individual passes do not each check for `optnone`. The check lives once, in the pass manager's instrumentation layer, in a thing called `OptNoneInstrumentation`, and it is asked before every pass runs on every function. A pass that has never heard of `optnone` still gets skipped, because it is never given the chance to run.
#
# You can watch that happen. `-debug-pass-manager` makes the instrumentation say what it is doing.

# %% id=watch_the_skips
skipped = irx.run("opt", "-passes=default<O2>", "-debug-pass-manager", "-S", "-",
                  stdin=o0.text).stderr

lines = [line for line in skipped.splitlines() if "due to optnone" in line]
for line in lines[:6]:
    print(line)
print(f"... {len(lines)} passes skipped in total")

# %% [markdown]
# ## Seventy six of them
#
# Every pass in the `-O2` pipeline, named, one line each, refused before it started. `SROAPass` is in that list, and it is the one that would have turned the stack slots into registers.
#
# `optnone` also travels with `noinline`, and not by convention. The IR verifier rejects a module that has one without the other, with the message `Attribute 'optnone' requires 'noinline'!`. The reasoning is that a function nobody may optimise is also one nobody may paste into a caller, because inlining it would drop its body into a context where the ban no longer applies.
#
# So `-O0` does not mean the optimiser did not run. It means clang wrote a note forbidding it, the note is still in the `.ll` file you saved, and it stays there no matter which tool picks the file up next.
#
# That is the part worth carrying forward. The IR is not only a program. It is a program plus a set of instructions about what may be done to it, and the second half is invisible until you go looking for it.

# %% id=strip_the_note
# Take the note away and change nothing else.
stripped = irx.Module.from_ll(
    o0.text.replace(" optnone", "").replace(" noinline", ""),
    name="optnone removed")
freed = stripped.opt("default<O2>", name="after opt -O2")

print(freed.body("add"))

# %% [markdown]
# ## Two instructions, from the pipeline that did nothing a moment ago
#
# Same `opt`, same `default<O2>`, same input code. The only edit was deleting two words from an attribute group, and the eight instructions collapsed to the two that `clang -O2` produced directly.
#
# The stack slots are gone because `SROA`, the pass named third in that skip list, noticed that those slots are only ever written and read inside one function and never have their address escape, so they can be registers instead. Once they are registers the loads and stores have nothing left to move. The pass was in the pipeline the whole time and was being turned away at the door.

# %% id=the_toolkit_flag
# Which is why compile_c does not give you the default.
from_toolkit = irx.compile_c(SOURCE)

print("optnone in irx.compile_c output:", "optnone" in from_toolkit.text)
print()
print(from_toolkit.opt("sroa").body("add"))

# %% [markdown]
# ## What to keep
#
# `irx.compile_c` passes `-Xclang -disable-O0-optnone` on your behalf. Every lesson after this one uses it, and every lesson after this one therefore gets `-O0` IR that you can actually run passes on. It is worth knowing that this is a deliberate departure from what the compiler does by default, because if you compile something yourself with plain `clang -O0` and then wonder why your pass does nothing, this is the answer, and it costs people an afternoon.
#
# The three things to keep:
#
# The front end emits deliberately naive IR. Stack slots and redundant loads are the normal output of a correct front end, not a sign that something went wrong.
#
# The optimiser is a separate program reading a file. You can run it yourself, on IR from anywhere, as many times as you like, in any order.
#
# The file it reads carries instructions about itself. `optnone` is the bluntest one and there are many more. Attributes are how the front end tells the optimiser what it is allowed to assume, and most of the surprising behaviour in a pipeline comes from that channel rather than from the code.
#
# Next: what the rest of that file actually says.
