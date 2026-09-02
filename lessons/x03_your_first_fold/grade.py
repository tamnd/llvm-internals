"""Grades the boss fight. Build your pass, then call grade("yourpassname").

Three cases, and a solver has the last word on all of them. The structural check
comes first because "your pass did not fire" and "your pass fired and was wrong"
are different problems with different fixes, and a message that confuses the two
sends a reader off to debug the wrong half of their code.
"""

import irx

AND_FORM = """define i32 @f(i32 noundef %a, i32 noundef %b) {
  %c = icmp sgt i32 %a, 0
  %sh = shl i32 %a, %b
  %x = icmp sgt i32 %sh, 5
  %r = select i1 %c, i1 %x, i1 false
  %z = zext i1 %r to i32
  ret i32 %z
}
"""

OR_FORM = """define i32 @f(i32 noundef %a, i32 noundef %b) {
  %c = icmp sgt i32 %a, 0
  %sh = shl i32 %a, %b
  %x = icmp sgt i32 %sh, 5
  %r = select i1 %c, i1 true, i1 %x
  %z = zext i1 %r to i32
  ret i32 %z
}
"""

# Neither arm is a constant, so there is nothing here a peephole should touch.
NEITHER = """define i32 @f(i32 noundef %a, i32 noundef %b, i32 noundef %c) {
  %p = icmp sgt i32 %a, 0
  %q = icmp sgt i32 %b, 0
  %s = icmp sgt i32 %c, 0
  %r = select i1 %p, i1 %q, i1 %s
  %z = zext i1 %r to i32
  ret i32 %z
}
"""

CASES = [
    ("select %c, %x, false", AND_FORM, "and", "an and"),
    ("select %c, true, %x", OR_FORM, "or", "an or"),
    ("select %c, %x, %y", NEITHER, "select", "left alone"),
]


def has(text, op):
    """Whether the function ends up with this operation in it.

    Substring matching would find the `or` inside `%or.cond` and the `and`
    inside a name somebody chose, so the operation has to be read as the word
    after the equals sign.
    """
    for line in text.splitlines():
        if " = " in line and line.split(" = ", 1)[1].split(" ")[0] == op:
            return True
    return False


def grade(pass_name):
    def no(why):
        print(f"not yet: {why}")
        return False

    for label, before, want, described in CASES:
        ran = irx.run("opt", *irx.plugin.load_flags(), f"-passes={pass_name}",
                      "-S", "-", stdin=before, check=False)
        if not ran.ok:
            return no(f"opt would not run `{pass_name}`. Build the plugin cell above first, "
                      f"and check the name you registered matches the name you passed here.")
        after = ran.stdout

        if not has(after, want):
            got = "an and" if has(after, "and") else "an or" if has(after, "or") else "a select"
            return no(f"`{label}` should end up as {described} and your pass left {got}.")

        report = irx.alive(before, after, verbose=False)
        if not len(report):
            return no(f"Alive2 had nothing to say about `{label}`, which usually means the "
                      f"function got renamed. Keep the name @f.")

        result = report[0]
        if result.status == "timeout":
            return no(f"Alive2 ran out of time on `{label}`, so nothing was proved either way. "
                      f"These functions are small, so this is worth reporting as a bug.")
        if result.status == "error":
            return no(f"Alive2 failed on `{label}`: {result.kind}.")
        if result.status == "wrong":
            inputs = ", ".join(f"{name} = {value}" for name, value in result.example)
            return no(f"`{label}`: {result.kind.lower()}. It breaks on {inputs}. "
                      f"Your version gives {result.target[-1][1]} where the original gives "
                      f"{result.source[-1][1]}.")

    print(f"solved: `{pass_name}` folds both shapes, leaves the third alone, "
          f"and Alive2 verified all three.")
    print("That is a proof for these three functions at this width, and not a proof "
          "that your pass is correct in general.")
    return True
