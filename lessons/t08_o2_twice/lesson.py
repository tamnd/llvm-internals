# ---
# id: t08_o2_twice
# title: -O2 twice is not -O2
# question: If the pipeline were finished, why does running it again change anything?
# part: I
# env: E0
# minutes: 35
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string, t06_who_says_it_is_stale, t07_which_one_did_it]
# ---

# %% [markdown]
# # `-O2` twice is not `-O2`
#
# A hundred and twenty entries have run over your function. Every one of them looked at it, and the ones that had something to do did it. There is a natural thing to believe at that point, which is that the result is finished: run the same pipeline again and nothing can possibly happen, because the passes that would have fired already fired.
#
# It takes one function and one comparison to find out.

# %% id=run_it_twice
LOOP = "int sum_to(int n) { int t = 0; for (int i = 0; i < n; i++) t += i; return t; }"

once = irx.compile_c(LOOP, name="loop").opt("default<O2>")
twice = once.opt("default<O2>")
thrice = twice.opt("default<O2>")

for label, module in (("-O2", once), ("-O2 -O2", twice), ("-O2 -O2 -O2", thrice)):
    print(f"{label:<12} {len(module.instructions('sum_to')):>2} instructions")

print()
print("second run changed something:", once.body("sum_to") != twice.body("sum_to"))
print("third run changed something: ", twice.body("sum_to") != thrice.body("sum_to"))

# %% [markdown]
# ## The second run has work to do and the third does not
#
# So `-O2` is not a fixed point of itself, and it takes two applications to reach one here.
#
# This is not a bug and it is not a rare corner. It follows from what T05 established: the pipeline is a list, run once each, in a fixed order. Nothing in it loops back. Whether a pass fires depends on what the IR looks like when its turn comes, and its turn comes exactly once.
#
# Before the explanation, the same three versions of the function should agree about arithmetic. Appending a `main` in `.ll` and handing the lot to `lli` is the cheapest way to check.

# %% id=all_three_agree
MAIN = """
define i32 @main() {
  %a = call i32 @sum_to(i32 100)
  %b = urem i32 %a, 251
  ret i32 %b
}
"""

flat = irx.compile_c(LOOP, name="loop")
for label, module in (("-O0", flat), ("-O2", once), ("-O2 -O2", twice)):
    print(f"{label:<9} sum_to(100) % 251 = "
          f"{irx.run('lli', '-', stdin=module.text + MAIN, check=False).code}")

# %% [markdown]
# ## Same answer, one instruction fewer
#
# 4950 is the sum of nought to ninety nine and 181 is what is left of it modulo 251, from all three. Nobody is wrong. One of them is a single instruction shorter, and the question is which pass was responsible and why it did not get to be responsible the first time round.
#
# T07 answered the first half of that question with a binary search, and the property being searched for does not have to be a crash. It can be "is this function already in its final shape".

# %% id=gate_second_run
irx.gate(
    "The second `-O2` removes an instruction the first one left behind. What has to be true "
    "of the pass that removes it?",
    {
        "It ran the first time too, and did nothing": "It did run, and it did do things. What "
                                                      "matters is what the function looked "
                                                      "like at the moment it ran.",
        "It was skipped the first time": "Nothing skips it. Every entry in the pipeline runs, "
                                         "which T04 and T05 both leaned on.",
        "It needs an analysis that was invalidated": "T06's machinery, but not this. An "
                                                     "analysis being recomputed does not "
                                                     "change what a pass is able to see.",
        "It is nondeterministic": "Then the third run would keep changing things, and it does "
                                  "not. Both runs are deterministic.",
    },
    answer="It ran the first time too, and did nothing",
    note="Two passes are involved and the order between them is the entire story.",
)

# %% id=where_did_it_change
def bisect(module, limit):
    """The IR and the log from -O2 with a cap on how many pass runs may happen."""
    r = irx.run("opt", "-passes=default<O2>", f"-opt-bisect-limit={limit}", "-S", "-",
                stdin=module.text)
    return irx.Module.from_ll(r.stdout), (r.stderr or "").splitlines()


def first_limit(module, done):
    """The smallest cap whose output already satisfies done, by binary search."""
    _, log = bisect(module, 100000)
    low, high = 0, len(log)
    while low < high:
        middle = (low + high) // 2
        if done(bisect(module, middle)[0]):
            high = middle
        else:
            low = middle + 1
    return log[low - 1], log


line, log = first_limit(once, lambda m: m.body("sum_to") == twice.body("sum_to"))
print(f"{len(log)} pass runs in the second -O2")
print(line)

# %% [markdown]
# ## `gvn on sum_to`
#
# Global value numbering, whose job is noticing that two expressions compute the same thing and keeping one of them. So the second run found a redundant computation.
#
# Which is a strange thing to find, because `gvn` also ran during the first `-O2`, over this same function. To see what it was looking at, watch the two instructions in question across both runs.

# %% id=the_two_adds
import re


def adds(module):
    """Every 32 bit add in sum_to, which is where the change happens."""
    return [ln.strip() for ln in module.body("sum_to").splitlines()
            if re.search(r"= add( nsw| nuw)* i32", ln)]


def run_number(log, name):
    """Which numbered run is this pass, in a log we already have."""
    return next(n for n, ln in enumerate(log, 1) if f") {name} on" in ln)


