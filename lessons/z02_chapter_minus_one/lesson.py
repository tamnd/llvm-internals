# ---
# id: z02_chapter_minus_one
# title: Chapter minus one, the C++ that exists so you can read LLVM's C++
# question: I do not write C++. Can I still read a pass?
# part: 0
# env: E0
# minutes: 60
# needs: [z01_two_lines_at_the_top]
# ---

# %% [markdown]
# # Chapter minus one, the C++ that exists so you can read LLVM's C++
#
# This is not a C++ course, and finishing it will not make you a C++ programmer. It has one target, and here it is: `llvm/lib/Transforms/Scalar/DCE.cpp`, which is dead code elimination, one of the smallest real passes in the tree. This is the function that drives it, with its two comments taken out for space:
#
# ```cpp
# static bool eliminateDeadCode(Function &F, TargetLibraryInfo *TLI) {
#   bool MadeChange = false;
#   SmallSetVector<Instruction *, 16> WorkList;
#   for (Instruction &I : llvm::make_early_inc_range(instructions(F))) {
#     if (!WorkList.count(&I))
#       MadeChange |= DCEInstruction(&I, WorkList, TLI);
#   }
#
#   while (!WorkList.empty()) {
#     Instruction *I = WorkList.pop_back_val();
#     MadeChange |= DCEInstruction(I, WorkList, TLI);
#   }
#   return MadeChange;
# }
# ```
#
# By the end of this lesson that is readable, and the pass it comes from is readable, and so is most of the rest of the tree, because LLVM writes in a small and consistent subset of C++ and repeats it everywhere.
#
# If you already write C++, take the gate below. If you get it without effort, skip to Z03 and lose nothing.

# %% id=gate_skip
irx.gate(
    "In that function, what is the difference between `Function &F` and `Instruction *I`?",
    {
        "One is a reference and cannot be null, the other is a pointer and can": "That is the "
            "convention, it is enforced by the language for the reference and by habit for the "
            "pointer, and it is most of what LLVM's ampersands and asterisks are telling you. "
            "If that was obvious, skip to Z03.",
        "One is passed by value, the other by address": "A reference is not a copy. Both of them "
            "refer to an object that lives somewhere else, which is the point of using either.",
        "One is const and the other is not": "Neither is const here. `const` is written down when "
            "it is meant, and it is absent from both of these.",
        "One is a template parameter": "No angle brackets in either. `SmallSetVector<Instruction "
            "*, 16>` on the line above is the template.",
    },
    answer="One is a reference and cannot be null, the other is a pointer and can",
    note="Everything else in this lesson is at that level, and the last cell is that pass in full.",
)

# %% id=cpp_runs_here
# Every snippet below is compiled by the pinned clang and run by lli, with no C++
# library linked, which is why they all print with printf rather than with cout.
PRELUDE = "#include <cstdio>\n"


def cpp(source, *flags):
    """Compile this C++ with the pinned clang and run it, giving back what it printed."""
    text = irx.run("clang", "-x", "c++", "-std=c++17", "-fno-exceptions", "-fno-rtti",
                   *flags, "-S", "-emit-llvm", "-o", "-", "-", stdin=PRELUDE + source).stdout
    return irx.run("lli", "-", stdin=text).stdout


print(cpp('int main() { printf("the pinned clang compiles C++ too\\n"); return 0; }'), end="")

# %% [markdown]
# ## Two flags that are not incidental
#
# `-fno-exceptions` and `-fno-rtti` are there because LLVM is built that way. No `try`, no `throw`, no `dynamic_cast`, no `typeid`. So two of the C++ features a course would spend a week on are ones you will never meet in this tree, and one of them, `dynamic_cast`, is replaced by something LLVM wrote itself, which you will meet constantly and which gets its own section below.
#
# ## The asterisk and the ampersand
#
# Almost every parameter in LLVM is one of three things: a value, a reference, or a pointer. The difference is the first thing to be able to read.

