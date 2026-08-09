"""What was actually found about each candidate, recorded before anything was decided.

This module is the reconnaissance record. Every value in it is an observation
with a locator: a URL that was fetched, a commit that was pinned, a digest that
was computed twice, a line of upstream code, a sentence of a paper. Nothing here
derives a gate result — :mod:`fpbench.experiments.stage10a_preflight` does that,
and it can only read what is here.

The split matters because the two candidates fail for entirely different
reasons, and both reasons are about *absence*. An absence is easy to assert and
hard to establish, so the shape of this module is: name the places that were
searched, say what each one yielded, and let the conclusion follow. An
``official_source_found: false`` that does not enumerate where it looked is an
opinion (docs/adr/0090).

Two things are deliberately **not** here:

* no reported accuracy from either paper. Stage 10A does not choose between
  candidates on numbers produced by different experiments (docs/adr/0093);
* no conclusion for a gate that was never reached. The observations gathered
  while reading a paper for the identity gate are recorded as observations, and
  the gate that would have used them is published ``NOT_REACHED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from fpbench.core.algorithm4_errors import (
    CandidateAuthenticityError,
    InputDomainError,
)
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash
from fpbench.core.third_party_models import ThirdPartyComponentKind
from fpbench.experiments import stage10a_candidate_identity as frozen

__all__ = [
    "SearchOutcome",
    "SearchLocation",
    "AFRNET_SEARCH_LOCATIONS",
    "AFRNET_EXCLUDED_EVIDENCE",
    "afrnet_source_discovery",
    "UpstreamRepository",
    "JIPNET_REPOSITORY",
    "RepositoryFile",
    "JIPNET_PINNED_FILES",
    "jipnet_source_manifest",
    "OriginClaim",
    "ORIGIN_CLAIMS",
    "origin_claim",
    "authenticity_report",
    "DeclaredModelInput",
    "InputDomainObservation",
    "InputDomainContract",
    "INPUT_DOMAIN_CONTRACTS",
    "input_domain_contract",
    "input_domain_contract_document",
    "RequiredArtifactSketch",
    "ARTIFACT_SKETCHES",
    "artifact_sketches",
    "RouteObservation",
    "ROUTE_OBSERVATIONS",
    "route_observations",
    "ScoreObservation",
    "SCORE_OBSERVATIONS",
    "score_observations",
    "DatasetRole",
    "TrainingDataset",
    "TrainingProvenanceObservation",
    "TRAINING_PROVENANCE",
    "training_provenance",
    "RuntimeObservation",
    "RUNTIME_OBSERVATIONS",
    "runtime_observations",
    "reconnaissance_fingerprint",
]


# ------------------------------------------------------------- the AFR-Net search


class SearchOutcome(str, Enum):
    """What one searched location yielded.

    ``NOT_READABLE`` is separate from ``NOTHING_FOUND`` and never merged into
    it. A page this project could not read is a place where nothing was
    established, not a place where nothing exists.
    """

    NOTHING_FOUND = "NOTHING_FOUND"
    PAPER_ONLY = "PAPER_ONLY"
    RELATED_WORK_ONLY = "RELATED_WORK_ONLY"
    NOT_READABLE = "NOT_READABLE"
    IMPLEMENTATION_FOUND = "IMPLEMENTATION_FOUND"
    CHECKPOINT_FOUND = "CHECKPOINT_FOUND"


@dataclass(frozen=True, slots=True)
class SearchLocation:
    """One place an author-supplied implementation was looked for."""

    location_id: str
    description: str
    locator: str
    outcome: SearchOutcome
    finding: str
    observed_utc: str

    def __post_init__(self) -> None:
        validate_id(self.location_id)
        if not self.finding.strip():
            raise CandidateAuthenticityError(
                f"{self.location_id}: a searched location records what it "
                "yielded; a blank finding is an unperformed search"
            )


_OBSERVED = "2026-08-09T00:00:00Z"

#: The formal search for an author-supplied AFR-Net implementation. Nine
#: locations, each with what it returned on the date above (spec section 5).
AFRNET_SEARCH_LOCATIONS: tuple[SearchLocation, ...] = (
    SearchLocation(
        location_id="arxiv_abstract_page",
        description="the arXiv listing for the paper, including its version history",
        locator="https://arxiv.org/abs/2211.13897",
        outcome=SearchOutcome.PAPER_ONLY,
        finding=(
            "Two versions, v1 (25 Nov 2022) and v2 (3 Dec 2022). The page "
            "carries no code link, no project page and no repository URL."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="paper_body_and_references",
        description="the full text of arXiv:2211.13897v2, searched for a code statement",
        locator="https://arxiv.org/pdf/2211.13897v2",
        outcome=SearchOutcome.NOTHING_FOUND,
        finding=(
            "No 'code is available', 'code will be released' or repository "
            "sentence anywhere in sixteen pages. The single GitHub URL in the "
            "paper is reference [44], rwightman/pytorch-image-models, which is "
            "a dependency the authors used and not a release of this work."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="msu_biometrics_publications",
        description="the MSU Biometrics Research Group publication database",
        locator="https://biometrics.cse.msu.edu/publications.js",
        outcome=SearchOutcome.PAPER_ONLY,
        finding=(
            "Two entries for this work, the 2022 arXiv report and the 2023 "
            "TBIOM journal paper. Each carries exactly two links, 'arxiv' and "
            "'IEEE'. Other entries in the same file do carry a third 'Database' "
            "link, so the absence of one here is the group's own record rather "
            "than a limitation of the page."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="msu_biometrics_databases",
        description="the MSU Biometrics downloads and databases page",
        locator="https://biometrics.cse.msu.edu/pub/databases.html",
        outcome=SearchOutcome.NOTHING_FOUND,
        finding="The page does not mention AFR-Net.",
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="msu_biometrics_projects",
        description="the MSU Biometrics project pages",
        locator="https://biometrics.cse.msu.edu/projects.html",
        outcome=SearchOutcome.NOTHING_FOUND,
        finding="The page does not mention AFR-Net.",
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="first_author_github_account",
        description="the first author's GitHub account",
        locator="https://github.com/groszste",
        outcome=SearchOutcome.RELATED_WORK_ONLY,
        finding=(
            "Five repositories, of which two are forks. The only fingerprint "
            "work published there is SpoofGAN, a different paper by the same "
            "author. There is no AFR-Net repository."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="group_github_organisation",
        description="a GitHub organisation for the authors' research group",
        locator="https://github.com/msu-biometrics",
        outcome=SearchOutcome.NOTHING_FOUND,
        finding=(
            "No such organisation exists; the GitHub API answers 404. No group "
            "organisation publishing this work was located under any other name."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="github_repository_search",
        description="GitHub repository search for the algorithm name",
        locator="https://api.github.com/search/repositories?q=AFRNet",
        outcome=SearchOutcome.NOTHING_FOUND,
        finding=(
            "A search for 'AFR-Net fingerprint' returns nothing. A search for "
            "'AFRNet' returns five repositories, none of which is fingerprint "
            "recognition and none of which belongs to either author; their "
            "subjects are zero-shot learning, retinal OCTA segmentation and "
            "unrelated coursework."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="model_and_code_indexes",
        description="the Papers with Code entry, which now redirects to Hugging Face",
        locator="https://huggingface.co/papers/2211.13897",
        outcome=SearchOutcome.NOTHING_FOUND,
        finding=(
            "No official and no community implementation is listed. The models "
            "section reads 'No model linking this paper'."
        ),
        observed_utc=_OBSERVED,
    ),
    SearchLocation(
        location_id="ieee_supplementary_material",
        description="the IEEE Xplore article page, for supplementary material",
        locator="https://ieeexplore.ieee.org/document/10255275",
        outcome=SearchOutcome.NOT_READABLE,
        finding=(
            "The article page returned no readable content to this project, so "
            "the presence or absence of supplementary material there was not "
            "established. This location is recorded as unread rather than as "
            "empty."
        ),
        observed_utc=_OBSERVED,
    ),
)

#: Things that exist, are about AFR-Net, and are *not* evidence of an
#: author-supplied artifact. Enumerated so the identity gate can say why it did
#: not count them, rather than silently not counting them (spec section 6).
AFRNET_EXCLUDED_EVIDENCE: tuple[tuple[str, str, str], ...] = (
    (
        "jipnet_afrnet_reproduction",
        "https://github.com/XiongjunGuan/JIPNet/blob/"
        "40d8445c5b3afa55b409ae3221377e54e3ace53f/inference_AFRNet.py",
        "An executable AFR-Net published by the JIPNet authors, whose own README "
        "states that the comparison models are reproduced from their papers and "
        "that some were adjusted for partial-fingerprint scenarios. Its route is "
        "RidgeNet enhancement, then PFVNet's AlignNet, then AFRNet, then a "
        "weighted cosine of the CNN and ViT halves of the embedding. The paper "
        "states that the pose rectification used by DeepPrint, DesNet and AFR-Net "
        "could not be performed on partial fingerprints and that AlignNet was "
        "substituted, marking the result with an asterisk. Substituting a "
        "component of the published route makes this a different algorithm "
        "(docs/adr/0090).",
    ),
    (
        "granted_us_patent",
        "https://patents.google.com/patent/US20240412553A1/en",
        "MSU records a granted US patent 12,380,728, 'Attention Driven "
        "Fingerprint Recognition Network' (AFR-Net), dated 5 August 2025. A "
        "patent is a description of a method and not an executable artifact; it "
        "is recorded here as an observed fact about the work's status and is not "
        "the basis of any Stage 10A conclusion.",
    ),
)


def afrnet_source_discovery() -> Mapping[str, Any]:
    """The search, published in full, with the three findings it settles."""
    official_source_found = any(
        location.outcome is SearchOutcome.IMPLEMENTATION_FOUND
        for location in AFRNET_SEARCH_LOCATIONS
    )
    official_checkpoint_found = any(
        location.outcome is SearchOutcome.CHECKPOINT_FOUND
        for location in AFRNET_SEARCH_LOCATIONS
    )
    return {
        "schema": "stage_10a_afrnet_source_discovery_v1",
        "candidate": frozen.AFRNET.candidate_id,
        "gate": frozen.PreflightGate.IDENTITY.value,
        "paper": frozen.AFRNET.paper_locator,
        "paper_preprint": frozen.AFRNET.paper_arxiv_locator,
        "authors": list(frozen.AFRNET.authors),
        "locations_searched": len(AFRNET_SEARCH_LOCATIONS),
        "official_source_found": official_source_found,
        "official_checkpoint_found": official_checkpoint_found,
        "official_inference_route_found": (
            official_source_found and official_checkpoint_found
        ),
        "locations": [
            {
                "location_id": location.location_id,
                "description": location.description,
                "locator": location.locator,
                "outcome": location.outcome.value,
                "finding": location.finding,
                "observed_utc": location.observed_utc,
            }
            for location in AFRNET_SEARCH_LOCATIONS
        ],
        "excluded_evidence": [
            {"evidence_id": name, "locator": locator, "why_excluded": reason}
            for name, locator, reason in AFRNET_EXCLUDED_EVIDENCE
        ],
        "not_found_is_not_proof_of_absence": True,
        "notes": [
            "This document establishes that no author-supplied AFR-Net "
            "implementation and no author-supplied AFR-Net checkpoint were "
            "located. It does not establish that none exists, and one location "
            "was not readable from here.",
            "Either finding alone would be enough: Stage 10A needs both a source "
            "and a checkpoint from the original authors before it can call a "
            "route AFR-Net.",
        ],
    }


# ------------------------------------------------------ the JIPNet source manifest


@dataclass(frozen=True, slots=True)
class UpstreamRepository:
    """One official repository, pinned by a commit and by archive bytes.

    ``default_branch_observed`` is recorded and then never used as an identity,
    for the reason Stage 9A gives: a branch moves, and this repository's ``main``
    moved twice during the period the paper was current.
    """

    repository_id: str
    upstream_name: str
    html_locator: str
    default_branch_observed: str
    commit: str
    commit_date_utc: str
    archive_locator: str
    archive_filename: str
    archive_sha256: str
    archive_size_bytes: int
    license_spdx: str
    license_document_sha256: str
    readme_document_sha256: str
    acquired_twice_byte_identical: bool
    acquisition_timestamp_utc: str
    role: str

    def __post_init__(self) -> None:
        validate_id(self.repository_id)
        if len(self.commit) != 40 or set(self.commit) - set("0123456789abcdef"):
            raise CandidateAuthenticityError(
                f"{self.repository_id}: a pinned commit is a full 40-character "
                "SHA. 'main', 'master', 'latest' and 'HEAD' are not identities"
            )


#: Observed 2026-08-09. The commit is the identity; the branch name is a note.
JIPNET_REPOSITORY = UpstreamRepository(
    repository_id="jipnet_main",
    upstream_name="XiongjunGuan/JIPNet",
    html_locator="https://github.com/XiongjunGuan/JIPNet",
    default_branch_observed="main",
    commit="40d8445c5b3afa55b409ae3221377e54e3ace53f",
    commit_date_utc="2026-04-16T04:02:16Z",
    archive_locator=(
        "https://codeload.github.com/XiongjunGuan/JIPNet/tar.gz/"
        "40d8445c5b3afa55b409ae3221377e54e3ace53f"
    ),
    archive_filename="JIPNet-40d8445c.tar.gz",
    archive_sha256=(
        "79924b66d1a194415931b86f65ada4505714e19e76ffb805aa622f17f952cf44"
    ),
    archive_size_bytes=2583931,
    license_spdx="MIT",
    license_document_sha256=(
        "d039e1af5ef20f591d61ed86cb9670bd028532eead17315aeeb346722431d89f"
    ),
    readme_document_sha256=(
        "ae8984b5f2197ef4305011c52b691d823dc618339df7335a22a847487103ce64"
    ),
    acquired_twice_byte_identical=True,
    acquisition_timestamp_utc="2026-08-09T00:00:00Z",
    role=(
        "the official JIPNet implementation: the model, the inference script, "
        "the inference configuration and the training-data construction scripts"
    ),
)


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    """One file inside the pinned repository, cited by digest.

    Cited rather than quoted. The digest and the size say which bytes a
    statement in this stage's evidence is about, without this repository holding
    any of them (docs/adr/0083).
    """

    relative_path: str
    sha256: str
    size_bytes: int
    role: str


#: Every upstream file a Stage 10A statement rests on. Each digest was computed
#: from the pinned archive and cross-checked against ``raw.githubusercontent``
#: at the same commit.
JIPNET_PINNED_FILES: tuple[RepositoryFile, ...] = (
    RepositoryFile(
        "README.md",
        "ae8984b5f2197ef4305011c52b691d823dc618339df7335a22a847487103ce64",
        9408,
        "declares the repository the official implementation, lists the Drive "
        "folders, and states that the comparison models are reproductions",
    ),
    RepositoryFile(
        "LICENSE",
        "d039e1af5ef20f591d61ed86cb9670bd028532eead17315aeeb346722431d89f",
        1070,
        "the MIT licence text",
    ),
    RepositoryFile(
        "inference.py",
        "244dc17366273c0c14b3f3ee418a52b89520a7c59cef0cfd8d2c1cc6ace67d19",
        4779,
        "the official JIPNet inference route, from image read to written score",
    ),
    RepositoryFile(
        "inference_AFRNet.py",
        "53bb7d31d51bf6c15e1198ba5a4dadb6cd2845a9eff9cc4b77dc5854481d6dfd",
        7790,
        "the reproduced AFR-Net route: RidgeNet, PFVNet AlignNet, AFRNet, "
        "weighted cosine",
    ),
    RepositoryFile(
        "models/JIPNet.py",
        "2511b0f42debfccdc395ffbcb2080123a5fa5abb31a6ddc55422cc9481d51e8b",
        3130,
        "the model class, whose forward applies the sigmoid to the "
        "classification output",
    ),
    RepositoryFile(
        "ckpts/JIPNet/config.yaml",
        "5c89462bc27514d2a029b58333393a36c6028e2585f4cc945a35e944d73e7837",
        299,
        "the inference configuration shipped with the repository: input_size 160",
    ),
    RepositoryFile(
        "make_data/generate_patch.py",
        "6c2c5c762524aa9f4ded728d579466e0b89e61a39d31f0d905b78279121afef3",
        9158,
        "the training-data construction script, and the only place in the "
        "repository where a full fingerprint becomes a patch",
    ),
    RepositoryFile(
        "requirements.txt",
        "1175cf980968c55cc88f2c984846afeaf43a9de6daa8b0495f6ed1ad57f05703",
        164,
        "the pinned dependency set",
    ),
)


def jipnet_source_manifest() -> Mapping[str, Any]:
    """The repository, pinned, with the files this stage's statements cite."""
    repository = JIPNET_REPOSITORY
    return {
        "schema": "stage_10a_jipnet_source_manifest_v1",
        "candidate": frozen.JIPNET.candidate_id,
        "gate": frozen.PreflightGate.IDENTITY.value,
        "paper": frozen.JIPNET.paper_locator,
        "paper_preprint": frozen.JIPNET.paper_arxiv_locator,
        "authors": list(frozen.JIPNET.authors),
        "repository_id": repository.repository_id,
        "upstream_name": repository.upstream_name,
        "upstream_locator": repository.html_locator,
        "role": repository.role,
        "default_branch_observed_at_acquisition": repository.default_branch_observed,
        "branch_names_are_not_identities": True,
        "upstream_commit": repository.commit,
        "upstream_commit_date_utc": repository.commit_date_utc,
        "source_archive_locator": repository.archive_locator,
        "source_archive_filename": repository.archive_filename,
        "source_archive_sha256": repository.archive_sha256,
        "source_archive_size_bytes": repository.archive_size_bytes,
        "acquired_twice_byte_identical": repository.acquired_twice_byte_identical,
        "license_spdx": repository.license_spdx,
        "license_document_sha256": repository.license_document_sha256,
        "readme_document_sha256": repository.readme_document_sha256,
        "acquisition_timestamp_utc": repository.acquisition_timestamp_utc,
        "cited_files": [
            {
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "role": item.role,
            }
            for item in JIPNET_PINNED_FILES
        ],
        "official_checkpoint_locator": (
            "https://drive.google.com/drive/folders/"
            "1q9yopPjOFt9c9odCT1o4nheLvwrJaCu7"
        ),
        "official_checkpoint_locator_is_an_identity": False,
        "notes": [
            "The archive was acquired twice from the same locator and came back "
            "byte-identical, which is what makes a generated tarball usable as "
            "an identity here.",
            "The repository ships no weights. Every ckpts/<model>/download.md "
            "says to fetch the file from the link on the README page, and that "
            "link is a Google Drive folder — a place, not bytes. No Stage 10A "
            "conclusion rests on any checkpoint, because the artifact gate was "
            "never reached.",
        ],
    }


