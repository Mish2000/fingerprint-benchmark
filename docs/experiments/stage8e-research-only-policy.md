# Stage 8E — Repository-wide research-only third-party usage policy

**Outcome:** `RESEARCH_ONLY_THIRD_PARTY_POLICY_READY`

Stage 8E writes down what this project is, separates what upstream's terms *say*
from what this project has decided to *do*, applies both to every third-party
component already in the repository, and makes the "no upstream bytes in Git"
rule enforceable rather than customary.

It resolves no licence question, and its marker says so in a field.

## Why it came before Stage 9A

Stage 9A was going to integrate a fourth algorithm whose upstream carries
conflicting notices — a permissive `LICENSE` file beside documentation that
restricts use. Under Stage 8A's policy that is `LICENSE_BLOCKED`, which would
have ended the stage before it started.

The instinct was to make an exception. That would have been the fourth
component-specific licensing argument this project has had, after Stage 8A's
gate, Stage 8B's owner instruction and Stage 8C's inherited unresolved status —
three different shapes for one recurring question, and no rule to point at when
algorithms 5, 6 and 7 arrive.

So the exception became a policy instead, and it is the policy that Stage 9A now
runs against.

## What it decided

Four ADRs, and the second is the one that matters most.

[ADR 0081](../adr/0081-fpbench-is-personal-educational-research-only.md) freezes
the purpose: `PERSONAL_EDUCATIONAL_RESEARCH`, with six denials each `False` and
each enforced by the declaration's own constructor. Not `academic` — this project
has no institutional affiliation and a vocabulary offering the word would see it
claimed. No `LICENSE` file is added, and no bespoke "research only licence" is
written: a purpose declaration and a copyright licence are different instruments.

[ADR 0082](../adr/0082-third-party-license-observation-is-separate-from-local-research-use.md)
splits the observation from the decision. A `LicenseObservation` describes the
notices and has no field for a conclusion; a `ResearchUseAssessment` decides and
cites the observation by fingerprint. The operating rule follows: licensing does
not block local personal educational research merely because commercial use,
redistribution, sublicensing or publication is restricted. Restrictions are
recorded and respected; blockers are a short closed list.

[ADR 0083](../adr/0083-third-party-bytes-are-never-redistributed-by-fpbench.md)
makes `DO_NOT_VENDOR` the default, for upstream *source* as much as for
checkpoints, and moves the enforcement from `.gitignore` to a guard over what Git
actually tracks.

[ADR 0084](../adr/0084-ambiguous-upstream-rights-may-be-risk-accepted-without-becoming-a-license-finding.md)
gives the unresolved case a third state that cannot be mistaken for permission.

## What it built

```
src/fpbench/core/third_party_models.py    the vocabulary and the containers
src/fpbench/core/third_party_errors.py    the failure vocabulary
src/fpbench/third_party/purpose.py        the frozen declaration
src/fpbench/third_party/policy.py         the decision table
src/fpbench/third_party/manifest.py       the record every algorithm fills in
src/fpbench/third_party/artifacts.py      the local store, resolved at runtime
src/fpbench/third_party/transformations.py  the upstream-modification ladder
src/fpbench/third_party/repository_guard.py the public-repository enforcement
src/fpbench/third_party/verify.py         re-derivation of a stored position
```

`fpbench.third_party` imports `core` and itself, and nothing else — enforced
structurally, not by review. It names no algorithm, imports no runtime, and
reads no result.

## The decision table

```
blockers?                 ->  BLOCKED
owner risk accepted?      ->  OWNER_RISK_ACCEPTED          permission UNRESOLVED
intersection required?    ->  ALLOWED_UNDER_RESTRICTIVE_
                              INTERSECTION                 permission ESTABLISHED
otherwise                 ->  ALLOWED                      permission ESTABLISHED
```

In that order, in one function, and `assess_research_use` has no parameter
through which a caller could supply a decision instead of the facts.
`verify_usage_record` re-runs the same table over the stored facts.

## What it was applied to

Twelve components, three routes plus the dataset, mapped by the same engine
Stage 9A will use:

| decision | count |
|---|---|
| `ALLOWED` | 7 |
| `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` | 1 |
| `OWNER_RISK_ACCEPTED` | 4 |
| `BLOCKED` | 0 |

The four risk-accepted ones are the two NIST NBIS archives, the certified build
made from them, and the learned extractor's checkpoint. All four keep
`intended_use_permission_status: UNRESOLVED`, and the marker refuses to be
written with a risk-accepted count of zero — a marker claiming this repository
has no unresolved permissions would be describing a different repository.

The one intersection is NIST SD300, whose delivery terms restrict the field of
use and whose every plausible reading permits local research without
redistribution.

**Nothing historical was rewritten.** Stage 8A's `LICENSE_BLOCKED`, Stage 8B's
`weights_license_status: unresolved` and every byte under
`evidence/stage8a-…`, `evidence/stage8b-…`, `evidence/flx-…`,
`evidence/nbis-…`, `evidence/sourceafis-…`, `evidence/sd300-…` and
`evidence/stage8d-…` are exactly as published. Stage 8E produced a new mapping
beside them.

## What it enforces

The guard reads `git ls-files` and applies eight rules — model-weight extensions,
known checkpoint filenames, runtime binaries, archives, dataset and biometric
image formats, vendoring directory names, the exact digests of every upstream
artifact this project pins, and a one-megabyte ceiling. One exception, by name:
the ten synthetic imaging fixtures under `tests/fixtures/imaging/`.

Every workflow is scanned for tokens that would falsify the policy's three CI
claims: no restricted artifact is downloaded, no third-party byte is uploaded,
and no container image containing one is published.

## Verifying it

```bash
make stage8e-contract
```

```bash
make stage8e-evidence
```

Neither needs a dataset, a runtime, a checkpoint, Java, a network or a workspace.

## Publishing it

Two commits, because the marker is derived against the exact bytes of the other
five documents:

```bash
make stage8e-documents
```

commit those five, then

```bash
make stage8e-publish
```

which refuses a dirty tree, pins the commit it was derived at, and writes
`stage-8e-finalization.json` alone.

## What this opens

Stage 9A, unchanged in scope and changed in one premise. The fourth algorithm's
conflicting notices remain conflicting; they are no longer a blocker by
themselves. 9A asks:

> Do all plausible upstream restrictions permit our exact
> `PERSONAL_EDUCATIONAL_RESEARCH` use?

and if they do, `research_use_decision: ALLOWED_UNDER_RESTRICTIVE_INTERSECTION`
opens execution even while `redistribution_decision` stays `NOT_ESTABLISHED`.

Every algorithm from 9A onward fills in the same `ThirdPartyUsageRecord` instead
of relitigating licensing, and the gate is mechanical.