# %% id=pointers_and_references
print(cpp("""
struct Function { int size; };

void byValue(Function f)      { f.size = 99; }
void byReference(Function &f) { f.size = 99; }
void byPointer(Function *f)   { if (f) f->size = 99; }

int main() {
  Function a{1}, b{1}, c{1};
  byValue(a);
  byReference(b);
  byPointer(&c);
  printf("by value %d, by reference %d, by pointer %d\\n", a.size, b.size, c.size);

  byPointer(nullptr);
  printf("and a null pointer was a legal thing to pass\\n");
  return 0;
}
"""), end="")

# %% [markdown]
# ## What the three of them mean when you see them in a signature
#
# `Function f` copies. The function got its own `Function` and the caller's is untouched, which is why `a` is still 1. LLVM almost never does this for anything bigger than an integer or a `StringRef`, so if you see a plain type in a parameter list it is usually a small one on purpose.
#
# `Function &f` is a reference. It is another name for the caller's object, so writing through it changes the caller's, and there is no such thing as a null reference. That is the whole message of `Function &F` in the DCE code: this function exists, you did not have to check, and the compiler will not let you pass nothing.
#
# `Function *f` is a pointer, an address. It can be null, and `byPointer(nullptr)` above passes nothing at all and returns quietly. Reading through a pointer needs `->` instead of `.`, which is the one piece of punctuation that tells you which of the two you are looking at without going back to the declaration.
#
# So `DCEInstruction(&I, WorkList, TLI)` reads as: take the address of this instruction, because the callee's parameter is a pointer, and hand the work list over by reference so the callee's insertions land in ours.
#
# `const` is the fourth word in the same sentence.

# %% id=const_is_a_promise
refused = irx.run("clang", "-x", "c++", "-std=c++17", "-fsyntax-only", "-", check=False, stdin="""
struct Instruction { int opcode; };
void look(const Instruction &I) { I.opcode = 0; }
""")

print("exit code:", refused.code)
print((refused.stderr or "").strip().splitlines()[0])

# %% [markdown]
# ## `const` is checked, not documentation
#
# `const TargetLibraryInfo *TLI` in the DCE signature says the pass reads that information and does not change it, and the compiler enforces it. When you are reading an unfamiliar function, the `const` on its parameters is a free summary of which of them it might write to, and it is one of the few comments in C++ that cannot go stale.
#
# Read `const Instruction &I` as "an instruction that is definitely there and that I will not modify", and `Instruction *I` as "an instruction that might not be there and that I might modify".
#
# ## Angle brackets
#
# `SmallSetVector<Instruction *, 16>` has two things in the brackets and only one of them is a type.

# %% id=templates_are_stencils
print(cpp("""
template <class T, unsigned N>
struct SmallVector {
  T items[N];
  unsigned count = 0;
  void push_back(T value) { if (count < N) items[count++] = value; }
  T *begin() { return items; }
  T *end() { return items + count; }
};

int main() {
  SmallVector<int, 4> numbers;
  numbers.push_back(2);
  numbers.push_back(3);
  numbers.push_back(5);

  int total = 0;
  for (int &value : numbers)
    total += value;

  printf("%u values, total %d, sizeof %zu bytes and not one of them on the heap\\n",
         numbers.count, total, sizeof(numbers));
  return 0;
}
"""), end="")

# %% [markdown]
# ## A template is a stencil, and the brackets fill it in
#
# `SmallVector<int, 4>` is not a class. `SmallVector` is a stencil, and writing `<int, 4>` makes the compiler stamp out a real class where every `T` is `int` and every `N` is 4. Write `<double, 8>` next to it and you get a second, unrelated class from the same stencil. This is why LLVM's headers are full of code that appears to have no types in it.
#
# The `4` is the point of the real `SmallVector`. The elements live inside the object, so a vector of four things does no allocation at all, and it only reaches for the heap if you push a fifth. That is the trade the name is announcing, and `SmallSetVector<Instruction *, 16>` in the DCE pass is saying that most functions have fewer than sixteen newly dead instructions at a time and that the common case should not touch the allocator.
#
# The loop is the other thing to read. `for (int &value : numbers)` visits every element, and the `&` means `value` is the element rather than a copy of it, so assigning to it would change the vector. That is exactly `for (Instruction &I : ...)`, and it is why that loop can modify the function it is walking.
#
# A range based `for` needs `begin()` and `end()` and nothing else, which is why LLVM can hand you `instructions(F)` and have it work in a loop even though there is no container of that name anywhere.
#
# ## The one LLVM idiom you cannot avoid
#
# `dynamic_cast` is off. LLVM replaced it, in a way you can write in twenty lines.

