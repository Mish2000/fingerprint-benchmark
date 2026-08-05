# 0077 — Stage 8C finalization binds the Stage 8B qualified route

*Status: Accepted — 2026-08-05, stage 8C*

## Context

Stage 8B qualified a route and published ten documents about it. Stage 8C
executes that route 6,000 times through the generic research engine, which knows
nothing about flx and must keep knowing nothing about it (docs/adr/0007,
docs/adr/0040).

Three things have to be reconciled for that to be more than an assertion.

**Which runtime is pinned.** The engine's mechanism is a content-addressed
runtime bundle: an integration names its asset roles, the store copies those
files into the workspace and every stored result is attributed to the resulting
bundle fingerprint. For NBIS the three roles are two executables and a build
manifest. For flx the runtime is 2.06 GB — a virtual environment, an extracted
source tree and an 875 MB checkpoint — and the checkpoint's licence status is
`unresolved`. Copying it into the workspace would be making a second copy of
weights the project has permission to *execute* locally and no established
permission to redistribute (docs/adr/0068).

**How a Decimal score reaches a float schema.** ADR 0073 fixed the score as a
Decimal built from a canonical 17-significant-digit string, never rounded and
never clamped. `RawResultRecord.raw_score` is an IEEE double, and it is the same
field four finalised SourceAFIS and NBIS runs are stored in. Changing its type
would rewrite every historical result fingerprint, which Stage 8C is explicitly
forbidden to do.

**What the final marker has to name.** The general research receipt binds run,
plan, result set, audit, validation and completion. It knows nothing about
artifact digests, profile fingerprints or the Stage 8B outcome, so on its own it
cannot say that the 6,000 scores came from the qualified route rather than from
something that merely had the same adapter id.

## Decision

**The bundle pins the three repository-owned files that decide what the worker
does, and pins the artifacts by frozen digest instead of by copy.**

```
flx_worker_script    integrations/flx/worker/flx_worker.py   (primary)
flx_runtime_lock     configs/flx/flx_runtime_lock_v1.txt
flx_runtime_policy   configs/flx/stage8b_flx_runtime_policy_v1.yaml
```

The worker script is what executes; the lock is every distribution importable
inside it, at one version and one wheel digest; the policy is every deadline it
runs under. All three are small, committed, and byte-identical to what a
reviewer can read in this repository.

The lock and the policy are read from the bundle's own copies, so a run is
literally driven by the dependency set and the deadlines it recorded. The worker
script is treated differently: Stage 8B's `FlxLearnedFingerprintIntegration`
starts it at its repository path, and Stage 8C does not reach into a qualified
route to redirect it. Instead the pinned copy is proved byte-identical to the
file that will execute, before the adapter exists. That establishes the same
fact — the bytes in this run's bundle are the bytes that ran — without modifying
anything the Stage 8B qualification rests on, and a repository script that
differs from the pinned one is a hard failure rather than a warning.

The source archive and the checkpoint are pinned by
`fpbench.flx.identity.SOURCE_ARCHIVE_SHA256` and `CHECKPOINT_SHA256`, which are
frozen constants re-verified by `verify_bundle_artifacts()` — full re-hash of
the archive, of all six imported source files and of all 875,770,140 checkpoint
bytes — before the model is loaded, on every worker start. Neither ever enters
the workspace, and neither is ever published (docs/adr/0072).

**The score is stored as the IEEE double it already is, with its canonical text
beside it.** The general schema is unchanged. Every successful flx result
carries:

```
raw_score                          the IEEE double, in the existing float field
adapter_metadata["flx.raw_score_decimal"]   the canonical 17-digit text
```

Seventeen significant digits is the digit count that always recovers an IEEE
double exactly — that is why Stage 8B chose it — so the two representations are
the same number and nothing is truncated, rounded or normalised. The flx
validator re-derives the text from the stored double for all 6,000 rows and
fails the run if any pair disagrees, which makes the equality a checked property
of the stored evidence rather than a property of the code that wrote it.

**`stage-8c-finalization.json` is the document that binds the route**, written
last, after the general chain is complete. It names, at minimum:

```
stage8b_finalization_fingerprint  aa6897bf...  and the outcome it carries
source archive, checkpoint, runtime manifest, preprocessing, representation,
score and adapter profile fingerprints
run / plan / result-set / completion ids and fingerprints
run source commit, and that its tree was clean
reference run, plan and result-set ids, and the pair manifest hash
prepared set id and fingerprint, transform profile and runtime fingerprints
audit, algorithm-validation, receipt, research-finalization and alignment
  fingerprints, plus the alignment and operational-summary content hashes
planned / stored / success / algorithmic-failure / blocking-failure counts
permits_decisions: false          opens_stage_8d: true
prior_result_scores_read: false   score_statistics_published: false
verifier source commit, and the exact content hash of every published file
```

## Alternatives considered

**Pin the checkpoint as a runtime asset role.** Puts 875 MB of
licence-unresolved weights into the workspace for no gain: the digest constant
plus the pre-load re-hash already proves the exact bytes were executed, and the
copy would prove the same thing twice while creating a redistribution question.

**Pin nothing and rely on the digest constants alone.** Then the run is
attributed to a bundle that holds no evidence of what ran, and a change to the
worker script or to a deadline would not move any recorded identity.

**Change `RawResultRecord.raw_score` to Decimal.** Rewrites the result
fingerprints of four finalised runs and every receipt, marker, decision set and
metric set that cites them. The spec asks for Decimal support only if it is
generically required; it is not, because the general float field already holds
the exact value.

**Store only the canonical text and leave `raw_score` empty.** A successful
result with no score is invalid in the general schema, and would make flx
results unreadable by every tool that reads the other two algorithms'.

**Let the general research receipt carry the artifact identities.** It is
algorithm-neutral by design and shared with two finalised chains. Adding flx
fields to it would change what a SourceAFIS receipt hashes.

## Consequences

The workspace runtime bundle for flx is a few hundred kilobytes and fully
reviewable. Anyone can diff the three pinned files against the repository.

A reader who wants to check that the published scores came from the qualified
route follows one chain: the Stage 8C marker names the Stage 8B finalization
fingerprint, which names the artifact binding, the runtime manifest and all four
profiles, each of which is a published document with its own fingerprint.

Evidence-only verification can check every link above without torch, without the
checkpoint, without SD300 and without the raw ResultSet — and it says so, rather
than implying CI executed the algorithm (spec section 29).

If the worker script, the lock or the policy changes, the bundle fingerprint
moves and the run cannot be resumed. That is the intended behaviour: it is a
different runtime.
