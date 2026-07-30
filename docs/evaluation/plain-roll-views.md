# The three evaluation views

A view is a named, fingerprinted list of comparisons together with the reason each one is
in or out. It is not a metric, and it contains no arithmetic.

The separation exists because a sentence like "SourceAFIS matched 94% of mated pairs" is
three decisions in a trench coat: which pairs counted, what counted as a match, and what
happened to the ones that failed. Stage 5A fixes the first two and writes them down where
they can be reviewed. The third, and the division, come later.

```
results/<run_id>/decisions/<decision_set_id>/evaluation-views/
├── plain-roll-mated-unconditional/     manifest.json  entries.parquet
├── plain-roll-mated-both-self-match/   manifest.json  entries.parquet
└── plain-roll-non-mated-sanity/        manifest.json  entries.parquet
```

## 1. Mated, unconditional

`plain_roll_mated_unconditional_v1` — **1,500 rows, every one included.**

Every mated PLAIN–ROLL comparison in the protocol: plain finger *i* against rolled finger
*i*, same subject, same release.

Nothing is excluded, including comparisons that produced no score. Whether a failure
belongs in a denominator is a metric question, and answering it here would bake one
answer into the data. A failed comparison appears with `decision_status = undecidable`
and `decision = null`, and it is still `included`.

The view cites no eligibility set. Verification refuses one that does — an
"unconditional" view that quietly filtered would be the exact confusion this stage exists
to prevent.

## 2. Mated, conditional on both SELF matches

`plain_roll_mated_both_self_match_v1` — **1,500 rows, included where the finger
qualified.**

The same 1,500 comparisons. A row is `included` exactly when its eligibility unit is
`ELIGIBLE`; otherwise it is present with `included = false` and one of:

| exclusion_reason | meaning |
|---|---|
| `self_ineligible` | a SELF comparison produced a `NON_MATCH` |
| `self_undetermined` | a SELF comparison produced no decision at all |

**The excluded rows are kept.** A view that dropped them would be smaller and
unauditable: "which pairs did you leave out, and why?" is the first question any reviewer
asks of a conditional result, and it should be answerable from the file
([ADR 0024](../adr/0024-conditional-mated-evaluation-requires-both-self-matches.md)).

Each excluded row carries the eligibility unit id and record hash that excluded it, so
the decision is traceable to the two SELF comparisons behind it.

**The conditional view does not change the unconditional one.** They are separate
artefacts with separate fingerprints. That is what "reported twice" means.

**The number of included rows is not stored.** In this view that number *is* the
interesting result. It is derived on demand in the workspace and appears in no manifest,
no fingerprint and no committed receipt.

## 3. Non-mated, sanity check

`plain_roll_non_mated_same_subject_cyclic_v1` — **1,500 rows, all included, no SELF
filter.**

Plain finger *i* against rolled finger *i+1* of the same subject, wrapping at ten. The
expectation is zero matches; a non-zero count is a red flag worth investigating
immediately.

The manifest records what the set is, in fields that reach its own fingerprint:

```yaml
negative_kind: same_subject_different_finger
pairing_strategy: cyclic_finger_shift
finger_shift: 1
closed_set: true
primary_fmr_estimate: false
purpose: negative_sanity_check
```

### This is not a false-match rate

It has the shape of one — 1,500 non-mated comparisons with decisions attached — and it is
not one:

* **closed set**: fifty subjects, chosen once, not a population;
* **same subject on both sides**: within-person impostors are not representative of
  between-person impostors;
* **one fixed pairing**: shift 1, one direction, not the 4,500 available negative
  pairings and not a sample of them;
* **no confidence interval is possible** from a design nobody chose for estimation.

`require_honest_view_name` refuses any view or policy id containing `fmr`, `fnmr`, `eer`,
`impostor_rate`, `population` or `accuracy`. That is deliberately blunt: a name is what
survives into a slide, long after the caveat
([ADR 0025](../adr/0025-same-subject-different-finger-is-a-sanity-check.md)).

### And there is no conditional non-mated view

An impostor pair spans two fingers, so "did its finger pass SELF?" has two answers and no
agreed rule for combining them. Inventing one would be a metric policy nobody approved.
If one is wanted later it gets its own policy id and its own ADR.

## Identity

Every view fingerprint covers the policy, the run, the result set, the decision set, the
eligibility set (where there is one), the pair manifest, the policy metadata, and the
ordered entries **including their inclusion state and exclusion reasons**.

Two views over the same pairs that include different subsets are different views — which
is the entire distinction between the first two.

Verification recomputes the `included` flag from the eligibility verdict rather than
trusting the stored value. It is one boolean per row, everything conditional rests on it,
and it is the easiest thing in the chain to change without anyone noticing.

## What comes next, and does not exist yet

FMR, FNMR, EER, ROC, DET, confidence intervals, a resolution ranking, and any statement
about how well SourceAFIS performed. All of it needs denominators — how a failed
comparison is counted, whether an undetermined unit is excluded or imputed — and a
justification for the threshold. None of that is in this stage.
