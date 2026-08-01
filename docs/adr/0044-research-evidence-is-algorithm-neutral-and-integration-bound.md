# 0044 — Research evidence is algorithm-neutral and integration-bound

*Status: Accepted — 2026-08-02, stage 7A*

## Context

The generic research engine could drive a second adapter, but its durable
receipt still called one runtime asset a bridge jar and called the validator a
SourceAFIS validator. It also stored `integration_id` only in the mutable
current-run pointer. Two integrations with the same adapter and runtime roles
could therefore prepare and execute the same run even when they selected
different validators.

The already published SourceAFIS receipts and finalization markers are evidence.
Changing their fields, fingerprints or identifiers is not a schema migration;
it is retroactively changing a claim.

## Decision

New research runs use an algorithm-neutral evidence schema:

- receipts store `runtime_asset_sha256s`, covering every role in the pinned
  bundle;
- receipts and finalization markers store
  `algorithm_validation_fingerprint`;
- both store `integration_id` and `integration_fingerprint`;
- the integration fingerprint covers the integration id, adapter id, ordered
  runtime roles and primary runtime role. Hook implementations remain covered
  by the pinned fpbench source commit.

The same integration identity is inserted into the research environment, so it
reaches both `environment_fingerprint` and `run_fingerprint`. Every execute,
inspect and finalize reload compares the recorded identity with the supplied
integration before it can use the validator.

Receipt schemas 1 and 2 and finalization schemas 1 through 3 are explicit legacy
types. They keep their original SourceAFIS fields and fingerprint rules. A
legacy run whose environment predates integration identity follows that legacy
path; new runs cannot silently fall back to it.

## Consequences

A new algorithm does not require a core receipt or finalization change. A
multi-tool runtime cites all its executable bytes, and its evidence contains no
field or value inherited from the first algorithm.

Changing `integration_id`, role order or primary role produces a different
environment and run. Loading a prepared run through another integration is a
preflight failure even when the adapter descriptor and bundle happen to agree.

The old SourceAFIS run, result-set, decision-set, metric-set and paired-evaluation
identities remain unchanged and continue to verify through the explicit legacy
reader.

## Alternatives considered

**Rename the old fields in place.** Rejected because the serialized content is
part of the evidence fingerprint.

**Keep integration identity only in the pointer.** Rejected because the pointer
is navigation, not authority, and does not bind the validator used at
finalization.

**Hash Python callables.** Rejected because callable source is already pinned by
the clean repository commit and Python object serialization is not a stable
identity format.
