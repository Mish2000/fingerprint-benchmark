# 0061 — Stage 8A qualifies artifacts, not papers

*Status: Accepted — 2026-08-04, stage 8A*

## Context

Stage 8A starts with three research targets: AFR-Net, the Minutiae-Guided
Vision Transformer (MGViT), and the fixed-length extractor published by `flx`.
The papers are relevant evidence about why those targets are interesting. They
are not executable evidence that this project can reproduce an image-to-score
pipeline.

A paper can describe a complete architecture while omitting the exact model
variant, trained parameters, input transformation, dependency versions, or
comparison function. A repository can likewise reproduce figures or training
while providing no inference path. Calling either one "available" would move
the missing choices into our integration and make our locally invented choices
look like properties of the published algorithm.

This distinction matters before any benchmark image is read. Stage 8A is not a
literature ranking and does not measure accuracy. It asks the narrower,
auditable question: does a particular, legally usable, content-identified
artifact already contain a complete and reproducible route from the project's
canonical PNG to a finite raw score?

## Decision

Stage 8A qualifies exact acquired artifacts. A candidate's paper establishes
its scientific claim and tier, but never satisfies an artifact gate.

Every qualification report binds the frozen candidate identity to an
acquisition manifest. That manifest identifies the actual implementation,
source revision or source archive, checkpoint, configuration, inference
components, dependency lock and relevant licences. The report then evaluates
the acquired bytes against all hard gates: scientific identity, complete
inference code, weights, preprocessing, representation, score, independent
SELF extraction, determinism, offline operation, licensing, architectural fit
and the future decision path.

The gates are conjunctive. There is no weighted literature score through which
novelty, reported accuracy or a high candidate tier can compensate for a
missing executable component. Tier ordering and the predeclared tie-breakers
are consulted only after all mandatory gates have passed.

Candidate-specific conclusions are not part of this registry-freeze decision.
They arrive only after acquisition and hard-gate derivation. A missing artifact
must remain missing in those later reports; this ADR does not authorize filling
the gap merely to obtain a selected outcome. A later release of upstream code
or weights requires a newly fingerprinted acquisition and qualification; it
does not retroactively alter a finished decision.

The reserve candidate, id3 Finger SDK, is outside stage 8A. Failure of the
modern artifacts does not silently activate it. Adding or substituting a
candidate requires a new registry version, registry fingerprint and ADR.

## Alternatives considered

**Rank the papers and implement the highest-ranked design.** This would answer a
different question and attribute our architecture and preprocessing choices to
the authors. It is also incompatible with the stage's no-reimplementation
boundary.

**Treat an upstream repository URL as an artifact.** A mutable URL does not say
which bytes ran. Qualification needs the exact source, checkpoint and component
identities, even when they all originate in one repository.

**Use a weighted readiness score.** A candidate with no weights could receive a
high average from novelty and documentation. The resulting number conceals the
specific condition that makes execution impossible.

**Fall back automatically to the commercial reserve.** That would change the
frozen candidate set, legal constraints and selection policy after seeing the
outcome.

## Consequences

Stage 8A can finish honestly with no selected matcher. No model is run over
SD300, no 6,000-pair experiment is started, and no performance conclusion is
made.

Qualification reports can be reproduced from content-addressed acquisition
evidence, and every rejection names exact failed gates rather than an informal
assessment. The cost is that a promising paper may remain unusable until its
authors publish the missing material. That cost is preferable to creating an
unidentified local algorithm and reporting it under an upstream name.
