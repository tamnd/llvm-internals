# ---
# id: t11_not_what_clang_optimised
# title: The -O0 file is not what clang -O2 optimised
# question: Does opt -passes=default<O2> give me what clang -O2 gives me?
# part: I
# env: E0
# minutes: 40
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string, t06_who_says_it_is_stale, t07_which_one_did_it, t08_o2_twice, t09_the_machine_in_the_ir, t10_the_names]
# ---

# %% [markdown]
# # The `-O0` file is not what `clang -O2` optimised
#
# Every lesson so far has done the same thing: compile at `-O0`, hand the result to `opt`, watch what happens. That is a method, and a method deserves to be checked. `clang -O2` runs the pipeline T05 counted, so the two routes should agree.
#
# Mostly they do. This lesson is about the places they do not, because both of them are things you would otherwise discover by being wrong in public.
#
# Comparing IR needs care, since the two routes number their values differently. Compare the shape instead.

# %% id=five_that_agree
import re

CASES = {
    "loop":  "int f(int n) { int t = 0; for (int i = 0; i < n; i++) t += i; return t; }",
    "abs":   "int f(int a, int b) { return a > b ? a - b : b - a; }",
    "fma":   "double f(double a, double b, double c) { return a * b + c; }",
    "rec":   "int f(int n, int acc) { return n == 0 ? acc : f(n - 1, acc + 1); }",
    "switch": "int f(int c) { switch (c) { case 1: return 10; case 2: return 20; "
              "default: return 0; } }",
}


def shape(module, name="f"):
    """The body with every name replaced by the order it first appears in."""
    seen, out = {}, []
    for line in module.body(name).splitlines():
        line = line.split(";")[0].strip()
        if line and not line.endswith(":"):
            out.append(re.sub(r"[%!][\w.]+",
                              lambda m: m.group(0)[0] + str(seen.setdefault(m.group(0), len(seen))),
                              line))
    return out


def clang_o2(source, *flags):
    """What clang -O2 emits, without opt being involved at all."""
    return irx.Module.from_ll(
        irx.run("clang", "-x", "c", "-std=c17", "-O2", "-S", "-emit-llvm",
                "-fno-discard-value-names", "-o", "-", *flags, "-", stdin=source).stdout)


for label, source in CASES.items():
    direct = clang_o2(source)
    through_opt = irx.compile_c(source, name=label).opt("default<O2>")
    print(f"  {label:<7} clang -O2 {len(shape(direct)):>2} lines, "
          f"-O0 then opt {len(shape(through_opt)):>2} lines, "
          f"same shape: {shape(direct) == shape(through_opt)}")

# %% [markdown]
# ## Five for five
#
# A loop, a branch, floating point, self recursion and a switch, and in every case the two routes produce the same instructions in the same order. That is worth having: it means ten lessons of running `opt` over `-O0` output have been looking at the thing `clang -O2` actually produces, and not at an artefact of the method.
#
# Now a sixth case, which is two functions rather than one.

# %% id=the_call_that_did_not_inline
TWO = """
static int g(int x) { return x * 3; }
int f(int n) { return g(n) + g(n + 1); }
"""

direct = clang_o2(TWO)
through_opt = irx.compile_c(TWO, name="two").opt("default<O2>")

print("clang -O2");        print(direct.body("f").rstrip())
print()
print("-O0 then opt");     print(through_opt.body("f").rstrip())

# %% [markdown]
# ## One of them inlined and one of them did not
#
# `clang -O2` folded both calls away and worked out that `g(n) + g(n + 1)` is `6n + 3`. The `opt` route left two calls standing.
#
# The pipeline was the same. `default<O2>` contains the inliner in both routes, it ran in both routes, and T07's bisect would find it running in both. Something about the input made it decline.

# %% id=gate_inline
irx.gate(
    "Same LLVM, same pipeline, same source. Why did the inliner leave `g` alone in one of them?",
    {
        "The -O0 file says not to": "clang writes attributes at -O0 that are instructions to "
                                    "later passes, and one of them survives the flag this "
                                    "toolkit passes.",
        "opt has no cost model without a target": "It has one. T09 showed opt building a "
                                                  "target machine from the triple, and the "
                                                  "triple is in the file.",
        "The inliner needs the C source": "No pass reads C. Everything after the front end "
                                          "works on the IR alone.",
        "`static` is lost by the time opt runs": "It is not. `static` became internal linkage, "
                                                 "which is in the file and is what lets the "
                                                 "call be specialised at all.",
    },
    answer="The -O0 file says not to",
    note="Read the attribute group at the bottom of the -O0 file.",
)

# %% id=what_the_o0_file_says
def attributes(source, *flags):
    """The first attribute group clang writes for this source."""
    text = irx.run("clang", "-x", "c", "-std=c17", "-O0", "-S", "-emit-llvm",
                   "-o", "-", *flags, "-", stdin=source).stdout
    group = next(ln for ln in text.splitlines() if ln.startswith("attributes #0"))
    return [word for word in group.split("{")[1].split("}")[0].split() if '"' not in word]


print("clang -O0                          ", attributes(TWO))
print("clang -O0 -disable-O0-optnone      ",
      attributes(TWO, "-Xclang", "-disable-O0-optnone"))

# %% [markdown]
# ## `noinline nounwind optnone`
#
# There it is, and there is the flag this book has been passing on your behalf since T01. `irx.compile_c` runs clang with `-Xclang -disable-O0-optnone`, which removes `optnone` and leaves `noinline` exactly where it was.
#
# `optnone` is the stronger of the two. Without the flag, the file you get from `clang -O0` is closed to almost everything.

