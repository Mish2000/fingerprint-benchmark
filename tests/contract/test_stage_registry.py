"""The README, the evidence index and the markers must describe one set of runs.

They are three hand-maintained descriptions of the same thing, and they drifted:
the README's Stage 20A section ended "...which opens Stage 20B" while Stage 20B's
marker had already declared ``MINDTCT_MCC_SDK_V2_CANONICAL_RAW_COMPLETE`` and
``publication_eligible: true``. Nobody was misled on purpose; there was simply
nothing that would notice.

The registry in :mod:`fpbench.experiments.stage_registry` is the authority these
check against.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.experiments.stage_registry import (
    PUBLISHED_STAGES,
    PublishedStage,
    read_marker,
    stages_missing_from,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"


@pytest.mark.parametrize("stage", PUBLISHED_STAGES, ids=lambda s: s.stage)
def test_a_registered_stage_has_the_evidence_it_claims(stage: PublishedStage) -> None:
    directory = REPOSITORY_ROOT / stage.directory
    assert directory.is_dir(), f"Stage {stage.stage} has no {stage.directory}"
    assert (directory / stage.marker).is_file(), (
        f"Stage {stage.stage} has no {stage.marker}"
    )


@pytest.mark.parametrize("stage", PUBLISHED_STAGES, ids=lambda s: s.stage)
def test_a_registered_stage_marker_states_an_outcome(stage: PublishedStage) -> None:
    marker = read_marker(stage, REPOSITORY_ROOT)
    outcome = marker.get(stage.outcome_key)
    assert isinstance(outcome, str) and outcome.strip(), (
        f"Stage {stage.stage}'s marker carries no {stage.outcome_key!r}"
    )


def test_every_evidence_directory_with_a_marker_is_registered() -> None:
    """A stage published without a registry row is the drift running the other way."""
    registered = {stage.directory for stage in PUBLISHED_STAGES}
    unregistered = sorted(
        directory.relative_to(REPOSITORY_ROOT).as_posix()
        for directory in EVIDENCE.iterdir()
        if directory.is_dir()
        and any(directory.glob("stage-*-finalization.json"))
        and directory.relative_to(REPOSITORY_ROOT).as_posix() not in registered
    )
    assert not unregistered, (
        f"evidence directories carry a stage marker but no registry row: "
        f"{unregistered}. Add them to fpbench.experiments.stage_registry"
    )


def test_the_readme_documents_every_stage_the_registry_says_it_should() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    missing = stages_missing_from(readme)
    assert not missing, (
        "README.md has no section for "
        + ", ".join(f"Stage {stage.stage}" for stage in missing)
        + ". The evidence for it is published and the README does not say so"
    )


@pytest.mark.parametrize("stage", PUBLISHED_STAGES, ids=lambda s: s.stage)
def test_the_readme_does_not_call_a_finished_stage_unopened(
    stage: PublishedStage,
) -> None:
    """A stage whose marker says COMPLETE must not be described as still ahead.

    The specific phrasing that went stale was "opens Stage 20B". Anything of
    that shape, naming a stage whose own marker reports completion, is the same
    mistake.
    """
    marker = read_marker(stage, REPOSITORY_ROOT)
    outcome = str(marker.get(stage.outcome_key, ""))
    if "COMPLETE" not in outcome:
        pytest.skip(f"Stage {stage.stage} did not finish a run")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (f"opens Stage {stage.stage}", f"opens stage {stage.stage}"):
        if phrase not in readme:
            continue
        assert stage.readme_heading and stage.readme_heading in readme, (
            f"README.md says {phrase!r} and Stage {stage.stage}'s marker reports "
            f"{outcome}. Either the stage has a section of its own or the "
            "sentence is out of date"
        )


def test_a_publication_eligible_stage_is_in_the_readme() -> None:
    """``publication_eligible: true`` is a claim the README has to honour."""
    unpublished = []
    for stage in PUBLISHED_STAGES:
        marker = read_marker(stage, REPOSITORY_ROOT)
        if marker.get("publication_eligible") is not True:
            continue
        if stage.readme_heading is None:
            unpublished.append(stage.stage)
    assert not unpublished, (
        "these stages declare publication_eligible and name no README section: "
        f"{unpublished}"
    )
