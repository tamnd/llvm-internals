# ---
# id: t07_which_one_did_it
# title: It crashes at -O0 and works at -O2, and one pass is why
# question: Which pass in -O2 did that to my program?
# part: I
# env: E0
# minutes: 30
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir, t03_reading_ll, t04_the_pass_tape, t05_the_pipeline_string, t06_who_says_it_is_stale]
# ---

# %% [markdown]
# # It crashes at `-O0` and works at `-O2`, and one pass is why
#
# You now know that `-O2` is a string of about a hundred and twenty entries, and that the entries do not all run once. Which is a problem the first time one of them does something to your program that you need to explain.
#
# Reading a hundred and twenty pass names to guess which is the wrong move, and this lesson is about the right one. It takes about a second and reads none of them.
#
# Here is a program that gives two different answers depending on how hard you optimise it.

# %% id=two_answers
DEEP = """
int down(int n, int acc) {
  return n == 0 ? acc : down(n - 1, acc + 1);
}

int main(void) {
  return down(1000000, 0) % 7;
}
"""

deep = irx.compile_c(DEEP, name="deep")


def answer(module):
    """What lli does with this module, whether or not it survives it."""
    r = irx.run("lli", "-", stdin=module.text, check=False)
    return f"returned {r.code}" if r.code >= 0 else f"killed by signal {-r.code}"


print("-O0:", answer(deep))
print("-O2:", answer(deep.opt("default<O2>")))

# %% [markdown]
# ## A million frames, and then not
#
# `down` calls itself a million times before it returns anything, and each call needs a stack frame. At `-O0` the stack runs out and the process dies on a signal. At `-O2` the same source returns 1, which is the right answer, and it does so without a million frames anywhere.
#
# Neither run is a bug. This is a legal C program and both endings are things a C implementation may do with it. But something in that pipeline changed the amount of stack this program needs from unbounded to constant, and "something in that pipeline" is not a good enough answer when the difference is a crash.
#
# `opt` will number the passes for you.

# %% id=the_numbering
def bisect(limit):
    """Run -O2 with a cap on how many passes are allowed, and keep the log."""
    r = irx.run("opt", "-passes=default<O2>", f"-opt-bisect-limit={limit}", "-S", "-",
                stdin=deep.text)
    return r.stdout, (r.stderr or "").splitlines()


_, numbered = bisect(100000)

o2 = irx.run("opt", "-passes=default<O2>", "-print-pipeline-passes", "-disable-output", "-",
             stdin=deep.text).stdout.strip()

print(f"{o2.count(',') + 1} entries in the pipeline string")
print(f"{len(numbered)} numbered pass runs")
print()
print("\n".join(numbered[:6]))

# %% [markdown]
# ## More runs than entries
#
# The count on the left is larger than the count on the right, and T05 and T06 between them have already told you why. An entry like `sroa` is a function pass, so it runs once per function, and this module has two. A loop pass runs once per loop. The pipeline is a list of entries; this is a list of *runs*, which is what a number has to count if it is going to be useful for finding one.
#
# Read the first few lines and you can see the module passes going first and then `lower-expect on down`, a function pass, named with the function it was handed.
#
# `-opt-bisect-limit=N` is not only a numbering. It is a cap. Every pass asks whether it is allowed to run, and above the limit the answer is no.

# %% id=over_the_limit
print("\n".join(bisect(8)[1][6:12]))

# %% [markdown]
# ## `NOT running pass (9)`
#
# Above the cap, passes are skipped and say so. So `-opt-bisect-limit=8` gives you the IR that `-O2` would produce if it stopped after eight pass runs, `-opt-bisect-limit=0` gives you the input back, and a large enough limit gives you `-O2`.
#
# Which turns "which pass did it" into a question with a monotone answer, and a monotone answer can be searched.

# %% id=gate_bisect
irx.gate(
    "Suppose the pass we are looking for is run number 37. What do the two limits either "
    "side of it produce?",
    {
        "36 crashes, 37 returns": "Right. The property is monotone, which is the whole reason "
                                  "a search works: below the pass it is missing, at or above "
                                  "it, it has happened.",
        "36 and 37 both crash, the fix needs later passes too": "That would be true if one "
                                                                "pass set up another. Here one "
                                                                "pass is sufficient on its own, "
                                                                "and the last cell proves it.",
        "Both return, the limit is not that precise": "It is exactly that precise. The cap is "
                                                      "counted in pass runs, not in stages.",
        "36 returns, 37 crashes": "Backwards. Passes are only ever added as the limit rises.",
    },
    answer="36 crashes, 37 returns",
    note="The search below does not assume the number. It finds it in eight probes.",
)