# ------------------------------------------------------------ the origin claims


@dataclass(frozen=True, slots=True)
class OriginClaim:
    """One candidate's implementation origin, with what supports it.

    ``supporting_locators`` is required for the two admissible origins and must
    be empty for the rest: a claim of an author-official implementation with
    nothing behind it is exactly the claim this stage exists to refuse.
    """

    candidate_id: str
    origin: frozen.ImplementationOrigin
    subject: str
    supporting_locators: tuple[str, ...]
    upstream_self_description: str
    basis: str

    def __post_init__(self) -> None:
        validate_id(self.candidate_id)
        if self.origin.is_admissible_for_algorithm_4 and not self.supporting_locators:
            raise CandidateAuthenticityError(
                f"{self.candidate_id}: {self.origin.value} is claimed with no "
                "locator behind it. An origin is established by pointing at "
                "what the authors published, not by asserting it"
            )
        if (
            not self.origin.is_admissible_for_algorithm_4
            and self.supporting_locators
        ):
            raise CandidateAuthenticityError(
                f"{self.candidate_id}: {self.origin.value} carries supporting "
                "locators, which would read as partial credit. A non-official "
                "origin is refused whatever supports it"
            )


ORIGIN_CLAIMS: tuple[OriginClaim, ...] = (
    OriginClaim(
        candidate_id=frozen.AFRNET.candidate_id,
        origin=frozen.ImplementationOrigin.UNKNOWN,
        subject=(
            "no executable artifact attributable to the AFR-Net authors was "
            "located"
        ),
        supporting_locators=(),
        upstream_self_description=(
            "The paper describes the architecture and the realignment strategy "
            "and makes no statement about code availability."
        ),
        basis=(
            "Ten locations were searched and none yielded an author-supplied "
            "implementation or checkpoint. UNKNOWN rather than "
            "PAPER_RECONSTRUCTION, because Stage 10A reconstructed nothing: "
            "there is no fpbench AFR-Net to classify."
        ),
    ),
    OriginClaim(
        candidate_id=frozen.JIPNET.candidate_id,
        origin=frozen.ImplementationOrigin.AUTHOR_OFFICIAL_IMPLEMENTATION,
        subject=(
            "XiongjunGuan/JIPNet at commit 40d8445c, the repository the paper "
            "names as its code"
        ),
        supporting_locators=(
            "https://arxiv.org/abs/2405.03959 abstract: "
            "'Code is available at: https://github.com/XiongjunGuan/JIPNet.'",
            "https://github.com/XiongjunGuan/JIPNet README: "
            "'This repo is the official implementation of'",
        ),
        upstream_self_description=(
            "The README states the repository is the official implementation of "
            "the TIFS 2025 paper, and the paper's abstract names the same "
            "repository."
        ),
        basis=(
            "The paper and the repository name each other, the author list "
            "matches, and the repository carries the authors' own copyright "
            "headers. The claim is about JIPNet only: the same repository's "
            "PFVNet, AFRNet, DesNet, DeepPrint and A-KAZE routes are described "
            "by their own README as reproductions."
        ),
    ),
)


def origin_claim(candidate_id: str) -> OriginClaim:
    for item in ORIGIN_CLAIMS:
        if item.candidate_id == candidate_id:
            return item
    raise CandidateAuthenticityError(f"no origin claim for {candidate_id!r}")


def authenticity_report(candidate_id: str) -> Mapping[str, Any]:
    """One candidate's origin classification, and what it does and does not cover."""
    item = frozen.candidate(candidate_id)
    claim = origin_claim(candidate_id)
    return {
        "schema": "stage_10a_authenticity_report_v1",
        "candidate": item.candidate_id,
        "gate": frozen.PreflightGate.IDENTITY.value,
        "display_name": item.display_name,
        "implementation_origin": claim.origin.value,
        "origin_is_admissible_for_algorithm_4": (
            claim.origin.is_admissible_for_algorithm_4
        ),
        "accepted_origins": [origin.value for origin in frozen.ACCEPTED_ORIGINS],
        "subject": claim.subject,
        "supporting_locators": list(claim.supporting_locators),
        "upstream_self_description": claim.upstream_self_description,
        "basis": claim.basis,
        "declared_non_candidates": [
            {"identity": name, "description": description}
            for name, description in frozen.DECLARED_NON_CANDIDATES
        ],
        "notes": [
            "A THIRD_PARTY_REIMPLEMENTATION is never published under the name of "
            "the algorithm it reproduces, and an ADJUSTED one is not published "
            "under that name even with a qualifier attached to the run "
            "(docs/adr/0090).",
        ],
    }