# %% id=optnone_is_a_wall
walled = irx.Module.from_ll(
    irx.run("clang", "-x", "c", "-std=c17", "-O0", "-S", "-emit-llvm", "-o", "-", "-",
            stdin=CASES["loop"]).stdout)

after = walled.opt("default<O2>")
print(f"instructions before {len(walled.instructions('f'))}, after {len(after.instructions('f'))}")

r = irx.run("opt", "-passes=default<O2>", "-debug-pass-manager", "-disable-output", "-",
            stdin=walled.text, check=False)
log = (r.stdout + r.stderr).splitlines()
skipped = [ln for ln in log if "due to optnone attribute" in ln]

print(f"{len(skipped)} passes skipped, {sum(ln.startswith('Running pass:') for ln in log)} ran")
print(skipped[0])
print(skipped[1])

# %% [markdown]
# ## Ninety odd refusals and forty passes that did not care
#
# The function comes out with the same instruction count it went in with. The passes that did run are the module level ones, which are handed the module rather than any one function and so are never asked the question. They are the reason the file is not byte identical afterwards even though the function is.
#
# The refusal is not inside each pass. It is one callback, registered once, that every optional pass is asked before it runs:
#
# ```cpp
# bool OptNoneInstrumentation::shouldRun(StringRef PassID, Any IR) {
#   bool ShouldRun = true;
#   if (const auto *F = unwrapIR<Function>(IR))
#     ShouldRun = !F->hasOptNone();
#   ...
#   if (!ShouldRun && DebugLogging) {
#     errs() << "Skipping pass " << PassID << " on " << getIRName(IR)
#            << " due to optnone attribute\n";
#   }
# ```
#
# LangRef puts it plainly: `optnone` means "most optimization passes will skip this function", and it "requires the `noinline` attribute to be specified on the function as well, so the function is never inlined into any caller".
#
# That last sentence is the one that costs you. Turning `optnone` off does not turn `noinline` off, so the file the toolkit hands you is open to every pass except the one that would have removed a call. You can take it off by hand.

# %% id=putting_the_inlining_back
freed = irx.Module.from_ll(
    irx.run("opt", "-passes=forceattrs,default<O2>", "-force-remove-attribute=g:noinline",
            "-S", "-", stdin=irx.compile_c(TWO, name="two").text).stdout)

print(freed.body("f").rstrip())
print()
print("same shape as clang -O2:", shape(freed) == shape(direct))

# %% [markdown]
# ## `forceattrs` and a name
#
# `-force-remove-attribute=g:noinline` takes the attribute off that one function, and then the rest of `default<O2>` does what `clang -O2` did, to the instruction. That is the diagnosis confirmed in T08's style rather than asserted.
#
# It is also a tool worth keeping. `forceattrs` is how you ask "would this have been inlined if the front end had let it", and the `-force-attribute` half of the same pass lets you push in the other direction.
#
# One difference left, and it is not an attribute.

# %% id=the_metadata_that_is_not_there
ALIAS = "int f(int *a, float *b) { *a = 1; *b = 2.0f; return *a; }"

flat = irx.compile_c(ALIAS, name="alias")
for label, module in (("clang -O2", clang_o2(ALIAS)),
                      ("clang -O2 -fno-strict-aliasing", clang_o2(ALIAS, "-fno-strict-aliasing")),
                      ("-O0 then opt", flat.opt("default<O2>"))):
    body = module.body("f")
    print(f"  {label:<32} tbaa nodes {module.text.count('!tbaa'):>2}  "
          f"loads {body.count('load '):>2}  "
          f"{next(ln.strip() for ln in body.splitlines() if 'ret ' in ln)}")

# %% [markdown]
# ## `ret i32 1` against `ret i32 %0`
#
# `clang -O2` knows the answer is 1. The `opt` route reloads it, because as far as that module is concerned the store through `float *b` might have changed what `int *a` points at.
#
# In C it cannot, and the reason `clang -O2` knows is `!tbaa`, metadata attached to each memory operation that names the language level type being accessed. The IR has no types on memory, so the front end writes the type system down as metadata and `TypeBasedAliasAnalysis` reads it back. clang emits it when optimisations are on and not at `-O0`, which is why the `-O0` file has none.
#
# The middle row is the check. Ask `clang -O2` for the same thing with `-fno-strict-aliasing` and the metadata is gone and so is the folding, which lands on exactly the IR the `opt` route produced. The passes are not the variable. The metadata is.
#
# ## What to keep
#
# For a single self contained function, `clang -O0` then `opt -passes=default<O2>` gives what `clang -O2` gives. Five different shapes of function agree instruction for instruction, so the method the rest of this book uses is sound.
#
# `clang -O0` marks every function `noinline nounwind optnone`. `optnone` makes nearly every pass skip the function, through one instrumentation callback rather than through checks inside the passes, and `-debug-pass-manager` prints a line for each refusal.
#
# `-Xclang -disable-O0-optnone`, which `irx.compile_c` passes for you, removes `optnone` and leaves `noinline`. So the inliner does nothing on `-O0` IR, and any experiment about inlining needs that dealt with.
#
# `forceattrs` with `-force-remove-attribute=name:noinline` deals with it, and puts the result back to what `clang -O2` produces.
#
# `-O0` IR carries no `!tbaa`, so alias analysis is weaker than it is in a real `-O2` compile, and a store through one pointer type can block folding a load through another. `clang -O2 -fno-strict-aliasing` reproduces the `-O0` behaviour exactly, which is how you tell that metadata rather than passes made the difference.
#
# The general shape of both findings is the same. The pipeline is not the only input. The IR carries attributes and metadata that instruct it, and a file produced at one optimisation level is not the file produced at another.
#
# Next: the end of Part I, and the five questions you can now answer about any compiler you are handed.
