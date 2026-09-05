# ---
# id: t02_first_look_at_the_ir
# title: What a .ll file says, and two things it deliberately does not
# question: I opened a .ll file and I do not know what I am looking at
# part: I
# env: E0
# minutes: 30
# needs: [t01_one_line_of_c]
# ---

# %% [markdown]
# # What a `.ll` file says, and two things it deliberately does not
#
# T01 left you holding a file that gets passed between programs. This lesson is about reading it.
#
# Most of it is learnable in an afternoon. There are functions, the functions have blocks, the blocks have instructions, and the instructions have types. That part behaves the way you expect.
#
# The two parts that do not behave the way you expect are the two this lesson spends its time on, because they are where people who already know C get stuck. The first is that a pointer in LLVM IR has no idea what it points at, and that is not an omission. The second is that the register names you are reading, `%0`, `%1`, `%2`, are not stored anywhere. They are generated when the file is printed, by a counter, and knowing how that counter works turns an error message you will definitely hit from baffling into obvious.

# %% id=whole_module
# A small C file with one of everything, so the module has something in each
# section rather than being nothing but a define.
SOURCE = """
#include <stddef.h>

int counter;
static const char *NAME = "widget";

extern int external_thing(int);

const char *name(void) { return NAME; }

int bump(int by) {
  counter += by;
  return external_thing(counter);
}
"""

mod = irx.compile_c(SOURCE, name="bump.ll")

# Every top level line, sorted into the five things a module is made of.
KINDS = {
    "target ": "target description",
    "source_filename": "target description",
    "@": "global variable",
    "define": "function with a body",
    "declare": "function without one",
    "attributes": "attribute group",
    "!": "metadata",
}

for line in mod.lines:
    if not line or line.startswith((" ", ";", "}")) or line.endswith(":"):
        continue
    kind = next((v for k, v in KINDS.items() if line.startswith(k)), "?")
    print(f"{kind:<24} {line[:64]}")

# %% [markdown]
# ## A module is a short list of top level things
#
# That is the whole outer structure. A couple of lines describing the machine the IR was written for, some globals, some functions with bodies, some functions without, then attribute groups and metadata hanging off the bottom for anything that needs to be said about the things above.
#
# `@` starts a global, `%` starts something local to a function, and `!` starts metadata. Those three sigils tell you which namespace a name lives in, and they are the fastest way to orient yourself in a file you have never seen.
#
# Now inside a function.

# %% id=inside_a_function
print(mod.body("bump"))

# %% [markdown]
# ## Blocks, and the rule about the last instruction
#
# A function is a list of basic blocks. A basic block is a label, then some instructions, then exactly one instruction that says where to go next. That last one is called a terminator, and `ret` is the one above.
#
# The rule is stricter than it sounds. Not "usually ends with a terminator". Every block has exactly one terminator, it is the last instruction, and no other instruction in the block may be one. A block you can fall out of the bottom of is not something LLVM will accept. T03 is about what happens when there is more than one block and the terminators start branching.
#
# So far so ordinary. Here is the first part that is not.

# %% id=four_pointers
# Four C functions. Four completely different pointer types, one of which is a
# pointer to a 128 byte struct and one of which is a pointer to code.
POINTERS = """
struct big { double a[16]; };

int         *pi(int *p)              { return p; }
char        *pc(char *p)             { return p; }
struct big  *pb(struct big *p)       { return p; }
int (*pf(int (*f)(void)))(void)      { return f; }
"""

for line in irx.compile_c(POINTERS).lines:
    if line.startswith("define"):
        # dso_local is there on Linux and not on macOS and means nothing here.
        print(line.replace("dso_local ", "").rstrip(" {"))

# %% [markdown]
# ## The pointer type does not have a pointee
#
# Four different C types went in. One type came out: `ptr`. Not `i32*`, not `i8*`, not `%struct.big*`. There is no such thing any more. LangRef spends its entire section on the pointer type describing address spaces and representation width and never once mentions what is on the other end, because nothing is recorded about what is on the other end.
#
# If you have read anything about LLVM written before about 2023, this is the single biggest thing that changed. Typed pointers were removed. The old syntax still parses, so old material keeps working well enough to mislead you rather than failing where you would notice.

