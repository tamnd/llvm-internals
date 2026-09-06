# ---
# id: z04_what_the_book_may_say
# title: Observed, cited, inferred
# question: The book keeps telling me things. How does it know, and how do I know it knows?
# part: 0
# env: E0
# minutes: 30
# needs: [z01_two_lines_at_the_top, z03_going_and_looking]
# ---

# %% [markdown]
# # Observed, cited, inferred
#
# Z03 was about the address on a claim. This one is about the claim.
#
# Every lesson in this book has a `claims.yaml` next to it, and every factual sentence the lesson makes is in it with one of three words attached. `observed` means somebody ran it. `cited` means it is written down in LLVM at the pinned tag, at the line given. `inferred` means neither, and a lesson is allowed at most three.
#
# Three words rather than one, because they are three different kinds of true and they fail in different ways. This lesson takes one small question, answers it all three ways, and shows you where the answers stop agreeing. That is the last thing before Part I.

# %% id=the_observation
import urllib.request

SOURCE = """
int with_signed(int x)        { return x + 1 > x; }
unsigned with_unsigned(unsigned x) { return x + 1 > x; }
"""

optimised = irx.compile_c(SOURCE, name="overflow", opt="-O2")
for name in ("with_signed", "with_unsigned"):
    print(optimised.body(name), "\n")

# %% [markdown]
# ## Two facts and no reason
#
# The two functions are the same question in two types. `x + 1 > x` is either always true or false exactly once, depending on what happens at the top of the range, and the compiler gives different answers.
#
# The signed one is `ret i32 1`. There is no addition and no comparison left, and nothing that depends on `x` at all. The unsigned one keeps a real comparison against the largest value it can hold, because `x + 1 > x` is false there, and one input out of four billion is enough to stop the fold.
#
# You have now observed something. Note carefully what you have and have not got. You have got what this compiler did on this machine in this run. You have not got a reason, you have not got a rule, and you have not got any promise that the next release does the same. An observation is a fact with no scope on it, and a book made of nothing else is a book that is right by accident.
#
# The reason is visible one flag lower down, before any optimiser has run.

# %% id=where_it_came_from
def the_add(module, name):
    """The one addition in a function, at whatever optimisation level built it."""
    return next(ln.strip() for ln in module.body(name).splitlines() if " add " in ln)


plain = irx.compile_c(SOURCE, name="overflow-O0")
for name in ("with_signed", "with_unsigned"):
    print(f"  {name:<15} {the_add(plain, name)}")

# %% [markdown]
# ## One keyword
#
# `add nsw` in the first, plain `add` in the second, both at `-O0` with the optimiser switched off entirely. The front end put that flag there while building the IR, which means the difference was decided by the language rules before any pass was in a position to have an opinion.
#
# So the fold is not the optimiser being clever about signed integers. It is the optimiser being told something about this particular addition, and believing it. The next question is what exactly it was told, and that question has an address.

# %% id=gate_which_word
irx.gate(
    "This book wants to write down: \"clang folds `x + 1 > x` to a constant for `int` and does "
    "not for `unsigned`\". Which word does that sentence get?",
    {
        "`observed`": "You ran it and it printed that. It is the strongest thing you can say "
                      "about a sentence describing what a compiler did, and it is a claim about "
                      "this build rather than about LLVM.",
        "`cited`": "It is not written down anywhere in LLVM in that form. LangRef defines what "
                   "`nsw` means; no document promises what clang emits for a particular C "
                   "expression, which is why running it is the only way to know.",
        "`inferred`": "Inference is for a conclusion you reason your way to. This one you did "
                      "not reason about, you watched it happen, and calling it inferred would "
                      "understate the evidence.",
        "It does not need a word": "Every factual sentence gets one. A sentence with no word is "
                                   "how a book fills up with things everybody assumes and "
                                   "nobody checked.",
    },
    answer="`observed`",
    note="Observed, and the citation field says which two machines and what they printed. "
         "The rule underneath it is a different claim with a different word.",
)

# %% id=the_rule
TAG = irx.toolchain.TAG
RAW = "https://raw.githubusercontent.com/llvm/llvm-project"

with urllib.request.urlopen(f"{RAW}/{TAG}/llvm/docs/LangRef.md", timeout=30) as response:
    langref = response.read().decode("utf-8").splitlines()

for line in langref[10670:10674]:
    print(" ", line)

# %% [markdown]
# ## The rule, at an address
#
# `llvm/docs/LangRef.md:10671-10674@llvmorg-23.1.0`, fetched the way Z03 fetched things. If `nsw` is present, the result of the `add` is a poison value when signed overflow occurs.
#
# That is the cited half, and it is a different shape from the observed half. It does not say what any compiler does. It says what the flag means, which leaves the optimiser free to fold on the assumption that the overflowing case never happens, because a program that reaches it has already lost the right to expect anything. Part II is about what that sentence really costs; here the point is only that the sentence exists, has a number, and is the durable part.
#
# The observation is evidence that clang uses the rule. The citation is evidence that the rule is there to be used. Neither one is the other, and a book that ran the first and wrote it up as though it were the second is a book that will be wrong the first time somebody changes a heuristic.
#
# There is a way to check that the two are connected rather than merely both true.