# --------------------------------------------------------------- the input domain


@dataclass(frozen=True, slots=True)
class DeclaredModelInput:
    """What the model's own code and configuration say it is handed."""

    geometry_pixels: tuple[int, int] | None
    channels: int
    dtype: str
    value_range: str
    normalization: str
    normalization_locator: str
    declared_ppi: int | None
    ppi_statement: str
    geometry_locators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InputDomainObservation:
    """One observed fact about how a candidate obtains its input."""

    observation_id: str
    statement: str
    locator: str
    is_inference_time: bool

    def __post_init__(self) -> None:
        validate_id(self.observation_id)


@dataclass(frozen=True, slots=True)
class InputDomainContract:
    """Whether ``canonical_500`` reaches a candidate's declared input.

    ``resolution`` is the gate's whole answer. Everything else exists so that a
    reader can check it: what the model declares it takes, what upstream does at
    inference time, and what upstream does elsewhere and that Stage 10A refuses
    to promote into an inference route (docs/adr/0091).
    """

    candidate_id: str
    declared_input: DeclaredModelInput
    resolution: frozen.InputDomainResolution
    transformation_authority: str | None
    observations: tuple[InputDomainObservation, ...]
    refused_constructions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.candidate_id)
        if self.resolution.admits_candidate and not self.transformation_authority:
            raise InputDomainError(
                f"{self.candidate_id}: {self.resolution.value} without a named "
                "authority. A transformation nobody upstream defines is a "
                "transformation fpbench chose (docs/adr/0092)"
            )
        if (
            self.resolution is frozen.InputDomainResolution.NOT_REACHED
            and self.observations
        ):
            raise InputDomainError(
                f"{self.candidate_id}: a gate that was never reached publishes "
                "no observations of its own"
            )


