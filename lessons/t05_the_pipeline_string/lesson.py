# ---
# id: t05_the_pipeline_string
# title: The pipeline is a string, and -O2 will print you its own
# question: Why does -passes= reject a pass I have already used?
# part: I
# env: E0
# minutes: 35
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape]
# ---

# %% [markdown]
# # The pipeline is a string, and `-O2` will print you its own
#
# T04 ended with three pass names in a row, `sroa,indvars,loop-deletion`, which is enough to make a loop disappear. That comma separated list is a pipeline, and it is the only interface `opt` has. Everything else, `-O2` included, is a name for one of these strings.
#
# Which makes the string worth understanding, because it has two rules that are not written down anywhere you would look first, and one of them produces an error message that reads like the tool is broken.
#
# We are going to find both by taking the three passes that worked and typing them in a different order.

# %% id=same_names_new_order
import re

LOOP = """
int sum_to(int n) {
  int total = 0;
  for (int i = 0; i < n; i++)
    total += i;
  return total;
}
"""

loop = irx.compile_c(LOOP, name="sum_to")


def shape(module):
    """Instructions and blocks, which is enough to see whether a loop is left."""
    body = module.body("sum_to").splitlines()
    labels = [ln for ln in body if re.match(r"^[\w.$-]+:", ln)]
    return (f"{len([ln for ln in body if ln.startswith('  ')]):>2} instructions, "
            f"{len(labels)} blocks: {', '.join(ln.split(':')[0] for ln in labels)}")


print(f"{'-O0, as clang wrote it':<30} {shape(loop)}")
for pipeline in ("sroa,indvars,loop-deletion", "sroa,loop-deletion,indvars"):
    print(f"{pipeline:<30} {shape(loop.opt(pipeline))}")

# %% [markdown]
# ## The same three passes, and one of them wasted
#
# Same names, same passes, same input. Read the block names. One order leaves a function with no loop in it, keeping only the entry block and the one the loop used to exit to. The other still has `for.cond` and `for.body` in it, so the pass whose entire job is deleting loops ran and did nothing.
#
# `loop-deletion` removes a loop whose result nobody needs. On the way in, the result is needed, because `total` is returned. `indvars` is what changes that, by working out a closed form for the sum and rewriting the code after the loop to use it. Only then is the loop dead. Run `loop-deletion` first and it looks at a live loop and moves on, and it does not get a second chance, because a pipeline runs each entry once, in the order you wrote it.
#
# That is the first rule, and it is the one people expect. Here is the one they do not.

# %% id=gate_reorder
irx.gate(
    "We reverse the whole thing: `-passes=loop-deletion,indvars,sroa`. What comes out?",
    {
        "The loop is still there": "That is what the cell above would suggest and it is a fair "
                                   "read. It is not what happens, and the reason has nothing to "
                                   "do with loops.",
        "The same as sroa,indvars,loop-deletion": "No. Nothing reorders a pipeline for you, and "
                                                  "T04 is a whole lesson about that.",
        "opt refuses to run": "Right, and the message is the interesting part. It names one of "
                              "the three as unknown, and it is a pass you have used twice "
                              "already in this lesson.",
        "It runs, and sroa undoes the other two": "Passes do not undo each other, and sroa has "
                                                  "nothing to do on IR with no allocas left.",
    },
    answer="opt refuses to run",
    note="All three names are real. Something about the order stops them being usable together.",
)

# %% id=the_order_that_will_not_parse
backwards = irx.run("opt", "-passes=loop-deletion,indvars,sroa", "-disable-output", "-",
                    stdin=loop.text, check=False)
print("exit code:", backwards.code)
print(backwards.stderr.strip())

# %% [markdown]
# ## `unknown loop pass 'sroa'`
#
# `sroa` is not unknown. We ran it twice in the first cell. It is unknown *as a loop pass*, and the reason the parser was looking among the loop passes is the name at the front of the list.
#
# Every pass in LLVM belongs to a level: module, call graph component, function, or loop. That is not a label, it is what the pass is handed to work on. `sroa` is handed a function. `loop-deletion` is handed one loop.
#
# When `opt` reads your string it looks at the first name only, decides which level that pass belongs to, and wraps the whole list at that level. Put `loop-deletion` first and the entire list becomes a loop pipeline, so `sroa` is looked up among the loop passes, where it is not.
#
# The comment in the parser says it in a sentence:
#
# ```cpp
# // If the first name isn't at the module layer, wrap the pipeline up
# // automatically.
# StringRef FirstName = Pipeline->front().Name;
# ```
#
# One name decides, and it decides for everything after it.

