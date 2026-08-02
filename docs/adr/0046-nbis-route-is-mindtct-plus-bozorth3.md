# 0046 — The NBIS algorithm identity is MINDTCT and BOZORTH3 together

*Status: Accepted — 2026-08-02, stage 7B*

## Context

NBIS is not a matcher. It is a collection of tools, and the route this project
uses is two of them in sequence:

```
gray8 PNG at 500 ppi -> MINDTCT -> XYT -> BOZORTH3 -> raw score
```

MINDTCT decides what counts as a minutia, where it is, which direction it points
and how reliable it is. BOZORTH3 only compares the two lists it is handed. Almost
every decision that could move a score is made by the extractor, and the matcher
sees a few hundred integers.

The obvious name for the algorithm is therefore the wrong one. Calling it
`bozorth3` — after the thing that prints the number — would let two runs against
different MINDTCT builds share an `algorithm_id`, an `algorithm_fingerprint` and
every artefact derived from them, while comparing different templates. Nothing
downstream would notice: the results would look ordinary and be incomparable.

docs/adr/0014 already says an algorithm's identity has to describe the whole
pipeline. NBIS is the case that makes the rule bite.

## Decision

One identity for the whole route:

```
algorithm_id             nbis_mindtct_bozorth3
adapter_id               nbis_mindtct_bozorth3_subprocess
adapter_version          1
adapter_contract_version 1
implementation_version   5.0.0
score_direction          higher_is_better
deterministic            true
```

and a pipeline description that names both halves separately, so that a future
build where the two versions diverge is expressible rather than lost:

```
extractor_id/version   mindtct  / 5.0.0
matcher_id/version     bozorth3 / 5.0.0
pipeline_kind          extract_then_match
integration_mode       subprocess_per_stage
```

The **runtime bundle carries three files**, not one: both executables and the
build manifest. Either executable can change a score, and the manifest is what
says the executables are the ones NIST's own tests were run against. A bundle
holding two of the three is not this route's runtime (docs/adr/0042).

`primary_runtime_asset_role` is `nbis_mindtct_executable`. It carries no research
meaning and exists only because a receipt renders one role first; the identity is
the whole bundle.

## Consequences

Rebuilding either tool produces a different bundle id, a different environment
fingerprint and therefore a different run. That is the intended cost: a score
attributed to "NBIS 5.0.0" without saying which build produced it is not
attributable at all.

A future route that used MINDTCT with a different matcher, or BOZORTH3 with a
different extractor, is a different `algorithm_id`. It would share this
repository's adapter tooling and none of its identity.

## Alternatives considered

**Name it `bozorth3`, after the matcher.** It is the name the literature uses,
and it hides the component that makes most of the decisions.

**Name it `nbis`, after the package.** NBIS contains NFIQ, an ANSI/NIST codec, a
WSQ codec and a dozen other tools. A run of two of them is not a run of NBIS.

**Two identities, one per tool, joined at analysis time.** The harness has no
concept of half a comparison, and a pair of identities would have to be
recombined by every consumer — with nothing checking that the combination was the
one that actually ran.