_JIPNET_BLOB = (
    "https://github.com/XiongjunGuan/JIPNet/blob/"
    "40d8445c5b3afa55b409ae3221377e54e3ace53f/"
)

INPUT_DOMAIN_CONTRACTS: tuple[InputDomainContract, ...] = (
    InputDomainContract(
        candidate_id=frozen.AFRNET.candidate_id,
        declared_input=DeclaredModelInput(
            geometry_pixels=None,
            channels=0,
            dtype="",
            value_range="",
            normalization="",
            normalization_locator="",
            declared_ppi=None,
            ppi_statement=(
                "Not examined. The identity gate stopped this candidate, so no "
                "input contract was derived for it."
            ),
            geometry_locators=(),
        ),
        resolution=frozen.InputDomainResolution.NOT_REACHED,
        transformation_authority=None,
        observations=(),
        notes=(
            "There is no author-supplied AFR-Net to declare an input, so there "
            "is nothing here to be compatible or incompatible with. The paper's "
            "own statement that its network takes 3x224x224 is recorded in the "
            "source-discovery document as a fact about the paper, not as a "
            "model input contract.",
        ),
    ),
    InputDomainContract(
        candidate_id=frozen.JIPNET.candidate_id,
        declared_input=DeclaredModelInput(
            geometry_pixels=(160, 160),
            channels=1,
            dtype="float32",
            value_range="[0, 1]",
            normalization="(255.0 - pixel) / 255.0, i.e. inverted and scaled",
            normalization_locator=f"{_JIPNET_BLOB}inference.py",
            declared_ppi=None,
            ppi_statement=(
                "Neither the repository nor the paper declares a pixels-per-inch "
                "assumption, and neither declares that one is unnecessary. The "
                "evaluation datasets do not share a resolution: NIST SD14 and "
                "FVC2002 DB1_A are 500 ppi while FVC2004 DB2_A and FVC2006 DB2_A "
                "are 569 ppi, and no resampling to a common scale appears "
                "anywhere in the repository."
            ),
            geometry_locators=(
                f"{_JIPNET_BLOB}ckpts/JIPNet/config.yaml (model_cfg.input_size: 160)",
                f"{_JIPNET_BLOB}inference.py (patch_size = 160)",
                f"{_JIPNET_BLOB}examples/data (all eight shipped images are "
                "160x160 8-bit grayscale PNG)",
                "arXiv:2405.03959v4 Fig. 3 caption: 'Paired fingerprint patches "
                "with the same shape are input, specifically 160x160, 120x120, "
                "or 96x96 in this paper.'",
            ),
        ),
        resolution=frozen.InputDomainResolution.FPBENCH_CONSTRUCTION_REQUIRED,
        transformation_authority=None,
        observations=(
            InputDomainObservation(
                observation_id="inference_reads_the_pair_directly",
                statement=(
                    "The official inference script reads two PNG files with "
                    "cv2.imread, inverts and scales them, and hands them to the "
                    "model. It performs no crop, no resize and no geometric "
                    "operation of any kind, and it does not inspect the image "
                    "size."
                ),
                locator=f"{_JIPNET_BLOB}inference.py",
                is_inference_time=True,
            ),
            InputDomainObservation(
                observation_id="no_resize_exists_in_the_repository",
                statement=(
                    "cv2.resize appears nowhere in the repository. The only "
                    "torch interpolations are inside the reproduced DeepPrint "
                    "and RidgeNet models, neither of which is part of the JIPNet "
                    "route."
                ),
                locator=f"{_JIPNET_BLOB}",
                is_inference_time=True,
            ),
            InputDomainObservation(
                observation_id="the_only_crop_is_training_side",
                statement=(
                    "The single function that turns a full fingerprint into a "
                    "patch is cut_patch, and it lives in the training-data "
                    "construction script and in the training data loader. "
                    "Neither is imported by any inference script."
                ),
                locator=f"{_JIPNET_BLOB}make_data/generate_patch.py",
                is_inference_time=False,
            ),
            InputDomainObservation(
                observation_id="the_crop_is_a_property_of_a_pair",
                statement=(
                    "generate_patch.py samples the patch centre from the common "
                    "mask of two already-aligned impressions of the same finger, "
                    "and then samples a second centre on a ring around it. Which "
                    "160x160 window a fingerprint yields therefore depends on "
                    "which other fingerprint it is being compared with, and on "
                    "the state of a pseudo-random generator. A benchmark input "
                    "cannot be a function of the gallery image it will be "
                    "compared to."
                ),
                locator=f"{_JIPNET_BLOB}make_data/generate_patch.py",
                is_inference_time=False,
            ),
            InputDomainObservation(
                observation_id="the_crop_is_randomly_rotated",
                statement=(
                    "Each patch is cut after a rotation drawn uniformly from "
                    "[-180, 180] degrees. The paper states the same: full "
                    "fingerprints are cropped 'with a random relative rotation "
                    "from [-180, 180]'."
                ),
                locator="arXiv:2405.03959v4 section IV-A",
                is_inference_time=False,
            ),
            InputDomainObservation(
                observation_id="the_construction_chain_cannot_run",
                statement=(
                    "The construction chain begins with affine_pairs.py, which "
                    "imports fptools.fp_verifinger. That module is not in the "
                    "repository, and the README states the script will not run "
                    "because of licensing restrictions and that its source "
                    "cannot be released."
                ),
                locator=f"{_JIPNET_BLOB}make_data/affine_pairs.py",
                is_inference_time=False,
            ),
            InputDomainObservation(
                observation_id="the_paper_states_two_different_patch_sets",
                statement=(
                    "Section III describes the input as 160x160, 120x120 or "
                    "96x96; section IV-A describes the constructed evaluation "
                    "patches as 160x160, 128x128 and 96x96. The middle size "
                    "differs between the two statements. Only 160x160 is "
                    "reproduced by the released configuration."
                ),
                locator="arXiv:2405.03959v4 sections III and IV-A",
                is_inference_time=False,
            ),
        ),
        refused_constructions=(
            "centre-cropping a 160x160 window because it looks reasonable",
            "resizing a whole fingerprint to 160x160",
            "cropping around an estimated core or singular point",
            "choosing the highest-quality 160x160 region",
            "generating several patches and taking the maximum of their scores",
            "cropping plain and rolled impressions under different rules",
            "using SD300 to find out which crop works best",
            "adopting the paper's VeriFinger alignment as an inference step",
        ),
        notes=(
            "The model would accept a differently-shaped tensor without "
            "complaining. That is not the question the gate asks. The question "
            "is whether an upstream authority defines how a full 500 ppi "
            "fingerprint becomes the input this model was released for, and no "
            "such definition exists (docs/adr/0091).",
            "The VeriFinger alignment in the paper belongs to partial-pair "
            "simulation for training and evaluation-set construction. Promoting "
            "it to an inference step would produce VeriFinger plus an fpbench "
            "crop policy plus JIPNet, which is a new algorithm and not JIPNet "
            "(docs/adr/0092).",
        ),
    ),
)


