# Stage 8E — Repository-wide research-only third-party usage policy

**Outcome:** `RESEARCH_ONLY_THIRD_PARTY_POLICY_READY`

This directory is the published evidence that a repository-wide third-party usage
policy exists, that it has been applied to every component this project already
depends on, and that the public repository is enforced against it.

It is **not** evidence that any upstream licence question was resolved.

## What the outcome asserts

```
project purpose frozen and fingerprinted
licence observation separated from research-use decision
every already-integrated component mapped by the same engine
no third-party byte tracked in this public repository
no workflow downloads, uploads or publishes upstream bytes
```

## What it denies

Each of these is a field in `stage-8e-finalization.json`, checked by the marker's
own constructor rather than written as prose:

```
commercial_use_by_project                false
third_party_redistribution_by_project    false
third_party_bytes_permitted_in_git       false
historical_evidence_changed              false
upstream_license_question_resolved       false
fpbench_license_added                    false
```

No licence was resolved. No historical conclusion was rewritten. No `LICENSE`
file was added to this repository, and no bespoke "research only licence" was
written — a purpose declaration and a copyright licence are different
instruments, and inventing one to express the other would create a new legal
question rather than answer one (docs/adr/0081).

## The purpose

```
PERSONAL_EDUCATIONAL_RESEARCH

commercial use by project owner:         false
commercial deployment:                   false
commercial service:                      false
third-party redistribution:              false
third-party sublicensing:                false
benchmark publication as academic work:  false
```

Not `academic`. This project is not carried out within any institution, and a
vocabulary offering the word would eventually see it claimed.

## The rule

> Third-party licensing does not block local personal educational research
> execution merely because commercial use, redistribution, sublicensing or
> publication is restricted.

Upstream rights are recorded faithfully and are never rewritten to suit a
decision. Three questions stay apart:

```
What does upstream licensing say?   ->  LicenseObservation      (a description)
May fpbench execute it locally?     ->  ResearchUseDecision     (a decision)
May fpbench redistribute it?        ->  RedistributionDecision  (never exercised)
```

## What the policy was applied to

Twelve components, four manifests, none blocked:

| research-use decision | count |
|---|---|
| `ALLOWED` | 7 |
| `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` | 1 |
| `OWNER_RISK_ACCEPTED` | 4 |
| `BLOCKED` | 0 |

| licence observation status | count |
|---|---|
| `OPEN_SOURCE_PERMISSIVE` | 6 |
| `UNKNOWN` | 3 |
| `OPEN_SOURCE_COPYLEFT` | 1 |
| `SOURCE_AVAILABLE` | 1 |
| `NO_LICENSE_FOUND` | 1 |

The four `OWNER_RISK_ACCEPTED` components are the two NIST NBIS archives, the
certified build made from them, and the learned extractor's checkpoint. Every one
of them keeps:

```
intended_use_permission_status:  UNRESOLVED
```

That field says the project owner decided to proceed with a local research
operation despite an ambiguity nobody resolved. It does not say the use is
permitted (docs/adr/0084).

The single `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` is NIST SD300: its delivery
terms restrict the field of use, every plausible reading of them permits local
research without redistribution, and the record rests explicitly on
`dataset_access_terms_satisfied: true` — because Stage 8E changed nothing about
dataset rights.

## What was not touched

Nothing historical. Stage 8A's `LICENSE_BLOCKED` and Stage 8B's
`weights_license_status: unresolved` are exactly as published, and not one byte
under `evidence/stage8a-…`, `evidence/stage8b-…`, `evidence/flx-…`,
`evidence/nbis-…`, `evidence/sourceafis-…`, `evidence/sd300-…` or
`evidence/stage8d-…` changed. Stage 8E produced a new mapping beside them.

## The files

| File | What it is |
|---|---|
| `project-purpose.json` | the frozen declaration and its six denials, derived in code and checked against this document |
| `third-party-policy.json` | the operating rule: what is not a blocker, what is, the five owner-risk conditions, what the repository may and may not hold |
| `legacy-component-audit.json` | twelve components, each with an observation, an assessment and a usage record, plus four per-route manifests |
| `repository-artifact-audit.json` | what Git actually tracks, what the workflows actually do, and what `.gitignore` still covers |
| `policy-contract-report.json` | the structural facts: module digests, the vocabulary, enforced absences, and the policy qualification's cases |
| `stage-8e-finalization.json` | the last-written authority, binding all of the above and the exact bytes of every file here |

## What is not in this directory

No licence text. No upstream source. No checkpoint byte, embedding or descriptor.
No fingerprint image. No score and no threshold. No absolute path on anybody's
machine.

The digests in `legacy-component-audit.json` are *expectations about files that
live outside this repository*, and every one of them was already published here
before Stage 8E existed — in `integrations/nbis/nbis-5.0.0.lock.json`, in Stage
8B's artifact binding and runtime manifest, and in the prepared-image set.

## Verifying it

```bash
pytest -m "stage8e" -q
```

The gate re-reads Stage 8D's marker to confirm the stage this one follows,
rebuilds the purpose and the policy from source and compares them with the
committed JSON, re-runs the legacy audit over all twelve components, re-runs the
repository and workflow audits over the real tracked file list, recomputes both
engine source fingerprints, and re-hashes every file in this directory against
the marker.

Nothing in it needs a dataset, a runtime, a checkpoint, Java, a network or a
workspace.

## What this opens

Stage 9A — algorithm 4, artifact qualification — with one premise changed. Its
upstream's conflicting notices remain conflicting; they are no longer a blocker
by themselves. Every algorithm from 9A onward fills in the same
`ThirdPartyUsageRecord` rather than relitigating licensing, and the gate is
mechanical.
