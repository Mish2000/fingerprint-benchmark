"""Everything Stage 10A froze before it looked at either candidate.

These constants are the stage's contract with itself: the two candidates, the
seven hard gates and the order they run in, the vocabulary an origin claim may
use, the closed list of blocker codes, the outcomes, and the tie-break criteria
that apply only to survivors. They are asserted by the contract suite,
republished in the finalization, and a later change to any of them is a
different preflight rather than a quiet correction to this one.

Stage 10A asks one question:

.. code-block:: text

    which, if either, of AFR-Net and JIPNet can enter fpbench as Algorithm 4
    without an fpbench reconstruction, without invented preprocessing, and
    without SD300 being consulted to make it fit?

It is allowed to answer "neither" (docs/adr/0089).

Nothing here is derived at import time, nothing reads a workspace, nothing
downloads anything, and nothing is a fingerprint image, a score, a tensor or an
upstream byte. What is here about upstream is a *description*: a URL, a commit
SHA, a digest, a size, a file name, a declared tensor shape, and the name of a
function in a file. Under Stage 8E's policy those are exactly the things a
public repository may hold about a third-party component (docs/adr/0083).

This module exists for the reason :mod:`fpbench.experiments.stage9a_flare_identity`
does: the candidate evidence, the gate engine and the finalization marker all
need the frozen values, and a shared constant module is the alternative to an
import cycle between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from fpbench.core.algorithm4_errors import CandidateIdentityError
from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE_10A_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "ALGORITHM_SLOT",
    "STAGE_10A_SELECTED_OUTCOME",
    "STAGE_10A_NO_SURVIVOR_OUTCOME",
    "STAGE_10A_OUTCOMES",
    "CANDIDATE_PASS_SUFFIX",
    "CANDIDATE_FAIL_SUFFIX",
    "EVIDENCE_DIRECTORY",
    "STAGE_10A_FINALIZATION_NAME",
    "README_NAME",
    "CANDIDATE_SET_NAME",
    "CANDIDATE_COMPARISON_NAME",
    "AFRNET_SOURCE_DISCOVERY_NAME",
    "JIPNET_SOURCE_MANIFEST_NAME",
    "AUTHENTICITY_REPORT_NAME",
    "ARTIFACT_MANIFEST_NAME",
    "INPUT_DOMAIN_CONTRACT_NAME",
    "INFERENCE_ROUTE_AUDIT_NAME",
    "SCORE_CONTRACT_NAME",
    "TRAINING_PROVENANCE_NAME",
    "RUNTIME_SMOKE_NAME",
    "PREFLIGHT_REPORT_NAME",
    "candidate_document_names",
    "REQUIRED_EVIDENCE_FILES",
    "STAGE8E_FINALIZATION_FINGERPRINT",
    "STAGE8E_OUTCOME",
    "STAGE8E_PURPOSE_FINGERPRINT",
    "STAGE8E_POLICY_FINGERPRINT",
    "ImplementationOrigin",
    "ACCEPTED_ORIGINS",
    "PreflightGate",
    "GATE_ORDER",
    "GateStatus",
    "GATE_DOCUMENTS",
    "InputDomainResolution",
    "SD300OverlapStatus",
    "BlockerCode",
    "GATE_BLOCKERS",
    "CandidateIdentity",
    "AFRNET",
    "JIPNET",
    "CANDIDATES",
    "candidate",
    "DECLARED_NON_CANDIDATES",
    "TieBreakCriterion",
    "TIE_BREAK_CRITERIA",
    "BENCHMARK_INPUT_PROFILE",
    "BENCHMARK_INPUT_PPI",
    "BENCHMARK_INPUT_PIXEL_FORMAT",
    "FORBIDDEN_PUBLISHED_KEYS",
    "STAGE_10A_SOURCE_FILES",
    "STAGE_10A_ADRS",
    "STAGE_10A_DOCUMENTS",
    "ARTIFACT_STORE_PREFIX",
    "PREFLIGHT_ARTIFACT_MARKER",
    "all_frozen_identifiers",
]

STAGE_10A_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_10a_finalization"

#: The benchmark slot this preflight is selecting for. Nothing here fills it.
ALGORITHM_SLOT = "algorithm_4"

#: The two outcomes, and there are exactly two. ``NO_SURVIVOR`` is a complete
#: and correct result: weakening a gate to obtain an Algorithm 4 is the failure
#: mode Stage 9A's FLARE reading exists to warn about (docs/adr/0089).
STAGE_10A_SELECTED_OUTCOME = "ALGORITHM4_CANDIDATE_SELECTED"
STAGE_10A_NO_SURVIVOR_OUTCOME = "ALGORITHM4_PREFLIGHT_NO_SURVIVOR"
STAGE_10A_OUTCOMES = (STAGE_10A_SELECTED_OUTCOME, STAGE_10A_NO_SURVIVOR_OUTCOME)

#: Per-candidate verdict names, assembled from the candidate's own token so that
#: ``AFRNET_PREFLIGHT_PASS`` cannot drift from ``AFRNET``.
CANDIDATE_PASS_SUFFIX = "_PREFLIGHT_PASS"
CANDIDATE_FAIL_SUFFIX = "_PREFLIGHT_FAIL"

EVIDENCE_DIRECTORY = Path("evidence") / "stage10a-algorithm4-candidate-preflight"

#: The last-written authority, and the last file committed.
STAGE_10A_FINALIZATION_NAME = "stage-10a-finalization.json"
README_NAME = "README.md"
CANDIDATE_SET_NAME = "candidate-set.json"
CANDIDATE_COMPARISON_NAME = "candidate-comparison.json"

#: Per-candidate documents. The first one differs by candidate on purpose: for
#: JIPNet there is a repository to pin, and for AFR-Net there is only the record
#: of a search (docs/adr/0090).
AFRNET_SOURCE_DISCOVERY_NAME = "source-discovery.json"
JIPNET_SOURCE_MANIFEST_NAME = "source-manifest.json"
AUTHENTICITY_REPORT_NAME = "authenticity-report.json"
ARTIFACT_MANIFEST_NAME = "artifact-manifest.json"
INPUT_DOMAIN_CONTRACT_NAME = "input-domain-contract.json"
INFERENCE_ROUTE_AUDIT_NAME = "inference-route-audit.json"
SCORE_CONTRACT_NAME = "score-contract.json"
TRAINING_PROVENANCE_NAME = "training-provenance.json"
RUNTIME_SMOKE_NAME = "runtime-smoke.json"
PREFLIGHT_REPORT_NAME = "preflight-report.json"


# ------------------------------------------------------- the candidate identity


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """One Algorithm 4 candidate, named before anything was concluded about it.

    ``marker_token`` is the upper-case name the marker and the per-candidate
    verdicts use. ``candidate_id`` is the lower-case one that names a directory
    and a JSON key. They are two spellings of one identity and the contract
    suite checks they stay that way.

    ``first_document`` differs between the two candidates because the first
    thing Stage 10A has to record differs: JIPNet has an official repository to
    pin, AFR-Net has only the record of where its implementation was looked for.
    """

    candidate_id: str
    marker_token: str
    display_name: str
    paper_title: str
    paper_locator: str
    paper_arxiv_locator: str
    authors: tuple[str, ...]
    first_document: str

    def __post_init__(self) -> None:
        validate_id(self.candidate_id)
        if self.marker_token != self.candidate_id.upper():
            raise CandidateIdentityError(
                f"{self.candidate_id}: the marker token {self.marker_token!r} is "
                "a second spelling of one identity and must be the upper-case "
                "form of the candidate id"
            )
        if self.first_document not in (
            AFRNET_SOURCE_DISCOVERY_NAME,
            JIPNET_SOURCE_MANIFEST_NAME,
        ):
            raise CandidateIdentityError(
                f"{self.candidate_id}: {self.first_document!r} is not one of the "
                "two shapes a candidate's first document may take"
            )

    @property
    def pass_outcome(self) -> str:
        return f"{self.marker_token}{CANDIDATE_PASS_SUFFIX}"

    @property
    def fail_outcome(self) -> str:
        return f"{self.marker_token}{CANDIDATE_FAIL_SUFFIX}"


AFRNET = CandidateIdentity(
    candidate_id="afrnet",
    marker_token="AFRNET",
    display_name="AFR-Net: Attention-Driven Fingerprint Recognition Network",
    paper_title="AFR-Net: Attention-Driven Fingerprint Recognition Network",
    paper_locator=(
        "S. A. Grosz and A. K. Jain, 'AFR-Net: Attention-Driven Fingerprint "
        "Recognition Network', IEEE Transactions on Biometrics, Behavior, and "
        "Identity Science, vol. 6, no. 1 (2024) pp. 30-42, "
        "DOI 10.1109/TBIOM.2023.3317303"
    ),
    paper_arxiv_locator="arXiv:2211.13897v2",
    authors=("Steven A. Grosz", "Anil K. Jain"),
    first_document=AFRNET_SOURCE_DISCOVERY_NAME,
)

JIPNET = CandidateIdentity(
    candidate_id="jipnet",
    marker_token="JIPNET",
    display_name="JIPNet: Joint Identity Verification and Pose Alignment for Partial Fingerprints",
    paper_title="Joint Identity Verification and Pose Alignment for Partial Fingerprints",
    paper_locator=(
        "X. Guan, Z. Pan, J. Feng and J. Zhou, 'Joint Identity Verification and "
        "Pose Alignment for Partial Fingerprints', IEEE Transactions on "
        "Information Forensics and Security, vol. 20 (2025) pp. 249-263, "
        "DOI 10.1109/TIFS.2024.3516566"
    ),
    paper_arxiv_locator="arXiv:2405.03959v4",
    authors=("Xiongjun Guan", "Zhiyu Pan", "Jianjiang Feng", "Jie Zhou"),
    first_document=JIPNET_SOURCE_MANIFEST_NAME,
)

CANDIDATES: tuple[CandidateIdentity, ...] = (AFRNET, JIPNET)


def candidate(candidate_id: str) -> CandidateIdentity:
    """The frozen identity for one candidate id."""
    for item in CANDIDATES:
        if item.candidate_id == candidate_id:
            return item
    raise CandidateIdentityError(
        f"{candidate_id!r} is not a Stage 10A candidate; the set is "
        f"{[item.candidate_id for item in CANDIDATES]}"
    )


#: Things Stage 10A names so that nobody later mistakes them for a candidate.
#:
#: The AFR-Net inside JIPNet is a real artifact with a real identity. That
#: identity is not ``afr_net``, and admitting it under that name is precisely
#: the blurring docs/adr/0090 exists to prevent. If it is ever wanted, it is a
#: third candidate with the name below and a preflight of its own.
DECLARED_NON_CANDIDATES: tuple[tuple[str, str], ...] = (
    (
        "jipnet_authors_adjusted_afrnet_reimplementation",
        "The AFR-Net reproduction distributed inside XiongjunGuan/JIPNet, whose "
        "own README states that the comparison models are reproduced from their "
        "papers and that some were adjusted for partial-fingerprint scenarios. "
        "It is not AFR-Net and Stage 10A does not consider it as AFR-Net.",
    ),
)


# ---------------------------------------------------------------- vocabularies


class ImplementationOrigin(str, Enum):
    """Who produced the executable thing, and in what relation to the paper.

    Only the first two are admissible for an Algorithm 4 candidate. The rest are
    recorded so that a candidate can be refused by name rather than by
    impression (docs/adr/0090).
    """

    AUTHOR_OFFICIAL_IMPLEMENTATION = "AUTHOR_OFFICIAL_IMPLEMENTATION"
    AUTHOR_OFFICIAL_RELEASE = "AUTHOR_OFFICIAL_RELEASE"
    THIRD_PARTY_REIMPLEMENTATION = "THIRD_PARTY_REIMPLEMENTATION"
    ADJUSTED_THIRD_PARTY_REIMPLEMENTATION = "ADJUSTED_THIRD_PARTY_REIMPLEMENTATION"
    PAPER_RECONSTRUCTION = "PAPER_RECONSTRUCTION"
    UNKNOWN = "UNKNOWN"

    @property
    def is_admissible_for_algorithm_4(self) -> bool:
        return self in ACCEPTED_ORIGINS


ACCEPTED_ORIGINS: tuple[ImplementationOrigin, ...] = (
    ImplementationOrigin.AUTHOR_OFFICIAL_IMPLEMENTATION,
    ImplementationOrigin.AUTHOR_OFFICIAL_RELEASE,
)


class PreflightGate(str, Enum):
    """The seven hard gates. Every one of them is mandatory.

    There is no weighting between them and no score. A candidate that fails one
    fails, whatever the others say — which is the rule Stage 9A's FLARE reading
    produced, where a high-quality method with an unresolvable artifact identity
    would have won a ranking it should never have entered (docs/adr/0089).
    """

    IDENTITY = "IDENTITY"
    INPUT_DOMAIN = "INPUT_DOMAIN"
    ARTIFACTS = "ARTIFACTS"
    INFERENCE_ROUTE = "INFERENCE_ROUTE"
    SCORE_CONTRACT = "SCORE_CONTRACT"
    TRAINING_PROVENANCE = "TRAINING_PROVENANCE"
    RUNTIME_SMOKE = "RUNTIME_SMOKE"


#: The order, and it is the point of the stage. Identity and input domain come
#: first because they are the two that can be settled by reading, and settling
#: either of them negatively saves several hundred megabytes of download and a
#: runtime nobody needed (docs/adr/0089).
GATE_ORDER: tuple[PreflightGate, ...] = (
    PreflightGate.IDENTITY,
    PreflightGate.INPUT_DOMAIN,
    PreflightGate.ARTIFACTS,
    PreflightGate.INFERENCE_ROUTE,
    PreflightGate.SCORE_CONTRACT,
    PreflightGate.TRAINING_PROVENANCE,
    PreflightGate.RUNTIME_SMOKE,
)

#: The gate each per-candidate document reports on. A document whose gate was
#: never reached is published as ``NOT_REACHED`` and carries no conclusion.
GATE_DOCUMENTS: tuple[tuple[PreflightGate, str], ...] = (
    (PreflightGate.IDENTITY, AUTHENTICITY_REPORT_NAME),
    (PreflightGate.INPUT_DOMAIN, INPUT_DOMAIN_CONTRACT_NAME),
    (PreflightGate.ARTIFACTS, ARTIFACT_MANIFEST_NAME),
    (PreflightGate.INFERENCE_ROUTE, INFERENCE_ROUTE_AUDIT_NAME),
    (PreflightGate.SCORE_CONTRACT, SCORE_CONTRACT_NAME),
    (PreflightGate.TRAINING_PROVENANCE, TRAINING_PROVENANCE_NAME),
    (PreflightGate.RUNTIME_SMOKE, RUNTIME_SMOKE_NAME),
)


class GateStatus(str, Enum):
    """What one gate concluded, for one candidate.

    ``NOT_REACHED`` is not a soft failure and not a pass. It records that the
    candidate had already stopped, so this question was never asked. Publishing
    it as anything else would be inventing a conclusion (docs/adr/0089).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_REACHED = "NOT_REACHED"


