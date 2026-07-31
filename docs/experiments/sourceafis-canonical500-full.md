# The canonical 500 ppi SourceAFIS run

`configs/experiments/sourceafis_canonical500_full_v1.yaml`

## What it is

The same 6,000 SD300 comparisons the stage 4B native run performed, over the
shared canonical 500 ppi input set. Same protocol, same cohort, same pair
manifest, same pair order, same probe/candidate direction, same SourceAFIS
3.18.1, same unchanged adapter, same Java bridge, same 60-second timeout,
sequential, no retries.

The orchestration is literally the same code —
`fpbench.experiments.sourceafis_research` — and both experiments are thin
wrappers over it. That is not a tidiness argument: the claim of this stage is
that the two runs differ in exactly one thing, and two copies of the
orchestration would be two chances for the difference to be something else.

The one difference is which file the adapter opens.

## What does not change

The SourceAFIS algorithm identity is byte-for-byte the same descriptor:

```
algorithm_id            sourceafis_java
implementation_version  3.18.1
adapter_id              sourceafis_java_subprocess
adapter_version         1
integration_mode        subprocess_per_comparison
```

No adapter version bump, no bridge version bump, no `algorithm_fingerprint`
change. Native and canonical differ in the **execution profile fingerprint**,
the **preparation set fingerprint** and therefore the **run fingerprint** —
nowhere else.

## Running it

The preparation set must exist and be `PREPARATION_READY` first. Its id is
derived from its entry hashes and so is unknown until the last image is
materialised, which is why both configs are committed with a placeholder and
filled in afterwards. A run refuses to start while the placeholder is present
rather than inventing a set.

Preflight does not merely ask whether the set contains every requested image.
It binds the verified preparation definition and manifest to the authoritative
SD300 dataset id, image-manifest hash, protocol, cohort, pair manifest and exact
ordered image-id list. A rehashed but substituted source identity is a hard
preflight failure.

```bash
python -m fpbench.experiments.sourceafis_canonical500_full prepare
```
```bash
python -m fpbench.experiments.sourceafis_canonical500_full execute --max-new-jobs 500
```
```bash
python -m fpbench.experiments.sourceafis_canonical500_full status
```
```bash
python -m fpbench.experiments.sourceafis_canonical500_full finalize
```

## What each result records

Beyond everything a native result carries, `runner_metadata` holds:

```
preparer_id, preparer_version, runner_metadata_schema
preparation_set_id, preparation_set_fingerprint
transform_profile_id, transform_profile_fingerprint
transform_runtime_fingerprint
left_/right_ preparation_entry_hash
left_/right_ prepared_sha256
left_/right_ pixel_sha256
left_/right_ source_ppi, output_ppi, output_width, output_height
```

No path, ever. `raw_result_hash` already covers `runner_metadata`, so all of it
is inside the result-set fingerprint stage 6B will cite.

The validator checks each of these against the **entries of the actual set**,
not against another copy of the same claim. A result whose recorded entry hash,
file digest, raster digest and dimensions all match the entry for its own image
id could not have been produced from anything else.

Source resolutions are checked by joining back through the pair manifest —
SD300A entries from 500, SD300B from 1000, SD300C from 2000. They cannot be read
off adapter metadata, because by the time the adapter saw a file it was already
500 for all three.

## Timing

`preparation_ms` on a canonical result measures an entry lookup, a source-record
check, a `stat` and an object construction: microseconds. The resampling happened
before the run and is reported separately in the preparation summary. Comparing
the two runs' `preparation_ms` is meaningless in both directions.

## What this stage does not do

No threshold. No decision. No metric. No SELF eligibility. No native score is
read — `comparison_anchor` in the config records which native run stage 6B will
join against, and is used by nothing here.

Reaching `RESEARCH_READY` means 6,000 scores exist and can be attributed. It
does not mean they are better, worse, or the same. Whether identical SD300A
pixels produced identical scores is a stage 6B observation; stage 6A only proves
the pixels were identical.

The canonical research receipt names the preparation set id and fingerprint,
transform profile id and fingerprint, and transform-runtime fingerprint. Those
claims are re-derived from the run execution profile and the verified prepared
manifest during finalization and status inspection. Native receipts leave all
five fields null.

Algorithmic failures — template extraction, matching — are permitted and
counted. Infrastructure failures are not: a timeout, a crashed JVM, a decode
failure or a prepared-image drift blocks the receipt outright.
