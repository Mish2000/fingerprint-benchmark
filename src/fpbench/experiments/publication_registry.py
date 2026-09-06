"""Published-stage index extending the registry frozen by Stage 21A.

``stage_registry.py`` is part of Stage 21A's signed source closure. New
publication entries belong here so recording a completed stage preserves the
protocol fingerprint already bound into its raw result sets.
"""

from __future__ import annotations

from fpbench.experiments.stage_registry import (
    PUBLISHED_STAGES as FROZEN_STAGES,
    PublishedStage,
    read_marker,
)

__all__ = ["PUBLISHED_STAGES", "PublishedStage", "read_marker", "stages_missing_from"]

PUBLISHED_STAGES: tuple[PublishedStage, ...] = (
    *FROZEN_STAGES,
    PublishedStage(
        "21B",
        "evidence/stage21b-cross-subject-baseline-expansion",
        "stage-21b-finalization.json",
        "outcome",
        readme_heading="## Stage 21B",
    ),
)


def stages_missing_from(document: str) -> tuple[PublishedStage, ...]:
    """Return published stages whose required heading is absent."""
    return tuple(
        stage
        for stage in PUBLISHED_STAGES
        if stage.readme_heading and stage.readme_heading not in document
    )
