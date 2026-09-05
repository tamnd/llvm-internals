## What this changes

<!-- One or two sentences. What a reader gets that they did not have before. -->

## Checks

- [ ] `python tools/prosecheck.py .` is clean
- [ ] `python tools/refcheck.py` is clean, and `--ledger` leaves `docs/claims.md` unchanged
- [ ] No number in the prose was typed by hand
- [ ] Every citation is `path:line@llvmorg-23.1.0` and resolves
- [ ] Any claim about what is default, experimental or in progress carries a date and the command that establishes it
- [ ] Any Alive2 result is described as bounded verification and not as a proof

## For a lesson

- [ ] Notebook regenerated from the lesson source, not hand edited
- [ ] Runs cold, top to bottom, from the Colab badge
- [ ] Every `env=E1` cell has a replay recording
- [ ] Every widget has a working static fallback
- [ ] Boss fight has a grader and the failure message names the input
- [ ] Beginner review
- [ ] Expert review

## For a blueprint

- [ ] All nine sections, no reference to the chapter
- [ ] `bpc` regenerates with no diff
- [ ] Refinement obligation runs in CI and publishes a dated status
