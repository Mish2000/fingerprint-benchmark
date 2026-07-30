# 0025 — The cyclic same-subject impostor set is a sanity check, not an FMR experiment

## Status

Accepted. Implemented in `fpbench.evaluation.views` and enforced by
`require_honest_view_name`.

## Context

The protocol's fifth step compares plain finger *i* with rolled finger *i+1* of the same
subject, wrapping at ten, and expects 0% matches. It is a good check: if a matcher fires
on two obviously different fingers, something is badly wrong, and the expected answer is
known in advance.

It is also, structurally, a set of 1,500 non-mated comparisons with decisions attached —
which is exactly the shape of a false-match-rate calculation. Dividing one by the other
would produce a number, the number would look like an FMR, and it would be wrong in ways
that are invisible from the number itself:

* **Closed set.** 50 subjects, chosen once. An FMR is a statement about a population; this
  is a statement about these fifty people.
* **Same subject on both sides.** Impostor comparisons within one person are not
  representative of impostor comparisons between people, and the literature is not
  agreed on which direction the bias runs.
* **One fixed pairing.** Finger *i* against finger *i+1*, one shift, one direction. Not
  all 4,500 available negative pairings, and not a random sample of them.
* **No confidence interval is possible** from a design nobody chose for estimation.

[ADR 0008](0008-non-mated-pairing-strategy.md) recorded that this pairing is an
assumption still open for the supervisor. That makes labelling it correctly more
important, not less.

## Decision

**The view is named for what it is, records what it is not, and the name is enforced.**

The view kind is `plain_roll_non_mated_same_subject_cyclic_v1` — subject, strategy and
version, no rate anywhere in it. Its manifest carries policy metadata that reaches its own
fingerprint:

```yaml
negative_kind: same_subject_different_finger
pairing_strategy: cyclic_finger_shift
finger_shift: 1
closed_set: true
primary_fmr_estimate: false
purpose: negative_sanity_check
```

Verification refuses a stored view that has stopped declaring any of these.

`require_honest_view_name` refuses any view or policy id containing `fmr`, `fnmr`, `eer`,
`impostor_rate`, `population`, `general_fmr` or `accuracy`. That is a blunt instrument
and it is aimed at a specific, likely mistake: a name is what survives into a slide,
long after the caveat in the docstring.

**No SELF conditioning is applied to this view, and no conditional variant exists.** An
impostor pair spans two fingers, so "did its finger pass SELF?" has two answers and no
agreed rule for combining them. Inventing one here would be a metric policy nobody
approved. A conditional negative view can be added later, under its own policy id and its
own ADR.

## Alternatives

**Call it `non_mated_fmr` and add a caveat in the documentation.** This is the failure
mode. Names travel; caveats do not.

**Compute the rate and label it "preliminary".** A preliminary number is a number.

**Extend to all 4,500 directed negative pairs now.** A better negative set and out of
scope: it changes the pair manifest, and therefore the run, and therefore everything
downstream. It belongs to whichever stage decides how negatives should be constructed.

**Drop the sanity check.** It costs nothing to keep and would catch a catastrophic
integration bug that nothing else in the protocol would.

## Consequences

* The stage produces 1,500 impostor decisions and no rate derived from them.
* When a real FMR is wanted, it will need a negative-pair design chosen for estimation —
  cross-subject, and either exhaustive or a stated sample — which is a new pair manifest
  and a new run.
* The view is still useful as it stands: a non-zero count of matches in it is a red flag
  worth investigating immediately, and the count can be looked at in the workspace
  without being published as a rate.