# %% id=old_syntax
# Write it the old way, then make LLVM read it and print it back. `verify` is a
# pass that changes nothing, so the only thing between these two is the parser
# and the printer, which is exactly what we want to look at.
OLD = """
define i32 @deref(i32* %p) {
  %v = load i32, i32* %p
  ret i32 %v
}
"""

written = irx.Module.from_ll(OLD, name="what we typed")
print(written.body("deref"))
print("--- after LLVM has read it and printed it back")
print(written.opt("verify").body("deref"))

# %% [markdown]
# ## Written `i32*`, stored `ptr`
#
# The parser accepts `i32*` and throws the `i32` away. What you typed was never a type LLVM has; it was spelling that the parser translates and forgets.
#
# So if the pointer does not carry the type, where did the type go? Onto the instruction. `load i32, ptr %p` says load, an `i32`, from `%p`. The width of the access is a property of the access, which is the only place it was ever really true. A pointer gets loaded through as an `i32` in one place and memcpy'd as bytes in another, and there was never a single right answer to hang on the pointer.
#
# The old design pretended there was, and the pretence cost. Any time the front end needed to use a pointer at a different type it had to emit a `bitcast` that changed nothing at all, purely to satisfy the type system, and every pass in LLVM had to see through those casts to do its job. Deleting the pointee type deleted that entire category of instruction and the entire category of bug where a pass forgot to look through one.
#
# Here is the part that follows from it and catches people.

# %% id=nothing_checks_it
# Real IR from real C: a function that takes an int * and reads four bytes.
deref = irx.compile_c("int deref(int *p) { return *p; }")
print(deref.body("deref"))

# There are two loads and they read different types through the same one. The
# first reads a pointer out of the stack slot holding the argument, the second
# reads an i32 through that pointer.
#
# Change the four byte load to read eight bytes, and change nothing else.
widened = irx.Module.from_ll(
    deref.text.replace("load i32", "load i64")   # the access
              .replace("ret i32", "ret i64")     # what we hand back
              .replace("i32 @deref", "i64 @deref"),  # and the declared return type
    name="widened")

print("verifier accepts the widened load:", widened.is_valid())
print(widened.body("deref"))

# %% [markdown]
# ## Nothing in the file disagreed with us
#
# The C said `int *`. We made it read eight bytes through that pointer and the verifier had nothing to say, because there is nothing left in the file that remembers the argument was an `int *`. The `i32` we deleted was the only record, and it was a record of one access, not of the pointer.
#
# This is worth sitting with, because it changes what "well typed IR" means. The verifier will catch you adding an `i32` to a `float`. It cannot catch you reading the wrong width from a pointer, and it is not trying to. Reading eight bytes from a four byte object is undefined behaviour, and undefined behaviour is not a type error. It is a promise you made and broke, and LLVM finds out about it much later, if ever, in a way X04 is entirely about.
#
# The same logic runs through `getelementptr`, the address arithmetic instruction. It takes a type, but the type is there to give it a stride, not to describe memory.

# %% id=gep_is_arithmetic
# One line of C, compiled twice.
INDEX = "int at(int *xs, int i) { return xs[i]; }"

for level in ("-O0", "-O1"):
    line = next(ln.strip() for ln in irx.compile_c(INDEX, opt=level).lines
                if "getelementptr" in ln)
    print(f"{level}  {line}")

# %% [markdown]
# ## Same address, two different types
#
# At `-O0` the front end writes the GEP over `i32`, which strides four bytes per index. Somewhere in the `-O1` pipeline a pass rewrote it over `[4 x i8]`, which also strides four bytes per index. Same pointer in, same address out, and the type on the instruction changed anyway, because the type was only ever there to multiply the index by a stride.
#
# When you read a GEP, read it as arithmetic. The type is the unit.
#
# That is the first of the two things the file does not say. The second is smaller and you will hit it sooner.

# %% id=who_names_the_registers
# The same function twice. The only difference is a label on the entry block.
WITHOUT = "define i32 @f(i32 %a) {\n  %5 = add i32 %a, 1\n  ret i32 %5\n}\n"
WITH = "define i32 @f(i32 %a) {\nentry:\n  %99 = add i32 %a, 1\n  ret i32 %99\n}\n"

for wrote, label, text in (("%5", "no label on the entry block", WITHOUT),
                           ("%99", "entry: on the entry block", WITH)):
    print(f"--- {label}, and we wrote {wrote}")
    print(irx.Module.from_ll(text).opt("verify").body("f"))

# %% [markdown]
# ## Two surprises in six lines
#
# We wrote `%5` and got `%1`. We wrote `%99` and got `%0`. The number you type is not kept. And the two functions, which differ only by a label that names a block, number their instruction differently.
#
# Both fall out of one function, `SlotTracker::processFunction` in `AsmWriter.cpp`, which is the thing that decides what to print. It walks one counter over three lists in order: unnamed arguments, then for each block, the block itself if it has no name, then each instruction that has no name and does not return void.
#
# Read that against the two cases. The first function has a named argument, so nothing is consumed there. Its entry block has no label, so the block takes `%0`, and the instruction gets `%1`. The second function's block is called `entry`, so it takes nothing, and the instruction gets `%0`. A label you added for readability moved every number in the function.
#
# The clause about void is the other half of it.

# %% id=void_takes_nothing
# Numbered as if every instruction got one: 0, then 2, then 4. The parser allows
# it, because each is at least as large as the one it was expecting.
STORES = """
define i32 @f(i32 %a) {
entry:
  %0 = alloca i32
  store i32 %a, ptr %0
  %2 = add i32 %a, 1
  store i32 %2, ptr %0
  %4 = load i32, ptr %0
  ret i32 %4
}
"""
print(irx.Module.from_ll(STORES).opt("verify").body("f"))

# %% [markdown]
# ## Stores are not counted
#
# We numbered by line and got back `%0`, `%1`, `%2`. Seven instructions, three numbers. `store` and `ret` produce no value, so they get no slot and the counter walks past them.
#
# This is why the numbering in real `-O0` output looks like it has holes in it. It does not; you are looking at a count of values, not a count of lines.
#
# Now the error message. The parser lets you write any number that is at least as large as the next one it expects, and renumbers on the way out, which is why `%99` and `%4` both worked. Write one that is too small and it stops.

# %% id=the_error
# Unnamed arguments take slots too. Two of them here, so they are %0 and %1, and
# then the unnamed entry block is %2, which leaves %3 for the first instruction.
TOO_SMALL = """
define i32 @f(i32, i32) {
  %2 = add i32 %0, %1
  ret i32 %2
}
"""
print(irx.run("opt", "-S", "-", stdin=TOO_SMALL, check=False).stderr.strip())

# %% [markdown]
# ## `instruction expected to be numbered '%3' or greater`
#
# The first time you see that, having carefully counted your two arguments and written `%2`, it reads like the parser cannot count. It counted the entry block. Two unnamed arguments take `%0` and `%1`, the block with no label takes `%2`, and the first instruction you can write is `%3`. Give the block a name and `%2` is correct again.
#
# Both halves of that message come from the same place as the printing, which is the point. The numbers are not names. They are positions in a list that the printer walks, and the parser is checking you against the same walk.
#
# ## What to keep
#
# A module is target lines, globals, functions with and without bodies, then attributes and metadata. `@` is global, `%` is local, `!` is metadata.
#
# A function is blocks. A block is a label, instructions, and exactly one terminator, which is the last instruction and cannot appear anywhere else.
#
# A pointer is `ptr` and nothing more. The type belongs to the access, not to the pointer, and no part of LLVM is checking that your accesses agree with each other. The type on a `getelementptr` is a stride.
#
# Register numbers are assigned when the file is printed, by one counter over unnamed arguments and unnamed blocks and value producing instructions. They are not stored, they change when you add a label, and the parser checks you against the same counter.
#
# Next: more than one block, and how a value gets from one of them into another.
