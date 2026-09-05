# ---
# id: t10_the_names
# title: opt does not know what you meant
# question: Where does the list of pass names come from, and why is yours different?
# part: I
# env: E0
# minutes: 30
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string, t06_who_says_it_is_stale, t07_which_one_did_it, t08_o2_twice, t09_the_machine_in_the_ir]
# ---

# %% [markdown]
# # `opt` does not know what you meant
#
# Nine lessons of typing pass names into `-passes=` and every one of them was spelled correctly, which is not how anybody's first afternoon goes. This lesson is about what happens when they are not, because the failures are more informative than they look and they lead somewhere: to where the list of names comes from, and to why yours and mine are not the same list.
#
# Four ways to get it wrong.

# %% id=four_ways_to_be_wrong
SRC = "int f(int n) { int t = 0; for (int i = 0; i < n; i++) t += i; return t; }"
loop = irx.compile_c(SRC, name="f")


def try_passes(spec):
    """What opt says about this pipeline, whether or not it will run it."""
    r = irx.run("opt", f"-passes={spec}", "-disable-output", "-", stdin=loop.text, check=False)
    if r.code == 0:
        return "accepted"
    first = (r.stderr or "").strip().splitlines()[0]
    return first.split(": ", 1)[-1]


for spec in ("instcombine", "instcomb", "InstCombine", "inst-combine",
             "instcombine<foo>", "instcombine<max-iterations=3>"):
    print(f"  {spec:<32} {try_passes(spec)}")

# %% [markdown]
# ## Two different complaints
#
# Three of those failures say `unknown pass name`. The fourth says `invalid InstCombine pass parameter 'foo'`, and the difference between those two sentences is the whole of how the parser works. `instcombine<foo>` got far enough to be recognised as `instcombine`, and then failed on what was inside the angle brackets. `instcomb` never got that far.
#
# There is no spelling correction and no case folding. `InstCombine` is the name of the C++ class and is not a pass name; `inst-combine` is a plausible guess and is not one either. The names are exact strings, and the last line shows what the angle brackets are for: parameters, which T05 saw `opt` printing back at you in `instcombine<max-iterations=1;verify-fixpoint>`.
#
# So there is a list somewhere. `opt` will show it to you.

# %% id=the_printed_vocabulary
listing = irx.run("opt", "--print-passes").stdout

section, counted = None, {}
for line in listing.splitlines():
    if line.endswith(":") and not line.startswith(" "):
        section = line[:-1]
        counted[section] = 0
    elif line.strip() and section:
        counted[section] += 1

for name, how_many in counted.items():
    print(f"  {how_many:>4}  {name}")

# %% [markdown]
# ## The sections are the levels
#
# Module, CGSCC, Function, LoopNest, Loop, MachineFunction: the same nesting T05 built pipelines out of, used here to organise a vocabulary. Each level has its passes, its passes that take parameters, and its analyses, which are the things `require<...>` can name.
#
# Two numbers are worth pausing on. There are more function passes than everything else put together, which is where most optimisation happens. And the machine function sections are marked `(WIP)`, because the backend's move to the new pass manager is not finished; those names exist and most pipelines cannot use them yet.
#
# Now the part that makes this lesson worth having. That listing is not the vocabulary. It is a vocabulary, and which one you get depends on the thing T09 was about.

# %% id=gate_names
irx.gate(
    "`opt --print-passes` was run with no input file. What can it not know?",
    {
        "Which target's passes to include": "The listing is printed before any module is "
                                            "read, so no triple has been seen and no backend "
                                            "has been asked for its names.",
        "Which optimisation level you want": "Levels are a property of `default<O2>`, not of "
                                             "the name list. Every name is available at every "
                                             "level.",
        "Which passes are analyses": "It knows exactly that, and prints them under their own "
                                     "headings, one set per level.",
        "Which passes take parameters": "It knows that too. That is what the `with params` "
                                        "sections are.",
    },
    answer="Which target's passes to include",
    note="Two modules, the same opt, and one name that exists for one of them.",
)

# %% id=the_target_brings_names
TARGETS = ["x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"]
NAMES = ["x86-partial-reduction", "x86-lower-amx-type", "aarch64-sve-shuffle-opts"]

for target in TARGETS:
    module = irx.compile_c(SRC, target=target, name="f")
    for name in NAMES:
        r = irx.run("opt", f"-passes={name}", "-disable-output", "-", stdin=module.text,
                    check=False)
        verdict = "accepted" if r.code == 0 else (r.stderr or "").strip().splitlines()[0]
        print(f"  {target:<28} {name:<26} {verdict.split(': ', 1)[-1]}")
    print()

print("in --print-passes:", [n for n in NAMES if n in listing])

# %% [markdown]
# ## Three names that exist for one module and not the other
#
# `x86-partial-reduction` and `x86-lower-amx-type` are real passes with real names, and `opt` will not accept either of them for the aarch64 module. `aarch64-sve-shuffle-opts` is real and is rejected for the x86-64 one. None of the three appears in `--print-passes`, which was printed without a module and therefore without a target.
#
# This is the same mechanism as T09's extra pipeline entry, seen from the other side. T09 quoted the first two lines of `AArch64TargetMachine::registerPassBuilderCallbacks` and passed over them:
#
# ```cpp
# #define GET_PASS_REGISTRY "AArch64PassRegistry.def"
# #include "llvm/Passes/TargetPassRegistry.inc"
# ```
#
# `AArch64PassRegistry.def` is a list of `MODULE_PASS`, `FUNCTION_PASS`, `LOOP_PASS` and `MACHINE_FUNCTION_PASS` lines, one per pass, each pairing a name with the expression that builds it. `aarch64-sve-shuffle-opts` is the one `LOOP_PASS` line in it. `X86PassRegistry.def` has the same four macros and three `FUNCTION_PASS` lines, two of which you tried above. `TargetPassRegistry.inc` includes whichever file the `#define` named, several times over, with the macros defined differently each time: once to build a name matcher and once to build the thing that constructs the pass. The generic passes come from `llvm/lib/Passes/PassRegistry.def` in the same shape, and it is 843 lines long.
#
# So the pass names are not a fixed vocabulary in `opt`. They are the generic registry plus whatever the module's target contributes, and the target is chosen by the triple.
#
# Spelling is one way to be rejected. Placement is the other.

