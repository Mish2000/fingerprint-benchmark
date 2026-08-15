"""What was actually retrieved about FingerCell, and what each retrieval is worth.

Two registers, and the difference between them is the whole point of this module.

**Public observations.** What Neurotechnology states publicly today: that a
FingerCell 3.3 trial exists, how large it is, how long it runs, which platforms
it targets, and which release is current. Every one carries the locator it was
read from and the date it was read, and every one is marked as what it is — an
*indication of what to look for in the archive*, never a value Stage 13A may
freeze. A product page describes a product; only the delivered bytes describe
*these* bytes (docs/adr/0113).

**Delivered observations.** What the archive itself says, once it is here. These
carry an archive-relative member path instead of a URL, and they are authorities:
``Revision.txt`` settles the revision, ``Include/FingerCell.h`` settles the API,
the shipped tutorials settle the official route, and ``SDK License.html`` settles
what the terms permit. Where a public page and a delivered member disagree, the
delivered member wins and the disagreement is published as a finding.

Every delivered observation also records *how* it was obtained. That is not
bookkeeping: the delivered licence forbids reverse engineering, decompilation and
disassembly, so a fact read out of a text file, a header or a sample source is on
a different footing from one inferred by looking at a compiled module. This
module marks the difference, and the gate engine treats the second kind as a
question to put to the runtime rather than as an answer (docs/adr/0120).

Nothing here downloads anything, activates anything, loads a runtime, or holds a
credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from fpbench.core.fingercell_preflight_errors import FingerCellObservationError
from fpbench.core.serialization import stable_hash

__all__ = [
    "RetrievalStatus",
    "ObservationWeight",
    "DeliveredEvidenceMethod",
    "PublicObservation",
    "DeliveredObservation",
    "PUBLIC_OBSERVATIONS",
    "DELIVERED_OBSERVATIONS",
    "OFFICIAL_LOCATOR",
    "OFFICIAL_LOCATOR_IS_UNTOKENIZED",
    "ADVERTISED_ARCHIVE_SIZE_BYTES",
    "ADVERTISED_TRIAL_DAYS",
    "ADVERTISED_PLATFORMS",
    "PUBLIC_NETWORK_CLAIM",
    "DELIVERED_NETWORK_CLAIM",
    "NETWORK_CLAIMS_AGREE",
    "public_rows",
    "delivered_rows",
    "observations_fingerprint",
]


class RetrievalStatus(str, Enum):
    """Whether the locator behind a statement was actually fetched.

    ``NOT_RETRIEVED`` exists so that a statement nobody checked can be recorded
    as one. An observation that reports what a page says without the page having
    been read is not an observation.
    """

    RETRIEVED = "RETRIEVED"
    NOT_RETRIEVED = "NOT_RETRIEVED"
    UNREACHABLE = "UNREACHABLE"


class ObservationWeight(str, Enum):
    """What a recorded statement may be used for."""

    #: Shapes the question. Never settles a gate.
    INDICATION_ONLY = "INDICATION_ONLY"

    #: Settles a value, because it came out of the delivered archive.
    DELIVERED_AUTHORITY = "DELIVERED_AUTHORITY"


class DeliveredEvidenceMethod(str, Enum):
    """How a delivered fact was obtained from the archive.

    Every member reads something the vendor ships *to be read*: a revision stamp,
    a C header, a sample source, a delivered build file, an HTML licence, a
    documentation PDF, or the directory layout itself. Nothing is translated and
    nothing is inspected that was not written for a developer to open.

    There is deliberately no member for reading a compiled module. Inspecting a
    shipped binary's import table or its embedded literals would sit close to a
    line the delivered licence draws — it forbids reverse engineering,
    decompilation and disassembly — and it answers a weaker question than it
    appears to: a static import table describes what a module *can* load, not
    what a process does load, and a string proves a name exists somewhere in a
    binary, not that it is a supported, externally-selectable property.

    Both questions it was reached for have supported answers. The link closure is
    named outright by the delivered build files, and the settings surface is
    named by the delivered documentation and headers and confirmed by the SDK's
    own property enumeration at runtime (docs/adr/0120).
    """

    DELIVERED_TEXT_FILE = "DELIVERED_TEXT_FILE"
    DELIVERED_HEADER = "DELIVERED_HEADER"
    DELIVERED_SAMPLE_SOURCE = "DELIVERED_SAMPLE_SOURCE"
    DELIVERED_BUILD_FILE = "DELIVERED_BUILD_FILE"
    DELIVERED_DOCUMENTATION = "DELIVERED_DOCUMENTATION"
    DIRECTORY_LISTING = "DIRECTORY_LISTING"

    @property
    def may_settle_a_gate(self) -> bool:
        """Every delivered method is an authority. The one that was not is gone."""
        return True


@dataclass(frozen=True, slots=True)
class PublicObservation:
    """One statement read from a public Neurotechnology page."""

    observation_id: str
    locator: str
    statement: str
    retrieval: RetrievalStatus
    retrieved_utc: str | None
    what_it_indicates: str
    weight: ObservationWeight = ObservationWeight.INDICATION_ONLY

    def __post_init__(self) -> None:
        for name in ("observation_id", "locator", "statement", "what_it_indicates"):
            if not str(getattr(self, name)).strip():
                raise FingerCellObservationError(
                    f"{self.observation_id or '<observation>'}: {name} is empty"
                )
        if self.retrieval is RetrievalStatus.RETRIEVED and not self.retrieved_utc:
            raise FingerCellObservationError(
                f"{self.observation_id}: a retrieved page records when it was read"
            )
        if self.retrieval is not RetrievalStatus.RETRIEVED and self.retrieved_utc:
            raise FingerCellObservationError(
                f"{self.observation_id}: a page that was not retrieved carries no "
                "retrieval date"
            )
        if self.weight is not ObservationWeight.INDICATION_ONLY:
            raise FingerCellObservationError(
                f"{self.observation_id}: a public page is an indication of what to "
                "look for in the archive and never an authority over it "
                "(docs/adr/0113)"
            )


@dataclass(frozen=True, slots=True)
class DeliveredObservation:
    """One fact read out of the delivered archive.

    ``member`` is a path *inside* the unpacked archive, never a path on a
    machine. ``method`` records how it was read, and a fact obtained from a
    compiled module's metadata is explicitly not an authority.
    """

    observation_id: str
    member: str
    statement: str
    method: DeliveredEvidenceMethod
    what_it_settles: str

    def __post_init__(self) -> None:
        for name in ("observation_id", "member", "statement", "what_it_settles"):
            if not str(getattr(self, name)).strip():
                raise FingerCellObservationError(
                    f"{self.observation_id or '<observation>'}: {name} is empty"
                )
        if self.member.startswith("/") or ":" in self.member:
            raise FingerCellObservationError(
                f"{self.observation_id}: {self.member!r} is not an archive-relative "
                "member; a published path must never name a machine"
            )

    @property
    def weight(self) -> ObservationWeight:
        if self.method.may_settle_a_gate:
            return ObservationWeight.DELIVERED_AUTHORITY
        return ObservationWeight.INDICATION_ONLY


# ------------------------------------------------------------- the public pages

#: The day the public pages below were read.
_READ_UTC = "2026-08-14"

#: The official download locator, as the vendor publishes it. Recorded because
#: it is stable and untokenized: it carries no signature, no expiry and no
#: session, so it names the artifact rather than one fetch of it.
OFFICIAL_LOCATOR = (
    "https://download.neurotechnology.com/FingerCell_3_3_SDK_2021-10-13.zip"
)
OFFICIAL_LOCATOR_IS_UNTOKENIZED = True

#: What the download page advertises. Confirmed against the response headers at
#: retrieval time, which is why the byte count is here rather than an approximate
#: "486 MB".
ADVERTISED_ARCHIVE_SIZE_BYTES = 509_667_736
ADVERTISED_TRIAL_DAYS = 30
ADVERTISED_PLATFORMS: tuple[str, ...] = (
    "Microsoft Windows",
    "Linux x86",
    "Linux x86-64",
)

#: The public page's network claim, and the delivered documentation's. They agree
#: on trial products, which is worth recording because the same documentation
#: states a much weaker requirement — a connection once every seven days — for
#: *purchased* internet licences. Reading the weaker one and planning around it
#: would be planning around the wrong licence type.
PUBLIC_NETWORK_CLAIM = "constant Internet connection required during evaluation"
DELIVERED_NETWORK_CLAIM = (
    "to use a trial product a constant internet connection is required"
)
NETWORK_CLAIMS_AGREE = True

PUBLIC_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="trial_is_published",
        locator="https://www.neurotechnology.com/download.html",
        statement=(
            "Neurotechnology publishes a direct FingerCell 3.3 SDK trial download "
            "of 509,667,736 bytes, described as a 30 day trial for Microsoft "
            "Windows and Linux on x86 and x86-64, requiring a constant internet "
            "connection during evaluation"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "that acquisition is a self-service action this project can perform "
            "itself, which is why Stage 13A has no vendor-pending state at all; "
            "the size and duration are what the delivered archive and its terms "
            "are then checked against"
        ),
    ),
    PublicObservation(
        observation_id="current_release",
        locator="https://www.neurotechnology.com/release-notes-fingercell-30.html",
        statement=(
            "the current FingerCell release is dated October 13 2021, with product "
            "revision 20211013 and revision hash "
            "394e593011b1b1dca288371e0af499198f4a77d1"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "which revision the delivered Revision.txt is expected to report; the "
            "revision hash is the vendor's own source identifier and is never a "
            "digest of anything this project computed"
        ),
    ),
    PublicObservation(
        observation_id="embedded_target",
        locator="https://www.neurotechnology.com/fingercell-technical-specifications.html",
        statement=(
            "the FingerCell technical specifications state resource and speed "
            "figures for embedded targets, using 234x332 at 500 ppi and 180x256 at "
            "385 ppi as the image sizes those figures are quoted for"
        ),
        retrieval=RetrievalStatus.NOT_RETRIEVED,
        retrieved_utc=None,
        what_it_indicates=(
            "that published speed and memory numbers describe a microcontroller at "
            "a particular image size, so neither the numbers nor the size may be "
            "carried into this benchmark: they are not a required input size and "
            "not an estimate for this host (docs/adr/0117)"
        ),
    ),
)


# --------------------------------------------------------- the delivered archive

DELIVERED_OBSERVATIONS: tuple[DeliveredObservation, ...] = (
    DeliveredObservation(
        observation_id="delivered_revision",
        member="FingerCell_3_3_SDK/Revision.txt",
        statement=(
            "the archive reports product revision number 20211013 and product "
            "revision hash 394e593011b1b1dca288371e0af499198f4a77d1"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_TEXT_FILE,
        what_it_settles=(
            "the exact product revision, and that it agrees with the public "
            "release notes rather than merely being assumed to"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_match_api",
        member="FingerCell_3_3_SDK/Include/FingerCell.h",
        statement=(
            "FingerCellMatch takes a FingerCell handle, a reference record handle "
            "and a candidate record handle, and writes the matching score through "
            "an NInt out-parameter"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_HEADER,
        what_it_settles=(
            "the raw 1:1 score route, its native signed-integer type, and the "
            "vendor's own names for the two sides of a comparison - which is where "
            "the frozen pair binding takes its words from"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_extract_api",
        member="FingerCell_3_3_SDK/Include/FingerCell.h",
        statement=(
            "FingerCellExtract takes a FingerCell handle and an image handle and "
            "writes one record buffer through an out-parameter"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_HEADER,
        what_it_settles=(
            "that one image produces one template through one call, with no "
            "record container and no multi-finger structure in the route"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_score_direction",
        member="FingerCell_3_3_SDK/Include/FingerCell.hpp",
        statement=(
            "the Match wrapper documents its return value as a matching score for "
            "which a bigger score means the fingerprints are more similar"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_HEADER,
        what_it_settles=(
            "the score direction, from the delivered binding rather than from a "
            "product page"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_template_formats",
        member="FingerCell_3_3_SDK/Include/FingerCell.h",
        statement=(
            "the delivered template format enumeration is Proprietary=0, Iso=1, "
            "Moc=2, Unknown=3"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_HEADER,
        what_it_settles=(
            "that the proprietary format is the zero value, and that ISO and MOC "
            "are separate exports this stage refuses as the compared "
            "representation"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_typed_settings",
        member="FingerCell_3_3_SDK/Include/FingerCell.hpp",
        statement=(
            "the delivered C++ binding exposes exactly three typed properties - "
            "ImageQualityThreshold with a documented range of 0 to 100 and default "
            "60, MatchingAlgorithm with a documented range of 0 to 100 and default "
            "0, and TemplateFormat - and exposes them through a generic named "
            "property mechanism inherited from the common object base"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_HEADER,
        what_it_settles=(
            "three of the score-affecting settings and their documented defaults, "
            "and - more importantly - that the typed surface is narrower than the "
            "property surface, so a closure built from the header alone would be "
            "incomplete"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_merge_api",
        member="FingerCell_3_3_SDK/Include/FingerCell.h",
        statement=(
            "the delivered API offers template merging across a bounded number of "
            "source records"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_HEADER,
        what_it_settles=(
            "that merging is a real and supported upstream scenario, and therefore "
            "that refusing it here is a deliberate protocol choice rather than an "
            "absence"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_official_route",
        member=(
            "FingerCell_3_3_SDK/Tutorials/FingerCell/CPP/FCVerifyFingerCPP/"
            "FCVerifyFingerCPP.cpp"
        ),
        statement=(
            "the official verification tutorial obtains a licence for the component "
            "named FingerCell, constructs one FingerCell object, and prints the "
            "integer returned by Match on two record buffers, applying no threshold "
            "and making no decision"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_SAMPLE_SOURCE,
        what_it_settles=(
            "the official 1:1 route end to end, that the score is readable without "
            "any decision, and that the entitlement obtained is FingerCell's own "
            "rather than a general biometric one"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_extraction_route",
        member=(
            "FingerCell_3_3_SDK/Tutorials/FingerCell/CPP/FCEnrollFingerFromImageCPP/"
            "FCEnrollFingerFromImageCPP.cpp"
        ),
        statement=(
            "the official extraction tutorial loads an image through the delivered "
            "image loader and passes it directly to Extract, with no cropping, "
            "resizing or enhancement of any kind between the file and the extractor"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_SAMPLE_SOURCE,
        what_it_settles=(
            "that the upstream route performs no preprocessing outside the SDK, so "
            "any that fpbench added would be fpbench's own"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_samples_by_binding",
        member="FingerCell_3_3_SDK/Samples",
        statement=(
            "the archive ships FingerCell samples for C++ on the desktop and for "
            "Java on Android, and ships no desktop Java sample and no C# sample "
            "for FingerCell; the FingerCell tutorials are C++ only"
        ),
        method=DeliveredEvidenceMethod.DIRECTORY_LISTING,
        what_it_settles=(
            "the binding selection. The engineering preference was Java, "
            "conditional on a complete and suitable sample existing for it; the "
            "only delivered Java sample targets Android, which is a different "
            "platform and a different licensing route from the Windows and Linux "
            "x86-64 target this benchmark runs on (docs/adr/0116)"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_bindings_present",
        member="FingerCell_3_3_SDK/Bin",
        statement=(
            "the archive ships a FingerCell native module and import library per "
            "platform, a FingerCell Java binding jar, and FingerCell assemblies for "
            "both .NET Framework and .NET Standard"
        ),
        method=DeliveredEvidenceMethod.DIRECTORY_LISTING,
        what_it_settles=(
            "that all three candidate bindings are genuinely shipped, so the "
            "selection is decided by the sample and tutorial coverage rather than "
            "by availability"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_terms_permit_testing",
        member="FingerCell_3_3_SDK/Documentation/SDK License.html",
        statement=(
            "the delivered licence agreement grants a personal, non-exclusive "
            "licence to use the SDK for the purpose of designing, developing, "
            "testing and distributing licensee products, and restricts reverse "
            "engineering, decompilation, disassembly, rental, removal of "
            "proprietary notices and transfer of rights; it states no restriction "
            "on publishing measurements obtained with the SDK"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_DOCUMENTATION,
        what_it_settles=(
            "the terms Stage 8E is applied to. The grant covers local testing, and "
            "the absence of a publication restriction is recorded as an absence "
            "that was looked for rather than as a permission that was assumed"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_trial_terms",
        member="FingerCell_3_3_SDK/Documentation/Activation.pdf",
        statement=(
            "the delivered activation guide states that trial products allow a 30 "
            "day trial period, that a constant internet connection is required to "
            "use a trial product, and that the trial must be activated - by a "
            "wizard on Windows or manually - before use"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_DOCUMENTATION,
        what_it_settles=(
            "that activation is a distinct, deliberate act rather than a "
            "side-effect of unpacking, which is what makes it possible to build "
            "and compile the qualification bridge before any clock starts "
            "(docs/adr/0115)"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_trial_flag",
        member="FingerCell_3_3_SDK/Bin/Licenses/TrialFlag.txt",
        statement=(
            "the archive ships a trial flag file, set to TRUE, which the delivered "
            "samples and tutorials read to decide whether to run in trial mode"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_TEXT_FILE,
        what_it_settles=(
            "that trial mode is selected by the delivered material itself, so the "
            "qualification bridge follows the same switch the official samples do "
            "rather than inventing a licensing path"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_link_closure",
        member=(
            "FingerCell_3_3_SDK/Tutorials/FingerCell/CPP/FCVerifyFingerCPP/Makefile"
        ),
        statement=(
            "the delivered tutorial build links exactly four Neurotechnology "
            "libraries - FingerCell, NMedia, NCore and NLicensing - and the "
            "matching project file names the same four import libraries against "
            "the 64-bit library directory and the delivered include directory"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_BUILD_FILE,
        what_it_settles=(
            "the runtime closure of the official 1:1 route, stated by upstream's "
            "own build rather than inferred from a compiled module. The general "
            "biometrics module that carries the vendor's other fingerprint engine "
            "is not among them, which is what the contamination claim rests on "
            "(docs/adr/0114, docs/adr/0120)"
        ),
    ),
    DeliveredObservation(
        observation_id="delivered_documented_settings",
        member="FingerCell_3_3_SDK/Documentation/FingerCell.pdf",
        statement=(
            "the delivered documentation gives the extractor's algorithm "
            "parameters and their defaults - a maximal and a minimal minutia "
            "count, a large-template switch, the template format - alongside the "
            "image quality threshold and the matching algorithm the binding "
            "exposes directly"
        ),
        method=DeliveredEvidenceMethod.DELIVERED_DOCUMENTATION,
        what_it_settles=(
            "that the externally-selectable settings surface is wider than the "
            "three typed accessors the C++ binding provides, so the closure gate "
            "enumerates a constructed engine through the supported property "
            "mechanism rather than ticking off the typed API. What it does not do "
            "is license a hunt through implementation internals: the gate closes "
            "settings upstream documents or exposes, not every name inside a "
            "module (docs/adr/0118)"
        ),
    ),
)


def public_rows() -> tuple[Mapping[str, Any], ...]:
    """The public register, as published rows."""
    return tuple(
        {
            "observation_id": item.observation_id,
            "locator": item.locator,
            "statement": item.statement,
            "retrieval": item.retrieval.value,
            "retrieved_utc": item.retrieved_utc,
            "what_it_indicates": item.what_it_indicates,
            "weight": item.weight.value,
        }
        for item in PUBLIC_OBSERVATIONS
    )


def delivered_rows() -> tuple[Mapping[str, Any], ...]:
    """The delivered register, as published rows."""
    return tuple(
        {
            "observation_id": item.observation_id,
            "member": item.member,
            "statement": item.statement,
            "method": item.method.value,
            "may_settle_a_gate": item.method.may_settle_a_gate,
            "what_it_settles": item.what_it_settles,
            "weight": item.weight.value,
        }
        for item in DELIVERED_OBSERVATIONS
    )


def observations_fingerprint() -> str:
    """One digest over both registers, so the marker pins what was known."""
    return stable_hash(
        {
            "schema": "stage_13a_observations_v1",
            "public": [dict(row) for row in public_rows()],
            "delivered": [dict(row) for row in delivered_rows()],
        },
        length=64,
    )


def _require_no_public_observation_settles_anything() -> None:
    for item in PUBLIC_OBSERVATIONS:
        if item.weight is not ObservationWeight.INDICATION_ONLY:
            raise FingerCellObservationError(  # pragma: no cover - constructor bites
                f"{item.observation_id} claims authority from a public page"
            )


def _require_delivered_ids_are_unique() -> None:
    ids = [item.observation_id for item in DELIVERED_OBSERVATIONS]
    duplicated = sorted({name for name in ids if ids.count(name) > 1})
    if duplicated:
        raise FingerCellObservationError(
            f"{duplicated} is recorded twice; two rows with one id would let a "
            "later edit change which one a reader saw"
        )


_require_no_public_observation_settles_anything()
_require_delivered_ids_are_unique()
