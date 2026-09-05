# ---
# id: t09_the_machine_in_the_ir
# title: The two lines at the top of the file, and the pass they add
# question: Why do my numbers not match the ones in the book?
# part: I
# env: E0
# minutes: 35
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string, t06_who_says_it_is_stale, t07_which_one_did_it, t08_o2_twice]
# ---

# %% [markdown]
# # The two lines at the top of the file, and the pass they add
#
# T05 counted the entries in `default<O2>` and got a hundred and twenty. If you ran that on a Linux x86-64 box you got a hundred and nineteen, and if you compared the two strings character by character you got 4791 against 4770. T07 counted pass runs and got 192 against 191. T08 got 111 against 110. Every lesson since T05 has had two numbers in its claims file and a note saying which machine produced which.
#
# This lesson is about that difference, and the answer is not what it looks like. It is not the operating system, and it is not that one machine has a newer LLVM. Both numbers can be produced on one machine, one after the other, in the next few cells.
#
# Start with the two lines T02 told you to look past.

# %% id=two_headers
SRC = "int f(int n) { int t = 0; for (int i = 0; i < n; i++) t += i; return t; }"

TARGETS = ["x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu",
           "thumbv7m-none-eabi", "wasm32-unknown-unknown"]

built = {t: irx.compile_c(SRC, target=t, name="f") for t in TARGETS}


def header(module, what):
    """The target datalayout or target triple line, without the ceremony."""
    prefix = f"target {what} = "
    line = next(ln for ln in module.lines if ln.startswith(prefix))
    return line[len(prefix):].strip('"')


for t in TARGETS:
    print(f"{t:<28} {header(built[t], 'datalayout')}")

# %% [markdown]
# ## The front end has already decided
#
# One line of C, four files, four different data layout strings. They are not decoration. `e` is little endian, `p:32:32` is a pointer that is 32 bits wide and 32 bit aligned, `i64:64` is a 64 bit integer aligned to 64 bits, `S128` is the stack alignment, and `n32:64` lists the integer widths this machine is natively good at. The aarch64 one contains `i8:8:32`, meaning an `i8` must be aligned to 8 bits and would prefer 32.
#
# Nothing downstream re-derives any of this. It is a string in the module and every pass that needs to know how big a pointer is reads it from there.
#
# You can watch it decide sizes.

# %% id=what_the_layout_says
SIZES = """
struct S { char c; long l; };
unsigned long sizes(void) {
  return sizeof(long) * 1000000 + sizeof(void *) * 10000
       + sizeof(struct S) * 100 + _Alignof(struct S);
}
long double_it(long x) { return x + x; }
"""

for t in TARGETS:
    m = irx.compile_c(SIZES, target=t, name="s").opt("mem2reg,instcombine")
    packed = int(next(ln for ln in m.body("sizes").splitlines() if " ret " in ln).split()[-1])
    print(f"{t:<28} long {packed // 1000000}  ptr {packed // 10000 % 100}  "
          f"struct S {packed // 100 % 100}  aligned {packed % 100}  "
          f"{m.body('double_it').splitlines()[0].split('@')[0].split()[-1]}")

# %% [markdown]
# ## `long` is not a type in the IR
#
# The compiler folded all four `sizeof`s to constants before anything in this book got to look at the function, so those numbers came out of the front end and not out of a pass. On the first two targets a `long` is eight bytes, on the last two it is four, and the struct is padded accordingly.
#
# The last column is the point. `double_it` takes a `long` and returns a `long` in every one of these files, and the IR says `i64` in two of them and `i32` in the other two. There is no `long` in the IR. There is no `int`, no `unsigned`, no `size_t`. By the time you are reading `.ll`, every C type has already been resolved to a width for one particular machine, and the file cannot be moved to another one.
#
# The same thing has happened to the calling convention.

# %% id=the_abi_is_in_the_signature
ABI = """
struct Pair { int a; int b; };
struct Big { double x[4]; };
int take(struct Pair p) { return p.a + p.b; }
double takebig(struct Big b) { return b.x[0]; }
"""

for t in TARGETS:
    m = irx.compile_c(ABI, target=t, name="abi")
    for fn in ("take", "takebig"):
        signature = m.body(fn).splitlines()[0].split(" @")[1].rstrip(" {")
        print(f"{t:<28} {signature}")
    print()