class InputDomainResolution(str, Enum):
    """How ``canonical_500`` reaches a model's declared input, if it does.

    Only the first two admit a candidate. ``FPBENCH_CONSTRUCTION_REQUIRED`` is
    the one that matters here: it says a transformation exists that would work,
    and that choosing it would be fpbench choosing (docs/adr/0092).
    """

    NATIVE_INPUT_ACCEPTED = "NATIVE_INPUT_ACCEPTED"
    UPSTREAM_AUTHORITATIVE_TRANSFORMATION = "UPSTREAM_AUTHORITATIVE_TRANSFORMATION"
    FPBENCH_CONSTRUCTION_REQUIRED = "FPBENCH_CONSTRUCTION_REQUIRED"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def admits_candidate(self) -> bool:
        return self in (
            InputDomainResolution.NATIVE_INPUT_ACCEPTED,
            InputDomainResolution.UPSTREAM_AUTHORITATIVE_TRANSFORMATION,
        )


class SD300OverlapStatus(str, Enum):
    """Whether the evaluation cohort appears in a candidate's training history.

    ``PROVEN_ABSENT`` requires an upstream statement that the dataset was not
    used. Silence is ``NO_EVIDENCE_FOUND``, and the two are never merged: a
    paper that does not mention SD300 has not said it did not use SD300.
    """

    POSITIVE_OVERLAP_FOUND = "POSITIVE_OVERLAP_FOUND"
    NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
    PROVEN_ABSENT = "PROVEN_ABSENT"
    UNRESOLVED = "UNRESOLVED"
    NOT_REACHED = "NOT_REACHED"

    @property
    def is_automatic_rejection(self) -> bool:
        return self is SD300OverlapStatus.POSITIVE_OVERLAP_FOUND


