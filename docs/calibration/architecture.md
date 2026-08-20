# Calibration architecture

The layer that chooses a threshold from labelled scores — and, as of Stage 8D,
has never chosen one.

## Calibration infrastructure is not a calibration experiment

These are two different things and the distinction is the whole of Stage 8D.

**Calibration infrastructure** is the machinery: the models, the exact
arithmetic, the boundary semantics, the selection rule, the refusals, the
storage. It is algorithm-neutral, dataset-neutral and target-neutral. It exists
now.

**A calibration experiment** is an act: choose a development cohort, choose a
pair-generation protocol, choose a target operating point, run the machinery over
each algorithm's scores, and publish the thresholds. It has not happened, and it
will not happen until the algorithm list is declared final (docs/adr/0078).

Stage 8D built the first and refused the second. Its finalization marker says so
in fields rather than in prose:

```
real_calibration_performed        false
real_development_dataset_selected false
production_threshold_count        0
evaluation_score_rows_read        false
```

## A threshold is not a raw score

A raw score is what an algorithm produced for one comparison. A threshold is a
*rule* about scores, and the two do not live in the same kind of space even when
they are written with the same digits.

The consequence that matters: a threshold cannot be read off a score
distribution by eye, and it cannot be transported. SourceAFIS's documented 40 is
a statement about SourceAFIS; NIST's "greater than 40" is a statement about
BOZORTH3; neither is a statement about the other, and neither is a statement
about a matcher that has not been calibrated (docs/adr/0058).

## A common operating policy is not a common numeric threshold

Five algorithms calibrated under one protocol share this:

```
same development cohort
same pair-generation rules
same target operating-point definition
same threshold-selection algorithm
```

and share no number. Each threshold stays on its own algorithm's scale:

```
SourceAFIS scores  →  SourceAFIS threshold
NBIS scores        →  NBIS threshold
flx scores         →  flx threshold
```

There is no artifact in this project in which two algorithms' thresholds are
commensurable, because `fpbench.calibration` performs no normalization of any
kind — no min-max, no z-score, no Platt scaling, no fusion. Those are absent from
the package rather than disabled in it, and a structural test enforces their
absence (docs/adr/0080).

## Ties cannot be split

A boundary is a predicate over a score's *value*. Two comparisons that produced
the same score therefore always receive the same decision, and there is no way to
accept one of three identical `0.4`s.

This has a visible cost: a target rate is usually undershot rather than reached.
Given five impostor comparisons scoring `0.4, 0.4, 0.4, 0.7, 0.7`, a ceiling of
one in five is satisfied only by `> 0.7`, which admits *none* of them, because
admitting one of the two `0.7`s is not something a threshold can express. The
alternative — breaking the tie by `pair_id`, or at random with a fixed seed —
would decide identical evidence differently, and that is not a threshold.

## The genuine population does not choose the boundary

The selection is defined over the impostor population and nothing else: the
candidate boundaries, the admissibility test, the permissiveness ordering and the
tie-break. Mated scores are read exactly once, at the end, to count what the
chosen boundary does to them.

That is stricter than it first sounds. A value only a mated comparison produced
cannot become a threshold at all — `>= 0.9` is not on the table when 0.9 is a
mated-only score. Without that restriction the genuine population selects the
boundary through the permissiveness ordering, which is the optimisation
docs/adr/0080 exists to refuse; the ADR's *Consequences* section records the
concrete case where it did.

## Test data cannot select a threshold

Choosing a threshold on the cohort it will later be reported on produces an error
rate that describes the fitting rather than the population. This has been
forbidden since docs/adr/0021 and was, until Stage 8D, enforced only against
*declarations*: a profile that said `test_cohort_used: true` was refused.

An engine cannot be protected that way, because it is handed scores and scores do
not carry a sentence about where they came from. So the enforcement is now double
(docs/adr/0079):

1. **Role.** Every source binding names a cohort role, and a role that is not
   `DEVELOPMENT` is refused before a single row is read.
2. **Identity.** A `ProtectedEvaluationRegistry` binds the identities of the
   evaluation material — the dataset, the cohort, the pair manifest, the shared
   prepared-image set, and the canonical run and `ResultSet` of every executed
   algorithm. A binding that resolves to any of them is refused *whatever role it
   claims*.

Running with no registry loaded is refused too, because that would look exactly
like running with one and finding nothing.

## A result-set name is not enough

A source binding cannot merely repeat a `result_set_fingerprint` beside an
unrelated body of scores. `verify_result_set_for_calibration` re-derives the
result-set fingerprint from its ordered entries, re-hashes every
`RawResultRecord`, requires exact job and pair coverage, and joins an exact
ground-truth mapping by `pair_id`. Only that verifier can construct
`VerifiedCalibrationResults`, which is the input accepted by the public source-
binding builder.

The binding then carries three descriptions of the labelled body: its
`labeled_results_hash`, the canonical `pair_ids` list, and the positionally
aligned `ground_truth` list. The operating point copies all three into its own
fingerprint. Selection and verification require both artifacts and the supplied
`LabeledResults` to agree exactly. Changing one score, status, failure code,
pair id, or truth label therefore makes the body a different source; it cannot
be calibrated or verified under the old binding.

## The packages

```
src/fpbench/calibration/
├── __init__.py      the dependency rule, and what may not exist here
├── models.py        the containers, and the only strict reader
├── protocol.py      sealing an artifact around its own fingerprint
├── source.py        re-hashing a ResultSet and deriving its labelled body
├── selection.py     candidate boundaries, and the one selection rule
├── validation.py    what must be true before a score is read
├── profiles.py      the bridge to DecisionProfile
└── verify.py        re-deriving a stored operating point

src/fpbench/core/calibration_models.py   the persisted dataclasses
src/fpbench/core/calibration_errors.py   the failure vocabulary
src/fpbench/storage/calibration_store.py append-only files
```

`fpbench.calibration` imports `fpbench.core` and nothing else from this project.
It never imports an adapter, an algorithm, or any derivation layer, and it never
names a matcher. A calibration engine that knew which algorithm it was
calibrating could branch on it, and a branch is how "one policy applied to each
algorithm separately" quietly becomes five policies.

## The artifacts

| Artifact | What it fixes | Where it lives |
|---|---|---|
| `CalibrationProtocol` | the policy: target rate, selection rule, tie policy, populations | `calibration/protocols/` |
| `CalibrationSourceBinding` | one verified result set and its exact labelled body hash, pair ids, and truth labels | `calibration/source-bindings/` |
| `CalibrationOperatingPoint` | the chosen boundary, observed counts, and the same exact labelled-body identity | `calibration/operating-points/` |
| `ProtectedEvaluationRegistry` | the identities calibration must refuse | published with the stage, not per workspace |

Every one of them validates its own fingerprint on construction, so a builder
cannot drift from the model it builds: a normalisation added on one side and
forgotten on the other fails immediately rather than producing an identity that
quietly means something else.

Storage is append-only. Writing an id that already holds byte-identical content
succeeds and changes nothing — re-running a finished calibration is how it gets
verified. Writing an id that holds *different* content fails, because every id is
derived from a digest of its own contents and a collision means something that
should have been determined by its inputs was not.

## Where the numbers are not

None of these artifacts holds a raw score. The operating point holds a threshold,
a comparator, counts, and the labelled-body identity; the source binding holds
the result-set identity, labelled-results hash, pair ids, and truth labels; the
registry holds protected identities. A calibration cites the scores it was
chosen from and leaves the scores where they were written, for the same reason a
`DecisionRecord` does: copying them would create a second place a score lives,
and the first thing a reader would have to stop trusting (docs/adr/0003).
