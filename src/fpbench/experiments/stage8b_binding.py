"""Prove Stage 8C is running the route Stage 8B actually qualified.

The experiment configuration restates fifteen Stage 8B identities so a reviewer
sees them in a diff.  Restated values catch a typo and nothing else: if the
qualification were republished with different profiles under the same numbers,
or if this repository's source no longer produced the profiles Stage 8B
published, the configuration would still load.

So preparation reads the published Stage 8B evidence itself, rebuilds all four
profiles from this repository's own source, and compares.  It needs no torch, no
checkpoint and no bundle to do it — the same separation Stage 8B's own
evidence-only verifier rests on.

The one thing this module does not do is re-verify the artifacts.  A digest is
not evidence that the bytes on disk still match it, so the archive, the five
imported source files and all 875,770,140 checkpoint bytes are re-hashed by
``verify_bundle_artifacts()`` before every model load, which happens inside the
adapter's environment check and therefore before any comparison
(docs/adr/0072, docs/adr/0077).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.errors import ResearchPreflightError
from fpbench.core.serialization import to_plain
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments import stage8c_identity as frozen

__all__ = [
    "Stage8BPublication",
    "read_stage8b_publication",
    "require_stage8b_binding",
]


@dataclass(frozen=True, slots=True)
class Stage8BPublication:
    """What the committed Stage 8B evidence says, read once."""

    outcome: str
    finalization_fingerprint: str
    artifact_binding_fingerprint: str
    runtime_manifest_fingerprint: str
    preprocessing_profile_fingerprint: str
    representation_profile_fingerprint: str
    score_profile_fingerprint: str
    adapter_profile_fingerprint: str
    source_archive_sha256: str
    checkpoint_sha256: str
    verifier_source_commit: str
    opens_stage_8c: bool


def read_stage8b_publication(
    *, repository_root: Path = REPOSITORY_ROOT
) -> Stage8BPublication:
    """Read the published Stage 8B chain, without a runtime.

    Raises:
        ResearchPreflightError: the publication is missing, unreadable, or does
            not verify against itself.
    """
    from fpbench.core.flx_errors import FlxError
    from fpbench.flx.loading import load_published_evidence
    from fpbench.storage.flx_store import Stage8BEvidenceStore

    root = Path(repository_root)
    try:
        store = Stage8BEvidenceStore(root)
        published = load_published_evidence(
            store,
            policy_config=root / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml",
            require_finalization=True,
        )
    except (FlxError, OSError, KeyError, TypeError, ValueError) as exc:
        raise ResearchPreflightError(
            f"the committed Stage 8B qualification cannot be read: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    finalization = published.finalization
    if finalization is None:
        raise ResearchPreflightError(
            "the Stage 8B publication carries no finalization, so nothing binds "
            "its profiles to an outcome"
        )
    return Stage8BPublication(
        outcome=str(getattr(finalization.outcome, "value", finalization.outcome)),
        finalization_fingerprint=finalization.fingerprint,
        artifact_binding_fingerprint=published.binding.fingerprint,
        runtime_manifest_fingerprint=published.manifest.fingerprint,
        preprocessing_profile_fingerprint=published.preprocessing.fingerprint,
        representation_profile_fingerprint=published.representation.fingerprint,
        score_profile_fingerprint=published.score.fingerprint,
        adapter_profile_fingerprint=published.adapter.fingerprint,
        source_archive_sha256=published.binding.source_archive_sha256,
        checkpoint_sha256=published.binding.checkpoint_sha256,
        verifier_source_commit=finalization.verifier_source_commit,
        opens_stage_8c=bool(published.report.opens_stage_8c),
    )


def require_stage8b_binding(
    binding: Any,
    artifact: Any,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> Stage8BPublication:
    """Three independent agreements, and the stage stops unless all three hold.

    1. **The configuration matches the publication.** Every fingerprint the
       experiment restates is the one the committed Stage 8B evidence carries.
    2. **The publication matches this source.** All four profiles are rebuilt
       from ``fpbench.flx`` and must equal what was published, so a profile that
       drifted after the qualification cannot be executed under its old identity.
    3. **The outcome permits execution.** ``FLX_RAW_SCORE_EXECUTION_READY``, and
       Stage 8B's own report says it opens Stage 8C.

    Args:
        binding: The experiment's ``Stage8BBinding``.
        artifact: The experiment's ``FlxArtifactIdentity``.

    Raises:
        ResearchPreflightError: any of the three fails.
    """
    published = read_stage8b_publication(repository_root=repository_root)

    differences: list[str] = []
    for label, declared, actual in (
        ("stage8b.finalization_fingerprint", binding.finalization_fingerprint,
         published.finalization_fingerprint),
        ("stage8b.outcome", binding.outcome, published.outcome),
        ("stage8b.runtime_manifest_fingerprint", binding.runtime_manifest_fingerprint,
         published.runtime_manifest_fingerprint),
        ("stage8b.preprocessing_profile_fingerprint",
         binding.preprocessing_profile_fingerprint,
         published.preprocessing_profile_fingerprint),
        ("stage8b.representation_profile_fingerprint",
         binding.representation_profile_fingerprint,
         published.representation_profile_fingerprint),
        ("stage8b.score_profile_fingerprint", binding.score_profile_fingerprint,
         published.score_profile_fingerprint),
        ("stage8b.adapter_profile_fingerprint", binding.adapter_profile_fingerprint,
         published.adapter_profile_fingerprint),
        ("artifact.source_archive_sha256", artifact.source_archive_sha256,
         published.source_archive_sha256),
        ("artifact.checkpoint_sha256", artifact.checkpoint_sha256,
         published.checkpoint_sha256),
    ):
        if declared != actual:
            differences.append(
                f"{label}: the experiment names {str(declared)[:12]}... and the "
                f"publication carries {str(actual)[:12]}..."
            )
    if differences:
        raise ResearchPreflightError(
            "Stage 8C is not bound to the published Stage 8B qualification: "
            + "; ".join(differences)
        )

    _require_profiles_match_this_source(published)

    if published.outcome != frozen.STAGE8B_OUTCOME:
        raise ResearchPreflightError(
            f"Stage 8B concluded {published.outcome!r}; only "
            f"{frozen.STAGE8B_OUTCOME!r} permits a benchmark-scale run "
            "(docs/adr/0065)"
        )
    if not published.opens_stage_8c:
        raise ResearchPreflightError(
            "the Stage 8B qualification report does not open Stage 8C"
        )
    return published


def _require_profiles_match_this_source(published: Stage8BPublication) -> None:
    """The published profiles are the ones this repository's source produces."""
    from fpbench.flx.integration import build_adapter_profile
    from fpbench.flx.preprocessing import build_preprocessing_profile
    from fpbench.flx.representation import build_representation_profile
    from fpbench.flx.score import build_score_profile

    drifted: list[str] = []
    for label, rebuilt, declared in (
        (
            "preprocessing",
            build_preprocessing_profile().fingerprint,
            published.preprocessing_profile_fingerprint,
        ),
        (
            "representation",
            build_representation_profile().fingerprint,
            published.representation_profile_fingerprint,
        ),
        ("score", build_score_profile().fingerprint, published.score_profile_fingerprint),
        (
            "adapter",
            build_adapter_profile().fingerprint,
            published.adapter_profile_fingerprint,
        ),
    ):
        if rebuilt != declared:
            drifted.append(
                f"{label}: this source produces {rebuilt[:12]}... and Stage 8B "
                f"published {declared[:12]}..."
            )
    if drifted:
        raise ResearchPreflightError(
            "the flx profiles this source produces are not the ones Stage 8B "
            "qualified, so a run under them would carry an identity it is not "
            "entitled to: " + "; ".join(drifted)
        )


def stage8b_binding_claims(published: Stage8BPublication) -> Mapping[str, Any]:
    """The publication, flattened for a marker or an evidence document."""
    return dict(to_plain(published))