class BlockerCode(str, Enum):
    """Why a candidate cannot enter fpbench as Algorithm 4. A closed list.

    Each member names something a reader could act on, and each is attached to
    exactly one gate below. "Not ideal", "some issues" and "probably works" are
    not among them and cannot be expressed here.
    """

    OFFICIAL_IMPLEMENTATION_NOT_FOUND = "OFFICIAL_IMPLEMENTATION_NOT_FOUND"
    OFFICIAL_CHECKPOINT_NOT_FOUND = "OFFICIAL_CHECKPOINT_NOT_FOUND"
    THIRD_PARTY_REIMPLEMENTATION_ONLY = "THIRD_PARTY_REIMPLEMENTATION_ONLY"

    BENCHMARK_INPUT_ROUTE_UNRESOLVED = "BENCHMARK_INPUT_ROUTE_UNRESOLVED"
    INPUT_DOMAIN_INCOMPATIBLE = "INPUT_DOMAIN_INCOMPATIBLE"
    FPBENCH_PREPROCESSING_CHOICE_REQUIRED = "FPBENCH_PREPROCESSING_CHOICE_REQUIRED"

    REQUIRED_ARTIFACT_MISSING = "REQUIRED_ARTIFACT_MISSING"
    ARTIFACT_IDENTITY_UNRESOLVED = "ARTIFACT_IDENTITY_UNRESOLVED"
    CHECKPOINT_COMPATIBILITY_UNRESOLVED = "CHECKPOINT_COMPATIBILITY_UNRESOLVED"
    CHECKPOINT_MODEL_MISMATCH = "CHECKPOINT_MODEL_MISMATCH"

    SCORE_ROUTE_UNRESOLVED = "SCORE_ROUTE_UNRESOLVED"
    PAIR_ORDER_SEMANTICS_UNRESOLVED = "PAIR_ORDER_SEMANTICS_UNRESOLVED"
    INFERENCE_DEPENDENCY_UNAVAILABLE = "INFERENCE_DEPENDENCY_UNAVAILABLE"

    SD300_TRAINING_OVERLAP_FOUND = "SD300_TRAINING_OVERLAP_FOUND"
    RESEARCH_USE_BLOCKED = "RESEARCH_USE_BLOCKED"

    LOCAL_SMOKE_FAILED = "LOCAL_SMOKE_FAILED"