# %% id=where_a_pass_lives
# One module pass, one function pass, one loop pass, in both orders.
PAIRS = (
    ("globaldce,instcombine", "module then function"),
    ("instcombine,globaldce", "function then module"),
    ("instcombine,loop-deletion", "function then loop"),
    ("loop-deletion,instcombine", "loop then function"),
)

for pipeline, what in PAIRS:
    r = irx.run("opt", f"-passes={pipeline}", "-disable-output", "-",
                stdin=loop.text, check=False)
    print(f"{pipeline:<28} {what:<22} {r.stderr.strip().split(': ')[-1] if r.code else 'ran'}")

# %% [markdown]
# ## Downhill only
#
# Read the right hand column. Every list that starts wide and goes narrower runs. Every list that starts narrow and then names something wider is rejected, and the message tells you which level it had settled on.
#
# So the rule is not that these passes are incompatible. The first name picks a level, and from there you can go down but not back up. `globaldce,instcombine` works because a function pass can be run over every function of a module. `instcombine,globaldce` does not, because there is no sensible way to run a module pass on one function.
#
# The going down is done by an adaptor, an object whose whole job is to take a pass at one level and run it enough times to cover a wider one. You never type them. LLVM will show them to you.

# %% id=print_the_pipeline
# -print-pipeline-passes prints the pipeline opt built, instead of running it.
for pipeline in ("sroa", "globaldce,instcombine,loop-deletion"):
    built = irx.run("opt", f"-passes={pipeline}", "-print-pipeline-passes",
                    "-disable-output", "-", stdin=loop.text).stdout.strip()
    print(f"you wrote: {pipeline}")
    print(f"opt built: {built}\n")

# %% [markdown]
# ## Three things you did not type
#
# `sroa` came back as `function(sroa<modify-cfg>),verify`, and all three additions are worth knowing about.
#
# The `function(...)` around it is the adaptor from the paragraph above. The `verify` on the end is `opt` checking the module on the way out, which is why a pass that produces broken IR is usually caught by the tool rather than by you two hours later.
#
# And `sroa<modify-cfg>` is the pass with its parameters written out. A pass is not one thing that either runs or does not. It is a class with options, and the pipeline string is where they get set.
#
# The second line has the detail that explains a lot of the pipeline text you will read later. It is `globaldce,function(instcombine<...>),function(loop(loop-deletion))`, with two separate `function(...)` wrappers rather than one holding both. Each name in the list got its own adaptor, so LLVM walks every function in the module and runs `instcombine`, then walks every function again and runs `loop-deletion` over the loops. Write `function(instcombine,loop(loop-deletion))` yourself and both passes run on the first function, then both on the second, and so on.
#
# The upstream documentation says to prefer the second, for cache locality around LLVM's own data structures, and notes that in some cases it changes the quality of the optimisation as well. That is the reason the real pipelines are written with the nesting spelled out instead of as a flat list.
#
# Speaking of which.

# %% id=the_o2_string
o2 = irx.run("opt", "-passes=default<O2>", "-print-pipeline-passes", "-disable-output", "-",
             stdin=loop.text).stdout.strip()

print(f"{len(o2)} characters")
print(f"{o2.count(',') + 1} entries, counting the ones inside the nesting")
print()
print(o2[:200], "...")
print("...", o2[-150:])

# %% [markdown]
# ## `-O2` is that
#
# There is no other `-O2`. The flag is a name for this text, the text is what the pass manager gets built from, and every part of it is something you are allowed to type.
#
# Including all of it at once.

# %% id=feed_it_back
by_name = irx.run("opt", "-passes=default<O2>", "-S", "-", stdin=loop.text).stdout
by_text = irx.run("opt", f"-passes={o2}", "-S", "-", stdin=loop.text).stdout

