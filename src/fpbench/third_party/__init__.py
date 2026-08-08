"""The repository-wide third-party usage policy, and the vocabulary it runs on.

Stage 8E's premise is that three questions had been collapsing into one:

.. code-block:: text

    What does upstream licensing say?      ->  LicenseObservation
                                               (a description)

    May fpbench execute it locally, under
    its declared purpose?                  ->  ResearchUseAssessment
                                               (a decision)

    May fpbench redistribute it?           ->  RedistributionRecord
                                               (always: it does not)

Keeping them apart is what lets this repository hold, without contradiction:

.. code-block:: text

    license_observation_status:  CONFLICTING_NOTICES
    research_use_decision:       ALLOWED_UNDER_RESTRICTIVE_INTERSECTION

— which says the licence question was not resolved and the execution question
was, on the narrow ground that every plausible reading permits one person running
one program on one machine.

**The layering.** The persisted containers live in
:mod:`fpbench.core.third_party_models`, because the storage layer may import only
``core``. The rules that derive them live here and the containers are re-exported,
which is the split :mod:`fpbench.calibration` and :mod:`fpbench.decisions` use.

**What this package will not do.** It never edits an earlier stage's published
conclusion; Stage 8A's ``LICENSE_BLOCKED`` and Stage 8B's
``weights_license_status: unresolved`` were correct answers to the questions
those stages asked, and Stage 8E asks a different one (docs/adr/0068,
docs/adr/0084). It never turns an absent licence into permission. And it never
puts an upstream byte in Git, whatever the licence allows (docs/adr/0083).
"""

from __future__ import annotations

from fpbench.core.third_party_models import (
    ArtifactStorageClass,
    IntendedUsePermissionStatus,
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    LocalArtifactPlacement,
    NonBlockingRestriction,
    OwnerRiskAcceptance,
    ProjectPurpose,
    ProjectPurposeDeclaration,
    RedistributionDecision,
    RedistributionRecord,
    ResearchUseAssessment,
    ResearchUseBlocker,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    ThirdPartyPolicy,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    TransformationClassification,
    UpstreamIdentity,
    UpstreamModificationStrategy,
    UpstreamTransformation,
)
from fpbench.third_party.artifacts import (
    THIRD_PARTY_ROOT_ENV,
    ArtifactVerification,
    build_placement,
    default_third_party_root,
    resolve_placement_path,
    resolve_third_party_root,
    verify_placed_artifact,
)
from fpbench.third_party.manifest import (
    build_usage_manifest,
    build_usage_record,
    require_manifest_opens_execution,
    storage_class_for,
)
from fpbench.third_party.policy import (
    INTENDED_OPERATION,
    PlausibleReading,
    assess_research_use,
    decide,
    intersection_permits_intended_use,
    needs_intersection,
    policy_fingerprint,
    third_party_policy,
)
from fpbench.third_party.purpose import (
    PROJECT_PURPOSE_STATEMENT,
    PROJECT_PURPOSE_TERM,
    project_purpose,
    purpose_fingerprint,
)
from fpbench.third_party.repository_guard import (
    RepositoryArtifactAudit,
    RepositoryFinding,
    audit_repository_artifacts,
    require_no_third_party_bytes_in_git,
)
from fpbench.third_party.transformations import (
    MODIFICATION_LADDER,
    choose_modification_strategy,
    record_transformation,
    require_integration_only,
    transformation_over_bytes,
)
from fpbench.third_party.verify import (
    UsageVerificationReport,
    verify_usage_manifest,
    verify_usage_record,
)

__all__ = [
    # vocabulary
    "ProjectPurpose",
    "ThirdPartyComponentKind",
    "LicenseObservationStatus",
    "ResearchUseDecision",
    "RedistributionDecision",
    "ResearchUseBlocker",
    "NonBlockingRestriction",
    "IntendedUsePermissionStatus",
    "ArtifactStorageClass",
    "UpstreamModificationStrategy",
    "TransformationClassification",
    # containers
    "ProjectPurposeDeclaration",
    "UpstreamIdentity",
    "LicenseEvidence",
    "LicenseObservation",
    "OwnerRiskAcceptance",
    "ResearchUseAssessment",
    "RedistributionRecord",
    "ThirdPartyUsageRecord",
    "ThirdPartyUsageManifest",
    "ThirdPartyPolicy",
    "LocalArtifactPlacement",
    "UpstreamTransformation",
    # purpose and policy
    "PROJECT_PURPOSE_TERM",
    "PROJECT_PURPOSE_STATEMENT",
    "INTENDED_OPERATION",
    "project_purpose",
    "purpose_fingerprint",
    "third_party_policy",
    "policy_fingerprint",
    "PlausibleReading",
    "intersection_permits_intended_use",
    "needs_intersection",
    "decide",
    "assess_research_use",
    # manifests
    "build_usage_record",
    "build_usage_manifest",
    "require_manifest_opens_execution",
    "storage_class_for",
    # artifacts
    "THIRD_PARTY_ROOT_ENV",
    "ArtifactVerification",
    "default_third_party_root",
    "resolve_third_party_root",
    "resolve_placement_path",
    "build_placement",
    "verify_placed_artifact",
    # upstream modification
    "MODIFICATION_LADDER",
    "choose_modification_strategy",
    "record_transformation",
    "transformation_over_bytes",
    "require_integration_only",
    # the public-repository guard
    "RepositoryArtifactAudit",
    "RepositoryFinding",
    "audit_repository_artifacts",
    "require_no_third_party_bytes_in_git",
    # verification
    "UsageVerificationReport",
    "verify_usage_record",
    "verify_usage_manifest",
]