#: Which gate each blocker belongs to. A blocker raised against a gate that was
#: never reached is a contradiction, and the engine refuses one.
GATE_BLOCKERS: tuple[tuple[PreflightGate, tuple[BlockerCode, ...]], ...] = (
    (
        PreflightGate.IDENTITY,
        (
            BlockerCode.OFFICIAL_IMPLEMENTATION_NOT_FOUND,
            BlockerCode.OFFICIAL_CHECKPOINT_NOT_FOUND,
            BlockerCode.THIRD_PARTY_REIMPLEMENTATION_ONLY,
        ),
    ),
    (
        PreflightGate.INPUT_DOMAIN,
        (
            BlockerCode.BENCHMARK_INPUT_ROUTE_UNRESOLVED,
            BlockerCode.INPUT_DOMAIN_INCOMPATIBLE,
            BlockerCode.FPBENCH_PREPROCESSING_CHOICE_REQUIRED,
        ),
    ),
    (
        PreflightGate.ARTIFACTS,
        (
            BlockerCode.REQUIRED_ARTIFACT_MISSING,
            BlockerCode.ARTIFACT_IDENTITY_UNRESOLVED,
            BlockerCode.RESEARCH_USE_BLOCKED,
        ),
    ),
    (
        PreflightGate.INFERENCE_ROUTE,
        (
            BlockerCode.CHECKPOINT_COMPATIBILITY_UNRESOLVED,
            BlockerCode.CHECKPOINT_MODEL_MISMATCH,
            BlockerCode.INFERENCE_DEPENDENCY_UNAVAILABLE,
        ),
    ),
    (
        PreflightGate.SCORE_CONTRACT,
        (
            BlockerCode.SCORE_ROUTE_UNRESOLVED,
            BlockerCode.PAIR_ORDER_SEMANTICS_UNRESOLVED,
        ),
    ),
    (
        PreflightGate.TRAINING_PROVENANCE,
        (BlockerCode.SD300_TRAINING_OVERLAP_FOUND,),
    ),
    (PreflightGate.RUNTIME_SMOKE, (BlockerCode.LOCAL_SMOKE_FAILED,)),
)