# %% [markdown]
# ## Four answers to "how do I pass a struct"
#
# The C is identical and every signature is different. A two `int` struct becomes one `i64` on x86-64 and aarch64, because both of those put it in a single register. On thumb it becomes `[2 x i32]`, and on wasm it is not passed at all: the caller puts it in memory and passes a `ptr noundef byval`.
#
# The four `double`s go one way on aarch64, as `[4 x double]`, and another way on x86-64, where they go in memory. The `struct.Pair` and `struct.Big` types you wrote in C survive only where the argument is passed in memory, and everywhere else they have been dissolved into whatever shape the registers want.
#
# So the front end has baked in the sizes, the alignments, the endianness and the calling convention. All of that is settled before the first pass runs. The question this lesson exists to answer is whether anything is left for the target to decide *after* that.

# %% id=gate_target
irx.gate(
    "Two machines run `opt -passes=default<O2> -print-pipeline-passes` on the same LLVM "
    "release. One prints 120 entries and the other prints 119. What is the difference?",
    {
        "The module's target adds a pass": "And you can produce both numbers on one machine "
                                           "by changing one line of the file, which is the "
                                           "next cell.",
        "The two machines have different LLVM builds": "The obvious guess, and worth ruling "
                                                       "out first, but both numbers come out "
                                                       "of one binary here.",
        "One of them passed a flag": "No flag is involved. The same command line gives both "
                                     "answers.",
        "The pipeline is printed in a nondeterministic order": "It is not. Run it a thousand "
                                                               "times and you get the same "
                                                               "string, whichever one you get.",
    },
    answer="The module's target adds a pass",
    note="The pipeline is built after the target has had a say in it.",
)

# %% id=the_pipeline_is_not_portable
import re
from collections import Counter


def pipeline(text):
    """The default<O2> string opt would build for this module, and any complaint about it."""
    r = irx.run("opt", "-passes=default<O2>", "-print-pipeline-passes", "-disable-output",
                "-", stdin=text)
    return r.stdout.strip(), (r.stderr or "").strip()


def names(built_pipeline):
    """Every pass name in the string, however deeply nested."""
    return [n for n in re.split(r"[(),]", built_pipeline) if n]


strings, complaints = {}, {}
for t in TARGETS:
    strings[t], complaints[t] = pipeline(built[t].text)
    print(f"{t:<28} {strings[t].count(',') + 1} entries  {len(strings[t])} characters"
          f"{'  (opt has no backend for it)' if complaints[t] else ''}")

arm, x86 = strings["aarch64-unknown-linux-gnu"], strings["x86_64-unknown-linux-gnu"]
print()
print("only on aarch64:", sorted(Counter(names(arm)) - Counter(names(x86))))
print("only on x86-64: ", sorted(Counter(names(x86)) - Counter(names(arm))))

# %% [markdown]
# ## One pass, and it is `loop-idiom-vectorize`
#
# There are your two numbers, both from the binary you are running right now. Three of the four targets agree on 119 entries and 4770 characters. Aarch64 has one more entry and 21 more characters, and 21 is the length of `loop-idiom-vectorize` plus the comma.
#
# The subtraction is worth doing rather than eyeballing a diff, because the entries are nested and a difference could have been a reordering, or the same pass appearing a ninth time instead of an eighth. It is neither. One name appears once on one target and nowhere on the other, and nothing goes the other way.
#
# If a row said `opt has no backend for it`, that is the other thing worth knowing. `opt` only reaches a target's opinion if that target was built into your `opt`, and a build with a reduced target list prints `failed to create target machine` on stderr for the ones it does not have and carries on with the generic pipeline. The min bundle this book ships is such a build. A 119 there does not mean the target has nothing to add; it means nobody asked it.
#
# Now, which of those two header lines caused it? The data layout knows the sizes, the triple names the machine. Change one and not the other.

# %% id=the_triple_alone
lie = built["x86_64-unknown-linux-gnu"].text.replace(
    'target triple = "x86_64-unknown-linux-gnu"',
    'target triple = "aarch64-unknown-linux-gnu"')
none = "\n".join(ln for ln in built["x86_64-unknown-linux-gnu"].lines
                 if not ln.startswith("target "))

for label, text in (("as clang wrote it", built["x86_64-unknown-linux-gnu"].text),
                    ("x86-64 layout, aarch64 triple", lie),
                    ("no target lines at all", none)):
    p, _ = pipeline(text)
    print(f"{label:<30} {p.count(',') + 1} entries  "
          f"loop-idiom-vectorize: {'loop-idiom-vectorize' in p}")

