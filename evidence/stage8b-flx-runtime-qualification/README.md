# Stage 8B — flx experimental runtime and adapter qualification

Final outcome: **`FLX_RAW_SCORE_EXECUTION_READY`**.

Stage 8B turned one public artifact into a local inference route and asked
whether that route could be executed at benchmark scale without changing
anything the engine already does. It did not read an SD300 image, open the
existing prepared-image set, run the pair manifest, execute any of the 6,000
comparisons, produce a research `ResultSet`, choose a threshold, create a
`DecisionProfile`, compute eligibility or metrics, compare against SourceAFIS
or NBIS, train, fine-tune, calibrate or reweight anything.

Every dynamic check ran on generated, non-biometric fixtures.

## What runs

| | |
| --- | --- |
| `algorithm_id` | `flx_deepprint_texminu_512_without_localization` |
| implementation | independent reimplementation, author-supplied for Rohwedder et al., BIOSIG 2023 |
| source | commit `7accfca1`, archive SHA-256 `60fa2c88…` |
| checkpoint | `best_model.pyt`, 875,770,140 bytes, SHA-256 `2683a044…` |
| variant | `DeepPrint_TexMinu_512_without_localization` |
| runtime | `flx_cpu_linux_x86_64_v1` — Ubuntu 24.04, x86_64, Python 3.12.3, torch 2.13.0+cpu, one thread |
| transform | `fpbench_canonical500_to_flx299_squarepad_v1` |
| representation | `flx_texminu_256x2_v1` — 256 + 256, each L2-normalized |
| score | `flx_texminu_equal_branch_dot_v1` — two dot products added, `Decimal`, higher is more similar |

It is deliberately not called "DeepPrint". The code is not DeepPrint's, the
weights are one variant with no localization branch, and the input route is
this project's own (docs/adr/0069).

## The fifteen gates

All fifteen passed. Every one is conjunctive, and the record type refuses any
other combination of gates and outcome.

```
artifact_identity_verified   runtime_identity_verified   checkpoint_loaded
model_variant_verified       strict_key_validation       preprocessing_contract
representation_contract      score_contract              self_independence
determinism                  restart                     offline_isolation
operational                  architecture_fit            license_status
```

The checkpoint loaded as pure tensors under `weights_only=True`, and
`DeepPrint_TexMinu(8000, 256, 256)` accepted its 1,170 state-dict entries under
`strict=True` with **zero missing and zero unexpected keys**.

Determinism holds at tolerance **zero**: A's texture and minutia representations
are bitwise identical in `[A, A]`, `[A, B]`, `[B, A]`, `[A, C]` and `[C, A]`.
Repeated extraction, repeated comparison and input order are also bitwise equal,
and a fresh process reproduces the representation, score and metadata exactly.

SELF independence records two `preprocess` calls, two `extract` calls, distinct
objects and distinct buffers. The adapter profile structurally establishes
`representation_cache_capability_present: false`; no constant is presented as a
dynamic cache observation. The two sides are equal, which is expected and is
not the thing being tested.

Nothing attempted to reach the network.

## Measurements, against limits frozen first

The operational limits were frozen before the authoritative Stage 8B
qualification probe and before the published measurements. A preliminary
generated-fixture timing read no SD300 data and was not used to tune a limit
from a biometric result. `stage8b_flx_runtime_policy_v1` inherits Stage 8A's
three full-run budgets by fingerprint rather than restating them.

| | measured | limit |
| --- | --- | --- |
| worker startup | 2.76 s | 60 s |
| model load | 1.11 s | 300 s |
| preprocess (median) | 4.89 ms | 60 s deadline |
| extract (median) | 0.756 s | 120 s deadline |
| compare (median) | 0.30 ms | 60 s deadline |
| peak RAM | 1.20 GB | 32 GB |
| bundle on disk | 2.06 GB | 10 GB |
| projected 12,000 extractions | 9,069 s (2.52 h) | 86,400 s |
| projected 6,000 comparisons | 1.81 s | 21,600 s |

