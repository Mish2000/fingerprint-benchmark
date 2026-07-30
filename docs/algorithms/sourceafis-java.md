# SourceAFIS for Java

The project's first real biometric integration.

## 1. Pipeline

`sourceafis_java` — SourceAFIS extraction followed by SourceAFIS matching, end to end
from two images to one similarity score.

Both halves of the identity are named even though they are the same implementation
here, because the next algorithm will not be so tidy: "Bozorth3" alone would omit
MINDTCT, and a result labelled that way could not be attributed
([ADR 0014](../adr/0014-algorithm-identity-describes-full-pipeline.md)).

```yaml
algorithm_id: sourceafis_java
display_name: SourceAFIS for Java
adapter_id: sourceafis_java_subprocess
adapter_version: "1"
adapter_contract_version: "1"
implementation_version: "3.18.1"
score_direction: higher_is_better
deterministic: true
capabilities: []

metadata:
  family_id: sourceafis
  pipeline_kind: end_to_end_image_matcher
  extractor_id: sourceafis_java
  extractor_version: "3.18.1"
  matcher_id: sourceafis_java
  matcher_version: "3.18.1"
  upstream_artifact: com.machinezoo.sourceafis:sourceafis:3.18.1
  implementation_language: java
  integration_mode: subprocess_per_comparison
  bridge_protocol: fpbench.sourceafis.bridge.v1
  input_mode: encoded_image
  dpi_policy: explicit_effective_ppi
  probe_side: left
  template_cache: disabled
  template_persistence: disabled
  seed_usage: ignored_algorithm_has_no_seed
```

All of that reaches `descriptor_fingerprint`, and therefore `run_id`. Changing the
SourceAFIS version, the bridge protocol, the integration mode, either half of the
pipeline, the adapter version, the DPI policy or the template-cache policy produces a
different run. Renaming `display_name` does not.

## 2. Version, coordinate, licence

| | |
|---|---|
| Version | 3.18.1, pinned exactly |
| Maven coordinate | `com.machinezoo.sourceafis:sourceafis:3.18.1` |
| Licence | Apache License 2.0 |
| Upstream | https://sourceafis.machinezoo.com/ |
| Minimum Java upstream | 11 |
| fpbench reference Java | **17** |

Newer JVMs may run it, but the exact Java version is part of the environment
fingerprint, so a run on another JVM is a different run. The pinned regression score is
only asserted on 17.

Everything bundled into the shaded jar is enumerated in
[integrations/sourceafis-java/THIRD_PARTY_NOTICES.md](../../integrations/sourceafis-java/THIRD_PARTY_NOTICES.md).
All of it is Apache-2.0 or MIT.

## 3. How it is invoked

One stateless JVM per comparison, JSON on stdin, one JSON document on stdout, protocol
`fpbench.sourceafis.bridge.v1`. Slow by design: it makes cross-comparison state
impossible, limits a crash to one result, and pins the JVM configuration exactly
([ADR 0015](../adr/0015-sourceafis-uses-stateless-java-bridge.md)).