# -------------------------------------------------------------- the benchmark

#: What a future Algorithm 4 adapter would receive, and the only thing it would
#: receive. Not SD300 raw A/B/C, and no further resampling inside fpbench: the
#: canonical profile already produced 500 ppi gray8 (docs/adr/0031).
BENCHMARK_INPUT_PROFILE = "canonical_500"
BENCHMARK_INPUT_PPI = 500
BENCHMARK_INPUT_PIXEL_FORMAT = "gray8"


# ---------------------------------------------------------------- the tie-break


@dataclass(frozen=True, slots=True)
class TieBreakCriterion:
    """One ordered criterion, applied only when both candidates have passed."""

    order: int
    criterion_id: str
    description: str

    def __post_init__(self) -> None:
        validate_id(self.criterion_id)


#: Applied in this order and only among hard-gate survivors (docs/adr/0093).
#:
#: Reported accuracy is deliberately absent. The two papers report on different
#: datasets under different protocols, so a comparison between their numbers
#: would be a comparison between two experiments rather than between two
#: candidates — and Stage 10A reads no evaluation data of its own to settle it.
TIE_BREAK_CRITERIA: tuple[TieBreakCriterion, ...] = (
    TieBreakCriterion(
        1,
        "canonical500_fit",
        "closer fit to the canonical_500 full-fingerprint benchmark",
    ),
    TieBreakCriterion(2, "executable_provenance", "cleaner executable provenance"),
    TieBreakCriterion(
        3,
        "external_inference_components",
        "fewer inference-time external components",
    ),
    TieBreakCriterion(
        4,
        "methodological_diversity",
        "methodological diversity against SourceAFIS, NBIS and flx",
    ),
    TieBreakCriterion(5, "runtime_practicality", "runtime practicality"),
    TieBreakCriterion(6, "learning_value", "learning value"),
)


