# Third-party usage policy

The rule, in one sentence:

> Third-party licensing does not block local personal educational research
> execution merely because commercial use, redistribution, sublicensing or
> publication is restricted.

That is not "licences do not matter". Upstream rights are recorded faithfully and
are never rewritten to suit a decision. What changes is which recorded fact is
allowed to *stop* something.

## Three questions, three answers, never one field

```
What does upstream licensing say?
                 |
                 v
        LicenseObservation          a description

                 =/=

May fpbench execute it locally
under this project's purpose?
                 |
                 v
        ResearchUseDecision         a decision

                 =/=

May fpbench redistribute it?
                 |
                 v
        RedistributionDecision      always: it does not
```

So this repository can hold, without contradiction:

```
license_observation_status:   CONFLICTING_NOTICES
research_use_decision:        ALLOWED_UNDER_RESTRICTIVE_INTERSECTION
redistribution_decision:      NOT_ESTABLISHED
```

— the licence question is not resolved, the execution question is, and nothing is
published. See
[ADR 0082](../adr/0082-third-party-license-observation-is-separate-from-local-research-use.md).

## The vocabulary

`LicenseObservationStatus` — a description of the notices:

```
OPEN_SOURCE_PERMISSIVE    OPEN_SOURCE_COPYLEFT    ACADEMIC_ONLY
RESEARCH_ONLY             NON_COMMERCIAL          SOURCE_AVAILABLE
CONFLICTING_NOTICES       NO_LICENSE_FOUND        UNKNOWN
```

`NO_LICENSE_FOUND` and `UNKNOWN` are different claims. The first means the
artifact was inspected and carried no terms; the second means no inspection has
been recorded here.

`ResearchUseDecision` — what this project may do:

```
ALLOWED
ALLOWED_UNDER_RESTRICTIVE_INTERSECTION
OWNER_RISK_ACCEPTED
BLOCKED
```

`RedistributionDecision` — what upstream permits, recorded and then not acted on:

```
ALLOWED    CONDITIONAL    NOT_ALLOWED    NOT_ESTABLISHED
```

## What is not a blocker

Recorded, respected, and does not stop execution:

```
non-commercial only
academic / research only
educational only
no redistribution
no sublicensing
copyleft
strong copyleft
weights may not be redistributed
commercial licence required for commercial deployment
attribution and notice retention
a notice conflict where every plausible reading
    still permits our exact local research use
```

Copyleft in particular. The obligations of the GPL and LGPL attach to *conveying*
the work; running it and making local copies is not conveying, so nothing is
triggered by local execution. Apache-2.0's conditions likewise attach to
distribution.

## What is a blocker

The closed list:

```
express prohibition of the intended research use
express prohibition of biometric use, where fingerprint
    recognition is the intended use
prohibition of modification, where faithful execution
    requires modification
access terms we cannot satisfy
an artifact obtained by bypassing authentication, a paywall,
    an access control, encryption or another technical restriction
terms incompatible with the intended local execution
artifact identity or provenance that cannot be established
dataset access terms that are not satisfied
permission that is unresolved with no risk accepted
```

## The intersection rule

When notices conflict — say a `LICENSE` file reading Apache-2.0 beside a README
reading "academic use only" — the project does not decide which wins. It asks:

> which uses does *every* plausible reading permit in common?

If local, non-commercial, educational research is in that set, the answer is
`ALLOWED_UNDER_RESTRICTIVE_INTERSECTION`, and the observation stays
`CONFLICTING_NOTICES`. There is no need to resolve a legal question that does not
affect the use actually being made.

The intersection is a conjunction. One reasonable reading that forbids the
operation blocks it, and an "intersection" over a single reading is refused —
that is just that reading, dressed up.

## The unresolved case

Where nothing at all was found, the answer is not "free to use". Default
copyright applies and nobody has granted anything. The project may still proceed,
under an explicit acceptance of risk, and only when all five conditions hold:

```
the artifact was intentionally published by its official authors
the artifact is publicly obtainable without circumventing any access control
the intended operation is local research only
no located term expressly prohibits that use
no bytes will be redistributed by this project
```

The record then says:

```
intended_use_permission_status:   UNRESOLVED
research_use_decision:            OWNER_RISK_ACCEPTED
```

`UNRESOLVED` stays. The owner accepted a risk; nobody established a right. Four
conditions out of five is a decision to block, and risk may not be accepted over
terms that *were* found. See
[ADR 0084](../adr/0084-ambiguous-upstream-rights-may-be-risk-accepted-without-becoming-a-license-finding.md).

## Component kinds have separate licences

Never assume `repository licence = checkpoint licence = dataset licence`
([ADR 0063](../adr/0063-code-and-model-weights-have-separate-identities-and-licenses.md)).
Every component is one of:

```
SOURCE_CODE    MODEL_WEIGHTS    RUNTIME_BINARY    PACKAGE_DEPENDENCY
DATASET        DOCUMENTATION    OTHER_ARTIFACT
```

and each gets its own observation and its own decision.

**Datasets are unchanged by this policy.** Biometric access terms, privacy and
data-use conditions are a different subject. A dataset record must state that its
own access terms are satisfied, it can never be risk-accepted, and if the terms
are not satisfied it is blocked. This policy is about software, models and
runtime artifacts.

## The manifest every new algorithm fills in

```
third_party_usage:

    purpose:                    personal_educational_research
    component_kind:             model_weights
    upstream_identity:          ...
    exact_version:              ...
    license_observation:        ...
    license_evidence:           ...
    research_use_decision:      ...
    research_use_basis:         ...
    owner_risk_acceptance:      false
    redistribution_decision:    NOT_ESTABLISHED
    redistributed_by_fpbench:   false
    stored_in_git:              false
    stored_in_ci_artifacts:     false
```

One `ThirdPartyUsageRecord` per component, one `ThirdPartyUsageManifest` per
integration, and the gate is mechanical: `assess_research_use` derives the
decision from the facts — there is no parameter through which a caller can supply
one — and `verify_usage_record` re-runs the same table over the stored facts and
compares.

This replaces the one-off reasoning each of the first three algorithms did.

## Where the bytes go

Nowhere near Git. See
[third-party-artifact-handling.md](third-party-artifact-handling.md).
