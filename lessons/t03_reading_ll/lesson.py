# ---
# id: t03_reading_ll
# title: There are no variables, and the thing that replaces them happens all at once
# question: My loop variable is assigned every iteration, so how can the IR assign every register only once?
# part: I
# env: E0
# minutes: 35
# needs: [t01_one_line_of_c, t02_first_look_at_the_ir]
# ---

# %% [markdown]
# # There are no variables, and the thing that replaces them happens all at once
#
# Here is the rule everybody hears about LLVM IR first: it is in SSA form, which means every register is assigned exactly once and never again.
#
# Here is a loop that adds up the numbers below `n`. It assigns `total` on every iteration.
#
# Both of those are true, and getting from one to the other is what this lesson is about. The answer is an instruction called `phi`, and once you have seen one you will see them in every piece of optimised IR you ever read. The part that catches people is not what a `phi` is. It is when it happens, and we are going to get that wrong on purpose and then run the program to find out.

# %% id=the_loop_at_o0
SOURCE = """
int sum_to(int n) {
  int total = 0;
  for (int i = 0; i < n; i++)
    total += i;
  return total;
}
"""

loop = irx.compile_c(SOURCE, name="sum_to at -O0")
print(loop.body("sum_to"))

# %% [markdown]
# ## Five blocks, and not a `phi` in sight
#
# The shape is worth reading before the detail. Five blocks, and the comment after each label tells you which blocks can jump to it. `for.cond` says `; preds = %for.inc, %entry`, so it is reached both on the way in and once round the loop, which is what makes it the loop header. Those comments are generated, they are always right, and they are the fastest way to see a control flow graph without drawing one.
#
# There are two kinds of branch. `br label %for.cond` goes one place. `br i1 %cmp, label %for.body, label %for.end` takes a one bit condition and picks between two, true first. That is the whole of control flow at this level. No `if`, no `while`, no `for`. Blocks, and the two shapes of `br`.
#
# Now the SSA question. `%0` through `%5` are each assigned once, so the rule holds, and yet `total` changes on every iteration. It changes because `total` is not a register. It is `%total`, an `alloca`, a stack slot, and it is written with `store` and read with `load`.
#
# That is the trick, and it is worth saying plainly: **SSA applies to registers. It does not apply to memory.** A stack slot can be written as many times as you like. So a front end that puts every local in a stack slot never has to think about SSA at all, which is exactly why clang does it, and it is why the eight instruction `add` in T01 looked the way it did.
#
# The pass that undoes it is the one T01 named. Run it on its own.

# %% id=mem2reg
promoted = loop.opt("mem2reg", name="after mem2reg")
print(promoted.body("sum_to"))

# %% [markdown]
# ## The stack slots became two `phi` instructions
#
# Same five blocks, same branches, same control flow. Three `alloca`s and eight `load` and `store` instructions are gone, and in their place are two lines at the top of the loop header.
#
# ```llvm
# %total.0 = phi i32 [ 0, %entry ], [ %add, %for.inc ]
# ```
#
# Read a `phi` as a question about where you came from. Each bracket is a pair of a value and a block label. If control arrived here from `%entry`, `%total.0` is `0`. If it arrived from `%for.inc`, `%total.0` is `%add`. There is one pair for every block that can branch here, which is why it matches the `; preds =` comment exactly.
#
# That is the answer to the opening question. `total` is not one thing assigned many times. It is a different register on each trip round the loop, and the `phi` is what says which value this trip starts with. The name `%total.0` is a courtesy from `mem2reg`, which knows the slot was called `total`.
#
# So far a `phi` looks like a small conditional assignment, and if you read it as one you will be right about almost everything. Here is the case where you will be wrong.

# %% id=the_swap
SWAP = """
int alternate(int a, int b, int n) {
  for (int i = 0; i < n; i++) { int t = a; a = b; b = t; }
  return a;
}
"""

swap = irx.compile_c(SWAP, name="alternate").opt("mem2reg")
print(swap.body("alternate"))

# %% [markdown]
# ## Two `phi` instructions that refer to each other
#
# ```llvm
# %b.addr.0 = phi i32 [ %b, %entry ], [ %a.addr.0, %for.inc ]
# %a.addr.0 = phi i32 [ %a, %entry ], [ %b.addr.0, %for.inc ]
# ```
#
# Look at the first line. It uses `%a.addr.0`, which is defined on the line below it. For any other instruction in LLVM that is illegal, and we will make the verifier say so in a minute.
#
# Now read the two lines as assignments, in order, the way you would read them in C, and work out what `alternate(10, 20, 1)` returns.
#
# Coming round the loop the second time, from `%for.inc`. `%b.addr.0` takes `%a.addr.0`, which is `10`. Then `%a.addr.0` takes `%b.addr.0`, which the line above set to `10`. Both are `10`. The swap did not swap; it clobbered. `a` comes back as `10`, and no number of further iterations changes it.
#
# Write down whether you believe that before running the next cell. It executes the IR, with `lli`, so this is not a prediction about what should happen.