def input_domain_contract(candidate_id: str) -> InputDomainContract:
    for item in INPUT_DOMAIN_CONTRACTS:
        if item.candidate_id == candidate_id:
            return item
    raise InputDomainError(f"no input-domain contract for {candidate_id!r}")


def input_domain_contract_document(candidate_id: str) -> Mapping[str, Any]:
    """One candidate's input-domain contract, as published."""
    contract = input_domain_contract(candidate_id)
    declared = contract.declared_input
    reached = contract.resolution is not frozen.InputDomainResolution.NOT_REACHED
    return {
        "schema": "stage_10a_input_domain_contract_v1",
        "candidate": contract.candidate_id,
        "gate": frozen.PreflightGate.INPUT_DOMAIN.value,
        "gate_status": (
            frozen.GateStatus.NOT_REACHED.value if not reached else None
        ),
        "benchmark_input_profile": frozen.BENCHMARK_INPUT_PROFILE,
        "benchmark_input_ppi": frozen.BENCHMARK_INPUT_PPI,
        "benchmark_input_pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        "declared_model_input": {
            "geometry_pixels": (
                list(declared.geometry_pixels) if declared.geometry_pixels else None
            ),
            "channels": declared.channels or None,
            "dtype": declared.dtype or None,
            "value_range": declared.value_range or None,
            "normalization": declared.normalization or None,
            "normalization_locator": declared.normalization_locator or None,
            "declared_ppi": declared.declared_ppi,
            "ppi_statement": declared.ppi_statement,
            "geometry_locators": list(declared.geometry_locators),
        },
        "resolution": contract.resolution.value,
        "resolution_admits_candidate": contract.resolution.admits_candidate,
        "transformation_authority": contract.transformation_authority,
        "resize_is_assumed_physically_neutral": False,
        "observations": [
            {
                "observation_id": observation.observation_id,
                "statement": observation.statement,
                "locator": observation.locator,
                "is_inference_time": observation.is_inference_time,
            }
            for observation in contract.observations
        ],
        "constructions_fpbench_refuses_to_invent": list(
            contract.refused_constructions
        ),
        "notes": list(contract.notes),
    }


# --------------------------------------------------------- gates never reached


@dataclass(frozen=True, slots=True)
class RequiredArtifactSketch:
    """What a candidate's artifact gate *would* have to close over.

    A sketch, not a manifest: no digest, no size and no local placement, because
    the artifact gate was not reached for either candidate and nothing was
    downloaded (spec section 18). It exists so that the cost of the gate nobody
    ran is visible rather than implied.
    """

    candidate_id: str
    artifact_role: str
    component_kind: ThirdPartyComponentKind
    locator: str
    locator_kind: str
    required_by: str
    transitive_from: str | None = None


ARTIFACT_SKETCHES: tuple[RequiredArtifactSketch, ...] = (
    RequiredArtifactSketch(
        candidate_id=frozen.JIPNET.candidate_id,
        artifact_role="JIPNet inference checkpoint, ckpts/JIPNet/best.pth",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        locator=(
            "https://drive.google.com/drive/folders/"
            "1q9yopPjOFt9c9odCT1o4nheLvwrJaCu7"
        ),
        locator_kind="google_drive_folder",
        required_by="the JIPNet route",
    ),
    RequiredArtifactSketch(
        candidate_id=frozen.JIPNET.candidate_id,
        artifact_role="the shipped inference configuration, ckpts/JIPNet/config.yaml",
        component_kind=ThirdPartyComponentKind.OTHER_ARTIFACT,
        locator=f"{_JIPNET_BLOB}ckpts/JIPNet/config.yaml",
        locator_kind="in_source_tree",
        required_by="constructing the model class the checkpoint fills",
    ),
    RequiredArtifactSketch(
        candidate_id=frozen.JIPNET.candidate_id,
        artifact_role="encoder_bath.pth, the pretrained encoder",
        component_kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        locator=(
            "https://drive.google.com/drive/folders/"
            "1q9yopPjOFt9c9odCT1o4nheLvwrJaCu7"
        ),
        locator_kind="google_drive_folder",
        required_by=(
            "training only, on the reading of the released files: the README "
            "presents it under 'Train', the shipped configs/JIPNet.yaml leaves "
            "pretrain_cfg.encoder_pth empty, and inference.py constructs JIPNet "
            "without encoder_pretrain_pth. Recorded as an open question rather "
            "than as a finding, because the artifact gate was not reached and "
            "the question is settled by loading the checkpoint, not by reading "
            "about it (spec section 16)."
        ),
        transitive_from="ckpts/JIPNet/best.pth",
    ),
)


def artifact_sketches(candidate_id: str) -> tuple[RequiredArtifactSketch, ...]:
    return tuple(
        item for item in ARTIFACT_SKETCHES if item.candidate_id == candidate_id
    )


@dataclass(frozen=True, slots=True)
class RouteObservation:
    """One fact about a candidate's inference route, recorded without auditing it."""

    observation_id: str
    statement: str
    locator: str

    def __post_init__(self) -> None:
        validate_id(self.observation_id)