The request carries **two paths and two resolutions** — no pair id, no subject, no
finger, no stage, no ground truth, no threshold
([ADR 0010](../adr/0010-adapter-context-excludes-ground-truth.md)). Protocol details
for the wire format are in
[the bridge's README](../../integrations/sourceafis-java/README.md).

## 4. Probe and candidate

```
left  = probe
right = candidate
```

Fixed. Never reversed, never averaged over both directions, never the maximum or
minimum of the two. If asymmetry is ever worth measuring it will be a separate
experiment, not a quiet change inside the adapter.

## 5. Resolution

Each side is sent its own `PreparedImage.effective_ppi`:

```
SD300A → 500      SD300B → 1000      SD300C → 2000
```

SourceAFIS **ignores the DPI embedded in an image** and has to be told, which is exactly
what this project needs: 10,115 SD300C files declare 5080 ppi and are genuinely 2000
([ADR 0004](../adr/0004-sd300c-effective-ppi.md)). The adapter never reads
`metadata_ppi`, never reads a `pHYs` chunk, and has no default.

All three values are verified to be accepted — no clamping, no fallback, no hidden
downsampling ([ADR 0016](../adr/0016-sourceafis-receives-explicit-effective-dpi.md)).

### Internal scaling is not our resampling

```
native profile (this stage)
    original bytes + effective DPI
    → SourceAFIS's own internal scaling to 500 ppi

canonical_500 profile (future, separate)
    shared fpbench resampling → derived 500-ppi PNG
    → SourceAFIS receives DPI 500
```

Two different things at two different layers. They are never mixed, and the second is a
separate execution profile and therefore a separate run.

## 6. Templates and transparency

* **No template cache**, no memoisation, no cross-call reuse.
* **No template serialisation or persistence.** SourceAFIS's native template format is
  tied to the implementation version and is best treated as a local cache with the
  source images retained — a good reason not to store one until there is a reason to
  want it.
* **Both sides are extracted independently**, even when the two paths are identical.
  `extraction_count: 2` is reported by the bridge and required by the adapter; a Java
  test counts the calls through an injected pipeline. A SELF comparison therefore costs
  two extractions of the same bytes, deliberately.
* **Algorithm transparency is off.** SourceAFIS can emit extraction and matching traces;
  that becomes an optional capability later, not part of the first integration.

`RawMatchResult.artifacts` is always `()`.

## 7. Score

A non-negative similarity, higher is better. Stored raw, with its direction, and
nothing else.

**The upstream threshold of 40 is documentation only.** SourceAFIS describes it as an
approximate correspondence to a 0.01% FMR while noting that the relationship depends on
image quality and population. It is not applied anywhere in this stage: no threshold, no
MATCH/NON_MATCH, no calibration ([ADR 0003](../adr/0003-decision-outside-adapter.md)).

`context.deterministic_seed` is unused — SourceAFIS has no seed — and that is recorded
as `seed_usage: ignored_algorithm_has_no_seed` rather than left to be inferred.

## 8. Timing

The bridge reports its own breakdown: `left_input_read`,
`left_template_extraction`, `right_input_read`, `right_template_extraction`,
`matcher_initialization`, `matching`, `bridge_total`. The runner separately measures
`adapter_ms` and `total_ms`.

The gap between `adapter_ms` and `bridge_total` is JVM startup, JSON serialisation and
process overhead. It is **not** subtracted, and `adapter_ms` must not be presented as
SourceAFIS's own speed at this stage.

## 9. Commands

```bash
make sourceafis-build          # build the bridge (one command, pinned Maven)
make sourceafis-java-test      # Java unit tests
make sourceafis-python-test    # Python tests that need a real JVM
make sourceafis-test           # build + all of the above
make sourceafis-sd300-smoke    # the 24-job real-SD300 pilot
```

The smoke test needs `FPBENCH_SD300_ROOT` set; see
[data/README.md](../../data/README.md).

## 10. Reproducing a comparison

```python
from fpbench.adapters import create_adapter

adapter = create_adapter("sourceafis_java_subprocess")
report = adapter.validate_environment()      # READY, or a reason why not
report.dependencies["sourceafis"]            # "3.18.1", as SourceAFIS reports it
report.dependencies["bridge.jar.sha256"]     # in the environment fingerprint
```

Then hand two `PreparedImage`s and a `ComparisonContext` to `adapter.compare(...)`, or
— normally — let `SingleJobRunner` do it. See the README's "Running the experiment"
section; nothing about the run path changes because the algorithm is real.

Environment validation refuses to proceed when the JVM is missing, the jar is missing,
the bridge protocol or version disagrees, or SourceAFIS on the classpath is not 3.18.1.
That last check reads the version *from SourceAFIS at runtime*, so a jar built from a
different release cannot quietly produce results attributed to 3.18.1.

## 10b. Research mode

The adapter has two modes, and the difference is not what it computes.

In **development mode** it runs `integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar`,
which is what `make sourceafis-test` and the pilot use. Convenient, and unsuitable for a
run whose numbers will be cited: that file is build output, and one `mvnw package`
replaces it at the same path.

In **research mode** the configuration additionally carries

```python
runtime_bundle_id            runtime_<12 hex>
runtime_bundle_fingerprint   64 hex
expected_bridge_jar_sha256   64 hex
expected_bridge_jar_size     bytes
fpbench_source_revision      40-character commit SHA
research_mode                True
```

All of them are required together — half a pin is not a pin — and the jar must live
inside `workspace/runtime/bundles/<bundle_id>/assets/`. `validate_environment()` then
re-hashes the jar **before** locating Java, so a wrong pin costs a hash rather than a
run, and records the file's identity (device, inode, size, `mtime_ns`). Before every
`compare()` that identity is re-checked with one `stat`; a mismatch raises
`RuntimeDriftError`, which the runner re-raises unrecorded and which stops the executor
immediately. The full digest is verified before and after each executor invocation
([ADR 0018](../adr/0018-external-runtime-assets-are-content-addressed.md)).

Every stored result then carries five extra metadata fields:

```yaml
runtime_bundle_id: runtime_...
runtime_bundle_fingerprint: ...
bridge_jar_sha256: ...
bridge_jar_size: ...
fpbench_source_revision: ...
```

Still no path, and still no threshold. A result found on its own can say which executable
and which harness commit produced it without consulting anything beside it.

## 11. Known limitations

* **One JVM per comparison.** Correct and slow. Whether to keep paying for it is a
  question for the full run's operational summary, not for guesswork.
* **`adapter_ms` includes JVM startup**, so it is not a measure of the algorithm. The
  bridge's own `bridge_total`, `left_template_extraction`, `right_template_extraction`
  and `matching` are reported separately for exactly this reason.
* **A byte-identical replacement of the pinned jar still raises `RuntimeDriftError`.**
  The cheap check cannot tell a harmless copy from a harmful one without re-hashing
  27 MB, and stopping is the only safe reading.
* **No accuracy claim.** See below.
* The synthetic test fixtures are procedural textures, not fingerprints; the scores they
  produce describe the generator, not SourceAFIS
  ([tests/fixtures/sourceafis/README.md](../../tests/fixtures/sourceafis/README.md)).
* SLF4J prints a no-op-logger notice to stderr on every invocation. Harmless; stdout
  stays clean.

## 12. What has *not* been done

**The integration mode has not changed.** Stage 4B runs the same stateless subprocess it
always did. A persistent JVM worker would be a different pipeline in every way that
matters — new adapter version, new `integration_mode`, new descriptor fingerprint, new
run, new ADR — and adopting one quietly in order to finish 6,000 comparisons faster would
make the results incomparable with everything before them
([ADR 0015](../adr/0015-sourceafis-uses-stateless-java-bridge.md)). The full run's
operational summary is what that decision should rest on.

**There is no accuracy claim, and no comparison against the dummy adapter.** No
threshold has been applied, no decision has been made, no SELF filtering has been derived
from real results, and no FMR, FNMR, ROC, DET or EER has been computed. Six thousand raw
scores do not change this: what is missing is not data but the definitions that would
make a number derived from it mean something — decision profiles, the SELF eligibility
rule, the failure denominators, and the provenance of whichever threshold is applied
([ADR 0003](../adr/0003-decision-outside-adapter.md)).

**Nothing is cached, stored or reused between comparisons.** No template is serialised,
no transparency output is produced, no artefact is written. The evidence validator checks
that `artifacts == ()` on every result rather than trusting it.
