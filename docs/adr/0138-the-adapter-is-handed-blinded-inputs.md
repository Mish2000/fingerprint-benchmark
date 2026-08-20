# ADR 0138 — the adapter is handed blinded inputs

## Status

Accepted.

## Context

`PreparedImage` documents itself as carrying "nothing that would let an adapter
infer what the comparison is for. There is no subject, no finger, no impression
and no pair here."

That was true of the fields it declares and false of two of their values.

`image_id` is minted by the dataset catalogue, and SD300's is composed as
`<release>_<subject>_<impression>_<finger>`
(`fpbench.datasets.sd300.catalog`). Handed two of those, an adapter can compare
the subject segments and answer *mated or not* without looking at a single
ridge. `local_path` carries the same information a second time, in the filename
NIST published.

Nothing in this repository exploited it. That is not the point. The product of
this benchmark is the demonstration that a score was earned, and a reader has no
way to rule out an inference that the inputs make available. "We did not do it"
is a weaker claim than "it could not have been done", and only one of the two
survives someone else running the adapter.

The same argument does not apply to everything on the object. Resolution, media
type, the publisher's digest, the prepared digest, the preparation-set
identities: an adapter has a legitimate need for each, and none of them names a
subject.

## Decision

**The runner does not hand an adapter the catalogue's `PreparedImage`. It hands
a blinded copy.**

`fpbench.execution.blinding.RunBlinding` gives every image a per-run alias —
`img_` and sixteen hex characters of an HMAC over a secret drawn fresh for the
run — and materialises the bytes at a path named after the alias, inside the
job's working directory. Every other field is carried across untouched.

Three properties, and each was chosen against an alternative:

*The alias is computed, not counted.* A counter would have made the first image
of the first pair `img_1`, and the order images are first seen in is itself a
fact about the manifest.

*The secret is per-run and never persisted.* Aliases from two runs cannot be
joined, and nothing published can be used to reverse them afterwards.

*The bytes are copied, per job, and removed with the job.* A hard link was the
obvious choice and is wrong. The prepared-image store requires a canonical
artefact to be *the only name for its bytes*, and refuses a set where one has
more — because a second name is a second way to rewrite a blob that is supposed
to be immutable. Blinding does not get to weaken an integrity control to save a
copy, so it pays for one. Staging once per *run* instead of per job would have
been cheaper still and would have hidden exactly the mid-run artefact
replacement `PreparedImageDriftError` exists to catch (ADR 0033).

## What this does not claim

**It is not a defence against a hostile adapter.** Adapters run in this process.
One that wanted the mapping could read it out of the runner's memory, and no
in-process arrangement changes that.

What it removes is inference *from the inputs*: the thing a well-meaning adapter
could do by accident, and the thing a reader cannot otherwise rule out. After
this, an adapter that knows which pairs are mated had to work for it — and that
is a different claim from "it might just have read the filename".

## Consequences

* Stored results are unaffected. `RawResultRecord` takes its image ids from the
  `ComparisonJob`, not from the `PreparedImage`, so the real ids continue to be
  recorded exactly as before.
* Preparer provenance is unaffected: `_runner_metadata` is assembled from the
  *unblinded* pair, because `side_metadata` describes the artefact rather than
  what the adapter was told about it.
* An adapter's error messages now name an alias. That is a small loss of
  readability in a log, and the run's own metadata maps it back.
* One extra copy of each side, per comparison. The adapters that shell out to a
  subprocess already stage their own copy, so this roughly doubles input staging
  and changes nothing else; the files are canonical 500 ppi PNGs and the copies
  are deleted as each job ends.
* A test double that scripts a score per pair of images can no longer look its
  script up by image id. `SingleJobRunner.blinding` is readable so the *harness*
  can invert the mapping and hand the double a translation — never the adapter
  under test, which receives exactly what production adapters receive.
* Constructing a `PreparedImage` with a real id remains normal and correct.
  What is not correct is passing one to `compare()` directly, and the class
  docstring says so.

## Alternatives

**Strip the id entirely.** An adapter that legitimately caches by input identity
could no longer do so, and the harness would have to reintroduce something
alias-shaped to replace it.

**Rename ids at the catalogue.** The catalogue's readability is load-bearing:
a manifest row, a log line and a result row are lined up by eye during
debugging. The blinding belongs at the boundary that has the problem.

**Document the hazard and rely on review.** This is what was already in place —
the docstring stating the property — and it is how the two fields came to
contradict it.