ROUTE_OBSERVATIONS: tuple[tuple[str, RouteObservation], ...] = (
    (
        frozen.JIPNET.candidate_id,
        RouteObservation(
            "single_forward_pass",
            "The route is one forward pass over a pair: both images are "
            "concatenated on the batch dimension, encoded by shared weights, "
            "split again, and fused by alternating self and cross attention. "
            "There is no separate enrolment step and no per-image template.",
            f"{_JIPNET_BLOB}models/JIPNet.py",
        ),
    ),
    (
        frozen.JIPNET.candidate_id,
        RouteObservation(
            "checkpoint_load_is_strict",
            "inference.py calls load_state_dict with its default strict=True "
            "and no key filtering, so a mismatch between the released "
            "checkpoint and the constructed class would raise rather than pass "
            "quietly. Whether it does raise was not tested: nothing was "
            "downloaded.",
            f"{_JIPNET_BLOB}inference.py",
        ),
    ),
)


def route_observations(candidate_id: str) -> tuple[RouteObservation, ...]:
    return tuple(item for cid, item in ROUTE_OBSERVATIONS if cid == candidate_id)


@dataclass(frozen=True, slots=True)
class ScoreObservation:
    """One fact about how a candidate produces a number, recorded without auditing it."""

    observation_id: str
    statement: str
    locator: str

    def __post_init__(self) -> None:
        validate_id(self.observation_id)


SCORE_OBSERVATIONS: tuple[tuple[str, ScoreObservation], ...] = (
    (
        frozen.JIPNET.candidate_id,
        ScoreObservation(
            "sigmoid_inside_the_model",
            "The model's forward applies torch.sigmoid to the classification "
            "output, so what leaves the network is already in [0, 1] and higher "
            "means more similar.",
            f"{_JIPNET_BLOB}models/JIPNet.py",
        ),
    ),
    (
        frozen.JIPNET.candidate_id,
        ScoreObservation(
            "inference_writes_it_unmodified",
            "inference.py squeezes the classification output and writes it "
            "under '1-2 matching probability' with two decimal places. Nothing "
            "between the model and the file scales, clamps, calibrates or "
            "thresholds it; the two decimals are the file format, not the "
            "value.",
            f"{_JIPNET_BLOB}inference.py",
        ),
    ),
    (
        frozen.JIPNET.candidate_id,
        ScoreObservation(
            "the_pair_is_structurally_ordered",
            "The classification head consumes the two branches concatenated on "
            "the channel dimension, in a fixed order. Nothing in the "
            "architecture symmetrises them, and no upstream statement says "
            "whether score(A,B) equals score(B,A). Establishing that would "
            "require running the released checkpoint both ways, which the "
            "artifact gate would have to be reached to do.",
            f"{_JIPNET_BLOB}models/ViT/ViT_reg_cla.py",
        ),
    ),
    (
        frozen.JIPNET.candidate_id,
        ScoreObservation(
            "pose_is_a_second_output_not_a_score",
            "The route returns two things. align_pred is a relative pose, "
            "written to the same file as a separate line, and no upstream code "
            "path lets it modify the classification output.",
            f"{_JIPNET_BLOB}inference.py",
        ),
    ),
)


def score_observations(candidate_id: str) -> tuple[ScoreObservation, ...]:
    return tuple(item for cid, item in SCORE_OBSERVATIONS if cid == candidate_id)


class DatasetRole(str, Enum):
    """What one dataset was to a released checkpoint. Kept separate on purpose."""

    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    CHECKPOINT_SELECTION = "CHECKPOINT_SELECTION"
    FINE_TUNING = "FINE_TUNING"
    PRETRAINING = "PRETRAINING"
    EVALUATION = "EVALUATION"


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    """One dataset, in one role, as the paper states it."""

    name: str
    role: DatasetRole
    detail: str


@dataclass(frozen=True, slots=True)
class TrainingProvenanceObservation:
    """What a candidate's released artifacts were trained on, as observed.

    Recorded during the identity gate, because reading the paper is how the
    identity gate is answered. It is not a Gate 6 conclusion for either
    candidate: neither reached Gate 6.
    """

    candidate_id: str
    datasets: tuple[TrainingDataset, ...]
    sd300_overlap_status: frozen.SD300OverlapStatus
    sd300_basis: str
    future_development_dataset_exclusions: tuple[str, ...] = ()
    discrepancies: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