# %% id=run_it
# A main that calls alternate and hands its answer back as the exit code, so we
# can read the answer without needing printf.
MAIN = """
define i32 @main() {
  %r = call i32 @alternate(i32 10, i32 20, i32 1)
  ret i32 %r
}
"""

for iterations in (1, 2, 3):
    main = MAIN.replace("i32 1)", f"i32 {iterations})")
    result = irx.run("lli", "-", stdin=swap.text + main, check=False)
    print(f"alternate(10, 20, {iterations}) = {result.code}")

# %% [markdown]
# ## It swaps
#
# One iteration gives `20`, two give `10`, three give `20`. It alternates, which is what the C says and what reading the `phi`s in order says is impossible.
#
# The `phi` instructions in a block do not run one after another. They all happen at once, on the edge you arrived on, and every one of them reads the values as they were in the block you came from. LangRef puts it as the use of each incoming value being deemed to occur on the edge from the predecessor block to this one, rather than at the point in the block where the `phi` is written.
#
# That single sentence explains both oddities. It explains the swap, because on that edge `%a.addr.0` still holds the previous trip's value when `%b.addr.0` reads it. And it explains the dominance question, because if the use happens on the edge then it is not a use inside this block at all, so there is nothing for the definition to have to come before.
#
# It is worth carrying the picture rather than the wording. The `phi`s at the top of a block are not instructions in a sequence. They are a description of what the block is handed when it is entered, and which set of values it is handed depends on the door you came in through.
#
# Two rules follow, and LLVM enforces both.

# %% id=the_two_rules
# One: an ordinary instruction may not use a value defined below it.
USE_BEFORE_DEF = """
define i32 @f(i32 %n) {
entry:
  %a = add i32 %b, 1
  %b = add i32 %n, 1
  ret i32 %a
}
"""

# Two: a phi may not have an ordinary instruction above it in its block.
LATE_PHI = """
define i32 @f(i32 %n) {
entry:
  br label %L
L:
  %x = add i32 %n, 1
  %p = phi i32 [ 0, %entry ]
  ret i32 %p
}
"""

for label, text in (("a use above its definition", USE_BEFORE_DEF),
                    ("a phi below an add", LATE_PHI)):
    stderr = irx.run("opt", "-passes=verify", "-disable-output", "-",
                     stdin=text, check=False).stderr
    print(f"{label}:")
    print("  " + stderr.strip().splitlines()[0])

# %% [markdown]
# ## `PHI nodes not grouped at top of basic block!`
#
# The first rule is the ordinary SSA one, and the message names it: the definition has to dominate every use, which for two instructions in one block means it has to come first.
#
# The second is the rule that makes the first one safe to break. Because the `phi`s are all at the very top, with nothing before them, there is never any question about what "the values from the predecessor" means. Let one ordinary instruction sit above a `phi` and that stops being well defined, so the verifier does not let you.
#
# The two rules are one design. `phi` is exempt from dominance, and the price of the exemption is that `phi`s must be first.
#
# ## Reading `.ll` from here
#
# You now have enough to read most optimised IR. The routine that works:
#
# Read the block labels and their `; preds =` comments first and get the shape. Loops announce themselves, because a loop header is a block one of whose predecessors is below it.
#
# Read the `phi`s at the top of each block as the block's parameters, one entry per incoming edge.
#
# Read everything else top to bottom as ordinary straight line code, because within a block it is exactly that, and every value it names is defined above it or in a block that dominates it.
#
# ## What to keep
#
# SSA is about registers. Memory is not in SSA and never was, which is why a front end can emit correct IR without thinking about SSA at all, and why `mem2reg` and `SROA` are the passes that everything else depends on running first.
#
# A `phi` says which value the block gets, depending on which block control came from, with one pair per predecessor.
#
# The `phi`s at the top of a block all take effect together, on the edge into the block. That is why two of them can swap a pair of values, and why one may name a value defined below it.
#
# Next: two hundred passes run when you type `-O2`, and finding out which one changed your function is harder than it sounds.
