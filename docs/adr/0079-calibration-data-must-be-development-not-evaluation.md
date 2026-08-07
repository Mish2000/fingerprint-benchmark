# 0079 — Calibration data must be development data, not evaluation data

*Status: Accepted — 2026-08-07, stage 8D*

## Context

docs/adr/0021 already forbids calibrating a threshold on the TEST cohort, and
`fpbench.decisions.profiles` already refuses a profile that admits
`calibration.test_cohort_used: true`. Both are declarations: the loader believes
what the YAML says about itself.

That was sufficient while no calibration engine existed. It stops being
sufficient the moment one does, because the engine is handed *scores*, and
scores do not carry a sentence about which cohort they came from. A caller who
passed the 6,000 published SD300 rows to a selector would be doing precisely
what docs/adr/0021 forbids, and every check in the project would pass: the rows
are well-formed, the fingerprints are valid, the arithmetic is exact.

There is also a naming problem. This project's frozen vocabulary calls the
protected role `CohortRole.TEST` — the value `"test"` is inside
`sd300_50_subjects_test_22f8d52a7478` and inside every cohort, run, plan,
result-set and preparation-set fingerprint derived from it. The calibration
literature calls that role *evaluation*, and reserves *test* for a third split.

## Decision

**The role is enforced, not declared.** Every score source handed to the
calibration engine arrives inside a `CalibrationSourceBinding` that names its
cohort role. A binding whose role is not `DEVELOPMENT` is refused *before a
single score is read* — before the labelled rows are iterated, not after they
are counted.

**Identity is checked as well as role.** A binding may claim `DEVELOPMENT` and
still resolve to protected evaluation data, through a copied cohort id, a
re-declared result set, or an honest mistake. So Stage 8D publishes a
`ProtectedEvaluationRegistry`: an artifact that binds the *identities* of the
evaluation material — the SD300 dataset, the 50-subject cohort, the canonical
pair manifest, and the canonical `ResultSet` fingerprint of each executed
algorithm — and nothing else. It holds no score, no count of scores and no
statistic. A source binding whose dataset, cohort, pair manifest, run or result
set matches a registered protected identity is refused whatever role it claims.

**`EVALUATION` is added as an alias of `TEST`, not as a new member.** The
existing member keeps the value `"test"`, so `CohortRole("test")` still resolves,
every stored document still parses, and no cohort fingerprint moves. Calibration
code reads `CohortRole.EVALUATION` and means the same object:

```python
CohortRole.EVALUATION is CohortRole.TEST      # True
CohortRole.EVALUATION.value == "test"          # unchanged, and inside fingerprints
```

Renaming the member instead would change the serialized value, and with it the
identity of the one cohort this project has.

**The impostor population is cross-subject.** A calibration protocol must
require `CROSS_SUBJECT_IMPOSTOR` pairs. The same-subject different-finger set
that exists in this project's protocol is registered as a *sanity check*, never
as an FMR estimate — 1,500 cyclic within-subject comparisons are not a sample of
the impostor population, and using them to bound a false-match rate would bound
the wrong quantity. `CalibrationPairTruth` therefore has exactly two members,
and there is no third one to select by accident.

## Alternatives considered

**Rename `CohortRole.TEST` to `EVALUATION`.** Semantically the better name, and
it moves `sd300_50_subjects_test_22f8d52a7478`, every cohort fingerprint derived
from it, and therefore every run, plan, result set, decision set, metric set and
finalization marker in the repository. A vocabulary improvement is not worth
re-deriving the published record.

**Keep relying on the declared `calibration.test_cohort_used` flag.** It
protects the profile document and cannot protect the engine, which never sees
the document.

**Register protected *scores* rather than protected identities.** It would work
and it would put the evaluation scores inside a Stage 8D artifact, which is the
exact thing the stage claims not to do.

**Allow same-subject different-finger pairs as a fallback impostor population.**
Convenient, and it would let a calibration run on a cohort too small to have
cross-subject impostors. The resulting rate would not be a false-match rate, and
nothing downstream would be able to tell.

## Consequences

`fpbench.calibration` cannot be handed evaluation data without raising. The
refusal is a `CalibrationLeakageError`, distinct from a malformed-input error, so
a caller cannot catch it by accident while handling parse failures.

`ProtectedEvaluationRegistry` has to be extended whenever a new algorithm
publishes a canonical `ResultSet`. That is deliberate: the registration is a step
in publishing an evaluation run, and a run that was never registered is a run the
engine would not refuse.

Drawing the development cohort remains future work, and it is now the *only*
thing standing between this infrastructure and a real calibration. It is
deferred by docs/adr/0078, not by this decision.