TRAINING_PROVENANCE: tuple[TrainingProvenanceObservation, ...] = (
    TrainingProvenanceObservation(
        candidate_id=frozen.AFRNET.candidate_id,
        datasets=(
            TrainingDataset("MSP", DatasetRole.TRAINING, "37,411 fingers, 447,988 images"),
            TrainingDataset("NIST SD 302", DatasetRole.TRAINING, "1,600 fingers, 20,008 images"),
            TrainingDataset("MSU Self-Collection", DatasetRole.TRAINING, "4,582 fingers, 57,813 images"),
            TrainingDataset("PrintsGAN", DatasetRole.TRAINING, "34,985 fingers, 524,775 synthetic images"),
            TrainingDataset("SpoofGAN", DatasetRole.TRAINING, "10,000 fingers, 150,000 synthetic images"),
            TrainingDataset(
                "MSU Finger Photo and Slap Database",
                DatasetRole.TRAINING,
                "1,243 fingers, 5,220 images",
            ),
            TrainingDataset(
                "IIT Bombay Touchless and Touch-based Database",
                DatasetRole.TRAINING,
                "200 fingers, 1,600 images",
            ),
            TrainingDataset("ManTech Phase 2", DatasetRole.TRAINING, "4,535 fingers, 64,061 images"),
            TrainingDataset("Synthetic Latent Prints", DatasetRole.TRAINING, "2,000 fingers, 16,000 images"),
            TrainingDataset("NIST SD 4", DatasetRole.TRAINING, "2,000 fingers, 4,000 images"),
            TrainingDataset(
                "MSU Finger Photo and Slap Database",
                DatasetRole.VALIDATION,
                "110 fingers, 200 images",
            ),
            TrainingDataset("MSP Latent", DatasetRole.VALIDATION, "524 fingers, 1,086 images"),
            TrainingDataset("NIST SD 302", DatasetRole.VALIDATION, "200 fingers, 2,528 images"),
        ),
        sd300_overlap_status=frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND,
        sd300_basis=(
            "NIST SD300 appears nowhere in the paper. NIST SD 302 does, in both "
            "the training and the validation split, and NIST SD 4 and NIST SD 14 "
            "appear as well. SD 302 is a different NIST special database and is "
            "not this project's evaluation cohort. No statement was found in "
            "either direction about SD300, so the status is that nothing was "
            "found and not that it is absent."
        ),
        notes=(
            "Recorded from the paper during the identity search. This is not a "
            "Gate 6 conclusion: the training-provenance gate was never reached "
            "for this candidate.",
        ),
    ),
    TrainingProvenanceObservation(
        candidate_id=frozen.JIPNET.candidate_id,
        datasets=(
            TrainingDataset(
                "NIST SD14",
                DatasetRole.TRAINING,
                "27,000 fingers, 2 impressions each; in Hybrid DB, split 95% "
                "train / 5% test with identities isolated between the halves",
            ),
            TrainingDataset(
                "FVC2004 DB1_A",
                DatasetRole.TRAINING,
                "100 fingers, 8 impressions; in Hybrid DB",
            ),
            TrainingDataset(
                "FVC2004 DB2_A",
                DatasetRole.TRAINING,
                "100 fingers, 8 impressions; in Hybrid DB",
            ),
            TrainingDataset(
                "FVC2006 DB2_A",
                DatasetRole.TRAINING,
                "140 fingers, 12 impressions; in Hybrid DB",
            ),
            TrainingDataset(
                "Hybrid DB_B",
                DatasetRole.EVALUATION,
                "the 5% held-out split of the same merged corpus, 22,672 pairs",
            ),
            TrainingDataset(
                "THU Small",
                DatasetRole.EVALUATION,
                "an in-house capacitive dataset, 100 fingers, test only",
            ),
            TrainingDataset(
                "FVC2002 DB1_A", DatasetRole.EVALUATION, "100 fingers, test only"
            ),
            TrainingDataset(
                "FVC2002 DB3_A", DatasetRole.EVALUATION, "100 fingers, test only"
            ),
        ),
        sd300_overlap_status=frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND,
        sd300_basis=(
            "No NIST special database numbered 300 appears anywhere in the "
            "paper or the repository. NIST SD14 does, as a training corpus. No "
            "statement was found in either direction about SD300."
        ),
        future_development_dataset_exclusions=(
            "NIST SD14",
            "FVC2004 DB1_A",
            "FVC2004 DB2_A",
            "FVC2006 DB2_A",
        ),
        discrepancies=(
            "The abstract names FVC2006 DB1_A among the evaluation datasets; "
            "Table III and Figure 6(g) name FVC2006 DB2_A. Recorded because a "
            "future exclusion list has to name the right database.",
        ),
        notes=(
            "Recorded from the paper during the identity search. This is not a "
            "Gate 6 conclusion: the training-provenance gate was never reached "
            "for this candidate.",
            "The exclusion list matters later rather than now. Should JIPNet "
            "ever be admitted, these four datasets cannot serve as clean "
            "development data for calibrating it without a further overlap "
            "analysis, because the released checkpoint was fitted on 95% of "
            "them (docs/adr/0079).",
        ),
    ),
)


def training_provenance(candidate_id: str) -> TrainingProvenanceObservation:
    for item in TRAINING_PROVENANCE:
        if item.candidate_id == candidate_id:
            return item
    raise CandidateAuthenticityError(f"no training provenance for {candidate_id!r}")


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    """One runtime red flag, observed by reading and not by executing."""

    observation_id: str
    statement: str
    locator: str

    def __post_init__(self) -> None:
        validate_id(self.observation_id)


RUNTIME_OBSERVATIONS: tuple[tuple[str, RuntimeObservation], ...] = (
    (
        frozen.JIPNET.candidate_id,
        RuntimeObservation(
            "pinned_dependency_set",
            "requirements.txt pins torch 2.1.2, timm 0.9.12, einops 0.8.1, "
            "opencv-python 4.8.1.78, opencv-contrib-python 4.10.0.84, PyYAML "
            "6.0.2, scipy 1.15.2, numpy 2.2.5, tqdm 4.66.1 and a line reading "
            "'skimage==0.0', which is a placeholder package and not "
            "scikit-image. numpy 2.x and torch 2.1.2 are not compatible, so the "
            "pinned set is not installable as written and a resolved "
            "environment would be this project's choice rather than upstream's.",
            f"{_JIPNET_BLOB}requirements.txt",
        ),
    ),
    (
        frozen.JIPNET.candidate_id,
        RuntimeObservation(
            "cpu_viability_is_not_established",
            "inference.py selects a device conditionally but loads the "
            "checkpoint with map_location='cuda:0' unconditionally and wraps "
            "the model in DataParallel over device_ids=[0]. On a host with no "
            "CUDA device the load would raise, so running this route on CPU "
            "would require changing upstream code.",
            f"{_JIPNET_BLOB}inference.py",
        ),
    ),
    (
        frozen.JIPNET.candidate_id,
        RuntimeObservation(
            "no_custom_ops_and_no_network",
            "The route uses no custom CUDA kernel, no compiled extension and no "
            "network access; timm is used only through its standard layers.",
            f"{_JIPNET_BLOB}models",
        ),
    ),
)


def runtime_observations(candidate_id: str) -> tuple[RuntimeObservation, ...]:
    return tuple(item for cid, item in RUNTIME_OBSERVATIONS if cid == candidate_id)


def reconnaissance_fingerprint() -> str:
    """Identify the observations this preflight was decided on.

    A change to any recorded fact changes this digest, and therefore changes the
    preflight fingerprint above it. Re-reading upstream and finding something
    different is a new preflight, not an amendment to this one.
    """
    return stable_hash(
        {
            "schema": "stage_10a_reconnaissance_v1",
            "afrnet_search": [
                (item.location_id, item.locator, item.outcome.value, item.finding)
                for item in AFRNET_SEARCH_LOCATIONS
            ],
            "afrnet_excluded": list(AFRNET_EXCLUDED_EVIDENCE),
            "jipnet_repository": [
                JIPNET_REPOSITORY.commit,
                JIPNET_REPOSITORY.archive_sha256,
                JIPNET_REPOSITORY.archive_size_bytes,
            ],
            "jipnet_files": [
                (item.relative_path, item.sha256, item.size_bytes)
                for item in JIPNET_PINNED_FILES
            ],
            "origins": [
                (item.candidate_id, item.origin.value) for item in ORIGIN_CLAIMS
            ],
            "input_domains": [
                (item.candidate_id, item.resolution.value)
                for item in INPUT_DOMAIN_CONTRACTS
            ],
            "training": [
                (item.candidate_id, item.sd300_overlap_status.value)
                for item in TRAINING_PROVENANCE
            ],
        },
        length=64,
    )
