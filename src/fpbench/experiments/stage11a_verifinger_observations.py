"""What was actually read, and where each statement was read from.

This module is Stage 11A's record of fact. Every value in it carries a *source
class*, and the source class is the point of the module: Stage 10B could only
record what a vendor's web pages said, and this stage can distinguish

.. code-block:: text

    OFFICIAL_DOWNLOAD_PAGE        a page, which can change tomorrow
    TRANSFER_METADATA             what the server sent, and what arrived
    PINNED_SDK_ARCHIVE            bytes inside an archive pinned by digest
    PINNED_DOCUMENTATION          the manual that ships with those bytes
    OFFICIAL_SAMPLE_IN_ARCHIVE    upstream's own code, inside the same archive

Only the last three are artifact evidence. A statement filed under the wrong one
is the failure mode this module exists to prevent, and the observation type
refuses a locator that does not match its class (spec section 5).

Three things shape the record.

**The documentation is pinned, not browsed.** Neurotechnology publishes a
standalone manual PDF and ships the same manual inside the SDK archive. Those two
were compared byte for byte and are the same file, so this stage's citations are
to a document that cannot drift away from the runtime it describes.

**Nothing here was executed.** Every fact below was read out of files: text
files, a PDF, Java sources, and the version resources compiled into the native
libraries. No licence was activated, no library was loaded and no score exists.

**No credential appears here, in any form.** The trial-activation mechanism is
recorded as a *procedure*; no serial, no activation identifier, no machine code
and no licence byte is recorded at all (spec section 43).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash
from fpbench.core.verifinger_preflight_errors import VeriFingerObservationError
from fpbench.experiments.stage11a_verifinger_identity import (
    ArtifactRoute,
    SettingProvenance,
)

#: The one sample settings may be taken from, as a path inside the archive.
#: The prose form lives in the identity module; this is what an observation
#: cites, so the two cannot disagree about which tutorial is authoritative.
AUTHORITATIVE_ROUTE_SAMPLE_PATH = (
    "Neurotec_Biometric_2025_2_SDK/Tutorials/Biometrics/Java/verify-finger/"
    "src/main/java/com/neurotec/tutorials/biometrics/VerifyFinger.java"
)

__all__ = [
    "OBSERVED_UTC",
    "ACQUIRED_UTC",
    "SourceClass",
    "Retrieval",
    "Observation",
    "AcquiredArtifact",
    "ArchiveMember",
    "NativeLibraryIdentity",
    "PublishedSetting",
    "AUTHORITATIVE_ROUTE_SAMPLE_PATH",
    "PRODUCT_IDENTITY_CLAIM",
    "ProductIdentityClaim",
    "SDK_ARCHIVE",
    "DOCUMENTATION_PDF",
    "ACQUIRED_ARTIFACTS",
    "REJECTED_ROUTES",
    "RejectedRoute",
    "ARCHIVE_MEMBER_COUNT",
    "ARCHIVE_UNCOMPRESSED_BYTES",
    "CITED_ARCHIVE_MEMBERS",
    "FINGER_DATA_FILES",
    "WINDOWS_X64_NATIVE_LIBRARIES",
    "JAVA_BINDING_JARS",
    "LANGUAGE_BINDINGS_IN_ARCHIVE",
    "PYTHON_BINDING_IN_MAIN_SDK",
    "ACQUISITION_OBSERVATIONS",
    "IDENTITY_OBSERVATIONS",
    "LICENSE_OBSERVATIONS",
    "CLOSURE_OBSERVATIONS",
    "INPUT_OBSERVATIONS",
    "EXTRACTION_OBSERVATIONS",
    "REPRESENTATION_OBSERVATIONS",
    "MATCHER_OBSERVATIONS",
    "SCORE_OBSERVATIONS",
    "EXECUTION_OBSERVATIONS",
    "NETWORK_OBSERVATIONS",
    "CAPACITY_OBSERVATIONS",
    "PROVENANCE_OBSERVATIONS",
    "PUBLISHED_EXTRACTOR_SETTINGS",
    "PUBLISHED_MATCHER_SETTINGS",
    "DOCUMENTED_SCORE_TYPE",
    "DOCUMENTED_SCORE_DIRECTION",
    "DOCUMENTED_SCORE_TRANSFORM",
    "DOCUMENTED_SCORE_ANCHORS",
    "OFFICIAL_ONE_TO_ONE_ROUTE",
    "SUPPORTED_IMAGE_CONTAINERS",
    "TRIAL_TERMS",
    "TrialTerms",
    "all_observations",
    "observation",
    "observation_rows",
    "setting_rows",
    "observations_fingerprint",
]

#: When the pages below were read and the artifacts were fetched. One timestamp
#: rather than one per row, because it was a single pass and a re-read would have
#: to repeat the pass.
OBSERVED_UTC = "2026-08-10T00:00:00Z"
ACQUIRED_UTC = "2026-08-10T13:41:45Z"


class SourceClass(str, Enum):
    """Where a statement came from, and therefore how much it is worth.

    The ordering is deliberate: a page is the weakest source and upstream's own
    code inside a pinned archive is the strongest. A gate that needs artifact
    evidence refuses to be satisfied by a page.
    """

    OFFICIAL_DOWNLOAD_PAGE = "OFFICIAL_DOWNLOAD_PAGE"
    TRANSFER_METADATA = "TRANSFER_METADATA"
    PINNED_SDK_ARCHIVE = "PINNED_SDK_ARCHIVE"
    PINNED_DOCUMENTATION = "PINNED_DOCUMENTATION"
    OFFICIAL_SAMPLE_IN_ARCHIVE = "OFFICIAL_SAMPLE_IN_ARCHIVE"

    @property
    def is_artifact_evidence(self) -> bool:
        """Whether this source is the pinned artifact rather than a web page."""
        return self in (
            SourceClass.PINNED_SDK_ARCHIVE,
            SourceClass.PINNED_DOCUMENTATION,
            SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        )


class Retrieval(str, Enum):
    """What happened when the source was reached."""

    READ = "READ"
    NOT_FOUND = "NOT_FOUND"
    NOT_READABLE = "NOT_READABLE"


@dataclass(frozen=True, slots=True)
class Observation:
    """One statement, and where it was read.

    ``statement`` is what the source says. It is never what the source implies.

    The refusals are all of one kind: a locator has to be the *sort of thing* the
    source class describes. An artifact-class observation whose locator is a URL
    would be a web page's sentence wearing an artifact's authority, which is the
    substitution this whole stage was written to avoid.
    """

    observation_id: str
    subject: str
    statement: str
    source_class: SourceClass
    locator: str
    retrieval: Retrieval = Retrieval.READ
    http_status: int | None = None
    observed_utc: str = OBSERVED_UTC

    def __post_init__(self) -> None:
        validate_id(self.observation_id)
        if not self.locator.strip():
            raise VeriFingerObservationError(
                f"{self.observation_id}: an observation with no locator is an "
                "assertion"
            )
        if not self.statement.strip():
            raise VeriFingerObservationError(
                f"{self.observation_id}: an observation records what the source "
                "said; a blank statement is an unperformed reading"
            )
        is_url = self.locator.startswith(("http://", "https://"))
        if self.source_class.is_artifact_evidence and is_url:
            raise VeriFingerObservationError(
                f"{self.observation_id}: {self.source_class.value} is artifact "
                "evidence and its locator is a URL. A sentence read from a web "
                "page does not become artifact evidence by being filed as one "
                "(spec section 5)"
            )
        if self.source_class is SourceClass.OFFICIAL_DOWNLOAD_PAGE and not is_url:
            raise VeriFingerObservationError(
                f"{self.observation_id}: a page observation needs the page's URL"
            )
        if self.retrieval is Retrieval.READ and self.http_status not in (None, 200):
            raise VeriFingerObservationError(
                f"{self.observation_id}: a source reported as read answered "
                f"{self.http_status}"
            )


# ------------------------------------------------------------- what was fetched


@dataclass(frozen=True, slots=True)
class AcquiredArtifact:
    """One official artifact, pinned by the seven fields required before import.

    There is no field here for a signed URL, a token or a cookie, and that
    absence is deliberate: a class that could carry one is a class that
    eventually does (spec section 4).
    """

    artifact_id: str
    route: ArtifactRoute
    official_locator_category: str
    locator: str
    filename: str
    size_bytes: int
    sha256: str
    downloaded_utc: str
    declared_version: str
    target_operating_systems: tuple[str, ...]
    target_architectures: tuple[str, ...]
    role: str

    def __post_init__(self) -> None:
        validate_id(self.artifact_id)
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise VeriFingerObservationError(
                f"{self.artifact_id}: an acquired artifact is identified by a "
                "SHA-256 digest over the bytes that arrived"
            )
        object.__setattr__(self, "sha256", digest)
        if int(self.size_bytes) <= 0:
            raise VeriFingerObservationError(
                f"{self.artifact_id}: an empty artifact was not acquired"
            )
        if "?" in self.locator or "@" in self.locator:
            raise VeriFingerObservationError(
                f"{self.artifact_id}: the locator carries a query string or "
                "userinfo, and a signed locator is not evidence (spec section 4)"
            )


@dataclass(frozen=True, slots=True)
class RejectedRoute:
    """A distribution that exists and is not the one being qualified.

    Recorded rather than omitted, because "we chose the main SDK" and "the other
    route turned out to be a different version" are different statements, and
    only the second one is what happened (spec section 3).
    """

    route: ArtifactRoute
    locator: str
    filename: str
    size_bytes: int
    declared_version: str
    why_not_this_route: str


@dataclass(frozen=True, slots=True)
class ArchiveMember:
    """One file inside a pinned archive, cited by digest and size."""

    relative_path: str
    size_bytes: int
    sha256: str
    role: str

    def __post_init__(self) -> None:
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise VeriFingerObservationError(
                f"{self.relative_path}: a cited member is identified by SHA-256"
            )
        object.__setattr__(self, "sha256", digest)
        if int(self.size_bytes) <= 0:
            raise VeriFingerObservationError(
                f"{self.relative_path}: an empty member cites nothing"
            )


@dataclass(frozen=True, slots=True)
class NativeLibraryIdentity:
    """One native library, and the identity compiled into it.

    Read from the library's own version resource rather than from a page or a
    filename. This is what "build/version" and "native library identities" mean
    in the runtime-identity gate (spec section 6).
    """

    relative_path: str
    size_bytes: int
    sha256: str
    file_description: str
    product_version: str
    product_name: str | None = None

    def __post_init__(self) -> None:
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise VeriFingerObservationError(
                f"{self.relative_path}: a native library is cited by SHA-256"
            )
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True, slots=True)
class PublishedSetting:
    """One externally selectable setting, with everything known about its value.

    ``documented_default`` and ``official_sample_value`` are separate fields on
    purpose. A value the vendor's own sample sets is an authority
    (``OFFICIAL_SAMPLE_EXPLICIT``); a value the manual states as the default is a
    different authority (``UPSTREAM_DOCUMENTED_DEFAULT``); and a setting with
    neither is exactly the hidden default the profile gates refuse to leave open
    (spec sections 14, 15 and 20).
    """

    name: str
    published_meaning: str
    is_score_affecting: bool
    documented_default: str | None = None
    official_sample_value: str | None = None
    official_sample_locator: str | None = None

    def __post_init__(self) -> None:
        if (self.official_sample_value is None) != (
            self.official_sample_locator is None
        ):
            raise VeriFingerObservationError(
                f"{self.name}: a value taken from an official sample names which "
                "sample, and a named sample without a value says nothing"
            )
        if (
            self.official_sample_locator is not None
            and self.official_sample_locator != AUTHORITATIVE_ROUTE_SAMPLE_PATH
        ):
            raise VeriFingerObservationError(
                f"{self.name}: the value comes from "
                f"{self.official_sample_locator!r}, and the authoritative route "
                f"is {AUTHORITATIVE_ROUTE_SAMPLE_PATH!r}. Upstream's tutorials do "
                "not agree with each other, so a profile assembled from two of "
                "them would be a configuration no upstream program has ever run "
                "(docs/adr/0105)"
            )

    @property
    def provenance(self) -> SettingProvenance:
        """Where a frozen value for this setting would come from, today.

        The authoritative sample outranks the manual, and deliberately: where
        upstream's own complete 1:1 program sets a value explicitly, that *is*
        the route being qualified, and the profile identity says so rather than
        claiming to be "the VeriFinger default" (spec section 16).

        Only one sample counts. A setting the authoritative sample leaves alone
        is a delivered runtime default to be read off the engine — never a value
        borrowed from a neighbouring tutorial that does set it.
        """
        if self.official_sample_value is not None:
            return SettingProvenance.OFFICIAL_SAMPLE_EXPLICIT
        if self.documented_default is not None:
            return SettingProvenance.UPSTREAM_DOCUMENTED_DEFAULT
        return SettingProvenance.UNRESOLVED

    @property
    def is_unresolved_score_affecting_default(self) -> bool:
        return self.is_score_affecting and not self.provenance.is_upstream_authority


# --------------------------------------------------------------- the identity


@dataclass(frozen=True, slots=True)
class ProductIdentityClaim:
    """Which product this stage is about, and what supports the claim."""

    product_name: str
    vendor: str
    declared_version: str
    supporting_sources: tuple[str, ...]
    distinguished_from: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.supporting_sources:
            raise VeriFingerObservationError(
                "a product identity is established by pointing at what upstream "
                "publishes, not by naming the vendor"
            )


PRODUCT_IDENTITY_CLAIM = ProductIdentityClaim(
    product_name="VeriFinger 2025.2 SDK",
    vendor="Neurotechnology",
    declared_version="2025.2",
    supporting_sources=(
        "Documentation/SDK License.html inside the pinned archive — the licence "
        "agreement is headed 'VeriFinger 2025.2, VeriLook 2025.2, VeriEye "
        "2025.2, VeriSpeak 2025.2, MegaMatcher 2025.2 SDK'",
        "Revision.txt inside the pinned archive — product revision number "
        "20260612",
        "Bin/Win64_x64/NBiometrics.dll version resource — ProductVersion "
        "'2025, 2, 0, 0', FileDescription 'Neurotechnology Biometrics 2025.2'",
        "Documentation/Activation.pdf inside the pinned archive — 'Version: "
        "2025.2.0.0. Release date: 6/12/2026.'",
        "Tutorials/Biometrics/Java/verify-finger — the official 1:1 tutorial "
        "declares VERSION '2025.2.0.0'",
    ),
    distinguished_from=(
        "the vendor's Python packages, which are version 2025.1",
        "MegaMatcher 2025.2, shipped in the same archive",
        "the separately downloadable Algorithm Demo application",
        "any NIST submission, which is a configuration under a protocol",
        "VeriFinger Extended, which is a different licence set",
    ),
)


# ------------------------------------------------------------- what was acquired

_DOWNLOAD_PAGE = "https://www.neurotechnology.com/download.html"
_DOWNLOAD_HOST = "https://download.neurotechnology.com"

#: The archive the qualification is about. One route, and the route is the main
#: SDK package: it is the only distribution the vendor publishes at 2025.2
#: (spec section 3).
SDK_ARCHIVE = AcquiredArtifact(
    artifact_id="neurotec_biometric_2025_2_sdk_archive",
    route=ArtifactRoute.MAIN_SDK_PACKAGE,
    official_locator_category=(
        "the vendor's own download page, 'Biometric SDKs trials', linking "
        "directly to the vendor's download host with no form, no account and no "
        "acceptance step in front of it"
    ),
    locator=f"{_DOWNLOAD_HOST}/Neurotec_Biometric_2025_2_SDK_2026-06-12.zip",
    filename="Neurotec_Biometric_2025_2_SDK_2026-06-12.zip",
    size_bytes=4_743_229_435,
    sha256="e30a0b603e453fe0a08157ed2331de71f8a3d3cdc6dcf001df649a36a69bafdc",
    downloaded_utc=ACQUIRED_UTC,
    declared_version="2025.2",
    target_operating_systems=("windows", "linux", "macos", "android", "ios"),
    target_architectures=("x86_64", "arm64", "armhf"),
    role=(
        "the trial distribution of five Neurotechnology SDKs, of which "
        "VeriFinger 2025.2 is one"
    ),
)

#: The manual, pinned as an artifact in its own right (spec section 5). It is
#: also inside the archive, and the two are the same bytes — which is what makes
#: citing it safe: the documentation cannot drift away from the runtime while the
#: runtime stays pinned.
DOCUMENTATION_PDF = AcquiredArtifact(
    artifact_id="neurotec_biometric_sdk_documentation_pdf",
    route=ArtifactRoute.DOCUMENTATION_BUNDLE,
    official_locator_category=(
        "the vendor's own download page, 'SDK documentation', stated on that "
        "page to cover VeriFinger 2025.2 SDK"
    ),
    locator=f"{_DOWNLOAD_HOST}/Neurotec_Biometric_SDK_Documentation.pdf",
    filename="Neurotec_Biometric_SDK_Documentation.pdf",
    size_bytes=124_277_015,
    sha256="ae8acd238e096f9849bb5ad9772e314baeac0ceedf64951898119d69a786a34d",
    downloaded_utc="2026-08-10T13:39:59Z",
    declared_version="2025.2",
    target_operating_systems=(),
    target_architectures=(),
    role="the SDK reference manual, 3,048 pages",
)

ACQUIRED_ARTIFACTS: tuple[AcquiredArtifact, ...] = (SDK_ARCHIVE, DOCUMENTATION_PDF)

#: The distribution that was not chosen, and why. The research that preceded this
#: stage expected the Python package to be the better route; the artifact
#: decided otherwise, and the reason is a version number rather than a
#: preference (spec section 3).
REJECTED_ROUTES: tuple[RejectedRoute, ...] = (
    RejectedRoute(
        route=ArtifactRoute.PYTHON_RESEARCH_PACKAGE,
        locator=f"{_DOWNLOAD_HOST}/Neurotec_Biometric_2025_1_Python_2025-10-31.zip",
        filename="Neurotec_Biometric_2025_1_Python_2025-10-31.zip",
        size_bytes=1_467_389_379,
        declared_version="2025.1",
        why_not_this_route=(
            "The vendor's Python packages are published at version 2025.1, not "
            "2025.2. They are described as including all required native "
            "libraries and as recommended for research, which is why the "
            "preceding research favoured them — but qualifying them would "
            "qualify a different version of the product from the one this stage "
            "is named for, and taking runtime files from both distributions is "
            "refused outright. The bytes were not downloaded."
        ),
    ),
)


# ------------------------------------------------- what is inside the archive

#: Every regular file in the archive was hashed. These two numbers are the shape
#: of the closure the artifact gate walks.
ARCHIVE_MEMBER_COUNT = 8_702
ARCHIVE_UNCOMPRESSED_BYTES = 6_796_855_547

_ROOT = "Neurotec_Biometric_2025_2_SDK/"

#: The archive members this stage quotes, each by digest. No byte of any of them
#: is stored in this repository (docs/adr/0083).
CITED_ARCHIVE_MEMBERS: tuple[ArchiveMember, ...] = (
    ArchiveMember(
        relative_path=f"{_ROOT}Revision.txt",
        size_bytes=100,
        sha256="cd0b12a058a25ec48d0b585a7c36943c3191a9495cd8d2ad50750b2f399751f6",
        role="the archive's own build identity",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}ReadMe.txt",
        size_bytes=4_153,
        sha256="2c116904a8fffe28ecd4d3234dca444d87f4ba8f77db643a40549d71c3088f25",
        role="what the archive is, and what installing it means",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Documentation/SDK License.html",
        size_bytes=40_239,
        sha256="e630df7aa7d72f7f030875cf911ffab7f2a2e1fd3b99de26b8f803a95e7aee10",
        role="the licence agreement Stage 8E is assessed against",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Documentation/Activation.pdf",
        size_bytes=2_260_719,
        sha256="7bfd029689c56796bcb7f5b5e3a2d94daefe325eb8e904afeb5a2e36ae2162b3",
        role="the licensing and activation guide, 67 pages",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
        size_bytes=124_277_015,
        sha256="ae8acd238e096f9849bb5ad9772e314baeac0ceedf64951898119d69a786a34d",
        role=(
            "the SDK manual, byte-for-byte the separately downloaded "
            "documentation artifact"
        ),
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Bin/Licenses/TrialFlag.txt",
        size_bytes=220,
        sha256="739cc7821fc784ccfae1dca1512a90b125b6ee4635b9a75dcc00a06092f575ad",
        role="the shipped trial-mode switch, delivered set to TRUE",
    ),
)

#: The fingerprint algorithm's data files. Both ship inside the pinned archive,
#: which is what closes the transitive inventory: nothing is fetched from a model
#: zoo at first use, and there is no ``.pth`` to demand from a black-box
#: commercial matcher (spec sections 9 and 10).
FINGER_DATA_FILES: tuple[ArchiveMember, ...] = (
    ArchiveMember(
        relative_path=f"{_ROOT}Bin/Data/Fingers.ndf",
        size_bytes=122_945_738,
        sha256="ecca8454d80820ceed7798d91db400bc84e92d1712adb82428c2c857b0cff2b1",
        role="the fingerprint extraction data file the engine loads",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Bin/Data/FingersMatching.ndf",
        size_bytes=4_242_028,
        sha256="6c05234db491930118e993baf2c45655c6f8c63266979150336c11adae9ec585",
        role="the fingerprint matching data file the engine loads",
    ),
)

#: The native libraries of the one platform this project would host, with the
#: identity each of them carries in its own version resource.
WINDOWS_X64_NATIVE_LIBRARIES: tuple[NativeLibraryIdentity, ...] = (
    NativeLibraryIdentity(
        relative_path=f"{_ROOT}Bin/Win64_x64/NBiometrics.dll",
        size_bytes=10_459_192,
        sha256="d66a702e2b4ffe4b98e737b195a72e5fc72e0e649533555793d77b60d8f20386",
        product_name="Neurotechnology Biometrics",
        file_description="Neurotechnology Biometrics 2025.2",
        product_version="2025, 2, 0, 0",
    ),
    NativeLibraryIdentity(
        relative_path=f"{_ROOT}Bin/Win64_x64/NBiometricClient.dll",
        size_bytes=2_886_712,
        sha256="15988f0e20bf1f6290fcd81ece7d2581bfa64519973675effa19a6f30f0a0edf",
        product_name="Neurotechnology Biometric Client",
        file_description="Neurotechnology Biometric Client 2025.2",
        product_version="2025, 2, 0, 0",
    ),
    NativeLibraryIdentity(
        relative_path=f"{_ROOT}Bin/Win64_x64/NCore.dll",
        size_bytes=1_867_320,
        sha256="ecef1f2921283a1e1414285c26872770fa8464545bf29c6f5967f4071e199c1c",
        product_name="Neurotechnology Core",
        file_description="Neurotechnology Core 2025.2",
        product_version="2025, 2, 0, 0",
    ),
    NativeLibraryIdentity(
        relative_path=f"{_ROOT}Bin/Win64_x64/NMedia.dll",
        size_bytes=5_605_432,
        sha256="91d6897461df67ab1db3403e2c0a9fa43297a1ae91c726e0b1213b0515544171",
        product_name="Neurotechnology Media",
        file_description="Neurotechnology Media 2025.2",
        product_version="2025, 2, 0, 0",
    ),
    # The only one of the five whose ``ProductName`` field this stage does not
    # publish. A plain scan of the version block returned an unrelated diagnostic
    # string for it, and a field that did not read cleanly is left null rather
    # than filled in from the neighbouring libraries' pattern.
    NativeLibraryIdentity(
        relative_path=f"{_ROOT}Bin/Win64_x64/NLicensing.dll",
        size_bytes=4_785_720,
        sha256="5b129f0031c7333a9eca23f97cf04582f7044de9f1df1f419507d0e44ae628dc",
        product_name=None,
        file_description="Neurotechnology Activation Service (Trial)",
        product_version="2025, 2, 0, 0",
    ),
)

#: The Java binding, which is the binding a Python benchmark would drive this SDK
#: through — as it already drives SourceAFIS.
JAVA_BINDING_JARS: tuple[ArchiveMember, ...] = (
    ArchiveMember(
        relative_path=f"{_ROOT}Bin/Java/neurotec-biometrics.jar",
        size_bytes=1_521_353,
        sha256="1ba85cb1512d033e3e9c9383a048112950324e1f77aef8deda84ea9761ab1f97",
        role="NBiometricClient, NSubject, NFinger and the matching result types",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Bin/Java/neurotec-core.jar",
        size_bytes=729_966,
        sha256="6457f9d040f2b9bee3bbad8e414f20cccd5c4d3671d62ca3ac2cf91f4ae44760",
        role="the object model the bindings are built on",
    ),
    ArchiveMember(
        relative_path=f"{_ROOT}Bin/Java/neurotec-licensing.jar",
        size_bytes=58_016,
        sha256="bdb8bb0c6c4a87ad2a613f52dfcb91b8844aa446d7d57f602ca9fa6c78b94e91",
        role="NLicense and NLicenseManager, the licence gate before any call",
    ),
)

#: Which language bindings the main SDK archive actually ships. Read from the
#: archive's own directory layout rather than from a marketing list.
LANGUAGE_BINDINGS_IN_ARCHIVE: tuple[str, ...] = (
    "C",
    "C++",
    ".NET",
    ".NET Standard",
    "Java",
    "Android (Java)",
)

#: There is none, and this is a finding rather than an omission. fpbench is a
#: Python project; the main 2025.2 archive has no Python binding, and the
#: vendor's Python distribution is 2025.1 (spec section 3).
PYTHON_BINDING_IN_MAIN_SDK = False


# ----------------------------------------------------------------- the record

ACQUISITION_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="download_page_publishes_a_direct_locator",
        subject="how the artifact is obtained",
        statement=(
            "The vendor's download page links directly to the archive on its "
            "own download host. There is no request form, no account, no "
            "click-through acceptance and no vendor approval step between the "
            "page and the bytes."
        ),
        source_class=SourceClass.OFFICIAL_DOWNLOAD_PAGE,
        locator=_DOWNLOAD_PAGE,
        http_status=200,
    ),
    Observation(
        observation_id="download_page_states_one_bundle_for_five_sdks",
        subject="what the trial download contains",
        statement=(
            "The page states that the trials package is a single zip archive "
            "including MegaMatcher 2025.2, VeriFinger 2025.2, VeriLook 2025.2, "
            "VeriEye 2025.2 and VeriSpeak 2025.2, and that developers choose "
            "which SDK to evaluate after downloading."
        ),
        source_class=SourceClass.OFFICIAL_DOWNLOAD_PAGE,
        locator=_DOWNLOAD_PAGE,
        http_status=200,
    ),
    Observation(
        observation_id="transfer_matched_the_advertised_length",
        subject="what arrived",
        statement=(
            "The server declared Content-Length 4743229435 and Last-Modified "
            "Fri, 12 Jun 2026 12:35:26 GMT; exactly 4743229435 bytes arrived. "
            "The documentation transfer declared and delivered 124277015 bytes."
        ),
        source_class=SourceClass.TRANSFER_METADATA,
        locator=SDK_ARCHIVE.locator,
        http_status=200,
    ),
    Observation(
        observation_id="documentation_is_the_same_bytes_as_the_shipped_manual",
        subject="whether the pinned manual describes the pinned runtime",
        statement=(
            "The separately downloaded documentation PDF and the copy inside "
            "the archive have the same SHA-256. The manual this stage cites is "
            "therefore the manual the pinned runtime ships with, and not a "
            "current web version that can move underneath it."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="python_distribution_is_a_different_version",
        subject="the route that was not taken",
        statement=(
            "The vendor's Python packages are published on the same page as "
            "Neurotec_Biometric_2025_1_Python_2025-10-31.zip — version 2025.1. "
            "The page describes them as recommended for research and as "
            "including all required native libraries, and states that the main "
            "SDK trial is not required in order to use them."
        ),
        source_class=SourceClass.OFFICIAL_DOWNLOAD_PAGE,
        locator=_DOWNLOAD_PAGE,
        http_status=200,
    ),
)

IDENTITY_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="archive_declares_its_own_revision",
        subject="the build identity the artifact carries",
        statement=(
            "Revision.txt reads 'Product revision number: 20260612' and "
            "'Product revision hash: 0738caf6a69459241bff6e800789cd61c160bbce'."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Revision.txt",
    ),
    Observation(
        observation_id="native_libraries_declare_2025_2",
        subject="what the binaries say they are",
        statement=(
            "The Windows x86-64 native libraries carry version resources naming "
            "ProductVersion '2025, 2, 0, 0' and descriptions such as "
            "'Neurotechnology Biometrics 2025.2'. This is the version compiled "
            "into the code, not a version printed on a page."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Bin/Win64_x64/NBiometrics.dll",
    ),
    Observation(
        observation_id="readme_defines_what_installation_means",
        subject="what installing this SDK consists of",
        statement=(
            "The ReadMe states that installation is two steps: extract the "
            "archive to a location on the local computer, and activate the "
            "licensing software, which is necessary for the SDK to work "
            "correctly."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}ReadMe.txt",
    ),
    Observation(
        observation_id="main_archive_ships_no_python_binding",
        subject="which bindings the qualified route could use",
        statement=(
            "The archive's Bin tree holds Android, Java, dotNET, "
            "dotNET_Standard, Linux, macOS and Windows directories, and Include "
            "and Lib trees for C and C++. There is no Python binding anywhere "
            "in it."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Bin/",
    ),
)

LICENSE_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="eula_names_verifinger_2025_2",
        subject="what the licence agreement covers",
        statement=(
            "The agreement is headed 'VeriFinger 2025.2, VeriLook 2025.2, "
            "VeriEye 2025.2, VeriSpeak 2025.2, MegaMatcher 2025.2 SDK' and "
            "defines the SDK's components, among them Fingerprint Extractor and "
            "Fingerprint Matcher."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Documentation/SDK License.html",
    ),
    Observation(
        observation_id="eula_grants_a_personal_development_licence",
        subject="what the licence permits",
        statement=(
            "Neurotechnology grants a personal, non-exclusive licence to use the "
            "SDK for the purpose of designing, developing, testing and "
            "distributing Licensee Products, and states that the SDK may only be "
            "used for a purpose or in a manner for which it was designed."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Documentation/SDK License.html",
    ),
    Observation(
        observation_id="eula_forbids_redistribution_and_circumvention",
        subject="what the licence forbids",
        statement=(
            "The agreement forbids sharing, publishing, renting or leasing the "
            "software, redistribution other than as prescribed, and any attempt "
            "to defeat, bypass, remove or circumvent the SDK's protection "
            "mechanisms or to reverse engineer it."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Documentation/SDK License.html",
    ),
    Observation(
        observation_id="activation_guide_states_trial_needs_no_serial",
        subject="how a trial licence is obtained",
        statement=(
            "The activation guide states that trial licensing grants a 30-day "
            "free trial period without any obligations, that activation is "
            "mandatory for trial versions as for purchased ones, and that "
            "activation does not involve the transmission of personal "
            "information. Manual trial activation is described as setting "
            "Trial = true in the licensing configuration file and starting the "
            "licensing service; no serial number is involved."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Activation.pdf",
    ),
    Observation(
        observation_id="trial_flag_ships_enabled",
        subject="the state the archive is delivered in",
        statement=(
            "Bin/Licenses/TrialFlag.txt contains TRUE, and its own comment "
            "explains that a TRUE first line makes the samples and tutorials use "
            "trial mode."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Bin/Licenses/TrialFlag.txt",
    ),
    Observation(
        observation_id="verifinger_standard_licence_names_two_finger_components",
        subject="which licences the 1:1 route needs",
        statement=(
            "The activation guide's VeriFinger Standard SDK section lists two "
            "licence names: Fingerprint Extractor, covering "
            "Biometrics.FingerExtraction and the detection and segmentation "
            "components, and Fingerprint Matcher, covering "
            "Biometrics.FingerMatching and MatchingFusion."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Activation.pdf",
    ),
    Observation(
        observation_id="official_sample_obtains_the_two_finger_licences",
        subject="what upstream's own 1:1 code asks for",
        statement=(
            "The verify-finger tutorial obtains the licences "
            "'FingerMatcher,FingerExtractor' from the local licensing service "
            "before constructing anything, and exits if they cannot be obtained."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/verify-finger/src/main/java/"
            "com/neurotec/tutorials/biometrics/VerifyFinger.java"
        ),
    ),
)

CLOSURE_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="finger_data_files_ship_inside_the_archive",
        subject="where the algorithm's models come from",
        statement=(
            "Bin/Data holds 27 Neurotechnology data files, of which two are the "
            "fingerprint ones: Fingers.ndf at 122945738 bytes and "
            "FingersMatching.ndf at 4242028 bytes. Both are inside the pinned "
            "archive; neither is fetched at first use."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Bin/Data/",
    ),
    Observation(
        observation_id="manual_describes_ndf_files_as_algorithm_dependencies",
        subject="what the data files are",
        statement=(
            "The manual states that the biometric engines use Neurotechnology "
            "data file dependencies which are required by the algorithm, that "
            "these files are saved in the SDK's Bin/Data folder, and lists which "
            "data file each modality needs."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="every_archive_member_was_hashed",
        subject="how far the inventory was taken",
        statement=(
            "All 8702 regular files in the archive were decompressed and hashed, "
            "totalling 6796855547 bytes. The inventory is therefore closed over "
            "the archive rather than sampled from it."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}",
    ),
)

INPUT_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="manual_accepts_png_fingerprint_images",
        subject="which containers the official loader reads",
        statement=(
            "The manual states that the technology accepts fingerprint, face and "
            "iris images for further processing as BMP, JPG, PNG or WebP files, "
            "so that almost any third-party capture hardware can be used."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="manual_requires_resolution_on_fingerprint_images",
        subject="whether resolution must be declared",
        statement=(
            "The manual states that an image can have horizontal and vertical "
            "resolution attributes and that they are required for a fingerprint "
            "image, while they do not make sense for a face image."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="manual_uses_500_dpi_as_the_minutia_coordinate_unit",
        subject="the resolution the representation is expressed in",
        statement=(
            "The manual describes each minutia as located by X and Y coordinates "
            "in 500 DPI units, and describes NFIQ 2.0 as optimised for plain "
            "impressions captured at 500 dpi."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="official_sample_loads_an_image_by_file_name_only",
        subject="what upstream's own 1:1 code does to an image",
        statement=(
            "The verify-finger tutorial creates an NFinger, sets its file name "
            "to the image path, adds it to an NSubject and verifies. There is no "
            "crop, no resize, no rotation, no enhancement and no segmentation "
            "step anywhere in it."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/verify-finger/src/main/java/"
            "com/neurotec/tutorials/biometrics/VerifyFinger.java"
        ),
    ),
)

EXTRACTION_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="engine_publishes_the_finger_extraction_settings",
        subject="which extraction settings are externally selectable",
        statement=(
            "The biometric engine publishes FingersExtractionScenario, "
            "FingersTemplateSize, FingersFastExtraction, FingersQualityThreshold, "
            "FingersMinimalMinutiaCount, FingersReturnBinarizedImage, "
            "FingersDeterminePatternClass, FingersDetectLiveness, "
            "FingersLivenessConfidenceThreshold, the three NFIQ calculation "
            "switches and MaximalThreadCount."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="finger_settings_carry_no_documented_default",
        subject="what the manual states about the fingerprint defaults",
        statement=(
            "The manual's parameter tables give each Fingers.* and Matching.* "
            "entry a type and a meaning and state no default value for any of "
            "them. The same tables do state defaults for the Faces.* entries — "
            "'Default: false', 'Default: 90 pixels', 'Default: ntsMedium' — so "
            "the absence on the fingerprint side is a property of the document "
            "rather than of the reading."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="a_different_tutorial_sets_template_size",
        subject="why the archive's tutorials cannot be combined",
        statement=(
            "The enroll-finger-from-image tutorial sets FingersTemplateSize to "
            "NTemplateSize.LARGE before creating a template. The verify-finger "
            "tutorial — the complete 1:1 program this stage qualifies — never "
            "touches that setting, and enroll-finger-from-image never sets the "
            "matching speed that verify-finger does. The two programs are "
            "configured differently, so a profile taking one value from each "
            "would be a configuration neither of them runs."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/enroll-finger-from-image/src/main/"
            "java/com/neurotec/tutorials/biometrics/EnrollFingerFromImage.java"
        ),
    ),
    Observation(
        observation_id="the_authoritative_sample_sets_two_things_only",
        subject="what upstream's own 1:1 program configures",
        statement=(
            "verify-finger sets exactly two engine properties before verifying: "
            "setMatchingThreshold(48) and "
            "setFingersMatchingSpeed(NMatchingSpeed.LOW). The threshold is "
            "discarded by the raw route. Every other setting on the route is "
            "whatever the engine is constructed with, which is a delivered "
            "runtime default and has to be read from a running engine."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=AUTHORITATIVE_ROUTE_SAMPLE_PATH,
    ),
    Observation(
        observation_id="manual_warns_fast_extraction_changes_accuracy",
        subject="a setting whose effect on the score upstream states",
        statement=(
            "FingersFastExtraction is documented as quicker than regular "
            "extraction but as creating a lower-quality template, which can "
            "reduce matching accuracy. It is therefore score-affecting by "
            "upstream's own description."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
)

REPRESENTATION_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="manual_describes_the_proprietary_template_hierarchy",
        subject="what the matcher compares",
        statement=(
            "The manual describes NFTemplate as the fingerprint template and "
            "NTemplate as the container that consolidates a subject's templates, "
            "and states that a packed NTemplate is the piece of information the "
            "matchers should receive."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="official_sample_offers_iso_and_ansi_as_export_formats",
        subject="the standard formats and where they sit in the route",
        statement=(
            "The enroll-finger-from-image tutorial writes an ISO or ANSI record "
            "only when asked for one on the command line, and otherwise reports "
            "the template as proprietary. The verification tutorial exports "
            "neither: it matches the subjects directly."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/enroll-finger-from-image/src/main/"
            "java/com/neurotec/tutorials/biometrics/EnrollFingerFromImage.java"
        ),
    ),
    Observation(
        observation_id="minex_is_a_separate_matching_scenario",
        subject="what interoperable matching would be",
        statement=(
            "NMatchingScenario publishes NotUsed, LatentFinger, "
            "FingerFastMatcherLicense and Minex, the last documented as matching "
            "ISO templates in a MINEX-compliant way. Interoperable matching is "
            "therefore a distinct scenario rather than the default route."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
)

MATCHER_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="engine_publishes_the_matching_settings",
        subject="which matching settings are externally selectable",
        statement=(
            "The biometric engine publishes FingersMatchingSpeed, "
            "FingersMaximalRotation, MatchingThreshold, MatchingScenario, "
            "MatchingWithDetails, MatchingFirstResultOnly and "
            "MatchingMaximalResultCount."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="matching_speed_is_a_documented_accuracy_tradeoff",
        subject="the preset family and what upstream says it costs",
        statement=(
            "NMatchingSpeed publishes Low = 0, Medium = 128 and High = 256, "
            "documented as 'Low matching speed (slower but more accurate)' and "
            "'High matching speed (faster but less accurate)'. The manual adds "
            "that the slow matcher offers low and medium and the fast matcher "
            "offers all three."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="official_sample_sets_matching_speed_explicitly",
        subject="which preset upstream's own 1:1 code selects",
        statement=(
            "The verify-finger tutorial calls "
            "setFingersMatchingSpeed(NMatchingSpeed.LOW) before verifying. It is "
            "an explicit choice in upstream's own working 1:1 example, not a "
            "value fpbench picked."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/verify-finger/src/main/java/"
            "com/neurotec/tutorials/biometrics/VerifyFinger.java"
        ),
    ),
    Observation(
        observation_id="matching_is_a_fusion_over_records",
        subject="how a single score is arrived at",
        statement=(
            "The manual states that matching is performed at the record level "
            "and the resulting scores are fused into a single similarity score, "
            "with the intermediate scores available through NMatchingDetails."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
)

SCORE_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="manual_defines_the_score_as_a_similarity",
        subject="what the number means",
        statement=(
            "The manual states that the result of a comparison is the similarity "
            "score and that a higher score suggests a higher probability that "
            "the feature collections come from the same subject."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="manual_defines_the_score_to_far_transform",
        subject="the scale the score is expressed on",
        statement=(
            "The manual gives the threshold/FAR correspondence explicitly — 0 at "
            "100%, 12 at 10%, 24 at 1%, 36 at 0.1%, 48 at 0.01%, 60 at 0.001%, "
            "72 at 0.0001%, 84 at 0.00001% and 96 at 0.000001% — together with "
            "the formula Threshold = -12 * log10(FAR), FAR expressed as a "
            "fraction. The score is a native quantity on a claimed-FAR scale."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="threshold_is_a_separate_engine_property",
        subject="where the threshold lives",
        statement=(
            "MatchingThreshold is documented as a settable integer property of "
            "the engine — 'Defines the matching threshold. Matching scores below "
            "this value will be ignored' — and the manual describes the "
            "threshold as what maps the score to a yes/no answer. The threshold "
            "is therefore outside the number rather than inside it."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="official_sample_reads_the_score_under_both_outcomes",
        subject="whether the score survives a negative decision",
        statement=(
            "The verify-finger tutorial accepts both NBiometricStatus.OK and "
            "NBiometricStatus.MATCH_NOT_FOUND and reads "
            "getMatchingResults().get(0).getScore() in either case, printing the "
            "score before it prints success or failure. A score below the "
            "threshold is still returned."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/verify-finger/src/main/java/"
            "com/neurotec/tutorials/biometrics/VerifyFinger.java"
        ),
    ),
    Observation(
        observation_id="official_sample_reads_the_score_from_the_reference_side",
        subject="which side carries the result",
        statement=(
            "The tutorial calls verify(referenceSubject, candidateSubject) and "
            "then reads the matching results from referenceSubject. The two "
            "arguments are named reference and candidate, so the API distinguishes "
            "the roles; whether the number depends on which is which is a "
            "question about behaviour, not about naming."
        ),
        source_class=SourceClass.OFFICIAL_SAMPLE_IN_ARCHIVE,
        locator=(
            f"{_ROOT}Tutorials/Biometrics/Java/verify-finger/src/main/java/"
            "com/neurotec/tutorials/biometrics/VerifyFinger.java"
        ),
    ),
)

EXECUTION_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="no_licence_was_activated_here",
        subject="what this stage did not do",
        statement=(
            "No licensing service was started, no trial was activated and no "
            "library was loaded. The archive was inspected as files. Everything "
            "that needs a running licensed engine is therefore unestablished, "
            "and is published as unestablished rather than inferred from the "
            "documentation."
        ),
        source_class=SourceClass.TRANSFER_METADATA,
        locator="the local artifact store under this stage's prefix",
    ),
    Observation(
        observation_id="activation_installs_a_licensing_service",
        subject="what activating would involve",
        statement=(
            "The activation guide describes starting the licensing service — "
            "'pg.exe -i' on Windows, 'sudo ./run_pgd.sh start' on Linux and "
            "macOS — and states that trial products may not be used on a "
            "computer that is simultaneously running licensed Neurotechnology "
            "products. A 30-day clock starts at activation."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Activation.pdf",
    ),
)

NETWORK_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="eula_describes_internet_activation_as_a_licence_check",
        subject="what the network is used for",
        statement=(
            "The agreement defines Internet Activation as storing a licence file "
            "on the computer, which allows the component to run on that "
            "computer after checking the licence over the internet, and states "
            "that an internet connection should be available for a short period "
            "at least once in seven days."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Documentation/SDK License.html",
    ),
    Observation(
        observation_id="download_page_requires_a_constant_connection_for_trials",
        subject="what the trial requires",
        statement=(
            "The download page states that a constant internet connection is "
            "required during SDK evaluation, and the activation guide repeats it "
            "for trial products."
        ),
        source_class=SourceClass.OFFICIAL_DOWNLOAD_PAGE,
        locator=_DOWNLOAD_PAGE,
        http_status=200,
    ),
    Observation(
        observation_id="the_components_are_local_native_libraries",
        subject="where the computation happens",
        statement=(
            "The extraction and matching components are native libraries inside "
            "the archive, and the fingerprint data files they load are inside it "
            "too. The licence agreement's server-side components — Matching "
            "Server, Management Service, Image Processing Service — are separate "
            "licensed components that the 1:1 route does not use."
        ),
        source_class=SourceClass.PINNED_SDK_ARCHIVE,
        locator=f"{_ROOT}Bin/Win64_x64/",
    ),
)

CAPACITY_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="trial_is_thirty_days_with_no_stated_call_quota",
        subject="what the trial licence limits",
        statement=(
            "The activation guide states that all trial versions come with a "
            "30-day trial period and that access ends when it expires, and adds "
            "that trial use requires a constant internet connection and excludes "
            "simultaneous use of licensed products on the same computer. No "
            "API-call quota is stated anywhere in the guide."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Activation.pdf",
    ),
    Observation(
        observation_id="download_page_calls_the_trial_thirty_days",
        subject="what the vendor advertises",
        statement=(
            "The download page offers 30-day trial versions of the biometric "
            "SDKs and states that the trial package allows evaluation on "
            "Windows, Linux, macOS, iOS, Android and ARM Linux."
        ),
        source_class=SourceClass.OFFICIAL_DOWNLOAD_PAGE,
        locator=_DOWNLOAD_PAGE,
        http_status=200,
    ),
)

PROVENANCE_OBSERVATIONS: tuple[Observation, ...] = (
    Observation(
        observation_id="manual_makes_no_statement_about_development_data",
        subject="what upstream discloses about how the algorithm was built",
        statement=(
            "The manual documents the API, the formats and the algorithm's "
            "behaviour, and says nothing about the corpus the fingerprint "
            "algorithm was developed, trained, validated or calibrated on."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
    Observation(
        observation_id="no_pinned_source_mentions_sd300",
        subject="what the pinned sources say about this benchmark's cohort",
        statement=(
            "Neither the manual, the activation guide, the licence agreement nor "
            "the archive's own text files mentions SD300 in any role. That is an "
            "absence of evidence about development overlap and is recorded as "
            "such; it is not a statement that the dataset was not used."
        ),
        source_class=SourceClass.PINNED_DOCUMENTATION,
        locator=f"{_ROOT}Documentation/Neurotechnology Biometric SDK.pdf",
    ),
)


# ------------------------------------------------------------------ the settings

#: Every externally selectable extraction setting the pinned manual publishes for
#: fingerprints, with what is and is not known about each value.
PUBLISHED_EXTRACTOR_SETTINGS: tuple[PublishedSetting, ...] = (
    # ``NTemplateSize.LARGE`` appears in the *enrolment* tutorial, which is a
    # different program from the one being qualified. The verification tutorial
    # never touches this setting, so its value on the qualified route is whatever
    # the engine is constructed with — a delivered runtime default to be read,
    # not a value borrowed from a neighbour (docs/adr/0105).
    PublishedSetting(
        name="FingersTemplateSize",
        published_meaning="defines the size of the biometric template",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersExtractionScenario",
        published_meaning="defines the fingerprint extraction scenario",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersFastExtraction",
        published_meaning=(
            "quicker than regular extraction, but creates a lower-quality "
            "template which can reduce matching accuracy"
        ),
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersQualityThreshold",
        published_meaning=(
            "fingerprints with quality below this value will not be accepted"
        ),
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersMinimalMinutiaCount",
        published_meaning="defines the minimal fingerprint minutia count",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersDetectTips",
        published_meaning="defines whether only a tip of the fingerprint is present",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersDeterminePatternClass",
        published_meaning=(
            "whether the fingerprint pattern class should be determined"
        ),
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="FingersReturnBinarizedImage",
        published_meaning="whether a binarized image should be returned",
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="FingersCalculateNfiq",
        published_meaning="whether the NFIQ 1.0 quality value should be calculated",
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="FingersCalculateNfiq2",
        published_meaning="whether the NFIQ 2.0 quality value should be calculated",
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="FingersCalculateNfiq21",
        published_meaning="whether the NFIQ 2.1 quality value should be calculated",
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="FingersDetectLiveness",
        published_meaning="enables fingerprint presentation attack detection",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="FingersLivenessConfidenceThreshold",
        published_meaning="the fingerprint liveness confidence value",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="MaximalThreadCount",
        published_meaning="the maximum number of threads in the engine",
        is_score_affecting=False,
    ),
)

#: The matching side of the same inventory.
PUBLISHED_MATCHER_SETTINGS: tuple[PublishedSetting, ...] = (
    PublishedSetting(
        name="FingersMatchingSpeed",
        published_meaning=(
            "Low (slower but more accurate), Medium, or High (faster but less "
            "accurate)"
        ),
        is_score_affecting=True,
        official_sample_value="NMatchingSpeed.LOW",
        official_sample_locator=AUTHORITATIVE_ROUTE_SAMPLE_PATH,
    ),
    PublishedSetting(
        name="FingersMaximalRotation",
        published_meaning="the maximal rotation of the fingerprint",
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="MatchingScenario",
        published_meaning=(
            "NotUsed, LatentFinger, FingerFastMatcherLicense, or Minex for "
            "MINEX-compliant ISO template matching"
        ),
        is_score_affecting=True,
    ),
    PublishedSetting(
        name="MatchingWithDetails",
        published_meaning="whether the results include the per-record details",
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="MatchingMaximalResultCount",
        published_meaning="the maximum number of returned matching results",
        is_score_affecting=False,
    ),
    PublishedSetting(
        name="MatchingFirstResultOnly",
        published_meaning="whether matching stops at the first positive result",
        is_score_affecting=False,
    ),
)

#: What the pinned manual establishes about the number itself. Recorded as
#: observations that the score gate then reads, rather than as a contract asserted
#: here.
DOCUMENTED_SCORE_TYPE = "integer"
DOCUMENTED_SCORE_DIRECTION = "HIGHER_IS_MORE_SIMILAR"
DOCUMENTED_SCORE_TRANSFORM = (
    "a native similarity score on a claimed-FAR scale: upstream publishes "
    "score = -12 * log10(FAR) with FAR as a fraction, so 12 is a claimed 10% "
    "FAR, 48 a claimed 0.01% and 96 a claimed 0.000001%. fpbench performs no "
    "conversion of its own in either direction (spec section 24)"
)

#: The anchor points upstream tabulates, as ``(claimed FAR percent, score)``.
#: Published as the vendor's own correspondence table, and never used to convert
#: anything.
DOCUMENTED_SCORE_ANCHORS: tuple[tuple[str, int], ...] = (
    ("100%", 0),
    ("10%", 12),
    ("1%", 24),
    ("0.1%", 36),
    ("0.01%", 48),
    ("0.001%", 60),
    ("0.0001%", 72),
    ("0.00001%", 84),
    ("0.000001%", 96),
)

#: The 1:1 route as upstream's own tutorial performs it, step by step. This is
#: what a Stage 11B adapter would have to reproduce exactly.
OFFICIAL_ONE_TO_ONE_ROUTE: tuple[str, ...] = (
    "obtain the FingerExtractor and FingerMatcher licences",
    "construct one NBiometricClient",
    "create an NSubject per side, each holding one NFinger set to an image file",
    "select the score-affecting settings the sample selects",
    "call verify(reference, candidate)",
    "accept OK and MATCH_NOT_FOUND alike",
    "read the integer score from the reference subject's first matching result",
    "stop there — the decision the sample prints after that is not part of the "
    "raw route",
)

#: Containers the official loader reads, per the pinned manual.
SUPPORTED_IMAGE_CONTAINERS: tuple[str, ...] = ("BMP", "JPG", "PNG", "WebP")


@dataclass(frozen=True, slots=True)
class TrialTerms:
    """The evaluation licence, exactly as the pinned documentation states it.

    Unlike Stage 10B's candidate there is a number here — thirty days — and the
    absence of an API-call quota is recorded as an absence in the documentation
    rather than as permission (spec section 35).
    """

    duration_days: int
    api_call_quota_stated: bool
    requires_constant_internet: bool
    excludes_simultaneous_licensed_products: bool
    activation_mandatory: bool
    activation_transmits_personal_information: bool
    platform_bound: bool


TRIAL_TERMS = TrialTerms(
    duration_days=30,
    api_call_quota_stated=False,
    requires_constant_internet=True,
    excludes_simultaneous_licensed_products=True,
    activation_mandatory=True,
    activation_transmits_personal_information=False,
    platform_bound=True,
)


# ------------------------------------------------------------------ the record


def all_observations() -> tuple[Observation, ...]:
    """Every recorded observation, in one sequence, in declaration order."""
    return (
        *ACQUISITION_OBSERVATIONS,
        *IDENTITY_OBSERVATIONS,
        *LICENSE_OBSERVATIONS,
        *CLOSURE_OBSERVATIONS,
        *INPUT_OBSERVATIONS,
        *EXTRACTION_OBSERVATIONS,
        *REPRESENTATION_OBSERVATIONS,
        *MATCHER_OBSERVATIONS,
        *SCORE_OBSERVATIONS,
        *EXECUTION_OBSERVATIONS,
        *NETWORK_OBSERVATIONS,
        *CAPACITY_OBSERVATIONS,
        *PROVENANCE_OBSERVATIONS,
    )


def observation(observation_id: str) -> Observation:
    """One observation by id."""
    for item in all_observations():
        if item.observation_id == observation_id:
            return item
    raise VeriFingerObservationError(
        f"{observation_id!r} is not a recorded observation"
    )


def observation_rows(items: tuple[Observation, ...]) -> list[Mapping[str, Any]]:
    """The published shape of a group of observations."""
    return [
        {
            "observation_id": item.observation_id,
            "subject": item.subject,
            "statement": item.statement,
            "source_class": item.source_class.value,
            "source_is_artifact_evidence": item.source_class.is_artifact_evidence,
            "locator": item.locator,
            "retrieval": item.retrieval.value,
            "http_status": item.http_status,
            "observed_utc": item.observed_utc,
        }
        for item in items
    ]


def setting_rows(items: tuple[PublishedSetting, ...]) -> list[Mapping[str, Any]]:
    """The published shape of a group of settings.

    ``chosen_value`` is present and null on every row. A profile is frozen by
    choosing a value *with* a provenance, and no value may be chosen here: the
    gates that would choose them are gates about a running engine.
    """
    return [
        {
            "setting_name": item.name,
            "published_meaning": item.published_meaning,
            "is_score_affecting": item.is_score_affecting,
            "documented_default": item.documented_default,
            "official_sample_value": item.official_sample_value,
            "delivered_runtime_default": None,
            "chosen_value": None,
            "provenance": item.provenance.value,
            "provenance_is_upstream_authority": (
                item.provenance.is_upstream_authority
            ),
        }
        for item in items
    ]


def observations_fingerprint() -> str:
    """Identify the observations this preflight was decided on.

    A change to any recorded fact changes this digest, and therefore changes the
    preflight fingerprint above it. Re-reading the artifact and finding something
    different is a new preflight, not an amendment to this one.
    """
    return stable_hash(
        {
            "schema": "stage_11a_observations_v1",
            "observed_utc": OBSERVED_UTC,
            "acquired_utc": ACQUIRED_UTC,
            "observations": [
                (
                    item.observation_id,
                    item.source_class.value,
                    item.locator,
                    item.retrieval.value,
                    item.statement,
                )
                for item in all_observations()
            ],
            "artifacts": [
                (
                    item.artifact_id,
                    item.route.value,
                    item.filename,
                    item.size_bytes,
                    item.sha256,
                    item.declared_version,
                )
                for item in ACQUIRED_ARTIFACTS
            ],
            "rejected_routes": [
                (item.route.value, item.filename, item.declared_version)
                for item in REJECTED_ROUTES
            ],
            "archive": [ARCHIVE_MEMBER_COUNT, ARCHIVE_UNCOMPRESSED_BYTES],
            "cited_members": [
                (item.relative_path, item.sha256, item.size_bytes)
                for item in (*CITED_ARCHIVE_MEMBERS, *FINGER_DATA_FILES)
            ],
            "native_libraries": [
                (item.relative_path, item.sha256, item.product_version)
                for item in WINDOWS_X64_NATIVE_LIBRARIES
            ],
            "extractor_settings": [
                (
                    item.name,
                    item.documented_default,
                    item.official_sample_value,
                    item.is_score_affecting,
                )
                for item in PUBLISHED_EXTRACTOR_SETTINGS
            ],
            "matcher_settings": [
                (
                    item.name,
                    item.documented_default,
                    item.official_sample_value,
                    item.is_score_affecting,
                )
                for item in PUBLISHED_MATCHER_SETTINGS
            ],
            "score": [
                DOCUMENTED_SCORE_TYPE,
                DOCUMENTED_SCORE_DIRECTION,
                list(DOCUMENTED_SCORE_ANCHORS),
            ],
            "trial": [
                TRIAL_TERMS.duration_days,
                TRIAL_TERMS.api_call_quota_stated,
                TRIAL_TERMS.requires_constant_internet,
            ],
        },
        length=64,
    )
