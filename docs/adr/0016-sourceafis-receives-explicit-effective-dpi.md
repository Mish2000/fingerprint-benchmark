# 0016 — SourceAFIS receives the effective DPI explicitly, per side

## Status

Accepted. Implemented in `fpbench.adapters.sourceafis_java` and the Java bridge.

## Context

SourceAFIS scales every image internally to 500 ppi before extracting minutiae, and it
**ignores whatever resolution the file claims**. It has to be told.

For this project that is a gift rather than an inconvenience. SD300C declares 5080 ppi
in the `pHYs` chunk of 10,115 files that are genuinely 2000 ppi
([ADR 0004](0004-sd300c-effective-ppi.md)). An algorithm that read the embedded DPI
would silently rescale those images by a factor of 2.54 and produce minutiae from a
distorted print — with no error anywhere.

There is also a second, subtler confusion to prevent. SourceAFIS's internal scaling to
500 ppi is *not* the same thing as the canonical-500 resampling this project may adopt
later as a shared execution profile. They happen at different layers, produce different
pixels, and must not be conflated in a report.

## Decision

Each side is sent its own `PreparedImage.effective_ppi`, explicitly:

```
SD300A → 500      SD300B → 1000      SD300C → 2000
```

The adapter never reads `metadata_ppi`, never reads a `pHYs` chunk, never falls back to
a nominal value, and has no default. `dpi_policy: explicit_effective_ppi` is recorded in
the descriptor metadata and reaches the fingerprint, and both resolutions actually sent
are recorded on every result as `left_dpi` and `right_dpi`, so a reader never has to
infer them.

The two sides may differ. SD300 pairs do not cross releases, but the bridge must not
assume they agree, and a test asserts it does not.

**All three values must be accepted, with no clamping, no fallback and no hidden
downsampling.** If SourceAFIS ever rejected 2000, the correct response is to stop and
reconsider the profile explicitly — not to quietly substitute 500 and carry on. A test
asserts that `UNSUPPORTED_RESOLUTION` never occurs at any of the three.

The two profiles are documented as distinct, and are never mixed:

```
native profile (stage 4A)
    original image bytes + effective DPI
    → SourceAFIS's own internal scaling to 500 ppi

canonical_500 profile (future)
    shared fpbench resampling → a derived 500-ppi PNG
    → SourceAFIS receives DPI 500
```

The second is a separate execution profile and therefore a separate run, not a variant
of this one ([ADR 0014](0014-algorithm-identity-describes-full-pipeline.md): resolution
profile is not part of the algorithm's identity).

## Related decision: no template reuse

The same section of the contract, because it is the same class of hazard — something
that would be invisible in the score:

* both sides are read and extracted **independently**, even when the two paths are
  identical, which is exactly what a SELF comparison looks like;
* no template is serialised, cached, memoised or persisted;
* `extraction_count: 2` is reported by the bridge and verified by the adapter, which
  refuses any other value as a contract violation.

SourceAFIS's own documentation notes that its native template format is tied to the
implementation version and should be treated as a local cache with the source images
retained. That is a good reason to keep templates out of storage entirely until there is
a reason to want them, and no reason yet.

## Alternatives

**Let SourceAFIS read the embedded DPI.** Not possible — it ignores it — and would be
wrong for SD300C even if it were.

**Normalise everything to 500 ppi before handing it over.** A legitimate experiment, and
a different one. It belongs in a separate execution profile so that native and resampled
results stay distinguishable.

**Reuse the template on a SELF comparison.** Rejected. It would make SELF the one stage
that took a different code path, and SELF is the stage most likely to be measuring
something subtle.

## Consequences

* SD300C is compared at 2000 ppi, and SourceAFIS does more internal scaling work there
  than for SD300A. Extraction time differs by release; that is a measurement, not a
  problem.
* A SELF comparison costs two extractions of the same bytes. Deliberate, and reported.
* Any future preparer that resamples must declare a new `preparer_id`, so results
  produced under each stay distinguishable
  ([ADR 0004](0004-sd300c-effective-ppi.md)).