# %% [markdown]
# ## The triple, by itself
#
# A file whose sizes and alignments are x86-64's, whose only aarch64 thing is a string in a header line, gets the aarch64 pipeline. Take both lines away and you get the generic one. `opt` reads the triple, asks the registry for that target's backend, and hands the backend the pipeline while it is being built.
#
# Which is a hook with a name. The backend that took it looks like this:
#
# ```cpp
# void AArch64TargetMachine::registerPassBuilderCallbacks(PassBuilder &PB) {
# #define GET_PASS_REGISTRY "AArch64PassRegistry.def"
# #include "llvm/Passes/TargetPassRegistry.inc"
#
#   PB.registerLateLoopOptimizationsEPCallback(
#       [=](LoopPassManager &LPM, OptimizationLevel Level) {
#         if (Level != OptimizationLevel::O0)
#           LPM.addPass(LoopIdiomVectorizePass());
#       });
# ```
#
# `PassBuilder` keeps a list of callbacks for each of a dozen or so named places in the pipeline, and calls them while it builds. This one is documented as "the last point in the loop optimization pipeline before loop deletion" and as "the place to add passes that can remove loops, such as target-specific loop idiom recognition", which is exactly what aarch64 put there.
#
# So `default<O2>` is not a fixed list of passes. It is a fixed list with holes in it, and the target fills the holes. That is the mechanism behind every number in this book that came in a pair.
#
# One thing is left to check, and it is the part that decides how much any of this matters.

# %% id=and_yet_the_body_is_the_same
optimised = {t: built[t].opt("default<O2>") for t in TARGETS}
reference = optimised["x86_64-unknown-linux-gnu"].instructions("f")

for t in TARGETS:
    body = optimised[t].body("f")
    print(f"{t:<28} {len(optimised[t].instructions('f')):>2} instructions  "
          f"same as x86-64: {optimised[t].instructions('f') == reference}  "
          f"{body.splitlines()[0].split(' @')[0]}")

# %% [markdown]
# ## An extra pass that did nothing
#
# All four produce the same sixteen instructions. `loop-idiom-vectorize` ran on the aarch64 module, looked at this loop, found nothing it recognised, and returned. It is there for byte comparison loops of the kind `strcmp` is made of, on cores with the vector instructions to do them, and a counted `t += i` is not one.
#
# The last column is the only thing that is not identical, and it is not a pass's doing: three targets get `dso_local` on the definition and wasm gets `hidden`, which is another front end decision from the same place as the calling convention.
#
# That is the honest shape of this. The pipeline genuinely differs by target. For a great deal of ordinary code the output does not, because the passes a target adds are looking for patterns that are rare. Which is why it took nine lessons for the difference to show up as anything other than a number in a claims file.
#
# It is also why the number is worth knowing. When you count 119 entries and the person you are talking to counts 120, neither of you has the wrong LLVM. You have different modules.
#
# ## What to keep
#
# `target datalayout` and `target triple` are the two most consequential lines in a `.ll` file. The layout fixes sizes, alignments and endianness; the triple names the machine.
#
# There are no C types in the IR. `long` is `i64` on one target and `i32` on another, and a struct passed by value is `i64`, `[2 x i32]` or a `byval` pointer depending on where that machine's calling convention wants it. All of this is the front end's work and is finished before the first pass runs.
#
# The optimisation pipeline is target-dependent too. `default<O2>` has 120 entries for an aarch64 module and 119 for x86-64, thumb and wasm, on one machine, and the difference is `loop-idiom-vectorize`.
#
# The triple alone decides it. Change that one line, leave the data layout lying about a different machine, and the pipeline changes with the triple.
#
# Your `opt` has to have the backend. A build with a reduced target list warns on stderr and falls back to the generic pipeline, so read the warnings before drawing a conclusion from a count.
#
# The mechanism is extension points. `PassBuilder` exposes named places in the pipeline, a target's `registerPassBuilderCallbacks` adds passes at them, and `AArch64TargetMachine` uses the late loop optimisations point. The pipeline is built, not looked up.
#
# An extra pass is not an extra transformation. All four targets optimise this function to the same sixteen instructions, because the pass aarch64 added was looking for something that is not there.
#
# Next: what `opt` does when you hand it a pass name that does not exist, and what that tells you about how the names are resolved.
