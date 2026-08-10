"""What was actually readable about the id3 Finger SDK, recorded before anything was decided.

This module is the reconnaissance record. Every value in it is an observation
with a locator, a retrieval outcome and the date it was retrieved. Nothing here
derives a gate result — :mod:`fpbench.experiments.stage10b_preflight` does that,
and it can only read what is here.

Three things shape the record.

**A vendor page is not a package.** Everything below was read from public web
pages and from a public sample repository. None of it is the delivered SDK, and
none of it can stand in for the delivered SDK's own documentation: the version
on a web page is the version of a web page (spec sections 8 and 9).

**A locator that did not resolve is recorded as not resolving.** Five of the
documentation locators this stage was written against answer HTTP 404 today, and
the current reference tree lives under a versioned path beside them. Those
retrievals are published as ``NOT_FOUND`` with the status code, never quietly
replaced by the page that did resolve.

**No credential appears here, in any form.** The activation key format is
recorded as a *shape* the finalization verifier refuses, not as a key; the
licence file is recorded as a file name; no customer identifier, hardware code
or token is recorded at all (docs/adr/0098).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from fpbench.core.id3_preflight_errors import Id3ObservationError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash

__all__ = [
    "OBSERVED_UTC",
    "RetrievalOutcome",
    "PublicObservation",
    "PRODUCT_OBSERVATIONS",
    "PLATFORM_OBSERVATIONS",
    "DOCUMENTATION_OBSERVATIONS",
    "UNRESOLVED_LOCATORS",
    "ACQUISITION_OBSERVATIONS",
    "EVALUATION_TERM_OBSERVATIONS",
    "ROUTE_OBSERVATIONS",
    "EXTRACTION_OBSERVATIONS",
    "MATCHER_OBSERVATIONS",
    "SCORE_OBSERVATIONS",
    "PROVENANCE_OBSERVATIONS",
    "MODEL_OBSERVATIONS",
    "all_observations",
    "observation",
    "observation_rows",
    "UpstreamRepository",
    "SAMPLES_REPOSITORY",
    "RepositoryFile",
    "SAMPLES_PINNED_FILES",
    "PRODUCT_IDENTITY_CLAIM",
    "ProductIdentityClaim",
    "AcquisitionRoute",
    "ACQUISITION_ROUTE",
    "EvaluationTerms",
    "EVALUATION_TERMS",
    "PublishedMatcherOption",
    "PUBLISHED_MATCHER_OPTIONS",
    "PublishedExtractorOption",
    "PUBLISHED_EXTRACTOR_OPTIONS",
    "DOCUMENTED_SCORE_RANGE_MIN",
    "DOCUMENTED_SCORE_RANGE_MAX",
    "DOCUMENTED_SCORE_DIRECTION",
    "REQUIRED_MODEL_NAMES",
    "observations_fingerprint",
]

#: The one date every retrieval below was performed on. One date rather than one
#: per observation because they were performed in a single pass, and a pass is
#: what a re-read would have to repeat.
OBSERVED_UTC = "2026-08-10T00:00:00Z"


class RetrievalOutcome(str, Enum):
    """What one locator returned when it was fetched.

    ``NOT_FOUND`` is separate from ``NOT_READABLE`` and neither is merged into
    "nothing there". A 404 is a statement by the server; a page this project
    could not parse is a statement about this project.
    """

    READ = "READ"
    NOT_FOUND = "NOT_FOUND"
    NOT_READABLE = "NOT_READABLE"
    REDIRECTED_TO_A_VERSIONED_TREE = "REDIRECTED_TO_A_VERSIONED_TREE"


@dataclass(frozen=True, slots=True)
class PublicObservation:
    """One statement about the product, and where it was read.

    ``statement`` is what the source says. It is never what the source implies,
    and never what it would say if the missing page had resolved.
    """

    observation_id: str
    subject: str
    statement: str
    locator: str
    retrieval: RetrievalOutcome
    http_status: int
    observed_utc: str = OBSERVED_UTC

    def __post_init__(self) -> None:
        validate_id(self.observation_id)
        if not self.locator.strip():
            raise Id3ObservationError(
                f"{self.observation_id}: an observation with no locator is an "
                "assertion"
            )
        if not self.statement.strip():
            raise Id3ObservationError(
                f"{self.observation_id}: an observation records what the source "
                "said; a blank statement is an unperformed reading"
            )
        if self.retrieval is RetrievalOutcome.READ and self.http_status != 200:
            raise Id3ObservationError(
                f"{self.observation_id}: a page reported as read answered "
                f"{self.http_status}"
            )
        if self.retrieval is RetrievalOutcome.NOT_FOUND and self.http_status != 404:
            raise Id3ObservationError(
                f"{self.observation_id}: NOT_FOUND is the 404 outcome and this "
                f"answered {self.http_status}"
            )


# --------------------------------------------------------------- the product

_PRODUCT_PAGE = "https://id3technologies.com/software-development-kits/finger-sdk/"
_SDK_INDEX = "https://developer.id3technologies.com/sdks/"
_DOC_ROOT = "https://developer.id3technologies.com/finger-sdk/v4"

PRODUCT_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="product_page_names_the_product",
        subject="the product this stage is about",
        statement=(
            "The vendor publishes a product page headed Finger SDK, describing "
            "fingerprint capture, extraction, matching and liveness detection "
            "across platforms. It is a distinct product page from the vendor's "
            "other fingerprint offerings."
        ),
        locator=_PRODUCT_PAGE,
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="product_page_lists_languages",
        subject="the language bindings the vendor advertises",
        statement=(
            "C, C++, C#, Python, Java, Kotlin, Swift and Dart are listed. Python "
            "is among them, which is the binding fpbench would use."
        ),
        locator=_PRODUCT_PAGE,
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="product_page_slap_sample",
        subject="the sample the product page itself shows",
        statement=(
            "The page's own code sample is a four-finger slap route: "
            "detect_slap(image), extract_roi(image, fingers), "
            "create_template(roi), compare_templates(tmpl, ref). It is a slap "
            "route, and this benchmark holds single already-segmented "
            "impressions."
        ),
        locator=_PRODUCT_PAGE,
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

PLATFORM_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="sdk_index_lists_platforms",
        subject="the platforms the Finger SDK is offered for",
        statement=(
            "Windows (x86, x86-64), Linux (x86-64), macOS 10.9+ including Apple "
            "Silicon, Android 5.0+ and iOS 12.0+. The page adds that available "
            "languages may vary by platform and SDK."
        ),
        locator=_SDK_INDEX,
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)


# ------------------------------------------------------- the documentation tree

DOCUMENTATION_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="documentation_root_is_versioned",
        subject="where the current reference documentation lives",
        statement=(
            "The unversioned Finger SDK documentation path serves a redirect "
            "stub to ./v4/, and the stub's title names a different id3 product. "
            "The tree it redirects to is titled Finger SDK 4.5.0."
        ),
        locator="https://developer.id3technologies.com/finger-sdk/",
        retrieval=RetrievalOutcome.REDIRECTED_TO_A_VERSIONED_TREE,
        http_status=200,
    ),
    PublicObservation(
        observation_id="documentation_declares_one_version",
        subject="the version the readable documentation tree declares",
        statement=(
            "Every page under the versioned tree is titled Finger SDK 4.5.0. "
            "The mixture of 4.3.0 and 4.5.0 pages that the earlier flat layout "
            "carried is not present in the tree that resolves today."
        ),
        locator=f"{_DOC_ROOT}/",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="compare_templates_returns_an_integer_score",
        subject="the 1:1 comparison API and what it returns",
        statement=(
            "FingerMatcher.compareTemplates takes a reference template and a "
            "probe template and returns an integer described as 'Comparison "
            "score, in the range 0 to 65535'. The page directs the reader to "
            "FingerMatcherThreshold to take a match/no-match decision, which "
            "places the threshold outside the score."
        ),
        locator=f"{_DOC_ROOT}/reference/finger/finger_matcher/compare_templates.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="matcher_class_publishes_five_options",
        subject="the matcher options the class reference publishes",
        statement=(
            "FingerMatcher publishes maximumRotation, minexOnly, "
            "minutiaPatchOnly, multiscaleMatch and normalizedScores, and five "
            "comparison methods including compareTemplates and "
            "compareTemplateRecords. No default value is stated for any of the "
            "five options."
        ),
        locator=f"{_DOC_ROOT}/reference/finger/finger_matcher/finger_matcher.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="extractor_class_publishes_three_options",
        subject="the extractor options the class reference publishes",
        statement=(
            "FingerExtractor publishes minutiaDetectorModel, minutiaEncoderModel "
            "and threadCount, with createTemplate and createTemplateRecord. No "
            "finger-embedding model property appears on this class, although the "
            "performance page describes a finger-embedding fusion family."
        ),
        locator=(
            f"{_DOC_ROOT}/reference/finger/finger_extractor/finger_extractor.html"
        ),
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="performance_page_lists_four_fusions",
        subject="the template data families the vendor reports on",
        statement=(
            "Four combinations are reported: MINEX only; MINEX with minutia "
            "embeddings; MINEX with finger embedding; and all three together. "
            "The page also recommends a combination by sensor size — minutiae "
            "alone for interoperability, minutiae with minutia embeddings below "
            "200x200 px at 500 dpi, and all three above it."
        ),
        locator=f"{_DOC_ROOT}/biometric_performance.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="performance_page_names_evaluation_datasets",
        subject="the datasets the vendor evaluates on publicly",
        statement=(
            "FVC2000, FVC2002 and FVC2004 are named as the public benchmarks "
            "behind the reported figures. The page makes no statement about "
            "training data."
        ),
        locator=f"{_DOC_ROOT}/biometric_performance.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

#: The locators this stage was written against that no longer resolve, recorded
#: with the status they returned. Publishing them matters: the design that
#: produced Stage 10B cited these pages, and a reader comparing the two needs to
#: see that the citation was checked rather than repeated (spec section 9).
UNRESOLVED_LOCATORS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="flat_compare_template_records_page_gone",
        subject="the flat-layout page for the record-to-record comparison API",
        statement=(
            "HTTP 404. The equivalent page in the versioned tree resolves, and "
            "the two are not assumed to carry the same text."
        ),
        locator=(
            "https://developer.id3technologies.com/finger-sdk/reference/finger/"
            "finger_matcher/compare_template_records.html"
        ),
        retrieval=RetrievalOutcome.NOT_FOUND,
        http_status=404,
    ),
    PublicObservation(
        observation_id="flat_license_activate_buffer_page_gone",
        subject="the flat-layout page for buffer activation",
        statement=(
            "HTTP 404. Activation is nonetheless documented in the vendor's own "
            "public samples, which is where the activation observations below "
            "come from."
        ),
        locator=(
            "https://developer.id3technologies.com/finger-sdk/reference/finger/"
            "finger_license/activate_buffer.html"
        ),
        retrieval=RetrievalOutcome.NOT_FOUND,
        http_status=404,
    ),
    PublicObservation(
        observation_id="flat_finger_capture_api_page_gone",
        subject="the flat-layout capture API page",
        statement="HTTP 404.",
        locator=(
            "https://developer.id3technologies.com/finger-sdk/reference/"
            "finger_capture/api.html"
        ),
        retrieval=RetrievalOutcome.NOT_FOUND,
        http_status=404,
    ),
    PublicObservation(
        observation_id="flat_biometric_performance_page_gone",
        subject="the flat-layout performance page",
        statement="HTTP 404.",
        locator=(
            "https://developer.id3technologies.com/finger-sdk/"
            "biometric_performance.html"
        ),
        retrieval=RetrievalOutcome.NOT_FOUND,
        http_status=404,
    ),
    PublicObservation(
        observation_id="flat_device_manager_page_gone",
        subject="the flat-layout device manager page",
        statement=(
            "HTTP 404. The resolution and matcher-option statements this stage "
            "needed are read from the class reference pages in the versioned "
            "tree instead, and are attributed there."
        ),
        locator=(
            "https://developer.id3technologies.com/finger-sdk/reference/devices/"
            "device_manager/device_manager.html"
        ),
        retrieval=RetrievalOutcome.NOT_FOUND,
        http_status=404,
    ),
    PublicObservation(
        observation_id="second_portal_hostname_gone",
        subject="a second documentation hostname that search indexes still list",
        statement=(
            "developers.id3technologies.com redirects to the singular hostname, "
            "and its indexed fingerprint-sdk pages answer 404. Nothing in this "
            "stage rests on them."
        ),
        locator=(
            "https://developers.id3technologies.com/fingerprint-sdk/about/"
            "release_notes.html"
        ),
        retrieval=RetrievalOutcome.NOT_FOUND,
        http_status=404,
    ),
)


# ------------------------------------------------------- the official samples


@dataclass(frozen=True, slots=True)
class UpstreamRepository:
    """A public repository pinned by commit, not by branch.

    A branch is a moving target and therefore not an identity. Everything this
    stage quotes from the samples is quoted at the commit below.
    """

    upstream_name: str
    html_locator: str
    commit: str
    commit_date_utc: str
    release_label: str

    def __post_init__(self) -> None:
        commit = str(self.commit).strip().lower()
        if len(commit) != 40 or set(commit) - set("0123456789abcdef"):
            raise Id3ObservationError(
                f"{self.upstream_name}: a repository is pinned by a full commit "
                "SHA, and a branch name is not an identity"
            )
        object.__setattr__(self, "commit", commit)


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    """One upstream file this stage quotes, cited by digest and size."""

    relative_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise Id3ObservationError(
                f"{self.relative_path}: a cited file is identified by a SHA-256 "
                "digest"
            )
        object.__setattr__(self, "sha256", digest)
        if int(self.size_bytes) <= 0:
            raise Id3ObservationError(f"{self.relative_path}: an empty file cites nothing")


#: The vendor's own sample repository, under the vendor's own GitHub
#: organisation. It is not the SDK and this stage never treats it as the SDK: it
#: documents a route, and the SDK it documents arrives only on request.
SAMPLES_REPOSITORY = UpstreamRepository(
    upstream_name="id3Technologies/finger-sdk-samples",
    html_locator="https://github.com/id3Technologies/finger-sdk-samples",
    commit="75d02adc5adef73009a85cefd48231fb7803ac48",
    commit_date_utc="2026-01-27T15:09:41Z",
    release_label="Release 4.5.0.0",
)

#: Every sample file this stage quotes, with the digest and size computed from
#: the bytes served at the pinned commit. No byte of any of them is stored in
#: this repository (docs/adr/0083).
SAMPLES_PINNED_FILES: tuple[RepositoryFile, ...] = (
    RepositoryFile(
        relative_path="README.md",
        sha256="79f058e4c4eb62d178f5d8957c77f920cde554b8b15ae17817f6501c7fcfb071",
        size_bytes=5943,
    ),
    RepositoryFile(
        relative_path="CHANGELOG.md",
        sha256="7d84801c27fb37d3e3ca56f3c5bbc158ba973ccdc4b0ebeee9901676c499c3f0",
        size_bytes=1275,
    ),
    RepositoryFile(
        relative_path="python/RecognitionCLI.py",
        sha256="051b2b55a2b31f1941d6d970a3858f0ae1a6420e3789e7d9020df0bee3d61bbf",
        size_bytes=4418,
    ),
    RepositoryFile(
        relative_path="python/README.md",
        sha256="ad7757d32fe5014becf477dab187572a0e431a0d85500de68c036ede1d65b5b7",
        size_bytes=1229,
    ),
)

_SAMPLES_AT = (
    f"{SAMPLES_REPOSITORY.html_locator}/blob/{SAMPLES_REPOSITORY.commit}"
)


# --------------------------------------------------------------- the identity


@dataclass(frozen=True, slots=True)
class ProductIdentityClaim:
    """Which product this stage is about, and what supports the claim."""

    product_name: str
    vendor: str
    declared_sdk_version_public: str
    supporting_locators: tuple[str, ...]
    distinguished_from: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.supporting_locators:
            raise Id3ObservationError(
                "a product identity is established by pointing at what the "
                "vendor publishes, not by naming the vendor"
            )


PRODUCT_IDENTITY_CLAIM = ProductIdentityClaim(
    product_name="id3 Finger SDK",
    vendor="id3 Technologies",
    declared_sdk_version_public="4.5.0",
    supporting_locators=(
        f"{_PRODUCT_PAGE} — the vendor's Finger SDK product page",
        f"{_SDK_INDEX} — the vendor's SDK index, listing Finger SDK separately",
        f"{_DOC_ROOT}/ — the reference tree, titled Finger SDK 4.5.0",
        f"{_SAMPLES_AT}/README.md — the vendor's own samples, stating "
        "'Required id3 Finger SDK version: 4.5.0'",
    ),
    distinguished_from=(
        "the vendor's separate MicroFinger product",
        "any MINEX submission, which is a configuration under a protocol rather "
        "than a delivered package",
        "the samples repository itself, which contains no SDK",
        "any third-party wrapper or redistribution",
    ),
)


# ------------------------------------------------------------- getting a copy


@dataclass(frozen=True, slots=True)
class AcquisitionRoute:
    """How a copy of the package and a licence are obtained, as published.

    ``self_service_download`` is the field that decides whether an automated
    preflight can settle the acquisition gate on its own. Where it is false, the
    gate depends on a person-to-vendor exchange, and that is a fact about the
    route rather than a shortcoming of the stage (docs/adr/0095).
    """

    self_service_download: bool
    request_channel: str
    vendor_acceptance_required: bool
    delivers_package: bool
    delivers_activation_key: bool
    activation_is_hardware_bound: bool
    license_file_required_before_any_api_call: bool
    supporting_locators: tuple[str, ...]


ACQUISITION_ROUTE = AcquisitionRoute(
    self_service_download=False,
    request_channel="an e-mail request to the vendor's published contact address",
    vendor_acceptance_required=True,
    delivers_package=True,
    delivers_activation_key=True,
    activation_is_hardware_bound=True,
    license_file_required_before_any_api_call=True,
    supporting_locators=(
        f"{_SAMPLES_AT}/README.md — 'To run any of the samples, you need to get "
        "a license from id3 Technologies. For that, you must contact us'; and "
        "'once your request will be accepted, you will receive both a license "
        "activation key and a ZIP archive containing the SDK itself'",
        f"{_SAMPLES_AT}/README.md — activation runs against an activation key "
        "and a host hardware code, producing a licence file",
        f"{_SAMPLES_AT}/python/RecognitionCLI.py — the sample's first executable "
        "line is a licence check, with the comment that it must happen 'Before "
        "calling any function of the SDK'",
    ),
)

ACQUISITION_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="samples_readme_states_the_request_route",
        subject="how the package and the licence are obtained",
        statement=(
            "The vendor's samples README states that a licence must be obtained "
            "by contacting id3 Technologies, and that once the request is "
            "accepted the requester receives both a licence activation key and a "
            "ZIP archive containing the SDK. There is no download link and no "
            "self-service route."
        ),
        locator=f"{_SAMPLES_AT}/README.md",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="samples_readme_states_hardware_bound_activation",
        subject="what activation binds to",
        statement=(
            "Activation is performed with an activation key and a host hardware "
            "code, through a command-line tool or the licence APIs, and produces "
            "a licence file. The key is described as re-creditable on request "
            "and usable on several computers."
        ),
        locator=f"{_SAMPLES_AT}/README.md",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="samples_readme_states_models_are_separate",
        subject="where the models come from",
        statement=(
            "Models are installed into a separate models/ folder, and the README "
            "states that the download address for models is in the SDK's own "
            "developer guide. The guide ships with the package, so the model set "
            "cannot be enumerated without the package."
        ),
        locator=f"{_SAMPLES_AT}/README.md",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="sample_checks_the_license_before_anything",
        subject="what the SDK requires before any call",
        statement=(
            "The Python sample calls FingerLicense.check_license against a "
            "licence file as its first SDK call, with the comment that this must "
            "happen before calling any function of the SDK."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)


@dataclass(frozen=True, slots=True)
class EvaluationTerms:
    """The free evaluation, exactly as the product page states it.

    ``api_call_limit`` is deliberately typed as the string the page uses. There
    is no number to record, and recording ``None`` would lose the fact that a
    limit was advertised without one (docs/adr/0096).
    """

    offered: bool
    duration_days: int
    api_call_limit_statement: str
    api_call_limit_is_numeric: bool
    platform_limit_statement: str
    metering_semantics_published: bool
    locator: str


EVALUATION_TERMS = EvaluationTerms(
    offered=True,
    duration_days=30,
    api_call_limit_statement="Limited API calls",
    api_call_limit_is_numeric=False,
    platform_limit_statement="Single platform",
    metering_semantics_published=False,
    locator=_PRODUCT_PAGE,
)

EVALUATION_TERM_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="product_page_offers_a_30_day_evaluation",
        subject="the free evaluation the vendor advertises",
        statement=(
            "A free 30-day trial is offered, qualified on the same page by "
            "'Limited API calls' and 'Single platform'. No number accompanies "
            "the limit and no statement says which operations consume it."
        ),
        locator=_PRODUCT_PAGE,
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)


# ------------------------------------------------------------------ the route

ROUTE_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="sample_single_finger_route_has_no_detection_step",
        subject="what the vendor's single-image sample does",
        statement=(
            "The Python recognition sample loads two image files as 8-bit "
            "grayscale, sets the resolution on each, creates one template from "
            "each with FingerExtractor.create_template, and compares the two. "
            "There is no slap detection and no ROI extraction anywhere in it."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="sample_requires_500_dpi_input",
        subject="the resolution the processors require",
        statement=(
            "The sample sets the resolution of each image to 500 and comments "
            "that id3 Finger SDK processors use only 500 dpi images, that images "
            "at a different resolution must be rescaled before use, and that "
            "omitting the call produces an 'Invalid resolution' error during "
            "template extraction."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="sample_loads_images_as_grayscale_8_bits",
        subject="the pixel format the sample uses",
        statement=(
            "Images are loaded with PixelFormat.GRAYSCALE_8_BITS, and the "
            "sample's comment states that finger images are always loaded to "
            "8-bit grayscale."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

EXTRACTION_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="sample_loads_one_mandatory_model",
        subject="which models the sample loads",
        statement=(
            "One model is loaded, a minutia detector, described in the sample as "
            "mandatory and self-sufficient for creating ISO templates. A "
            "fingerprint aligner and encoder are described as optional and as "
            "producing additional proprietary template data; the sample does not "
            "load them."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="sample_sets_a_thread_count",
        subject="an extractor setting the sample chooses",
        statement=(
            "The sample constructs the extractor with a minutia detector model "
            "and a thread count of 4. The thread count is a choice the sample "
            "makes; no documented default for it was found."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="sample_names_a_detector_model_generation",
        subject="the model constant the sample names",
        statement=(
            "The model constant in the sample names a minutia detector "
            "generation, while the README's models folder lists file names with "
            "a different version suffix. Which file the constant resolves to is "
            "not established from public sources."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

MATCHER_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="sample_constructs_a_default_matcher",
        subject="how the sample builds the matcher",
        statement=(
            "The matcher is constructed with no arguments, and the sample "
            "comments that by default it uses all data found in the templates. "
            "It then sets minexOnly to True to force minutiae-only comparison "
            "for a second score."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="no_documented_default_for_matcher_options",
        subject="what the class reference says about defaults",
        statement=(
            "The FingerMatcher reference documents what each of the five options "
            "does and states no default for any of them. A runtime value read "
            "from the delivered package would therefore be a delivered-SDK "
            "default, not a documented one."
        ),
        locator=f"{_DOC_ROOT}/reference/finger/finger_matcher/finger_matcher.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="normalized_scores_carries_an_instruction",
        subject="one option the documentation qualifies",
        statement=(
            "normalizedScores is documented as forcing the matcher to normalise "
            "the scores, with the added sentence that it 'Should always be "
            "True'. That is an instruction rather than a stated default, and it "
            "is score-affecting either way."
        ),
        locator=f"{_DOC_ROOT}/reference/finger/finger_matcher/finger_matcher.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

SCORE_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="sample_states_the_score_range",
        subject="the range the sample states",
        statement=(
            "The sample comments that the matching process returns a score "
            "between 0 and 65535 and that to take a decision this score must be "
            "compared to a defined threshold."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="sample_applies_a_vendor_threshold",
        subject="what the sample does after scoring",
        statement=(
            "The sample compares the score with a named FingerMatcherThreshold "
            "constant to print a match or no-match decision, and recommends a "
            "threshold for 1:1 authentication. fpbench's raw route would take "
            "the score and stop; the threshold constant belongs to a later stage "
            "or to nothing at all."
        ),
        locator=f"{_SAMPLES_AT}/python/RecognitionCLI.py",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="two_comparison_apis_exist_side_by_side",
        subject="the choice the raw route would have to make",
        statement=(
            "compareTemplates compares two templates; compareTemplateRecords "
            "compares two template records. Both are published on the matcher "
            "class, and the single-image sample uses the first."
        ),
        locator=f"{_DOC_ROOT}/reference/finger/finger_matcher/finger_matcher.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

PROVENANCE_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="vendor_publishes_evaluation_not_training_data",
        subject="what the vendor discloses about data",
        statement=(
            "The performance page reports figures against FVC2000, FVC2002 and "
            "FVC2004 and describes MINEX-interoperable minutiae. Nothing on the "
            "readable pages describes the corpus the shipped models were trained "
            "on."
        ),
        locator=f"{_DOC_ROOT}/biometric_performance.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
    PublicObservation(
        observation_id="no_public_statement_mentions_sd300",
        subject="what the readable sources say about this benchmark's cohort",
        statement=(
            "No readable vendor page mentions SD300 in any role. That is an "
            "absence of evidence about training overlap and is recorded as "
            "such; it is not a statement that the dataset was not used."
        ),
        locator=f"{_DOC_ROOT}/biometric_performance.html",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

MODEL_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="model_file_names_are_public_but_not_their_bytes",
        subject="what is known about the model artifacts",
        statement=(
            "The samples README's models folder listing shows two file names, an "
            "aligner and a minutia detector, in a listing that is explicitly "
            "elided. No digest, no size and no download address is public, and "
            "the README states the addresses are in the SDK's developer guide."
        ),
        locator=f"{_SAMPLES_AT}/README.md",
        retrieval=RetrievalOutcome.READ,
        http_status=200,
    ),
)

#: The model file names visible in public sources. Two names out of an elided
#: listing: enough to know models are separate downloadable artifacts, and far
#: from enough to close an inventory over them (spec section 10).
REQUIRED_MODEL_NAMES: tuple[str, ...] = (
    "finger_aligner_v1a.id3nn",
    "finger_minutia_detector_v1a.id3nn",
)


@dataclass(frozen=True, slots=True)
class PublishedMatcherOption:
    """One matcher option, with what the documentation does and does not say."""

    name: str
    published_meaning: str
    documented_default: str | None
    is_score_affecting: bool


#: Every option the matcher class publishes. ``documented_default`` is ``None``
#: for all five, which is the finding: a value fpbench never sets is still a
#: value the score depends on, and it would have to be read from the delivered
#: package and recorded as a delivered-SDK default (docs/adr/0097).
PUBLISHED_MATCHER_OPTIONS: tuple[PublishedMatcherOption, ...] = (
    PublishedMatcherOption(
        name="maximumRotation",
        published_meaning=(
            "maximum supported rotation in degrees between two templates during "
            "matching, in the range 0 to 180"
        ),
        documented_default=None,
        is_score_affecting=True,
    ),
    PublishedMatcherOption(
        name="minexOnly",
        published_meaning=(
            "forces the matcher to use interoperable minutiae data only"
        ),
        documented_default=None,
        is_score_affecting=True,
    ),
    PublishedMatcherOption(
        name="minutiaPatchOnly",
        published_meaning="forces the matcher to use minutia patch data only",
        documented_default=None,
        is_score_affecting=True,
    ),
    PublishedMatcherOption(
        name="multiscaleMatch",
        published_meaning=(
            "for templates from the contactless detection module, where the dpi "
            "is approximated and may vary from the expected 500"
        ),
        documented_default=None,
        is_score_affecting=True,
    ),
    PublishedMatcherOption(
        name="normalizedScores",
        published_meaning=(
            "forces the matcher to normalise the scores, with the instruction "
            "that it should always be true"
        ),
        documented_default=None,
        is_score_affecting=True,
    ),
)


@dataclass(frozen=True, slots=True)
class PublishedExtractorOption:
    """One extractor option, with what the documentation does and does not say."""

    name: str
    published_meaning: str
    documented_default: str | None
    is_score_affecting: bool


PUBLISHED_EXTRACTOR_OPTIONS: tuple[PublishedExtractorOption, ...] = (
    PublishedExtractorOption(
        name="minutiaDetectorModel",
        published_meaning="the model used to detect minutiae in a finger image",
        documented_default=None,
        is_score_affecting=True,
    ),
    PublishedExtractorOption(
        name="minutiaEncoderModel",
        published_meaning=(
            "the model used to encode minutiae with proprietary features"
        ),
        documented_default=None,
        is_score_affecting=True,
    ),
    PublishedExtractorOption(
        name="threadCount",
        published_meaning="the number of threads used for feature extraction",
        documented_default=None,
        is_score_affecting=False,
    ),
)

#: What the readable documentation states about the score itself. Recorded as
#: observations, not as a settled contract: the gate that would settle it was
#: never reached, and a contract is settled against the delivered package's own
#: documentation rather than against a public page (spec sections 8 and 21).
DOCUMENTED_SCORE_RANGE_MIN = 0
DOCUMENTED_SCORE_RANGE_MAX = 65535
DOCUMENTED_SCORE_DIRECTION = "HIGHER_IS_MORE_SIMILAR"


# ------------------------------------------------------------------ the record


def all_observations() -> tuple[PublicObservation, ...]:
    """Every recorded observation, in one sequence, in declaration order."""
    return (
        *PRODUCT_OBSERVATIONS,
        *PLATFORM_OBSERVATIONS,
        *DOCUMENTATION_OBSERVATIONS,
        *UNRESOLVED_LOCATORS,
        *ACQUISITION_OBSERVATIONS,
        *EVALUATION_TERM_OBSERVATIONS,
        *ROUTE_OBSERVATIONS,
        *EXTRACTION_OBSERVATIONS,
        *MATCHER_OBSERVATIONS,
        *SCORE_OBSERVATIONS,
        *PROVENANCE_OBSERVATIONS,
        *MODEL_OBSERVATIONS,
    )


def observation(observation_id: str) -> PublicObservation:
    """One observation by id."""
    for item in all_observations():
        if item.observation_id == observation_id:
            return item
    raise Id3ObservationError(f"{observation_id!r} is not a recorded observation")


def observation_rows(
    items: tuple[PublicObservation, ...]
) -> list[Mapping[str, Any]]:
    """The published shape of a group of observations."""
    return [
        {
            "observation_id": item.observation_id,
            "subject": item.subject,
            "statement": item.statement,
            "locator": item.locator,
            "retrieval": item.retrieval.value,
            "http_status": item.http_status,
            "observed_utc": item.observed_utc,
        }
        for item in items
    ]


def observations_fingerprint() -> str:
    """Identify the observations this preflight was decided on.

    A change to any recorded fact changes this digest, and therefore changes the
    preflight fingerprint above it. Re-reading the vendor's pages and finding
    something different is a new preflight, not an amendment to this one.
    """
    return stable_hash(
        {
            "schema": "stage_10b_observations_v1",
            "observed_utc": OBSERVED_UTC,
            "observations": [
                (
                    item.observation_id,
                    item.locator,
                    item.retrieval.value,
                    item.http_status,
                    item.statement,
                )
                for item in all_observations()
            ],
            "samples_repository": [
                SAMPLES_REPOSITORY.commit,
                SAMPLES_REPOSITORY.release_label,
            ],
            "samples_files": [
                (item.relative_path, item.sha256, item.size_bytes)
                for item in SAMPLES_PINNED_FILES
            ],
            "acquisition": [
                ACQUISITION_ROUTE.self_service_download,
                ACQUISITION_ROUTE.vendor_acceptance_required,
                ACQUISITION_ROUTE.activation_is_hardware_bound,
                ACQUISITION_ROUTE.license_file_required_before_any_api_call,
            ],
            "evaluation": [
                EVALUATION_TERMS.offered,
                EVALUATION_TERMS.duration_days,
                EVALUATION_TERMS.api_call_limit_statement,
                EVALUATION_TERMS.api_call_limit_is_numeric,
                EVALUATION_TERMS.metering_semantics_published,
            ],
            "matcher_options": [
                (item.name, item.documented_default, item.is_score_affecting)
                for item in PUBLISHED_MATCHER_OPTIONS
            ],
            "extractor_options": [
                (item.name, item.documented_default, item.is_score_affecting)
                for item in PUBLISHED_EXTRACTOR_OPTIONS
            ],
            "models": list(REQUIRED_MODEL_NAMES),
        },
        length=64,
    )