# %% id=downhill_only
for spec in ("globalopt", "function(globalopt)",
             "instcombine", "cgscc(instcombine)", "loop(instcombine)",
             "licm", "loop(licm)"):
    print(f"  {spec:<24} {try_passes(spec)}")


def built_as(spec):
    """The pipeline opt actually assembles from this name, adaptors and all."""
    return irx.run("opt", f"-passes={spec}", "-print-pipeline-passes", "-disable-output",
                   "-", stdin=loop.text).stdout.strip()


print()
for spec in ("globalopt", "instcombine", "licm"):
    print(f"  {spec:<12} built as: {built_as(spec)}")

# %% [markdown]
# ## Wrapping goes one way
#
# `instcombine` is a function pass, and naming it alone or inside `cgscc(...)` both work, because a narrower pass can always be adapted to run inside a wider manager. Naming it inside `loop(...)` does not work, because `loop` is narrower than `function` and there is no adaptor that runs a function pass once per loop.
#
# `function(globalopt)` fails for the same reason in the other direction. `globalopt` looks at the whole module and a function pass manager has one function.
#
# The three built pipelines at the bottom are the wrapping happening. `globalopt` stays where it is. `instcombine` becomes `function(instcombine<...>)`. And `licm`, which is a loop pass, becomes `function(loop-mssa(licm<allowspeculation>))`, with two levels of adaptor put in for you. That is the code doing it:
#
# ```cpp
# if (!isModulePassName(FirstName, ModulePipelineParsingCallbacks)) {
#   bool UseMemorySSA;
#   if (isCGSCCPassName(FirstName, CGSCCPipelineParsingCallbacks)) {
#     Pipeline = {{"cgscc", std::move(*Pipeline)}};
#   } else if (isFunctionPassName(FirstName, FunctionPipelineParsingCallbacks)) {
#     Pipeline = {{"function", std::move(*Pipeline)}};
#   } else if (isLoopPassName(FirstName, LoopPipelineParsingCallbacks, UseMemorySSA)) {
#     Pipeline = {{"function", {{UseMemorySSA ? "loop-mssa" : "loop", ...}}}};
# ```
#
# It tries the levels in order from widest to narrowest and stops at the first one that recognises the name, which is why the error you get names the level it gave up at: `unknown pass name` from the module parser, `unknown function pass` from the function parser.
#
# One line of that is a special case, and it is the reason for the odd word in T06's output.

# %% id=licm_is_special
for spec in ("licm", "loop-mssa(licm)", "loop(licm)", "loop(loop-rotate)"):
    print(f"  {spec:<22} {try_passes(spec)}")

# %% [markdown]
# ## `loop-mssa` is not optional for `licm`
#
# `loop(loop-rotate)` is accepted, so `loop` is a real adaptor and the problem is not the word. `loop(licm)` is accepted by the parser and then dies while running, with a message from `LICMPass::run` saying `LICM requires MemorySSA (loop-mssa)`. The pass checks whether the memory analysis it needs is available and gives up if it is not.
#
# Which is why the parser hardcodes it. `isLoopPassName` sets `UseMemorySSA` to true for exactly two names, `licm` and `lnicm`, before it consults any registry, so a bare `licm` is wrapped in `loop-mssa` rather than `loop` and works. Ask for `loop(licm)` explicitly and you have overridden the one thing that was being done for you.
#
# T06 saw `loop-mssa` in a printed pipeline and had to note that the adaptor was not the one you asked for. This is where it comes from: two names in an `if`.
#
# ## What to keep
#
# Pass names are exact strings. No case folding, no spelling correction, no aliases for the C++ class name.
#
# The error tells you how far the parse got. `unknown pass name` means the name was never recognised; `invalid <Pass> parameter` means it was recognised and the angle brackets were wrong. The first names the level that gave up, which tells you where it looked.
#
# `opt --print-passes` lists the vocabulary by level, with separate sections for passes, passes that take parameters, and analyses. The machine function sections are marked `(WIP)`.
#
# That listing is incomplete, because it is printed without a module. A target contributes names through its own `<Target>PassRegistry.def`, and those names are accepted only for modules whose triple selects that target. `x86-partial-reduction` exists for an x86-64 module and does not exist for an aarch64 one, on the same `opt`.
#
# Adaptors are inserted downwards only. A narrower pass named in a wider place gets wrapped; a wider pass named in a narrower place is an error.
#
# `licm` and `lnicm` are hardcoded to be wrapped in `loop-mssa` rather than `loop`, because the pass calls it a fatal error to run without MemorySSA. Writing `loop(licm)` yourself parses and then dies.
#
# Next: `opt` is not the only thing that reads these names, and the first look at what `clang -O2` does that `opt -passes=default<O2>` does not.