# %% id=the_control
wrapping = irx.compile_c(SOURCE, name="wrapv", extra=("-fwrapv",))
print("at -O0 with -fwrapv:")
for name in ("with_signed", "with_unsigned"):
    print(f"  {name:<15} {the_add(wrapping, name)}")

folded = irx.compile_c(SOURCE, name="wrapv-O2", opt="-O2", extra=("-fwrapv",))
print("\nand the same -O2 as before:")
print(folded.body("with_signed"))

# %% [markdown]
# ## Take the rule away and the fold goes with it
#
# `-fwrapv` tells clang that signed overflow wraps rather than being undefined. The `nsw` disappears at `-O0`, and at `-O2` the signed function stops folding and turns into the same comparison the unsigned one had, against the largest `int` instead of the largest `unsigned`.
#
# Nothing about the optimiser changed between the two runs. One keyword's worth of permission changed, and the output changed with it, which is a considerably stronger piece of evidence than either half on its own. A claim that survives having its cause removed is a claim you understand.
#
# This is the shape the book tries to hit whenever it can afford it: watch it happen, find the rule that licenses it, then remove the rule and watch it stop.
#
# ## Writing it down
#
# Those three cells are three claims, and here is what they look like in the file next to this lesson, with the checks `tools/refcheck.py` runs on them written out small.

# %% id=the_ledger_entry
PIN = irx.toolchain.TAG
WORDS = ("observed", "cited", "inferred")

entries = [
    {"id": "signed-folds-and-unsigned-does-not", "confidence": "observed",
     "citation": "measured on macOS arm64 and Linux x86_64, both LLVM 23.1.0"},
    {"id": "nsw-means-poison-on-overflow", "confidence": "cited",
     "citation": f"llvm/docs/LangRef.md:10671-10674@{PIN}"},
    {"id": "removing-the-flag-removes-the-fold", "confidence": "observed",
     "citation": "measured on both hosts with and without -fwrapv"},
]

for entry in entries:
    trouble = []
    if entry["confidence"] not in WORDS:
        trouble.append(f"{entry['confidence']} is not one of {', '.join(WORDS)}")
    if entry["confidence"] == "cited" and "@" not in entry["citation"]:
        trouble.append("cited, but the citation is a sentence rather than a pointer")
    for tag in [p.split(",")[0] for p in entry["citation"].split("@")[1:]]:
        if tag != PIN:
            trouble.append(f"pinned to {tag}, but this build is {PIN}")
    print(f"  {entry['id']:<36} {'; '.join(trouble) or 'ok'}")

print(f"\n{sum(e['confidence'] == 'inferred' for e in entries)} inferred, and at most 3 are allowed")

# %% [markdown]
# ## The third word
#
# Nothing in this lesson is `inferred`, which is the normal case. It is the word for a sentence the book believes, cannot run, and cannot point at: a reason why something was designed the way it was, a statement about what usually happens across many programs, a conclusion drawn from two cited facts that no single document states.
#
# Those sentences are worth writing. They are also the ones most likely to be wrong, and they are invisible in prose, because a confident paragraph reads the same whether it rests on a measurement or on a plausible story. So they get counted. Three to a lesson, enforced by a script, and the effect of the cap is not that inference is forbidden but that it has to be worth the slot.
#
# The other effect is on you. When a lesson tells you something surprising, the ledger tells you in one column how hard it would be to check, and the honest answer is sometimes that the author reasoned it out and you should go and look yourself.
#
# ## What the machinery adds up to
#
# `docs/claims.md` is every claim in the book in one table, generated from the `claims.yaml` files and checked in, so it is one file to read and CI fails when it does not match its source. `refcheck` reads the same files and checks that every cell an evidence field names exists, that every citation carries the pinned tag, that a cited claim has a pointer rather than a sentence, and with a source tree, that the line range is inside the file it names. `prosecheck` reads the prose. `build.py check` reads the lessons. All four run on every change.
#
# None of that makes the book true. It makes the book checkable, which is the strongest thing tooling can do, and the difference matters: every one of these scripts can be satisfied by a claim that is confidently wrong at a line number that exists. What they buy is that a wrong claim stays findable, keeps its evidence attached, and cannot quietly drift away from the thing it was about.
#
# ## What to keep
#
# Three words. `observed` is a fact about a run, and this book's observed claims were run on two machines with different architectures, because a fact from one host is a fact about that host. `cited` is a fact about the pinned tree, at a line you can fetch. `inferred` is neither, is capped at three, and is where to be suspicious.
#
# An observation and a citation answer different questions. What happened, and what is guaranteed. Running something once tells you nothing about the next release; the rule at the address is the part with a scope on it.
#
# When you can, remove the cause and check that the effect goes away. A negative control costs one more compile and is worth more than both halves of the evidence it joins.
#
# That is Part 0. You have a pinned toolchain that tells you what it is, enough C++ to read LLVM's, a way to turn any claim into a URL, and the rules this book holds itself to.
#
# Next: Part I, which starts by asking what `-O2` actually is.