def watch(module, log, marks):
    for label, limit in marks:
        print(f"  {label:<20} after {limit:>3} runs: {adds(bisect(module, limit)[0])}")


first = bisect(flat, 100000)[1]
second = bisect(once, 100000)[1]

print("first -O2")
watch(flat, first, [("before indvars", run_number(first, "indvars") - 1),
                    ("after indvars", run_number(first, "indvars")),
                    ("after gvn", run_number(first, "gvn")),
                    ("all of it", len(first))])
print("second -O2")
watch(once, second, [("before reassociate", run_number(second, "reassociate") - 1),
                     ("after reassociate", run_number(second, "reassociate")),
                     ("after gvn", run_number(second, "gvn"))])

# %% [markdown]
# ## Fifteen runs too late
#
# Read the first block. Before `indvars` the only adds are the two inside the loop. After it there are four new ones, because that is `indvars` working out that the loop computes a closed form and writing it into the block before the loop. Two of the four matter here: `add i32 %n, %6` and then `add i32 %7, -1`, which together are `(n + %6) - 1`.
#
# `gvn` runs after that, sees it, and leaves it alone. It is right to. There is no repeated expression there. The block also contains `%0 = add i32 %n, -1`, and a human can see that `(n + %6) - 1` is `(n - 1) + %6` and therefore contains `%0`, but `gvn` numbers expressions as they are written and those two are not written the same way.
#
# Rewriting `(n + x) - 1` into `(n - 1) + x` is a different pass's job. It is `reassociate`, and in the second block you can watch it happen: `%7` becomes `add i32 %n, -1` and `%8` becomes `add i32 %7, %6`. Now there are two instructions computing `n - 1` and `gvn` deletes one of them.
#
# So both passes were present both times, in the same order, and did what they always do. The problem is the order. `reassociate` is run 32 of the first `-O2` and `indvars` is run 47, so the expression `reassociate` was needed for did not exist until fifteen runs after it had finished, and there is no second visit.
#
# If that diagnosis is right, then adding those three passes to the end of one `-O2` should produce exactly what two `-O2`s produce.

# %% id=the_repair
for extra in ("reassociate", "gvn", "reassociate,gvn", "reassociate,instcombine,gvn"):
    patched = irx.Module.from_ll(
        irx.run("opt", f"-passes=default<O2>,function({extra})", "-S", "-",
                stdin=flat.text).stdout)
    print(f"  -O2 then {extra:<28} same as two -O2s: "
          f"{patched.body('sum_to') == twice.body('sum_to')}")
    print(f"  {'':<8} {'':<28} {adds(patched)}")

# %% [markdown]
# ## Byte for byte, and only with all three
#
# Neither pass alone does it, which is the diagnosis being confirmed rather than merely restated. `reassociate` rewrites the expression and leaves the instruction count where it was. `gvn` on its own has nothing to number.
#
# The interesting failure is `reassociate,gvn`, which gets the instruction count right and the function wrong. Look at what it did to `%0`. After `reassociate` there are two instructions computing `n - 1`, and they are not identical: the one `indvars` wrote carries `nsw` and the one `reassociate` produced does not. `gvn` merges them and the survivor loses the flag, because a fact that is not on both copies cannot be true of the merged one.
#
# Put `instcombine` between them and it works out that the new `n - 1` cannot overflow either, both carry `nsw`, and the merge costs nothing. That is why the appended pipeline that reproduces two `-O2`s byte for byte has three passes in it and not two, and it is worth remembering the next time a flag goes missing.
#
# Three passes appended to a hundred and twenty produce what running all hundred and twenty again produces, for this function, because those three were the only ones with anything left to do.
#
# It would be a mistake to read that as a recipe. It is a diagnosis of one function. Append those three to every build and you will pay for them on every function in the program, almost always for nothing, and the next function whose fixed point is one pass away will need a different three.
#
# The real lesson is what the pipeline is. A hundred and twenty entries in a fixed order is a schedule, chosen because it pays off across a lot of real code, and every schedule of passes that create work for each other leaves something on the table. LLVM does not iterate to a fixed point because that would cost far more than it returns, and because there is no guarantee the fixed point is reachable at all.
#
# ## What to keep
#
# `-O2` is not idempotent. Running it twice on this function removes an instruction, and running it a third time changes nothing, so the fixed point here is two runs away rather than one.
#
# The reason is ordering, not laziness. `reassociate` is run 32 and puts expressions into the form `gvn` can number. `indvars` does not create the expression in question until run 47. Both passes ran, both did their jobs, and the one that had to go second went first.
#
# The T07 procedure is not only for crashes. Binary search over `-opt-bisect-limit` with the property "the function is already in its final shape" finds the pass that finished the job in the same eight probes.
#
# When you think you know why, say so in a form that can be wrong. Appending `reassociate,instcombine,gvn` to one `-O2` reproduces two `-O2`s byte for byte, and dropping any one of the three does not, which is a diagnosis that survived a test rather than a story that fits.
#
# Flags are part of a value. `gvn` merging two instructions that compute `n - 1`, one carrying `nsw` and one not, produces a survivor without it, which is why `instcombine` has to run in between.
#
# Next: the same function compiled for two different targets, and the one place in Part I where the answer depends on the machine.