# %% id=the_cast_family
print(cpp("""
struct Value {
  enum Kind { VK_Argument, VK_Instruction };
  const Kind kind;
  Value(Kind k) : kind(k) {}
  Kind getKind() const { return kind; }
};

struct Instruction : Value {
  int opcode;
  Instruction(int op) : Value(VK_Instruction), opcode(op) {}
  static bool classof(const Value *V) { return V->getKind() == VK_Instruction; }
};

template <class To> bool isa(const Value *V)     { return To::classof(V); }
template <class To> To *cast(Value *V)           { return (To *)V; }
template <class To> To *dyn_cast(Value *V)       { return isa<To>(V) ? cast<To>(V) : nullptr; }

int main() {
  Instruction add(11);
  Value argument(Value::VK_Argument);

  Value *both[] = {&add, &argument};
  for (Value *V : both) {
    if (Instruction *I = dyn_cast<Instruction>(V))
      printf("an instruction, opcode %d\\n", I->opcode);
    else
      printf("not an instruction, and dyn_cast said so by returning null\\n");
  }
  printf("isa says %d and %d\\n", isa<Instruction>(&add), isa<Instruction>(&argument));
  return 0;
}
"""), end="")

# %% [markdown]
# ## `isa`, `cast`, `dyn_cast`
#
# Three functions, and the difference between them is what happens when you are wrong.
#
# `isa<Instruction>(V)` asks and gives you a `bool`. `cast<Instruction>(V)` asserts: you are telling the compiler you already know, and in a build with assertions on you get a crash with a message if you did not. `dyn_cast<Instruction>(V)` asks and converts in one step, giving you a pointer or null.
#
# Which makes this line, which you will see thousands of times, one thing rather than two:
#
# ```cpp
# if (Instruction *OpI = dyn_cast<Instruction>(OpV))
# ```
#
# It declares `OpI` inside the `if`, and the `if` tests whether that pointer is non null. So the body runs only when the cast worked, and `OpI` is not in scope anywhere it could be null. Written with `auto *` instead of the type, which LLVM does about as often, it is the same line.
#
# The machinery under it is the `classof` in the toy above. Every class in the hierarchy knows how to recognise itself from a kind tag stored in the base, which is a switch on an integer rather than anything the C++ runtime does, and that is how LLVM gets a type test that costs almost nothing in a build with no RTTI at all.
#
# The real thing has more members of the family, and one of them is worth knowing about because the difference is easy to miss.

# %% id=gate_dyn_cast
irx.gate(
    "`V` might be null. What does `dyn_cast<Instruction>(V)` do?",
    {
        "Nothing good, it is undefined behaviour": "`dyn_cast` asserts that its argument is non "
            "null. The one that accepts null and returns null is `dyn_cast_if_present`, and "
            "confusing the two is a real bug people write.",
        "Returns null, which is the point of it": "That is what it does when the type is wrong. A "
            "null argument is a different situation and it is not the one `dyn_cast` handles.",
        "Returns a null pointer of the target type": "There is no such thing, and the question is "
            "about the argument rather than the result.",
        "Throws": "Exceptions are off in this tree, and the compile flags at the top of this "
            "lesson turn them off too.",
    },
    answer="Nothing good, it is undefined behaviour",
    note="isa_and_present, cast_if_present and dyn_cast_if_present are the null tolerant ones.",
)

# %% id=the_view_does_not_own
print(cpp("""
class StringRef {
  const char *Data;
  unsigned Length;
public:
  StringRef(const char *s) : Data(s), Length(0) { while (s[Length]) ++Length; }
  const char *data() const { return Data; }
  unsigned size() const { return Length; }
  StringRef drop_front(unsigned n) const {
    StringRef result(*this);
    result.Data += n;
    result.Length -= n;
    return result;
  }
};

int main() {
  const char buffer[] = "loop-idiom-vectorize";
  StringRef whole(buffer);
  StringRef tail = whole.drop_front(5);

  printf("%.*s then %.*s\\n", (int)whole.size(), whole.data(), (int)tail.size(), tail.data());
  printf("the tail copied nothing: %d\\n", tail.data() == buffer + 5);
  printf("a StringRef is %zu bytes whatever it points at\\n", sizeof(StringRef));
  return 0;
}
"""), end="")

# %% [markdown]
# ## A `StringRef` is a pointer and a length, and it owns nothing
#
# `drop_front` returned a new `StringRef` and copied no characters, because both of them point into the same buffer. That is the whole idea, and `ArrayRef<T>` is the same idea for arrays of anything else.
#
# It buys speed and it costs you one thing to remember: a view is only valid while the thing it views is. A `StringRef` into a string that has since been freed is a dangling pointer with a friendly name on it, and this is the single most common way to write a real bug in LLVM code. When you see a function returning `StringRef`, the question to ask is what it points into and how long that lives.
#
# ## Now read the pass
#
# Here is `DCEInstruction`, the other half of the file this lesson opened with, unedited:
#
# ```cpp
# static bool DCEInstruction(Instruction *I,
#                            SmallSetVector<Instruction *, 16> &WorkList,
#                            const TargetLibraryInfo *TLI) {
#   if (isInstructionTriviallyDead(I, TLI)) {
#     if (!DebugCounter::shouldExecute(DCECounter))
#       return false;
#
#     salvageDebugInfo(*I);
#     salvageKnowledge(I);
#
#     // Null out all of the instruction's operands to see if any operand becomes
#     // dead as we go.
#     for (unsigned i = 0, e = I->getNumOperands(); i != e; ++i) {
#       Value *OpV = I->getOperand(i);
#       I->setOperand(i, nullptr);
#
#       if (!OpV->use_empty() || I == OpV)
#         continue;
#
#       // If the operand is an instruction that became dead as we nulled out the
#       // operand, and if it is 'trivially' dead, delete it in a future loop
#       // iteration.
#       if (Instruction *OpI = dyn_cast<Instruction>(OpV))
#         if (isInstructionTriviallyDead(OpI, TLI))
#           WorkList.insert(OpI);
#     }
#
#     I->eraseFromParent();
#     ++DCEEliminated;
#     return true;
#   }
#   return false;
# }
# ```
#
# Line by line, with nothing in it that has not been in this lesson. It takes an instruction by pointer, a work list by reference so its insertions are visible to the caller, and library information it promises not to modify. If `isInstructionTriviallyDead` says no, it returns false and nothing happens.
#
# Otherwise it clears each operand in turn, and after each one asks whether the value that operand pointed at now has no users left. If it does not, and it is an instruction, it goes on the work list to be looked at later. `salvageDebugInfo(*I)` takes a reference, which is why there is a star in front of `I`: the pointer is being turned back into a reference for a function that wants one. Then the instruction removes itself from its parent block, a counter goes up, and it returns true.
#
# The one thing not covered here is `DebugCounter`, which is a debugging facility for limiting how many times a transformation is allowed to fire, and which T07 met from the outside under a different name.
#
# ## What to keep
#
# LLVM is built with `-fno-exceptions -fno-rtti`, so there is no `try`, no `throw`, no `dynamic_cast` and no `typeid` anywhere in this tree.
#
# A plain type copies. `T &` is another name for somebody else's object and can never be null. `T *` is an address, can be null, and is read through with `->`. `const` on a parameter is a promise the compiler enforces.
#
# `Name<T, N>` is a stencil being filled in. `SmallVector<int, 4>` stores its elements inside itself and only allocates when it outgrows them.
#
# `for (Instruction &I : whatever)` needs only `begin()` and `end()` to exist, and the `&` means you are looking at the element rather than a copy of it.
#
# `isa<T>(V)` asks, `cast<T>(V)` asserts, `dyn_cast<T>(V)` asks and converts and returns null when the answer is no. All three assert that `V` itself is non null; the `_if_present` versions are the ones that do not. `if (auto *I = dyn_cast<T>(V))` is the idiom, and it is everywhere.
#
# `StringRef` and `ArrayRef<T>` are a pointer and a length. They copy nothing and own nothing, and they are valid only as long as what they point at is.
#
# Next: where all of this lives, and how to find the file a claim came from.
