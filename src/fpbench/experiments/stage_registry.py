"""One list of the published stages, and what each one's marker says.

The README, ``evidence/README.md`` and the report workbooks are three
descriptions of the same set of runs, each maintained by hand. They drifted in
the obvious way: Stage 20A's README section ended "...which opens Stage 20B",
and Stage 20B had been run, published and marked ``publication_eligible`` for
some time. A reader with the repository was told the work was still ahead of the
project while the evidence directory said it was done.

This module is the authority the three descriptions are checked against. It does
*not* restate what a marker says — it names where each marker lives and what
key carries its outcome, and reads the rest. A registry that copied the outcome
would be a fourth thing to keep in step.

Adding a stage means adding a row here. ``tests/contract/test_stage_registry.py``
then requires the directory to exist, the marker to parse, and — for a stage
whose marker declares it publication-eligible — the README to have a section
naming it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "PUBLISHED_STAGES",
    "PublishedStage",
    "read_marker",
    "stages_missing_from",
]


@dataclass(frozen=True, slots=True)
class PublishedStage:
    """One stage that has an evidence directory in this repository."""

    #: How the stage is written in prose: ``"20B"``, ``"8E"``.
    stage: str
    #: The evidence directory, repository-relative.
    directory: str
    #: The finalization marker inside it.
    marker: str
    #: The marker key carrying the stage's final outcome.
    outcome_key: str
    #: The heading a README section for this stage must begin with. ``None``
    #: for a stage the README documents inside another stage's section.
    readme_heading: str | None = None

    @property
    def marker_path(self) -> Path:
        return Path(self.directory) / self.marker


#: Every stage with a published outcome document, oldest first.
PUBLISHED_STAGES: tuple[PublishedStage, ...] = (
    PublishedStage(
        # The oldest marker predates the `outcome` key. `kind` is what it
        # carries, and reading it here beats back-dating a field into published
        # evidence to satisfy a registry written years later.
        "7C",
        "evidence/nbis-canonical500-raw",
        "stage-7c-finalization.json",
        "kind",
        readme_heading="## Stage 7C",
    ),
    PublishedStage(
        "8C",
        "evidence/flx-canonical500-raw",
        "stage-8c-finalization.json",
        "outcome",
        readme_heading="## Stage 8C",
    ),
    PublishedStage(
        "8A",
        "evidence/stage8a-modern-matcher-selection",
        "stage-8a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "8B",
        "evidence/stage8b-flx-runtime-qualification",
        "stage-8b-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "8D",
        "evidence/stage8d-calibration-infrastructure",
        "stage-8d-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "8E",
        "evidence/stage8e-research-only-policy",
        "stage-8e-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "9A",
        "evidence/stage9a-flare-artifact-qualification",
        "stage-9a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "10A",
        "evidence/stage10a-algorithm4-candidate-preflight",
        "stage-10a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "10B",
        "evidence/stage10b-id3-finger-sdk-preflight",
        "stage-10b-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "11A",
        "evidence/stage11a-verifinger-2025_2-preflight",
        "stage-11a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "11B",
        "evidence/stage11b-verifinger-canonical500-raw",
        "stage-11b-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "12A",
        "evidence/stage12a-idkit-preflight",
        "stage-12a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "13A",
        "evidence/stage13a-fingercell-preflight",
        "stage-13a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        # No finalization marker: the stage never reached one. Its outcome lives
        # in the preflight report, and a registry that insisted on a marker
        # would have to pretend the stage does not exist.
        "14A",
        "evidence/stage14a-griaule-preflight",
        "preflight-report.json",
        "outcome",
    ),
    PublishedStage(
        "15A",
        "evidence/stage15a-fingerprints-matching",
        "stage-15a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "16A",
        "evidence/stage16a-fingerflow",
        "stage-16a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "17A",
        "evidence/stage17a-fingerprintmatcher",
        "stage-17a-finalization.json",
        "outcome",
    ),
    PublishedStage(
        "18A",
        "evidence/stage18a-secugen-openafis-reference",
        "stage-18a-finalization.json",
        "outcome",
        readme_heading="## Stage 18A",
    ),
    PublishedStage(
        "19A",
        "evidence/stage19a-mindtct-openafis",
        "stage-19a-finalization.json",
        "outcome",
        readme_heading="## Stage 19A",
    ),
    PublishedStage(
        "19B",
        "evidence/stage19b-openafis-capacity-extended",
        "stage-19b-finalization.json",
        "outcome",
        readme_heading="## Stage 19B",
    ),
    PublishedStage(
        "20A",
        "evidence/stage20a-mcc-sdk-preflight",
        "stage-20a-finalization.json",
        "outcome",
        readme_heading="## Stage 20A",
    ),
    PublishedStage(
        "20B",
        "evidence/stage20b-mindtct-mcc-canonical500-raw",
        "stage-20b-finalization.json",
        "outcome",
        readme_heading="## Stage 20B",
    ),
)


def read_marker(stage: PublishedStage, repository_root: Path) -> Mapping[str, Any]:
    """The stage's published marker, as stored."""
    path = Path(repository_root) / stage.marker_path
    return json.loads(path.read_text(encoding="utf-8"))


def stages_missing_from(document: str) -> tuple[PublishedStage, ...]:
    """Registry stages that declare a README heading the document does not have.

    Deliberately a substring check against the heading rather than a parse: a
    section can be titled anything after the stage's name, and pinning the rest
    of the title would make renaming a section a test failure.
    """
    return tuple(
        stage
        for stage in PUBLISHED_STAGES
        if stage.readme_heading and stage.readme_heading not in document
    )