# ----------------------------------------------------------- the closed stage
#
# Restated from evidence/stage8e-research-only-policy/. Stage 10A reads that
# marker to confirm the policy it reuses is the policy it thinks it reuses, and
# refuses on disagreement. Nothing under that directory is edited, and no module
# under src/fpbench/third_party/ or src/fpbench/core/third_party_*.py is edited
# either. Stage 10A adds no licensing subsystem (spec section 38).
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

#: Where the store keeps Stage 10A's artifacts, relative to
#: ``FPBENCH_THIRD_PARTY_ROOT``. Manifests hold no absolute path and none of
#: these is a place on any machine (docs/adr/0083).
ARTIFACT_STORE_PREFIX = "algorithm4-preflight"

#: The pytest marker for tests that need artifacts on this machine. They are not
#: part of the public CI, which fetches nothing.
PREFLIGHT_ARTIFACT_MARKER = "algorithm4_preflight_artifact"


# --------------------------------------------------------- the published files


def candidate_document_names(item: CandidateIdentity) -> tuple[str, ...]:
    """The nine documents one candidate publishes, in dependency order."""
    return (
        item.first_document,
        AUTHENTICITY_REPORT_NAME,
        ARTIFACT_MANIFEST_NAME,
        INPUT_DOMAIN_CONTRACT_NAME,
        INFERENCE_ROUTE_AUDIT_NAME,
        SCORE_CONTRACT_NAME,
        TRAINING_PROVENANCE_NAME,
        RUNTIME_SMOKE_NAME,
        PREFLIGHT_REPORT_NAME,
    )


