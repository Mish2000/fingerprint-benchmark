"""What was actually retrieved about Griaule, and what each retrieval is worth.

Two registers, and the difference between them is the whole point of this module.

**Route observations.** Every official Griaule route this project walked while
looking for the package: what was fetched, on what date, and what was found
there. These settle one thing only — whether the package can be obtained without
asking — and they settle it by exhaustion rather than by assertion.

**Product observations.** What Griaule's documentation site states about the GBS
Fingerprint SDK today: that it requires a licence and is distributed with a
90-day trial, that three builds exist, that extraction is limited to 500 x 500
pixels and larger images are cropped, that the new API is ``GrExtract`` and
``GrVerify`` with ``GrSetVerifyParameters``/``GrGetVerifyParameters`` beside
them, that the default verification threshold is 20 and the default rotation
tolerance is -1, and that BMP is a supported image container. Every one carries
the locator it was read from and the date it was read, and every one is marked as
what it is — an *indication of what to look for in the package*, never a value
Stage 14A may settle a gate from (docs/adr/0110).

That marking is not a formality here. The public page is undated, describes
Windows 7 through 10 as its compatibility target, and documents a migration from
a 2009 product. It is a fair description of the product line and it is not
evidence about the bytes anybody would receive today.

Nothing here downloads anything, activates anything, loads a library, or holds a
credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from fpbench.core.griaule_preflight_errors import GriauleObservationError
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage14a_griaule_identity import LocatorCategory

__all__ = [
    "RetrievalStatus",
    "ObservationWeight",
    "RouteOutcome",
    "ProductObservation",
    "OfficialRoute",
    "RefusedRouteCategory",
    "PRODUCT_OBSERVATIONS",
    "OFFICIAL_ROUTES",
    "REFUSED_ROUTE_CATEGORIES",
    "SELF_SERVICE_LOCATOR_FOUND",
    "NAMED_VENDOR_CONTACT_ROUTES",
    "ADVERTISED_TRIAL_DAYS",
    "ADVERTISED_BUILDS",
    "ADVERTISED_VERSION",
    "WHAT_WOULD_CHANGE_THE_STATUS",
    "product_rows",
    "route_rows",
    "refused_rows",
    "observations_fingerprint",
]


class RetrievalStatus(str, Enum):
    """Whether the locator behind a statement was actually fetched.

    ``NOT_RETRIEVED`` exists so that a route nobody checked can be recorded as
    one. A route reported without having been fetched is not an observation.

    ``BLOCKED`` is its own state and is not a synonym for ``UNREACHABLE``: a host
    that answers an automated client with a refusal is a host that is up. Reading
    one as "no such route exists" would turn a bot filter into a finding about
    the vendor.
    """

    RETRIEVED = "RETRIEVED"
    NOT_RETRIEVED = "NOT_RETRIEVED"
    UNREACHABLE = "UNREACHABLE"
    BLOCKED = "BLOCKED"


class ObservationWeight(str, Enum):
    """What a recorded statement may be used for."""

    #: Shapes the question. Never settles a gate.
    INDICATION_ONLY = "INDICATION_ONLY"

    #: Settles a value, because it came out of the delivered package.
    DELIVERED_AUTHORITY = "DELIVERED_AUTHORITY"


class RouteOutcome(str, Enum):
    """What walking one official route produced."""

    #: The route hands over a package without asking anybody.
    PACKAGE_OFFERED = "PACKAGE_OFFERED"

    #: The route exists, is about this product, and offers no package.
    NO_PACKAGE_OFFERED = "NO_PACKAGE_OFFERED"

    #: The route is a way of asking a person for one.
    CONTACT_ROUTE_ONLY = "CONTACT_ROUTE_ONLY"

    #: The route needs an account this project does not hold.
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"

    #: The route no longer exists.
    RETIRED_BY_VENDOR = "RETIRED_BY_VENDOR"

    #: The vendor answered and declined.
    REFUSED_BY_VENDOR = "REFUSED_BY_VENDOR"

    @property
    def settles_acquisition(self) -> bool:
        """Whether this outcome alone would end the acquisition question."""
        return self in (RouteOutcome.PACKAGE_OFFERED, RouteOutcome.REFUSED_BY_VENDOR)


@dataclass(frozen=True, slots=True)
class ProductObservation:
    """One statement read from a public Griaule page."""

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
                raise GriauleObservationError(
                    f"{self.observation_id or '<observation>'}: {name} is empty"
                )
        if self.retrieval is RetrievalStatus.RETRIEVED and not self.retrieved_utc:
            raise GriauleObservationError(
                f"{self.observation_id}: a retrieved page records when it was read"
            )
        if self.retrieval is not RetrievalStatus.RETRIEVED and self.retrieved_utc:
            raise GriauleObservationError(
                f"{self.observation_id}: a page that was not retrieved carries no "
                "retrieval date"
            )
        if self.weight is not ObservationWeight.INDICATION_ONLY:
            raise GriauleObservationError(
                f"{self.observation_id}: a public page is an indication of what to "
                "look for in the package and never an authority over it "
                "(docs/adr/0110)"
            )

    def as_row(self) -> Mapping[str, Any]:
        return {
            "observation_id": self.observation_id,
            "locator": self.locator,
            "statement": self.statement,
            "retrieval": self.retrieval.value,
            "retrieved_utc": self.retrieved_utc,
            "what_it_indicates": self.what_it_indicates,
            "weight": self.weight.value,
        }


@dataclass(frozen=True, slots=True)
class OfficialRoute:
    """One official Griaule route, walked and recorded."""

    route_id: str
    locator: str
    category: LocatorCategory
    description: str
    retrieval: RetrievalStatus
    retrieved_utc: str | None
    outcome: RouteOutcome
    what_was_found: str
    blocked_by: str

    def __post_init__(self) -> None:
        for name in ("route_id", "locator", "description", "what_was_found"):
            if not str(getattr(self, name)).strip():
                raise GriauleObservationError(
                    f"{self.route_id or '<route>'}: {name} is empty"
                )
        if not self.category.is_official:
            raise GriauleObservationError(
                f"{self.route_id}: {self.category.value} is not an official "
                "delivery channel, and recording it as one of the vendor's own "
                "routes would put a mirror in the chain of custody"
            )
        if self.retrieval is RetrievalStatus.RETRIEVED and not self.retrieved_utc:
            raise GriauleObservationError(
                f"{self.route_id}: a walked route records when it was walked"
            )
        if self.retrieval is not RetrievalStatus.RETRIEVED and self.retrieved_utc:
            raise GriauleObservationError(
                f"{self.route_id}: a route that was not retrieved carries no "
                "retrieval date"
            )
        if (
            self.retrieval is not RetrievalStatus.RETRIEVED
            and self.outcome is not RouteOutcome.CONTACT_ROUTE_ONLY
        ):
            raise GriauleObservationError(
                f"{self.route_id}: reports {self.outcome.value} for a route nobody "
                "retrieved. What a page says is not knowable from the fact that it "
                "exists"
            )

    def as_row(self) -> Mapping[str, Any]:
        return {
            "route_id": self.route_id,
            "locator": self.locator,
            "category": self.category.value,
            "description": self.description,
            "retrieval": self.retrieval.value,
            "retrieved_utc": self.retrieved_utc,
            "outcome": self.outcome.value,
            "what_was_found": self.what_was_found,
            "blocked_by": self.blocked_by,
        }


@dataclass(frozen=True, slots=True)
class RefusedRouteCategory:
    """A place the package is available, and will not be taken from."""

    category: LocatorCategory
    what_is_there: str
    why_it_is_refused: str

    def __post_init__(self) -> None:
        if self.category.is_official:
            raise GriauleObservationError(
                f"{self.category.value} is an official channel and cannot be "
                "recorded as a refused one"
            )
        for name in ("what_is_there", "why_it_is_refused"):
            if not str(getattr(self, name)).strip():
                raise GriauleObservationError(f"{self.category.value}: {name} is empty")

    def as_row(self) -> Mapping[str, Any]:
        return {
            "category": self.category.value,
            "what_is_there": self.what_is_there,
            "why_it_is_refused": self.why_it_is_refused,
        }


# ------------------------------------------------------------- the public pages

#: The day the pages and routes below were read.
_READ_UTC = "2026-08-15"

#: The finding G1 turns on, stated once as a constant so a test can pin it: no
#: official Griaule route retrieved on the date above offers the GBS Fingerprint
#: SDK package for download. The vendor's own installation instructions begin
#: after the file is already in hand.
SELF_SERVICE_LOCATOR_FOUND = False

#: The routes the vendor's own documentation names for anybody who does not have
#: the file. Both are e-mail addresses published on the SDK page itself; they are
#: recorded here as route *categories* rather than as addresses, because an
#: address in a published document is a value this stage's own guard refuses.
NAMED_VENDOR_CONTACT_ROUTES: tuple[str, ...] = (
    "the licensing address published on the SDK documentation page",
    "the support address published on the SDK documentation page",
    "the contact form published on the vendor's corporate site",
    "the request form published on the vendor's knowledge base",
)

#: What the SDK page advertises about the trial and the builds.
ADVERTISED_TRIAL_DAYS = 90
ADVERTISED_BUILDS: tuple[str, ...] = (
    "GBS Fingerprint SDK (x86-64)",
    "GBS Fingerprint SDK (x86)",
    "GBS Fingerprint SDK (Linux)",
)

#: The version the public documentation states. There is none, and that absence
#: is itself the reason the candidate identity carries a sentinel rather than a
#: number (docs/adr/0110).
ADVERTISED_VERSION: str | None = None

PRODUCT_OBSERVATIONS: tuple[ProductObservation, ...] = (
    ProductObservation(
        observation_id="trial_is_bundled_with_the_package",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "the SDK requires a software licence to work correctly and is "
            "distributed with a trial licence valid for 90 days, after which a "
            "licence must be purchased by e-mail and installed in a fixed "
            "system directory"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "that the trial arrives inside the package rather than through a "
            "separate provisioning step, which is the one structural difference "
            "from Stage 13A worth hoping for: FingerCell's archive was obtained "
            "and its entitlement never was. It indicates what to look for in a "
            "delivered package and establishes nothing about one"
        ),
    ),
    ProductObservation(
        observation_id="three_builds_no_version",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "the installation section names three builds — x86-64, x86 and Linux "
            "— states that the reader must already have one of them, and gives "
            "no version number, no build number, no release date and no download "
            "locator"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "that the platform question is answerable and the identity question "
            "is not. It is the direct reason implementation_version is a "
            "sentinel: there is no published number to freeze even if freezing "
            "one from a page were allowed"
        ),
    ),
    ProductObservation(
        observation_id="extraction_crops_larger_images",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "capture supports images up to 1280 x 1280 pixels at 125 to 1000 "
            "DPI, while extraction states a maximum image size of 500 x 500 "
            "pixels and that larger images are cropped"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "the exact question G2 exists to answer. A crop the extractor "
            "performs on a full image it was handed is algorithm behaviour; a "
            "crop the caller is required to perform first is fpbench choosing "
            "which part of the finger the algorithm sees. The page does not say "
            "which of the two the API requires, and only a delivered header and "
            "sample can (docs/adr/0124)"
        ),
    ),
    ProductObservation(
        observation_id="canonical_500_fits_the_documented_limit",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "the documented extraction maximum is 500 x 500 pixels and the "
            "documented minimum is 50 x 50"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "that this benchmark's canonical inputs are not obviously oversized "
            "for the documented limit, which is worth knowing and is not an "
            "answer: whether a given canonical image is within it is a property "
            "of that image, and whether the API accepts it unmodified is a "
            "property of the delivered package"
        ),
    ),
    ProductObservation(
        observation_id="extraction_and_verification_api",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "the current API performs fingerprint extraction and one-to-one "
            "verification through GrExtract and GrVerify, with "
            "GrSetVerifyParameters and GrGetVerifyParameters beside them; "
            "one-to-many identification is not performed by this SDK and the "
            "extraction-parameter calls of the previous generation are listed as "
            "discontinued"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "the shape G3 and G4 will be checked against. Two of those four "
            "calls are matcher parameters, which is why G4 cannot treat the "
            "settings surface as empty; and a discontinued extraction-parameter "
            "call indicates a narrower knob surface than Stage 13A's candidate "
            "had, which the delivered header must confirm rather than inherit"
        ),
    ),
    ProductObservation(
        observation_id="threshold_is_a_minimum_score",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "the threshold is described as the minimum score needed to state "
            "that two fingerprints match, with a default of 20 stated to give a "
            "1% false rejection rate, and the rotation tolerance as a maximum "
            "angle in degrees with a default of -1"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "that a score exists underneath the decision, which is necessary for "
            "G3 and nowhere near sufficient: a threshold described as a minimum "
            "score is consistent both with an API that returns the score and "
            "with one that returns only the comparison. Which of those the "
            "delivered header exposes is the gate. Neither default is applied "
            "here, and no calibration is performed against either"
        ),
    ),
    ProductObservation(
        observation_id="bmp_is_a_supported_container",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        statement=(
            "BMP files are supported for fingerprint image saving and loading, "
            "and the current API exposes file load and save entry points beside "
            "an image-conversion one"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        what_it_indicates=(
            "that a container adaptation may be needed and that it would be a "
            "container adaptation rather than preprocessing, provided every "
            "pixel value and the geometry survive it unchanged. The exact route "
            "comes from the delivered package"
        ),
    ),
)


# ------------------------------------------------------------ the walked routes

OFFICIAL_ROUTES: tuple[OfficialRoute, ...] = (
    OfficialRoute(
        route_id="sdk_documentation_page",
        locator="https://docs.griaule.com/sdks/en/fingerprintsdk.md",
        category=LocatorCategory.VENDOR_SELF_SERVICE_DOWNLOAD,
        description=(
            "the vendor's own GBS Fingerprint SDK page, checked first because a "
            "download link here would have settled the gate outright"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        outcome=RouteOutcome.NO_PACKAGE_OFFERED,
        what_was_found=(
            "installation instructions that begin after the file is already in "
            "hand — the reader is told to verify which of three builds they have "
            "and to double-click it. Every link on the rendered page was "
            "enumerated: none points to an installer, an archive or a download "
            "host, and the only outbound routes to the vendor are two e-mail "
            "addresses"
        ),
        blocked_by="the page documents installation and does not offer the file",
    ),
    OfficialRoute(
        route_id="documentation_site_index",
        locator="https://docs.griaule.com/llms.txt",
        category=LocatorCategory.VENDOR_SELF_SERVICE_DOWNLOAD,
        description=(
            "the documentation site's own complete page index, checked so that "
            "the conclusion above rests on the whole site rather than on one page"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        outcome=RouteOutcome.NO_PACKAGE_OFFERED,
        what_was_found=(
            "the full published index of the documentation site. It lists the "
            "suite's applications, its installation guides and its SDK release "
            "notes, and holds no download page, package registry or evaluation "
            "bundle for the fingerprint SDK"
        ),
        blocked_by="the site publishes documentation and does not publish packages",
    ),
    OfficialRoute(
        route_id="corporate_site_download_probe",
        locator="https://griaule.com/downloads",
        category=LocatorCategory.VENDOR_SELF_SERVICE_DOWNLOAD,
        description=(
            "the conventional download path on the vendor's corporate site, "
            "probed directly rather than inferred from the absence of a link"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        outcome=RouteOutcome.NO_PACKAGE_OFFERED,
        what_was_found=(
            "the host answers and the path does not exist. The localised variant "
            "of the same path was probed and does not exist either"
        ),
        blocked_by="there is no download section on the corporate site",
    ),
    OfficialRoute(
        route_id="corporate_contact_page",
        locator="https://griaule.com/en/contact/",
        category=LocatorCategory.VENDOR_SALES_DELIVERY,
        description=(
            "the corporate contact route, checked for a trial or evaluation "
            "request path"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        outcome=RouteOutcome.CONTACT_ROUTE_ONLY,
        what_was_found=(
            "a general contact form and regional telephone numbers. The page "
            "mentions no SDK, no trial, no evaluation and no download, so it is a "
            "way of reaching the vendor rather than a route to this product"
        ),
        blocked_by="a contact form is not a package",
    ),
    OfficialRoute(
        route_id="support_knowledge_base",
        locator="https://support.griaule.com/hc/en-us",
        category=LocatorCategory.VENDOR_SUPPORT_DELIVERY,
        description=(
            "the vendor's knowledge base, which its documentation names as the "
            "support route and which would be the natural home of a download "
            "article"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_READ_UTC,
        outcome=RouteOutcome.CONTACT_ROUTE_ONLY,
        what_was_found=(
            "a knowledge base offering an FAQ, guides and a request form. It has "
            "no downloads section, and a search of it returns nothing at all for "
            "the SDK — its articles are about the vendor's server products. The "
            "request form is a genuine official route and it asks a person for "
            "the package rather than serving one"
        ),
        blocked_by=(
            "the knowledge base publishes no package; its request form is the "
            "route, and a request is an act somebody has to perform"
        ),
    ),
    OfficialRoute(
        route_id="named_vendor_request",
        locator="VENDOR_SALES_OR_SUPPORT",
        category=LocatorCategory.VENDOR_SALES_DELIVERY,
        description=(
            "the route the vendor's own SDK page names for anybody who does not "
            "already hold the file: a request, in the requester's own name, to "
            "the addresses that page publishes"
        ),
        retrieval=RetrievalStatus.NOT_RETRIEVED,
        retrieved_utc=None,
        outcome=RouteOutcome.CONTACT_ROUTE_ONLY,
        what_was_found=(
            "the route exists and is the one the vendor points at. Nothing has "
            "been sent through it. It is recorded here as unwalked precisely so "
            "that no document in this stage can imply the vendor was asked and "
            "said nothing"
        ),
        blocked_by=(
            "the request has not been sent; sending it is this project's own "
            "next step and not a vendor dependency"
        ),
    ),
)

REFUSED_ROUTE_CATEGORIES: tuple[RefusedRouteCategory, ...] = (
    RefusedRouteCategory(
        category=LocatorCategory.SOFTWARE_CATALOGUE,
        what_is_there=(
            "several software-catalogue and freeware sites publish a Griaule "
            "fingerprint SDK download, some of them naming the 2007 and 2009 "
            "generations of the product"
        ),
        why_it_is_refused=(
            "not the vendor, not current, and not a chain of custody anything "
            "can be pinned to. A package whose provenance runs to a catalogue "
            "site is a package this stage could not identify even after hashing "
            "it"
        ),
    ),
    RefusedRouteCategory(
        category=LocatorCategory.RESELLER_OR_DISTRIBUTOR,
        what_is_there=(
            "at least one biometrics reseller publishes product pages for the "
            "vendor's fingerprint SDK"
        ),
        why_it_is_refused=(
            "a commercial route through a third party is still not the vendor "
            "handing over a package"
        ),
    ),
    RefusedRouteCategory(
        category=LocatorCategory.THIRD_PARTY_MIRROR,
        what_is_there=(
            "a manual for a 2014 edition of the SDK is mirrored on a document "
            "sharing site"
        ),
        why_it_is_refused=(
            "it may well be the vendor's own PDF, and it is still a document "
            "this project did not receive from the vendor, describing an edition "
            "nobody offered it"
        ),
    ),
    RefusedRouteCategory(
        category=LocatorCategory.UNLICENSED_REDISTRIBUTION,
        what_is_there=(
            "a download host advertises a build of the SDK together with a "
            "licence bypass"
        ),
        why_it_is_refused=(
            "it is refused for the obvious reason and recorded for a less "
            "obvious one: it is the first result a naive search for this package "
            "surfaces, and an evidence trail that simply omitted it would not "
            "show that it was seen and declined. No licence mechanism is "
            "bypassed, reset or worked around in this project, at any stage"
        ),
    ),
)

#: The acts that would move the acquisition state, in the order they would happen.
#: The first is this project's to perform; everything after it depends on a reply.
WHAT_WOULD_CHANGE_THE_STATUS: tuple[str, ...] = (
    "sending one official request, in the maintainer's own name, through a "
    "route the vendor publishes, stating that the use is academic, "
    "research-only and non-commercial",
    "a vendor reply that delivers the package and its bundled trial",
    "a vendor reply that declines, which would settle the gate as a refusal",
    "a vendor reply that confirms no package is available for this use, which "
    "would settle it as unavailable",
)


def product_rows() -> tuple[Mapping[str, Any], ...]:
    """Every public statement, as published rows."""
    return tuple(item.as_row() for item in PRODUCT_OBSERVATIONS)


def route_rows() -> tuple[Mapping[str, Any], ...]:
    """Every official route walked, as published rows."""
    return tuple(item.as_row() for item in OFFICIAL_ROUTES)


def refused_rows() -> tuple[Mapping[str, Any], ...]:
    """Every refused route category, as published rows."""
    return tuple(item.as_row() for item in REFUSED_ROUTE_CATEGORIES)


def observations_fingerprint() -> str:
    """One digest over everything this module records."""
    return stable_hash(
        {
            "schema": "stage_14a_observations_v1",
            "product": [dict(row) for row in product_rows()],
            "routes": [dict(row) for row in route_rows()],
            "refused": [dict(row) for row in refused_rows()],
            "self_service_locator_found": SELF_SERVICE_LOCATOR_FOUND,
            "what_would_change_the_status": list(WHAT_WOULD_CHANGE_THE_STATUS),
        },
        length=64,
    )


def _validate_module() -> None:
    """Checked at import: the routes have to support the finding they produce."""
    identifiers = [item.route_id for item in OFFICIAL_ROUTES]
    if len(identifiers) != len(set(identifiers)):  # pragma: no cover - defensive
        raise GriauleObservationError("a route is recorded twice")
    identifiers = [item.observation_id for item in PRODUCT_OBSERVATIONS]
    if len(identifiers) != len(set(identifiers)):  # pragma: no cover - defensive
        raise GriauleObservationError("an observation is recorded twice")
    offered = [
        item.route_id
        for item in OFFICIAL_ROUTES
        if item.outcome is RouteOutcome.PACKAGE_OFFERED
    ]
    if bool(offered) is not SELF_SERVICE_LOCATOR_FOUND:
        raise GriauleObservationError(
            f"the routes report {offered or 'no'} package offer and the module "
            f"states SELF_SERVICE_LOCATOR_FOUND is {SELF_SERVICE_LOCATOR_FOUND}"
        )
    walked = [
        item
        for item in OFFICIAL_ROUTES
        if item.retrieval is RetrievalStatus.RETRIEVED
    ]
    if len(walked) < 3:
        raise GriauleObservationError(
            "a claim that no self-service package exists rests on having walked "
            f"the vendor's routes, and only {len(walked)} were retrieved"
        )
    categories = {item.category for item in OFFICIAL_ROUTES}
    missing = {member for member in LocatorCategory if member.is_official} - categories
    if missing:
        raise GriauleObservationError(
            f"no route was walked for {sorted(item.value for item in missing)}, so "
            "the exhaustion this stage's finding rests on is incomplete"
        )
    if ADVERTISED_VERSION is not None:  # pragma: no cover - defensive
        raise GriauleObservationError(
            "the public documentation publishes no version, and recording one "
            "here would give the candidate an identity no artifact supports"
        )


_validate_module()
