"""Everything Stage 9A froze before it looked at a single byte of FLARE.

These constants are the stage's contract with itself: the candidate algorithm
identity, the four branches that make it that algorithm, the two upstream
repositories at exact commits, the artifacts the route needs, and the route the
paper states. They are asserted by the contract suite, republished in the
finalization, and a later change to any of them is a different qualification
rather than a quiet correction to this one (docs/adr/0086).

Nothing here is derived at import time, nothing reads a workspace, nothing
downloads anything, and nothing is a fingerprint image, a score or an upstream
byte. What is here about upstream is a *description*: a URL, a commit SHA, a
digest, a size, a Drive file id, and the name of a function in a file. Under
Stage 8E's policy those are exactly the things a public repository may hold
about a third-party component (docs/adr/0083).

This module exists for the reason :mod:`fpbench.experiments.stage8e_identity`
does: the artifact layer, the route resolution, the qualification and the
finalization marker all need the frozen values, and a shared constant module is
the alternative to an import cycle between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from fpbench.core.flare_errors import FlareIdentityError
from fpbench.core.identifiers import validate_id
from fpbench.core.third_party_models import ThirdPartyComponentKind

__all__ = [
    "STAGE_9A_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "STAGE_9A_READY_OUTCOME",
    "STAGE_9A_BLOCKED_OUTCOME",
    "STAGE_9A_OUTCOMES",
    "EVIDENCE_DIRECTORY",
    "STAGE_9A_FINALIZATION_NAME",
    "UPSTREAM_SOURCE_MANIFEST_NAME",
    "ARTIFACT_MANIFEST_NAME",
    "THIRD_PARTY_USAGE_MANIFEST_NAME",
    "TRAINING_PROVENANCE_NAME",
    "CHECKPOINT_COMPATIBILITY_NAME",
    "PAPER_ROUTE_CONTRACT_NAME",
    "PUBLIC_CODE_ROUTE_AUDIT_NAME",
    "TRANSFORM_GRAPH_RESOLUTION_NAME",
    "QUALIFICATION_REPORT_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ALGORITHM_CANDIDATE_ID",
    "ALGORITHM_DISPLAY_NAME",
    "BINARY_REPRESENTATION_ENABLED",
    "BranchIdentity",
    "BRANCHES",
    "BRANCH_COUNT",
    "REQUIRED_POSE_ESTIMATORS",
    "REQUIRED_ENHANCERS",
    "REQUIRED_SOURCE_REPOSITORIES",
    "DESCRIPTOR_FEATURE_DIMENSION",
    "DESCRIPTOR_SHAPE",
    "DESCRIPTOR_SCALAR_COUNT",
    "MASK_SHAPE",
    "MASK_SCALAR_COUNT",
    "ALIGNED_GEOMETRY",
    "FDRN_GEOMETRY",
    "INPUT_PPI",
    "INPUT_PROFILE",
    "INPUT_PIXEL_FORMAT",
    "SCORE_DIRECTION",
    "OperationAuthority",
    "RouteResolution",
    "BlockerCode",
    "UpstreamRepository",
    "FLARE_REPOSITORY",
    "FLARE_ENH_REPOSITORY",
    "UPSTREAM_REPOSITORIES",
    "RequiredArtifact",
    "REQUIRED_ARTIFACTS",
    "TRANSITIVE_ARTIFACT_SOURCES",
    "ARTIFACT_STORE_PREFIX",
    "PaperRouteStage",
    "PAPER_ROUTE",
    "PAPER_LOCATOR",
    "PAPER_ARXIV_LOCATOR",
    "FORBIDDEN_PUBLISHED_KEYS",
    "STAGE_9A_SOURCE_FILES",
    "STAGE_9A_ADRS",
    "STAGE_9A_DOCUMENTS",
    "FLARE_ARTIFACT_MARKER",
    "all_frozen_identifiers",
]

STAGE_9A_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_9a_finalization"

#: The two outcomes, and there are exactly two. ``BLOCKED`` is a complete and
#: correct result: this stage decides whether a faithful full route can be
#: frozen, and "no" is one of the answers it is allowed to reach
#: (docs/adr/0085).
STAGE_9A_READY_OUTCOME = "FLARE_FULL_ROUTE_ARTIFACTS_READY"
STAGE_9A_BLOCKED_OUTCOME = "FLARE_FULL_ROUTE_BLOCKED"
STAGE_9A_OUTCOMES = (STAGE_9A_READY_OUTCOME, STAGE_9A_BLOCKED_OUTCOME)

EVIDENCE_DIRECTORY = Path("evidence") / "stage9a-flare-artifact-qualification"

#: The last-written authority, and the last file committed.
STAGE_9A_FINALIZATION_NAME = "stage-9a-finalization.json"
UPSTREAM_SOURCE_MANIFEST_NAME = "upstream-source-manifest.json"
ARTIFACT_MANIFEST_NAME = "artifact-manifest.json"
THIRD_PARTY_USAGE_MANIFEST_NAME = "third-party-usage-manifest.json"
TRAINING_PROVENANCE_NAME = "training-provenance.json"
CHECKPOINT_COMPATIBILITY_NAME = "checkpoint-compatibility.json"
PAPER_ROUTE_CONTRACT_NAME = "paper-route-contract.json"
PUBLIC_CODE_ROUTE_AUDIT_NAME = "public-code-route-audit.json"
TRANSFORM_GRAPH_RESOLUTION_NAME = "transform-graph-resolution.json"
QUALIFICATION_REPORT_NAME = "qualification-report.json"

#: Exactly what the evidence directory holds. An extra file is a finding.
#:
#: There is no ``licensing-provenance.json``. Stage 8E owns that question now,
#: and a second licence document beside its manifest would be a second authority
#: (spec section 50).
REQUIRED_EVIDENCE_FILES = (
    "README.md",
    UPSTREAM_SOURCE_MANIFEST_NAME,
    ARTIFACT_MANIFEST_NAME,
    THIRD_PARTY_USAGE_MANIFEST_NAME,
    TRAINING_PROVENANCE_NAME,
    CHECKPOINT_COMPATIBILITY_NAME,
    PAPER_ROUTE_CONTRACT_NAME,
    PUBLIC_CODE_ROUTE_AUDIT_NAME,
    TRANSFORM_GRAPH_RESOLUTION_NAME,
    QUALIFICATION_REPORT_NAME,
    STAGE_9A_FINALIZATION_NAME,
)

# ----------------------------------------------------------- the closed stage
#
# Restated from evidence/stage8e-research-only-policy/. Stage 9A reads that
# marker to confirm the policy it reuses is the policy it thinks it reuses, and
# refuses on disagreement. Nothing under that directory is edited, and no
# module under src/fpbench/third_party/ or src/fpbench/core/third_party_*.py is
# edited either (spec section 3).
STAGE8E_FINALIZATION_FINGERPRINT = (
    "c08648dece292603eb9d4b6fff0b3412523af0730da59141b6e7a32ee02540e8"
)
STAGE8E_OUTCOME = "RESEARCH_ONLY_THIRD_PARTY_POLICY_READY"
STAGE8E_PURPOSE_FINGERPRINT = (
    "a62ab45681bdbd9cc4e741e1e5522583746b5d29f1fe911fa687fc7fee405443"
)
STAGE8E_POLICY_FINGERPRINT = (
    "de9cdbaa23522c4a15337d86b0ec2df8af8b79383a1f8014294e8c7855bf972a"
)


# ------------------------------------------------------- the candidate identity

#: The candidate, and only a candidate until the stage closes READY. Every
#: segment is a claim with an authority; docs/adr/0086 tabulates them.
ALGORITHM_CANDIDATE_ID = "flare_fdd_d6_dualpose_dualenh_maxcosine"

ALGORITHM_DISPLAY_NAME = (
    "FLARE FDD D=6 / Dual-Pose × Dual-Enhancement / Max Overlap-Masked Cosine"
)

#: The ``-b`` route is a separate optional mode in the official README with its
#: own thresholds and its own score expression. It is not the paper's Eq. 7 and
#: it is not this algorithm (docs/adr/0086).
BINARY_REPRESENTATION_ENABLED = False


@dataclass(frozen=True, slots=True)
class BranchIdentity:
    """One of the four arms of one matcher.

    Not one of four algorithms. The four are fused by a maximum before any score
    leaves the method, so a run that reported them separately would be reporting
    four numbers none of which is FLARE's (docs/adr/0085).
    """

    branch_id: str
    pose_estimator: str
    enhancer: str

    def __post_init__(self) -> None:
        validate_id(self.branch_id)


BRANCHES: tuple[BranchIdentity, ...] = (
    BranchIdentity("voting_unetenh", "VotingPose", "UNetEnh"),
    BranchIdentity("voting_priorenh", "VotingPose", "PriorEnh"),
    BranchIdentity("regression_unetenh", "RegressionPose", "UNetEnh"),
    BranchIdentity("regression_priorenh", "RegressionPose", "PriorEnh"),
)

#: Four. Not two, not three. The numeric order of the branches is not part of
#: the algorithm — ``max`` does not depend on order — but their presence is.
BRANCH_COUNT = 4
REQUIRED_POSE_ESTIMATORS = 2
REQUIRED_ENHANCERS = 2
REQUIRED_SOURCE_REPOSITORIES = 2

#: ``D``. The paper sets it in one sentence of §IV and the official inference
#: configuration sets it as ``ndim_feat``; Stage 9A checks that the two agree.
DESCRIPTOR_FEATURE_DIMENSION = 6

#: ``f ∈ R^{2D×16×16}``. One logical representation per branch, so a fingerprint
#: carries four of these and four masks — never a single vector of 3072.
DESCRIPTOR_SHAPE = (2 * DESCRIPTOR_FEATURE_DIMENSION, 16, 16)
DESCRIPTOR_SCALAR_COUNT = DESCRIPTOR_SHAPE[0] * DESCRIPTOR_SHAPE[1] * DESCRIPTOR_SHAPE[2]

#: ``S ∈ R^{1×16×16}``, and it is continuous. The official continuous matching
#: path uses the mask values inside the numerator and both denominator terms;
#: thresholding belongs to the binary path, which this identity excludes
#: (spec section 30).
MASK_SHAPE = (1, 16, 16)
MASK_SCALAR_COUNT = MASK_SHAPE[0] * MASK_SHAPE[1] * MASK_SHAPE[2]

#: The two intermediate geometries the paper names, in pixels.
ALIGNED_GEOMETRY = (512, 512)
FDRN_GEOMETRY = (256, 256)

# ------------------------------------------------------------- the input contract

#: What a future route would receive, and the only thing it would receive. Not
#: SD300 raw A/B/C, and no further resampling to 500 ppi inside fpbench: the
#: canonical profile already produced 500 ppi gray8 (docs/adr/0031).
INPUT_PPI = 500
INPUT_PROFILE = "canonical_500"
INPUT_PIXEL_FORMAT = "gray8"

#: Higher is more similar. A cosine similarity over overlapping foreground.
SCORE_DIRECTION = "HIGHER_IS_MORE_SIMILAR"


# ---------------------------------------------------------------- vocabularies


class OperationAuthority(str, Enum):
    """Where one route operation's behaviour comes from.

    The first four are admissible. The last three are admissible only where the
    operation provably cannot change a score — and an image-pipeline operation
    almost never cannot (docs/adr/0087).
    """

    PAPER_EXPLICIT = "PAPER_EXPLICIT"
    UPSTREAM_CODE_EXPLICIT = "UPSTREAM_CODE_EXPLICIT"
    UPSTREAM_DEFAULT_EXPLICIT = "UPSTREAM_DEFAULT_EXPLICIT"
    INTEGRATION_NEUTRAL = "INTEGRATION_NEUTRAL"
    ASSUMED = "ASSUMED"
    GUESSED = "GUESSED"
    CHOSEN_BY_FPBENCH = "CHOSEN_BY_FPBENCH"

    @property
    def is_authoritative(self) -> bool:
        return self in (
            OperationAuthority.PAPER_EXPLICIT,
            OperationAuthority.UPSTREAM_CODE_EXPLICIT,
            OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
            OperationAuthority.INTEGRATION_NEUTRAL,
        )


class RouteResolution(str, Enum):
    """How one operation's paper statement and code location relate.

    ``AMBIGUOUS`` and ``CONTRADICTORY`` are the two that gate: on a
    score-affecting operation either of them closes the stage ``BLOCKED``
    (spec section 44).
    """

    EXACT_MATCH = "EXACT_MATCH"
    IMPLEMENTATION_SUPPLIES_DETAIL = "IMPLEMENTATION_SUPPLIES_DETAIL"
    INTEGRATION_NEUTRAL_GLUE = "INTEGRATION_NEUTRAL_GLUE"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTORY = "CONTRADICTORY"

    @property
    def is_resolved(self) -> bool:
        return self in (
            RouteResolution.EXACT_MATCH,
            RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
            RouteResolution.INTEGRATION_NEUTRAL_GLUE,
        )


class BlockerCode(str, Enum):
    """Why score fidelity could not be established. A closed list.

    Each member names something a reader could act on. "It did not work" is not
    among them.
    """

    REQUIRED_ARTIFACT_MISSING = "REQUIRED_ARTIFACT_MISSING"
    ARTIFACT_IDENTITY_UNRESOLVED = "ARTIFACT_IDENTITY_UNRESOLVED"
    CHECKPOINT_MODEL_MISMATCH = "CHECKPOINT_MODEL_MISMATCH"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"
    TRANSFORM_ORDER_AMBIGUOUS = "TRANSFORM_ORDER_AMBIGUOUS"
    SCORE_AFFECTING_PARAMETER_UNRESOLVED = "SCORE_AFFECTING_PARAMETER_UNRESOLVED"
    PAPER_CODE_CONTRADICTION = "PAPER_CODE_CONTRADICTION"
    FULL_FOUR_BRANCH_ROUTE_UNRESOLVED = "FULL_FOUR_BRANCH_ROUTE_UNRESOLVED"
    SD300_TRAINING_OR_TUNING_OVERLAP_FOUND = "SD300_TRAINING_OR_TUNING_OVERLAP_FOUND"


# ------------------------------------------------------ the source repositories


@dataclass(frozen=True, slots=True)
class UpstreamRepository:
    """One official repository, pinned by a commit and by archive bytes.

    ``default_branch_observed`` is recorded and then never used as an identity.
    ``master`` moved under this project once already: the checkpoint-loading
    question that dominated the previous reading of FLARE was answered by a
    commit that landed after it was written. A stage that pinned a branch would
    have to be re-read every time upstream pushed (spec section 10).
    """

    repository_id: str
    upstream_name: str
    html_locator: str
    default_branch_observed: str
    commit: str
    archive_locator: str
    archive_filename: str
    archive_sha256: str
    archive_size_bytes: int
    license_document_sha256: str
    readme_document_sha256: str
    acquisition_timestamp_utc: str
    role: str

    def __post_init__(self) -> None:
        validate_id(self.repository_id)
        if len(self.commit) != 40 or set(self.commit) - set("0123456789abcdef"):
            raise FlareIdentityError(
                f"{self.repository_id}: a pinned commit is a full 40-character "
                "SHA. 'master', 'main', 'latest' and 'HEAD' are not identities "
                "(spec section 9)"
            )


#: Observed 2026-08-08. The commit is the identity; the branch name is a note.
FLARE_REPOSITORY = UpstreamRepository(
    repository_id="flare_main",
    upstream_name="Yu-Yy/FLARE",
    html_locator="https://github.com/Yu-Yy/FLARE",
    default_branch_observed="master",
    commit="7d13ca727d55cf43642f9fe1e67df785091fd7c2",
    archive_locator=(
        "https://codeload.github.com/Yu-Yy/FLARE/tar.gz/"
        "7d13ca727d55cf43642f9fe1e67df785091fd7c2"
    ),
    archive_filename="FLARE-7d13ca72.tar.gz",
    archive_sha256=(
        "4b11d6f32a5a0984e505517768f11fc56dcd2b5711789b20cf0e08be5595145e"
    ),
    archive_size_bytes=725804,
    license_document_sha256=(
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
    ),
    readme_document_sha256=(
        "9fe8a2f01270d7abe09375d2a413c60cc5b448047233ec9b711e5571910878f4"
    ),
    acquisition_timestamp_utc="2026-08-08T00:00:00Z",
    role="FLARE-Align and FLARE-Desc: pose estimation and FDD extraction",
)

FLARE_ENH_REPOSITORY = UpstreamRepository(
    repository_id="flare_enh",
    upstream_name="Yu-Yy/FLARE_ENH",
    html_locator="https://github.com/Yu-Yy/FLARE_ENH",
    default_branch_observed="master",
    commit="ee735b03669aa0d9e086b50c7d9b1771913a2ba4",
    archive_locator=(
        "https://codeload.github.com/Yu-Yy/FLARE_ENH/tar.gz/"
        "ee735b03669aa0d9e086b50c7d9b1771913a2ba4"
    ),
    archive_filename="FLARE_ENH-ee735b03.tar.gz",
    archive_sha256=(
        "ff85e815ddaf92bb03373d7b3475db20dc85403758252cb8148706e22cfbb981"
    ),
    archive_size_bytes=33181,
    license_document_sha256=(
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
    ),
    readme_document_sha256=(
        "4013b73a2459a0c0b8c136701e03e558519331f35be08c63b56887a152aa2e90"
    ),
    acquisition_timestamp_utc="2026-08-08T00:00:00Z",
    role="FLARE-Enh: UNetEnh and PriorEnh",
)

UPSTREAM_REPOSITORIES: tuple[UpstreamRepository, ...] = (
    FLARE_REPOSITORY,
    FLARE_ENH_REPOSITORY,
)


# --------------------------------------------------------- the artifact inventory


@dataclass(frozen=True, slots=True)
class RequiredArtifact:
    """One artifact the full route needs, described without being held.

    ``expected_sha256`` and ``expected_size_bytes`` are ``None`` until an
    enrollment on this machine has established them. That is the honest state
    for a checkpoint published on Google Drive: this repository has the locator,
    which is not the identity (spec section 15).

    ``discovered_from`` names the artifact that referred to this one, and is set
    for exactly the transitive dependencies. ``Prior.ckpt`` is not in either
    README's download list — it is named by ``vq.yaml`` inside the FLARE_ENH
    source tree, and a closed inventory that had not traversed the configuration
    would have missed it (spec section 11).
    """

    artifact_id: str
    component_role: str
    component_kind: ThirdPartyComponentKind
    subject: str
    upstream_name: str
    locator: str
    locator_kind: str
    upstream_relative_path: str
    store_relative_location: str
    repository_id: str
    required_by: tuple[str, ...]
    expected_sha256: str | None = None
    expected_size_bytes: int | None = None
    discovered_from: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.artifact_id)
        if self.locator_kind not in ("https_archive", "google_drive_file", "in_source_tree"):
            raise FlareIdentityError(
                f"{self.artifact_id}: {self.locator_kind!r} is not one of the "
                "three ways an artifact is located"
            )
        if (self.expected_sha256 is None) != (self.expected_size_bytes is None):
            raise FlareIdentityError(
                f"{self.artifact_id}: a digest and a size are established "
                "together or not at all. A digest with no size cannot say a "
                "truncated download is wrong before it is hashed"
            )

    @property
    def identity_established(self) -> bool:
        return self.expected_sha256 is not None


#: Where the store keeps FLARE's artifacts, relative to
#: ``FPBENCH_THIRD_PARTY_ROOT``. The exact structure may change; manifests hold
#: no absolute path and none of these is a place on any machine
#: (docs/adr/0083).
ARTIFACT_STORE_PREFIX = "flare"

REQUIRED_ARTIFACTS: tuple[RequiredArtifact, ...] = (
    # ------------------------------------------------------------- source trees
    RequiredArtifact(
        artifact_id="flare_source_archive",
        component_role="FLARE source snapshot",
        component_kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="the FLARE-Align and FLARE-Desc source at the pinned commit",
        upstream_name="Yu-Yy/FLARE",
        locator=FLARE_REPOSITORY.archive_locator,
        locator_kind="https_archive",
        upstream_relative_path=".",
        store_relative_location=f"{ARTIFACT_STORE_PREFIX}/source/{FLARE_REPOSITORY.archive_filename}",
        repository_id=FLARE_REPOSITORY.repository_id,
        required_by=("pose", "descriptor", "matching"),
        expected_sha256=FLARE_REPOSITORY.archive_sha256,
        expected_size_bytes=FLARE_REPOSITORY.archive_size_bytes,
        notes=(
            "Two independent acquisitions from the same locator produced "
            "byte-identical archives, which is what makes a generated tarball "
            "usable as an identity here (spec section 14).",
        ),
    ),
    RequiredArtifact(
        artifact_id="flare_enh_source_archive",
        component_role="FLARE_ENH source snapshot",
        component_kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="the UNetEnh and PriorEnh source at the pinned commit",
        upstream_name="Yu-Yy/FLARE_ENH",
        locator=FLARE_ENH_REPOSITORY.archive_locator,
        locator_kind="https_archive",
        upstream_relative_path=".",
        store_relative_location=(
            f"{ARTIFACT_STORE_PREFIX}/source/{FLARE_ENH_REPOSITORY.archive_filename}"
        ),
        repository_id=FLARE_ENH_REPOSITORY.repository_id,
        required_by=("enhancement",),
        expected_sha256=FLARE_ENH_REPOSITORY.archive_sha256,
        expected_size_bytes=FLARE_ENH_REPOSITORY.archive_size_bytes,
    ),
    # ------------------------------------------------------------- descriptor
    RequiredArtifact(
        artifact_id="flare_fdd_checkpoint",
        component_role="FDD checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject="desc_model.pth.tar, the Fixed-length Dense Representation Network",
        upstream_name="FLARE FDD model",
        locator="google-drive-file:1zvAI57L0TDC7q6kQgNh5_DwSbicjJ4hs",
        locator_kind="google_drive_file",
        upstream_relative_path="model_weights/desc_model.pth.tar",
        store_relative_location=f"{ARTIFACT_STORE_PREFIX}/fdd/desc_model.pth.tar",
        repository_id=FLARE_REPOSITORY.repository_id,
        required_by=("descriptor",),
        notes=(
            "extract_FDD.py builds FDD, wraps it in DataParallel and calls "
            "load_model on this path. The load is present, active and official.",
        ),
    ),
    # ------------------------------------------------------------------- pose
    RequiredArtifact(
        artifact_id="flare_voting_pose_checkpoint",
        component_role="VotingPose checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject="VotingPose.pth, the GRIDNET4 voting pose estimator",
        upstream_name="FLARE VotingPose model",
        locator="google-drive-file:1Zg4duNJ8mg-fkTACTzpPPK7DgNb9NRvA",
        locator_kind="google_drive_file",
        upstream_relative_path="model_weights/VotingPose.pth",
        store_relative_location=f"{ARTIFACT_STORE_PREFIX}/pose/VotingPose.pth",
        repository_id=FLARE_REPOSITORY.repository_id,
        required_by=("pose",),
    ),
    RequiredArtifact(
        artifact_id="flare_regression_pose_checkpoint",
        component_role="RegressionPose checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject="RegressionPose.pth, the FingerPose_2D_Single regression estimator",
        upstream_name="FLARE RegressionPose model",
        locator="google-drive-file:1AXpN8GBSqhlIXDilqPLfZf9n4Dc0pEpj",
        locator_kind="google_drive_file",
        upstream_relative_path="model_weights/RegressionPose.pth",
        store_relative_location=f"{ARTIFACT_STORE_PREFIX}/pose/RegressionPose.pth",
        repository_id=FLARE_REPOSITORY.repository_id,
        required_by=("pose",),
    ),
    # ------------------------------------------------------------ enhancement
    RequiredArtifact(
        artifact_id="flare_unetenh_checkpoint",
        component_role="UNetEnh checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject="unetenh.pth, the SqueezeUNet enhancement network",
        upstream_name="FLARE UNetEnh model",
        locator="google-drive-file:1U0uP8XoxWc90IPlEGnt2KIe0ATAA2VKl",
        locator_kind="google_drive_file",
        upstream_relative_path="pretrained_model/unetenh/unetenh.pth",
        store_relative_location=f"{ARTIFACT_STORE_PREFIX}/enhancement/unetenh/unetenh.pth",
        repository_id=FLARE_ENH_REPOSITORY.repository_id,
        required_by=("enhancement",),
    ),
    RequiredArtifact(
        artifact_id="flare_priorenh_checkpoint",
        component_role="PriorEnh checkpoint",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject="priorenh.pth, the VQFPEnhancer_PCNN enhancement network",
        upstream_name="FLARE PriorEnh model",
        locator="google-drive-file:1h3JD6ZhS_TUaCmBhINqKZ0Pb1ad-FRao",
        locator_kind="google_drive_file",
        upstream_relative_path="pretrained_model/priorenh/priorenh.pth",
        store_relative_location=(
            f"{ARTIFACT_STORE_PREFIX}/enhancement/priorenh/priorenh.pth"
        ),
        repository_id=FLARE_ENH_REPOSITORY.repository_id,
        required_by=("enhancement",),
    ),
    RequiredArtifact(
        artifact_id="flare_prior_codebook_checkpoint",
        component_role="Prior / VQ artifact required by PriorEnh",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject="Prior.ckpt, the frozen VQ-VAE codebook and high-resolution decoder",
        upstream_name="FLARE Prior model",
        locator="google-drive-file:14c0A4qRo_lrqa83e-_UpBvu79qEGkK5q",
        locator_kind="google_drive_file",
        upstream_relative_path="pretrained_model/priorenh/Prior.ckpt",
        store_relative_location=(
            f"{ARTIFACT_STORE_PREFIX}/enhancement/priorenh/Prior.ckpt"
        ),
        repository_id=FLARE_ENH_REPOSITORY.repository_id,
        required_by=("enhancement",),
        discovered_from="flare_priorenh_vq_config",
        notes=(
            "Named by vq.yaml's ckpt_path, not by a README download list. "
            "VQFPEnhancer_PCNN is constructed with it, so PriorEnh does not "
            "exist without it (spec section 11).",
        ),
    ),
    RequiredArtifact(
        artifact_id="flare_priorenh_vq_config",
        component_role="vq.yaml, the PriorEnh construction configuration",
        component_kind=ThirdPartyComponentKind.OTHER_ARTIFACT,
        subject=(
            "pretrained_model/priorenh/vq.yaml: codebook size, embedding "
            "dimension, the encoder and decoder configurations, and the path of "
            "the Prior artifact"
        ),
        upstream_name="Yu-Yy/FLARE_ENH",
        locator=(
            "https://raw.githubusercontent.com/Yu-Yy/FLARE_ENH/"
            "ee735b03669aa0d9e086b50c7d9b1771913a2ba4/"
            "pretrained_model/priorenh/vq.yaml"
        ),
        locator_kind="in_source_tree",
        upstream_relative_path="pretrained_model/priorenh/vq.yaml",
        store_relative_location=(
            f"{ARTIFACT_STORE_PREFIX}/enhancement/priorenh/vq.yaml"
        ),
        repository_id=FLARE_ENH_REPOSITORY.repository_id,
        required_by=("enhancement",),
        expected_sha256=(
            "e14e32f77116aef6e692915712f7fd9f70322aaa86209f158868747e61db8fac"
        ),
        expected_size_bytes=551,
        notes=(
            "Ships inside the FLARE_ENH source tree, so its identity follows "
            "from the pinned commit. It is enumerated separately because it is "
            "what the transitive traversal reads.",
        ),
    ),
    RequiredArtifact(
        artifact_id="flare_desc_configs",
        component_role="desc_configs.yaml, the FDD inference configuration",
        component_kind=ThirdPartyComponentKind.OTHER_ARTIFACT,
        subject=(
            "model_weights/desc_configs.yaml: PPI 500, middle_shape 512×512, "
            "tar_shape 256×256, ndim_feat 6, input_norm false"
        ),
        upstream_name="Yu-Yy/FLARE",
        locator=(
            "https://raw.githubusercontent.com/Yu-Yy/FLARE/"
            "7d13ca727d55cf43642f9fe1e67df785091fd7c2/"
            "model_weights/desc_configs.yaml"
        ),
        locator_kind="in_source_tree",
        upstream_relative_path="model_weights/desc_configs.yaml",
        store_relative_location=f"{ARTIFACT_STORE_PREFIX}/fdd/desc_configs.yaml",
        repository_id=FLARE_REPOSITORY.repository_id,
        required_by=("descriptor", "matching"),
        expected_sha256=(
            "616df359c8820efeb57ac7bacc7ba349c4403766bcbea3729ebe667c1ba6ecb9"
        ),
        expected_size_bytes=201,
    ),
)

#: Which artifacts were traversed to find further ones, and what they named.
#: There is no closed list of artifacts until a traversal has been done, so this
#: records that one was (spec section 11).
TRANSITIVE_ARTIFACT_SOURCES: tuple[tuple[str, str, str], ...] = (
    (
        "flare_priorenh_vq_config",
        "ckpt_path",
        "flare_prior_codebook_checkpoint",
    ),
)


# ------------------------------------------------------------ the paper route


@dataclass(frozen=True, slots=True)
class PaperRouteStage:
    """One stage of the route as the *paper* states it, with where it says so."""

    order: int
    stage_id: str
    statement: str
    paper_locator: str

    def __post_init__(self) -> None:
        validate_id(self.stage_id)


PAPER_LOCATOR = (
    "Pan, Guan, Duan, Feng and Zhou, 'Fixed-Length Dense Fingerprint "
    "Representation with Alignment and Robust Enhancement', IEEE TIFS vol. 21 "
    "(2026) pp. 1751-1765"
)
PAPER_ARXIV_LOCATOR = "arXiv:2505.03597v2"

#: The route, in the order §III-E gives it. Every entry is a quotation of a
#: statement the paper actually makes; nothing here is inferred.
PAPER_ROUTE: tuple[PaperRouteStage, ...] = (
    PaperRouteStage(
        order=0,
        stage_id="input",
        statement="a 500 ppi query image I_q and a gallery image I_g",
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E",
    ),
    PaperRouteStage(
        order=1,
        stage_id="pose_estimation",
        statement=(
            "FLARE first estimates the 2D pose using two complementary "
            "estimators"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III, pipeline overview",
    ),
    PaperRouteStage(
        order=2,
        stage_id="alignment_crop_512",
        statement=(
            "we first apply pose estimation and alignment, followed by cropping "
            "to 512×512 pixels"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E",
    ),
    PaperRouteStage(
        order=3,
        stage_id="enhancement",
        statement=(
            "the aligned images are then enhanced using two pose estimation "
            "methods and two enhancement strategies, producing four augmented "
            "versions of each image"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E",
    ),
    PaperRouteStage(
        order=4,
        stage_id="downsample_256",
        statement=(
            "each enhanced image is downsampled to 256×256 pixels before being "
            "input to the Fixed-length Dense Representation Network"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E",
    ),
    PaperRouteStage(
        order=5,
        stage_id="fdrn",
        statement=(
            "which produces dense descriptors f ∈ R^{2D×16×16} and foreground "
            "masks S ∈ R^{1×16×16}"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E",
    ),
    PaperRouteStage(
        order=6,
        stage_id="branch_similarity",
        statement=(
            "the matching score is computed by measuring the cosine similarity "
            "between the flattened dense representations, where only the "
            "overlapping foreground regions are considered"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E, Eq. 7",
    ),
    PaperRouteStage(
        order=7,
        stage_id="max_fusion",
        statement=(
            "the final matching score is obtained by taking the maximum over "
            "the four matching scores derived from different pose-enhancement "
            "combinations"
        ),
        paper_locator=f"{PAPER_ARXIV_LOCATOR} §III-E, Eq. 8",
    ),
)


# ------------------------------------------------------------- what is refused
#
# Refused at any depth of a published Stage 9A document. Each one would mean an
# upstream byte, a tensor, a fingerprint image, a score or a machine-specific
# path had reached the evidence of a stage whose entire subject is that none of
# them do (spec section 51).
#
# As in Stage 8E, no member may be a value of a published vocabulary: these
# documents count operations into maps keyed by enum value, so a forbidden key
# named ``source_code`` would refuse a count of source-code components rather
# than a body of source code.
FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "license_text",
        "license_body",
        "source_text",
        "file_contents",
        "contents",
        "payload",
        "blob",
        "base64",
        "weights",
        "state_dict",
        "checkpoint_bytes",
        "tensor",
        "tensors",
        "tensor_sample",
        "tensor_values",
        "parameter_values",
        "embedding",
        "embeddings",
        "descriptor_values",
        "mask_values",
        "enhanced_image",
        "image_bytes",
        "drive_response",
        "score",
        "scores",
        "raw_score",
        "raw_scores",
        "branch_score_values",
        "threshold",
        "thresholds",
        "subject_id",
        "subject_ids",
        "pair_id",
        "pair_ids",
        "image_id",
        "image_ids",
        "absolute_path",
        "local_path",
        "artifact_root",
        "gpu_path",
        "home_directory",
    }
)

#: Every source file Stage 9A owns outright, audited for import boundaries.
STAGE_9A_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/flare_errors.py",
    "src/fpbench/experiments/stage9a_flare_identity.py",
    "src/fpbench/experiments/stage9a_flare_artifacts.py",
    "src/fpbench/experiments/stage9a_flare_route.py",
    "src/fpbench/experiments/stage9a_flare_qualification.py",
    "src/fpbench/experiments/stage9a_flare_finalization.py",
)

STAGE_9A_ADRS: tuple[str, ...] = (
    "docs/adr/0085-stage-9-selects-the-full-flare-route.md",
    "docs/adr/0086-flare-identity-is-fdd-d6-dualpose-dualenh-maxcosine.md",
    "docs/adr/0087-flare-score-affecting-upstream-gaps-must-not-be-guessed.md",
    "docs/adr/0088-flare-paper-route-and-public-code-must-resolve-to-one-transform-graph.md",
)

STAGE_9A_DOCUMENTS: tuple[str, ...] = (
    "docs/experiments/stage9a-flare-artifact-qualification.md",
    "docs/algorithms/flare/upstream-artifacts.md",
    "docs/algorithms/flare/method-route.md",
    "docs/algorithms/flare/transform-graph.md",
    "docs/algorithms/flare/score-semantics.md",
)

#: The pytest marker for tests that need artifacts on this machine. They are not
#: part of the public CI, which fetches nothing (spec section 54).
FLARE_ARTIFACT_MARKER = "flare_artifact"


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 9A identifier, validated as a safe path and key component."""
    identifiers = (
        STAGE_FINALIZATION_KIND,
        ALGORITHM_CANDIDATE_ID,
        FLARE_ARTIFACT_MARKER,
        *(branch.branch_id for branch in BRANCHES),
        *(repository.repository_id for repository in UPSTREAM_REPOSITORIES),
        *(artifact.artifact_id for artifact in REQUIRED_ARTIFACTS),
        *(stage.stage_id for stage in PAPER_ROUTE),
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers
