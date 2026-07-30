# 0014 — An algorithm identity names the complete image-to-score pipeline

## Status

Accepted. Implemented in `fpbench.adapters.sourceafis_java` and enforced by
`descriptor_fingerprint`, which covers every pipeline metadata field.

## Context

The project compares algorithms. Before the first real one arrives, "algorithm" has to
be defined, and the obvious definition is wrong.

Almost nothing in this field ships as a complete image-to-score system. What exists is
extractors, matchers, and combinations of the two:

* **SourceAFIS** does both. One project, one version, one number.
* **NBIS** does not. `BOZORTH3` matches minutiae; `MINDTCT` produces them. A result
  labelled "Bozorth3" silently omits half of what produced it, and NIST's own
  documentation is explicit that BOZORTH3 consumes MINDTCT output.
* **OpenAFIS** is a matcher only. Using it means choosing an extractor, and the choice
  changes the results.

So a name like "Bozorth3" or "OpenAFIS" does not identify anything reproducible. Two
studies using the same matcher and different extractors would report numbers under the
same label — and a reader would have no way to know.

The same trap exists in the other direction. Resolution profile is *not* part of the
algorithm: `sourceafis_java` at native resolution and `sourceafis_java` at a canonical
500 ppi are the same implementation under two execution profiles, and folding the
profile into the name would make them look like different algorithms.

## Decision

**The unit of comparison is the complete pipeline that takes the experiment's input and
produces a raw score.** An identity names all of it.

Where extraction and matching come from separate implementations, both appear:

```
sourceafis_java              SourceAFIS extraction + SourceAFIS matching
nbis_mindtct_bozorth3        MINDTCT extraction + BOZORTH3 matching
<extractor>_openafis         a named extractor + OpenAFIS matching
```

A matcher-only name must never label a result that also depends on an unnamed
extractor.

`AlgorithmDescriptor.metadata` carries the pipeline explicitly, and all of it reaches
`descriptor_fingerprint`:

```yaml
family_id, pipeline_kind
extractor_id, extractor_version
matcher_id, matcher_version
upstream_artifact, implementation_language
integration_mode, bridge_protocol
input_mode, dpi_policy, probe_side
template_cache, template_persistence
```

SourceAFIS fills in extractor and matcher with the same value, because they *are* the
same implementation. The fields are still separate and still both populated — the point
is that the next algorithm will not be so tidy, and the schema must not have to change
when it arrives.

Changing any of these produces a different algorithm identity and therefore a different
`run_id`: SourceAFIS version, bridge protocol, integration mode, extractor or matcher,
adapter version, DPI policy, template-cache policy. `display_name` does not, because
renaming a matcher in a report must not invalidate results
([ADR 0002](0002-minimal-adapter-contract.md)).

Resolution profile stays out of the identity and lives in `ExecutionProfile`.

## Alternatives

**Name the matcher, document the extractor separately.** Rejected: documentation drifts
from data, and the identity is what a result record is joined on.

**One free-form `algorithm_name` string.** Rejected: it cannot be checked, and two
pipelines that differ in one component would be indistinguishable to any tool.

**Include the resolution profile in the name.** Rejected: it would present one
implementation as several, and make an execution-profile comparison look like an
algorithm comparison.

## Consequences

* Integrating NBIS means naming it `nbis_mindtct_bozorth3` and populating both halves,
  which is more typing and exactly the point.
* A pipeline that swaps in a different extractor is a *different algorithm* with a
  different fingerprint and a different run, not a variant of the old one.
* Reports must use the full identity. "SourceAFIS scored X" is acceptable prose only
  where the pipeline is stated nearby.
