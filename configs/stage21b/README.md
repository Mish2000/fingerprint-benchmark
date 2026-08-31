# Stage 21B local adapter configuration

`scripts/stage21b.py preflight` and `run` take a private YAML or JSON file. The
file is local operational input and must not be committed: only its SHA-256 is
bound into the run specification. Its outer shape is always:

```yaml
schema_version: 1
algorithm_id: sourceafis_java
adapter_id: sourceafis_java_subprocess
adapter_config:
  # the exact configuration accepted by that certified adapter
```

Use the same pinned research bundle/build that produced the predecessor run.
`research_mode: true` is mandatory. Runtime assets are re-hashed and must occur
in that method's hash-bound Stage 21A predecessor evidence; a digest from a
different roster method is not accepted.

The route-specific `adapter_config` keys are:

- SourceAFIS: the keys accepted by `SourceAfisJavaConfig.from_mapping`, including
  the pinned runtime-bundle identity, bridge digest/size and source revision.
- NBIS: `mindtct_executable`, `bozorth3_executable`, `build_manifest`,
  `research_mode`.
- FLX: `bundle_root`, `worker_script`, `runtime_lock`, `runtime_policy`,
  `research_mode`.
- VeriFinger: the keys accepted by `VeriFingerJavaConfig.from_mapping`, including
  installation, pinned bundle, bridge and runtime-manifest identities.
- MCC: `mindtct_executable`, `bozorth3_executable`, `build_manifest`,
  `mcc_bridge`, `mcc_bridge_manifest`, `mcc_sdk_dll`, `research_mode`.
- OpenAFIS capacity extension: `mindtct_executable`, `bozorth3_executable`,
  `build_manifest`, `openafis_bridge`, `research_mode`.

All filesystem values required by an adapter must be absolute. The preflight
does not create a benchmark score; it checks Stage 21A, the roster and pair
manifest, all prepared images, adapter availability, licence/runtime probes,
asset hashes, source cleanliness, workspace collision/integrity and free disk.
