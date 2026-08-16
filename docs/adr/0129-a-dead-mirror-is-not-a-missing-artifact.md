# A dead mirror is not a missing artifact

## Status

Accepted, implemented.

## Context

Stage 16A's G1 has one named failure: `SELF_SERVICE_ARTIFACT_INCOMPLETE`, raised
when a checkpoint the route needs is no longer obtainable without asking the
vendor or the author. That rule exists because three consecutive Algorithm 5
stages ended at somebody who had to answer, and docs/adr/0126 made self-service
acquisition a hard requirement in response.

FingerFlow's README publishes nine checkpoints. Two of the nine Google Drive
links — CoarseNet and FineNet — answer HTTP 404, and not through one endpoint's
quirk: `drive.google.com/uc`, `drive.google.com/file/d/` and
`drive.usercontent.google.com/download` all return 404 for both file ids. The
files are gone from that host.

The same README publishes a Dropbox link beside each of those two Drive links.
Both Dropbox links serve, and the bytes they serve are complete: 81,112,872 bytes
of CoarseNet and 654,226,304 of FineNet, both loading as valid HDF5.

The question is what a stage is entitled to conclude from the first dead link.
It is a real temptation to conclude quickly, because the answer is convenient:
a `SELF_SERVICE_ARTIFACT_INCOMPLETE` at G1 closes the stage in an afternoon and
never has to read the algorithm at all.

docs/adr/0122 already settled the shape of this for Stage 14A — a blocked fetch
is not a missing route — but that case was about *this* machine failing to
retrieve something. This one is different: the retrieval genuinely failed, from
every endpoint, and permanently. What rescues it is that the same publisher
published a second locator for the same artifact.

## Decision

**Obtainability is a property of the artifact, not of a URL.** A checkpoint is
self-service if *any* locator the upstream publishes serves it without a request
to a human. `SELF_SERVICE_ARTIFACT_INCOMPLETE` is raised only when no published
locator serves it.

Three things follow, and all three are in the evidence:

1. The acquisition record names, per checkpoint, **the locator that actually
   served the bytes** — not the one listed first. `CoarseNet` and `FineNet`
   record `source: dropbox`; the other seven record `source: google_drive`.
2. The dead locators are published as their own finding,
   `dead_upstream_locators`, with the host, the status and the endpoints tried.
   A reader must be able to see that two of nine links are broken without
   inferring it from the source field.
3. The served filename is recorded beside the stored one wherever they differ.
   Drive serves ClassifyNet as `ClassifyNet_6_classes.h5` and every VerifyNet
   weight under a misspelling — `VerfifyNet-10.h5`, `VerfiyNet-14.h5` — and a
   name that only exists in this repository's naming is not a fact about the
   artifact.

## Alternatives

**Fail at the first dead link.** Fastest, and wrong: it would publish
"FingerFlow's checkpoints are not obtainable", which is false, and it would end
the stage before the question worth answering — whether the route can be closed
— was ever asked. The candidate would then be unavailable to reconsider on a
basis that was never examined.

**Treat the mirror as an unofficial source.** Rejected. The Dropbox links are in
the upstream README, on the same lines as the Drive links, published by the same
author in the same commit. There is no sense in which one is official and the
other is not.

**Record only that the artifact was obtained.** Rejected. Two of nine published
links being dead is a real fact about this artifact's durability and belongs in
the evidence, whether or not it changes the gate.

## Consequences

G1 passes on nine checkpoints totalling 1,611,110,764 bytes, and the stage goes
on to ask G2, which is where it actually fails.

The cost is that acquisition can no longer be a single loop over a single host:
it resolves Google Drive's confirmation form for large files, follows Dropbox's
redirect for two, and carries a per-record source. That is more machinery than a
uniform fetch, and it is the machinery that made the finding above possible
rather than assumed.

The rule is general and applies to whatever candidate comes next: a stage may
report that a *locator* is dead, and may only report that an *artifact* is
unobtainable when every published locator for it has been tried.