# %% id=the_search
def survives(limit):
    """Does the program still crash if -O2 is allowed only this many pass runs?"""
    ir, _ = bisect(limit)
    return irx.run("lli", "-", stdin=ir, check=False).code >= 0


low, high = 0, len(numbered)
while low < high:
    middle = (low + high) // 2
    ok = survives(middle)
    print(f"  first {middle:>3} pass runs: {'returns' if ok else 'crashes'}")
    if ok:
        high = middle
    else:
        low = middle + 1

print()
print(numbered[low - 1])

# %% [markdown]
# ## `tailcallelim on down`
#
# Eight probes, each one an `opt` and an `lli`, and the culprit has a number and a name and the function it was working on.
#
# Nothing here understood the program. The search only ever asked a yes or no question about the whole run, and halved the range. That is worth saying because the same eight probes work when the symptom is not a crash. Replace "did it survive" with "is the answer wrong", or with "does this string still appear in the output", and the procedure is unchanged. This is how a miscompile gets pinned on a pass by somebody who has never read that pass.
#
# The name we landed on is `tailcallelim`, and the last thing to do is confirm it, because a bisect gives you a suspect rather than a verdict. There are two halves to that, and the flag next door does the first one.

# %% id=take_it_away
for label, flags in (("-O2 as it comes", []),
                     ("without tailcallelim", ["-opt-disable=tailcallelim"]),
                     ("without simplifycfg", ["-opt-disable=simplifycfg"])):
    built = irx.run("opt", "-passes=default<O2>", *flags, "-S", "-", stdin=deep.text).stdout
    print(f"{label:<21} {answer(irx.Module.from_ll(built))}")

# %% [markdown]
# ## Necessary, and then sufficient
#
# `-opt-disable` takes pass names and switches those off wherever they appear. Take `tailcallelim` out of an otherwise complete `-O2` and the crash comes back. Take out the pass that T05 counted eight times in the same string, which is not the one we are looking for, and nothing happens.
#
# That is the necessary half: without it, the rest of `-O2` cannot save this program. The sufficient half is the other direction.

# %% id=the_suspect_alone
alone = deep.opt("tailcallelim")

print("tailcallelim on its own:", answer(alone))
print("recursive calls to down left:", alone.body("down").count("call i32 @down"))
print()
print(alone.body("down").split("\ncond.true:")[0].rstrip())

# %% [markdown]
# ## One pass, out of a hundred and twenty, and the recursion is a loop
#
# `tailcallelim` on its own, with nothing else from `-O2`, is enough. The call is gone. In its place is a block called `tailrecurse` that the function branches back to, and two `phi` instructions at the top of it, one per parameter, exactly the shape T03 built by hand.
#
# That is what the transformation is. A call in tail position, whose result is returned unchanged, does not need a new frame: it can reuse this one, which makes it a jump to the top with new values for the parameters, which makes it a loop. The stack stops growing because there is nothing left to grow it.
#
# Note what has not happened. The `alloca`s are still there and so are the loads and stores, because `mem2reg` is not in this pipeline. One pass did one thing.
#
# ## What to keep
#
# `-opt-bisect-limit=N` caps how many pass runs are allowed and prints every run with a number, saying whether it ran or was skipped. `0` is the input, a large number is the full pipeline, and everything in between is a prefix.
#
# The count of runs is larger than the count of pipeline entries, because entries run per function and per loop.
#
# Because the cap is a prefix, any question you can ask of the output is monotone in the limit, so a binary search over the limit finds the exact run that changed the answer in about eight probes. The question can be anything you can automate: a crash, a wrong result, a missing instruction.
#
# Confirm the suspect from both sides. `-opt-disable=tailcallelim` takes it out of a full `-O2` and the crash comes back, and running it alone on the `-O0` IR is enough on its own, turning a recursive call into a `tailrecurse` block with a `phi` per parameter.
#
# Next: `-O2` on the same function twice in a row, and why the second run is not a no-op.