A projection is an operational gate. It is not a benchmark, not a quality
claim and not a promised wall clock.

## Three things that were measured rather than assumed

**One extraction is a duplicated pair.** The pinned texture branch squeezes its
batch dimension away and then normalizes along `dim=1`, so a batch of one
raises before any embedding exists. There is no single-image path in this
artifact. Each extraction therefore feeds the identical tensor twice and
represents row 0, asserting that the two rows are bitwise equal. The real
checkpoint produced bitwise-identical texture and minutia representations for A
across five legal content and position contexts at batch size two. An additional
batch-size-three diagnostic drifted slightly and is documented in ADR 0070 as
outside the fixed route. Spec section 17.6's
single-versus-batch comparison is recorded as `not_applicable` rather than
answered with an invented API. ADR 0070 is **Accepted** on the legal-context proof.

**A SELF score is 2.0000001192092896, not 2.** The branches are normalized in
float32, so each self-dot-product exceeds 1 by about an ulp. The declared range
stays `[-2, 2]`; enforcement allows the exact decimal
`0.000000476837158203125` (`2**-21`), four float32 ulps derived from the format
rather than fitted to the measurement. `range_validation_tolerance` and
`range_validation_policy: nominal_bounds_plus_symmetric_tolerance_no_clamp`
are part of `score_profile_fingerprint`. The score is never clamped
(docs/adr/0073).

**An all-white image does not resize to a constant.** The antialiased bilinear
resize computes its filter weights in float32 and they do not sum to exactly
one, so a uniform image lands in `[0.9999997615814209, 1.0000003576278687]`.
Clamping would change pixels in a step neither the spec nor upstream performs.
The allowance is `2**-20` and the values are left alone.

None of these is the determinism tolerance, which is still exactly `0`.

## Licence

The checkpoint's licence remains **unresolved**, and every document here says
so:

```
weights_license_status:   unresolved
redistribution_allowed:   not_established
publication_permission:   not_established
```

Executing it locally is something the project owner instructed. That is not a
licence finding, and no record type in Stage 8B can be constructed claiming
otherwise (docs/adr/0068). Stage 8A's `LICENSE_BLOCKED` conclusion is not
revised; Stage 8A asked whether the artifact qualified for selection under a
policy requiring established rights, and it did not.

The checkpoint is not committed, not redistributed and not published.

## What is published, and what is not

Published: hashes, sizes, versions, pass/fail observations, representation
hashes, score hashes, timings, memory and failure codes.

Not published: checkpoint bytes, source archive bytes, fixture
representations, embedding values, raw fixture scores, machine-local absolute
paths, environment secrets. The loader refuses to read a document containing
any of them.

## Re-verification

Verification needs neither torch nor the weights:

```console
python -m fpbench.experiments.stage8b_flx_runtime_qualification verify
```

It reloads strict JSON — duplicate keys, non-finite numbers, unknown and
missing fields are all errors — recomputes each record's fingerprint from its
claims, rebuilds all four profiles from this repository's source and compares
them to what was published, re-applies the fifteen gates to the published
probe, re-derives the finalization, and re-hashes the exact bytes of all ten
files. The boundary audit compares two fixed commits, reading the span's end
from the published marker so that Stage 8C can exist without editing Stage 8B
(docs/adr/0067).

## Next-stage gate

`FLX_RAW_SCORE_EXECUTION_READY` opens **Stage 8C — flx canonical_500 raw run**:
6,000 comparisons, 12,000 independent extractions, the same 3,000 prepared
canonical inputs, the same pair manifest, the same order, the same
probe/gallery direction, the same failure policy.

It produces raw scores and nothing else. Thresholds, decisions, eligibility and
metrics stay outside it (docs/adr/0065). Raw-score readiness is not decision
readiness, and `permits_decisions` is `false` in the report that opened it.
