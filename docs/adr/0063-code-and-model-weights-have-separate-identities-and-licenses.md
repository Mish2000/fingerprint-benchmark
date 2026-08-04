# 0063 — Code and model weights have separate identities and licences

*Status: Accepted — 2026-08-04, stage 8A*

## Context

A learned matcher is not identified by source code alone. The same constructor
can load checkpoints trained on different data, for different representation
dimensions or with different branches enabled. Conversely, a checkpoint cannot
be interpreted without the exact model code and configuration that assign
meaning to its tensors.

Distribution terms also do not automatically cross that boundary. A repository
may license source code while saying nothing about a checkpoint hosted on a
release page or cloud drive. Training data or a third-party minutiae component
may impose separate restrictions. Inferring that the source licence covers all
downloaded files would turn silence into permission.

The `flx` acquisition method makes the distinction concrete: its repository
and separately hosted checkpoint must be inspected and licensed as different
objects. Whatever the later acquisition finds about one cannot establish a
licence for the other.

## Decision

Source code and every model checkpoint are separate components in a candidate
artifact manifest. Each has its own identity, provenance and licence record.

Source identity includes, as applicable:

* canonical upstream URL;
* exact commit or immutable source archive;
* archive SHA-256 and byte size;
* implementation authors and relationship to the claimed paper; and
* the source-code licence text or an immutable reference to it.

Checkpoint identity includes:

* exact filename;
* SHA-256 and byte size;
* serialized format;
* model variant and embedding dimension;
* the upstream-documented training provenance; and
* a checkpoint-specific licence conclusion.

Configurations, external detectors and other components capable of changing a
representation or score also receive their own component identities. Required
third-party licences and upstream-stated dataset or training restrictions are
recorded separately.

The manifest's overall fingerprint covers every component and every licence
conclusion. Replacing checkpoint bytes while retaining the filename, moving the
source revision, changing the claimed model variant, or changing a licence
conclusion produces a different artifact identity. A cloud link by itself is
not an identity; acquisition must result in exact bytes whose digest and size
match the manifest.

Licence gates are fail-closed and scoped. A clear source-code licence cannot
satisfy an absent or ambiguous weights licence. At minimum, the evidence must
permit use in an academic benchmark and publication of the allowed evidence;
redistribution is recorded independently and is never inferred. Missing
permission for any required component makes the artifact `LICENSE_BLOCKED`,
even if it executes locally.

An exact source identity can therefore remain useful acquisition evidence even
when the corresponding checkpoint licence is absent or unclear. Likewise, a
paper or architecture description never stands in for checkpoint identity.

## Alternatives considered

**Give the entire artifact the repository's licence.** Rejected because a
repository licence applies according to its own scope; it does not create
rights in separately hosted trained parameters or third-party components.

**Identify a model by URL and filename.** Both can remain unchanged while their
bytes change. Content identity is required for reproducibility and tamper
detection.

**Hash only a combined runtime bundle.** A combined digest detects change but
does not reveal whether code or weights changed, and it cannot carry distinct
licence conclusions.

**Assume local execution is enough when redistribution is forbidden.** Local
execution and publication are separate permissions. The qualification records
both rather than silently treating one as the other.

## Consequences

Acquisition records are more verbose, and one candidate can be blocked despite
having fully inspectable code and weights. The gain is that a result can name
the exact program and trained state that produced it, and a reviewer can audit
legal conclusions at the component boundary where they actually apply.

Evidence publishes identities and conclusions, not model weights, proprietary
source, licence keys, embeddings or scores. If upstream later supplies a
checkpoint licence, that creates a new acquisition and qualification
fingerprint; it does not edit the historical blocked record.