def _required_evidence_files() -> tuple[str, ...]:
    names = [README_NAME, CANDIDATE_SET_NAME]
    for item in CANDIDATES:
        names.extend(
            (PurePosixPath(item.candidate_id) / name).as_posix()
            for name in candidate_document_names(item)
        )
    names.extend((CANDIDATE_COMPARISON_NAME, STAGE_10A_FINALIZATION_NAME))
    return tuple(names)


#: Exactly what the evidence directory holds, as repository-relative POSIX paths
#: below it. An extra file is a finding.
#:
#: There is no ``licensing-provenance.json`` and no per-candidate licence
#: document. Stage 8E owns that question and a second authority beside its
#: manifest would be a second policy (spec section 38).
REQUIRED_EVIDENCE_FILES: tuple[str, ...] = _required_evidence_files()


# ------------------------------------------------------------- what is refused
#
# Refused at any depth of a published Stage 10A document. Each one would mean an
# upstream byte, a tensor, a fingerprint image, a score or a machine-specific
# path had reached the evidence of a stage whose entire subject is that none of
# them do.
#
# As in Stage 8E and Stage 9A, no member may be a value of a published
# vocabulary: these documents count things into maps keyed by enum value, so a
# forbidden key named ``source_code`` would refuse a count of source-code
# components rather than a body of source code.
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
        "patch_pixels",
        "image_bytes",
        "drive_response",
        "score",
        "scores",
        "raw_score",
        "raw_scores",
        "matching_probability",
        "threshold",
        "thresholds",
        "reported_eer",
        "reported_tar",
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

#: Every source file Stage 10A owns outright, audited for import boundaries.
STAGE_10A_SOURCE_FILES: tuple[str, ...] = (
    "src/fpbench/core/algorithm4_errors.py",
    "src/fpbench/experiments/stage10a_candidate_identity.py",
    "src/fpbench/experiments/stage10a_candidate_evidence.py",
    "src/fpbench/experiments/stage10a_preflight.py",
    "src/fpbench/experiments/stage10a_finalization.py",
)

STAGE_10A_ADRS: tuple[str, ...] = (
    "docs/adr/0089-algorithm-4-selection-requires-preflight-before-commitment.md",
    (
        "docs/adr/0090-adjusted-third-party-reimplementations-do-not-inherit-"
        "original-algorithm-identity.md"
    ),
    "docs/adr/0091-benchmark-input-domain-compatibility-is-a-hard-candidate-gate.md",
    (
        "docs/adr/0092-fpbench-does-not-invent-score-affecting-input-construction-"
        "to-admit-a-candidate.md"
    ),
    "docs/adr/0093-algorithm-4-is-selected-only-among-hard-gate-survivors.md",
)

STAGE_10A_DOCUMENTS: tuple[str, ...] = (
    "docs/experiments/stage10a-algorithm4-candidate-preflight.md",
    "docs/algorithms/algorithm4-candidates/afrnet.md",
    "docs/algorithms/algorithm4-candidates/jipnet.md",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 10A identifier, validated as a safe path and key component."""
    identifiers = (
        STAGE_FINALIZATION_KIND,
        ALGORITHM_SLOT,
        ARTIFACT_STORE_PREFIX.replace("-", "_"),
        PREFLIGHT_ARTIFACT_MARKER,
        *(item.candidate_id for item in CANDIDATES),
        *(name for name, _ in DECLARED_NON_CANDIDATES),
        *(item.criterion_id for item in TIE_BREAK_CRITERIA),
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers
