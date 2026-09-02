"""Grades the boss fight. Call grade(pipeline, source) and read what it says."""

import irx

# gauss called with a spread of n, including one where the loop body never runs
# and one where it runs often enough that a wrong closed form is obvious.
DRIVER = """int printf(const char *, ...);
int main(void) {
  int cases[] = {0, 1, 2, 10, 1000, -5};
  for (int i = 0; i < 6; i++) printf("%d\\n", gauss(cases[i]));
  return 0;
}
"""
CASES = [0, 1, 2, 10, 1000, -5]
LIMIT = 4


def count(pipeline):
    """Top level passes. A comma inside brackets belongs to a nested pipeline."""
    depth, commas = 0, 0
    for char in pipeline:
        depth += (char == "(") - (char == ")")
        commas += char == "," and depth == 0
    return commas + 1


def loops(text):
    """Ask LLVM whether a loop is left, rather than looking for a branch.

    A fully optimised function is still full of branches, so reading the text
    for one would call almost anything a loop.
    """
    found = irx.run("opt", "-passes=print<loops>", "-disable-output", "-", stdin=text)
    return found.stderr.count("Loop at depth")


def opt(pipeline, text):
    out = irx.run("opt", f"-passes={pipeline}", "-S", "-", stdin=text, check=False)
    return out.stdout if out.ok else None


def answers(text):
    ran = irx.run("lli", "-", stdin=text, check=False)
    return ran.stdout.split() if ran.ok else None


def grade(pipeline, source):
    def no(why):
        print(f"not yet: {why}")
        return False

    if "default" in pipeline:
        return no(f"`{pipeline}` contains default, which is the pipeline you are taking apart.")
    if count(pipeline) > LIMIT:
        return no(f"`{pipeline}` is {count(pipeline)} passes and the limit is {LIMIT}.")

    after = opt(pipeline, irx.compile_c(source).text)
    if after is None:
        return no(f"opt would not run `{pipeline}`. Check the spelling against irx.passes().")
    left = loops(after)
    if left:
        return no(f"`{pipeline}` leaves {left} loop in gauss. Something has to make the loop "
                  "dead before anything will delete it.")

    runnable = irx.compile_c(source + DRIVER).text
    want = answers(runnable)
    mine = answers(opt(pipeline, runnable) or "")
    if mine is None or len(mine) != len(want):
        return no(f"the module `{pipeline}` produced does not run and print six answers.")
    for n, right, got in zip(CASES, want, mine):
        if right != got:
            return no(f"`{pipeline}` turns gauss({n}) from {right} into {got}.")

    print(f"solved: `{pipeline}` in {count(pipeline)} passes, no loop left, same answers.")
    return True
