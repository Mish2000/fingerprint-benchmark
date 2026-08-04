# 0066 — No paper reimplementation is accepted as an upstream algorithm

*Status: Accepted — 2026-08-04, stage 8A*

## Context

When a paper has no runnable artifact, implementing its diagram can look like a
reasonable way to keep a benchmark moving. It is not a neutral recovery step.
Papers necessarily leave implementation choices unstated: exact layer details,
initialization, training schedule, data cleaning, localization, minutiae
generation, alignment, fusion, normalization and score behavior. Each choice
can change the representations and scores.

Even a careful reproduction is therefore a new implementation with its own
authors, provenance and validation burden. Labeling it with the original
algorithm's name would imply that the original authors supplied or endorsed the
artifact. It would also let a high-tier paper pass stage 8A because this project
quietly manufactured the evidence the gate was supposed to test.

The issue is especially important for the frozen candidate set. AFR-Net and
MGViT are eligible only as official or author-supplied artifacts in tiers A and
B. The `flx` implementation is identifiable in tier C as its own exact
fixed-length extractor and model variant; it is not evidence that some other
paper's original release exists.

## Decision

Stage 8A never accepts a locally or independently reimplemented paper as the
original upstream algorithm.

Scientific identity records both `claimed_algorithm_name` and
`actual_implementation_name`, the implementation authors, and the relationship
to the paper. The allowed relationship is explicit — for example `official`,
`author_supplied`, or `independent_reimplementation`. An independently written
artifact retains that label in its identifier and every report. It may not use
an unqualified identifier such as `deepprint`, `afr_net` or `mgvit` when its
bytes did not come from the corresponding upstream authors.

A thin wrapper is permitted only around a complete artifact. It may translate
the project's call boundary, stage already identified local files, invoke the
upstream API and convert its documented scalar result into the common raw-score
type. It may not implement or replace a core component, including:

* localization or alignment;
* a minutiae detector or external minutiae representation;
* model architecture or missing branch;
* branch fusion or reweighting;
* embedding normalization;
* similarity function, realignment trigger or fallback; or
* any threshold hidden inside a nominal comparison API.

Supplying one of those components creates a different complete pipeline under
ADR 0014. Considering it in a later stage requires a new candidate identifier,
registry version, registry fingerprint, provenance, licences and ADR. It does
not repair the frozen upstream candidate in place.

Accordingly, implementing AFR-Net or MGViT locally would not make an absent
official artifact complete. The separately named `flx` candidate is assessed
under its own implementation relationship; it is not renamed as an original
upstream release.

## Alternatives considered

**Call a faithful reproduction the original algorithm.** Fidelity is a claim
that cannot erase independent authorship or recover unpublished training and
implementation choices.

**Allow reimplementation only for a small missing component.** A "small"
localization, normalization or score function can change every representation
or comparison. Core behavior is a categorical boundary, not a line-count
threshold.

**Place the replacement in the adapter without changing identity.** Adapter
placement does not make algorithmic code into plumbing. The fingerprint and
name must describe the full image-to-score pipeline regardless of module
location.

**Reject independent reimplementations forever.** They can be legitimate
research artifacts when named honestly and evaluated as new candidates. The
decision forbids misattribution, not independent engineering.

## Consequences

Stage 8A can end without a matcher even when the papers appear implementable.
That preserves the meaning of its tier labels and makes any fail-closed result
auditable.

Future work may propose a separately named reproduction, but it starts with a
new registry decision and cannot inherit the original paper's official status,
tier or artifact qualification. Thin integration code remains possible once an
upstream artifact is complete; the boundary prevents that wrapper from growing
into an undisclosed new algorithm.
