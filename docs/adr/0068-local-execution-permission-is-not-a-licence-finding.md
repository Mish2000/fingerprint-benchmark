# 0068 — Local execution permission is not a licence finding

*Status: Accepted — 2026-08-05, stage 8B*

## Context

Stage 8A ended at `NO_MODERN_MATCHER_READY`. The `flx` candidate was rejected
`LICENSE_BLOCKED`, and two of its recorded failures were
`WEIGHTS_LICENSE_NOT_ESTABLISHED` and
`WEIGHTS_HOLD_AND_EXECUTE_PERMISSION_UNESTABLISHED`.

Stage 8B nevertheless loads `best_model.pyt` and runs it. The project owner
instructed that the checkpoint may be used for a local, non-published learning
experiment. That instruction is real and it is sufficient to run the code on
this machine. It is not, and cannot be, a statement about what the checkpoint's
licence permits, because no licence accompanied the checkpoint at all.

The tempting shortcut is to let the two collapse: the experiment proceeds, so
mark the licence resolved and move on. That would put a false provenance claim
inside a fingerprint, where it would be re-published by every downstream stage
that binds to it.

## Decision

Permission to execute and licence status are separate fields with separate
sources, and Stage 8B records both.

Stage 8B's evidence keeps saying, in every document that mentions the
checkpoint:

```
weights_license_status:   unresolved
redistribution_allowed:   not_established
publication_permission:   not_established
```

`FlxArtifactBinding` and `FlxQualificationReport` refuse to be constructed with
any other value for `weights_license_status`. There is no code path that can
set it to `resolved`, so a later stage cannot inherit a cleared licence by
accident.

The unresolved licence does not block the local experiment. It does block
four specific things, none of which Stage 8B does: publishing the checkpoint,
copying it into this repository, presenting the source licence as the weights
licence, and claiming the licensing was clarified.

Stage 8A's historical conclusion is not revised. `LICENSE_BLOCKED` remains the
correct answer to the question Stage 8A asked, which was whether the artifact
qualified for selection under a policy that requires established rights.
Stage 8B asks a different question, under an explicit instruction, and answers
it without touching the first.

## Alternatives considered

**Mark the weights licence resolved because the owner authorised use.** Wrong
category. The owner can authorise their own machine; they cannot supply terms
the author never published. The claim would be false in the evidence and would
propagate.

**Re-run Stage 8A so that `flx` passes.** That would rewrite a finding to match
a later convenience. Stage 8A's gates measured what was actually available, and
nothing about the artifact's licensing changed.

**Refuse to execute until the licence is resolved.** Defensible, and it is what
Stage 8A itself did. It is not what the project owner asked for at this stage,
and the cost — no learned-representation route at all — is theirs to weigh.

**Record the permission but drop the licence fields.** Silence reads as "not a
problem" to the next reader. An explicit `unresolved` reads as unresolved.

## Consequences

Every Stage 8B document carries an unresolved licence, permanently. Any future
publication of Stage 8C results must confront it rather than discover it late.

Stage 8B may produce raw scores locally and may publish hashes, counts,
timings and pass/fail observations about them. It may not publish the
checkpoint, the source archive bytes, representations, embeddings or raw
fixture scores, and the evidence verifier refuses documents that contain them.

If the licence is ever established, that is a new record with its own
provenance, not an edit to these documents.