print("same IR from the name and from the printed string:", by_name == by_text)

# %% [markdown]
# ## The printed pipeline is not a summary
#
# It is the thing itself, and it round trips. That is not luck. `opt` builds a second pipeline out of what it is about to print, so a string it cannot parse is caught rather than handed to you, and there is a hidden flag, `-disable-pipeline-verification`, whose only purpose is turning that check off.
#
# This is the tool to reach for when a pipeline question comes up and you would rather not read C++ to answer it. What does `-O1` leave out that `-O2` has? Print both and diff them. Does `-Os` run the vectoriser? Print it and search. The answer becomes a string comparison rather than an archaeology exercise.
#
# It also settles what a pass is, because now you can count.

# %% id=eight_simplifycfgs
settings = [set(one.split(";")) for one in re.findall(r"simplifycfg<([^>]*)>", o2)]

print(f"simplifycfg appears {len(settings)} times, "
      f"with {len({frozenset(s) for s in settings})} distinct sets of options")

for option in ("keep-loops", "switch-to-arithmetic", "switch-to-lookup"):
    on = [n for n, s in enumerate(settings, 1) if option in s]
    print(f"  {option:<21} on in {len(on)}: {on}")

# %% [markdown]
# ## The same pass, tuned differently at each point in the run
#
# `simplifycfg` is one pass, it is scheduled eight times, and the copies are not identical.
#
# Read the three options together and the shape of the pipeline falls out of them. Seven of the eight are asked to keep loops intact, because the loop passes have not finished with them. The one that is not is the same one, and the only one, allowed to turn a `switch` into a lookup table. It runs late, once nothing downstream is going to look at the loops or the branches again, and it is the point where the pipeline stops preserving structure for the benefit of later passes and starts spending it.
#
# One option, one function, and you can watch that decision happen.

# %% id=one_option_one_table
SWITCH = """
int pick(int x) {
  switch (x) {
    case 0: return 7;  case 1: return 91;  case 2: return 3;
    case 3: return 55; case 4: return 12;  case 5: return 400;
    default: return 0;
  }
}
"""

switch = irx.compile_c(SWITCH, name="pick").opt("mem2reg")

for option in ("no-switch-to-lookup", "switch-to-lookup"):
    out = irx.Module.from_ll(
        irx.run("opt", f"-passes=simplifycfg<{option}>", "-S", "-", stdin=switch.text).stdout)
    globals_ = [ln.split(" =")[0] for ln in out.lines if ln.startswith("@")]
    print(f"simplifycfg<{option:<19}> {len(out.instructions('pick')):>2} instructions, "
          f"globals: {globals_ or 'none'}")

# %% [markdown]
# ## A six way branch became one load
#
# With the option off, `pick` is a `switch` and its arms. With it on, the six answers have been written into a constant array called `@switch.table.pick`, and the function is a range check and a load out of it.
#
# Neither is more correct. The second is better when the values are dense and worse when they are sparse, which is a judgement, and the judgement belongs to whoever wrote the pipeline rather than to the pass. The pass takes an option.
#
# That is the thing to carry out of this lesson. When you read that a pass "does" something, ask which instance, at which point in the pipeline, with which options, because all three answers are in a string you can print.
#
# ## What to keep
#
# A pipeline is a comma separated list, run in order, once each. `sroa,indvars,loop-deletion` deletes the loop and `sroa,loop-deletion,indvars` does not, with no error either way.
#
# Every pass belongs to a level. The first name in your list picks the level for the whole list, which is why `loop-deletion,indvars,sroa` fails with `unknown loop pass 'sroa'`. From that level you can nest downwards and never upwards, and the nesting you leave out gets filled in with one adaptor per name.
#
# `opt -passes=... -print-pipeline-passes -disable-output` prints the pipeline that was built, adaptors and default parameters included. Feed the output back to `-passes=` and you get the same IR, byte for byte, because `opt` checks that for you before it prints.
#
# `default<O2>` is one of those strings. `simplifycfg` appears in it eight times with five different sets of options, so "which pass did it" is a question whose answer names an instance and not only a pass.
#
# Next: the pass that runs is not always the pass that decided, because most transforms are gated on an analysis computed somewhere else.
