"""What was actually retrieved about Innovatrics IDKit, and what it is worth.

Two records, and the difference between them is the whole point of this module.

**The acquisition attempt.** Every official route this project could walk, what
was found at the end of it, and what stopped it. Walked on 2026-08-13, before a
line of adapter was written, because Stage 10B's lesson was that a preflight
which starts by describing a product it never requested ends up publishing a
verdict about a route nobody tried (docs/adr/0107).

**The public observations.** What Innovatrics states publicly about IDKit today.
Every one carries the locator it was read from and the date it was read, and
every one is marked as what it is: an *indication of what to look for in the
package*, never a value Stage 12A may freeze. The support material is undated,
names an API — ``IEngine_*`` — from an older generation than the 7.6 the learning
portal advertises, and describes behaviour the delivered package may have changed
(docs/adr/0110).

So no gate below the acquisition gate is answered from anything here. These
statements shape the questions the package will be asked; they do not answer
them.

Nothing here downloads anything, activates anything, or holds a credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from fpbench.core.idkit_preflight_errors import IdkitObservationError
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage12a_idkit_identity import (
    AcquisitionStatus,
    ProductFamily,
)

__all__ = [
    "RetrievalStatus",
    "RouteOutcome",
    "AcquisitionRoute",
    "ACQUISITION_ROUTES",
    "REFUSED_ROUTES",
    "OBSERVED_ACQUISITION_STATUS",
    "ACQUISITION_STATUS_BASIS",
    "WHAT_WOULD_CHANGE_THE_STATUS",
    "PublicObservation",
    "PUBLIC_OBSERVATIONS",
    "ADVERTISED_PRODUCT_FAMILY",
    "ADVERTISED_VERSION_INDICATION",
    "ADVERTISED_VERSION_IS_NOT_AUTHORITATIVE",
    "observation",
    "observation_rows",
    "route_rows",
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


class RouteOutcome(str, Enum):
    """What happened at the end of one acquisition route."""

    #: The route delivered the package.
    PACKAGE_DELIVERED = "PACKAGE_DELIVERED"

    #: The route exists and ends at an authentication this project cannot pass.
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"

    #: The route is real but carries no package — a catalogue, a course, a
    #: documentation site.
    NO_PACKAGE_OFFERED = "NO_PACKAGE_OFFERED"

    #: The route has been retired by the vendor and says so.
    RETIRED_BY_VENDOR = "RETIRED_BY_VENDOR"

    #: The route requires a person-to-vendor exchange that has not been made.
    PERSON_TO_VENDOR_REQUEST_NOT_MADE = "PERSON_TO_VENDOR_REQUEST_NOT_MADE"

    #: The vendor was asked and declined.
    REFUSED_BY_VENDOR = "REFUSED_BY_VENDOR"


@dataclass(frozen=True, slots=True)
class AcquisitionRoute:
    """One official route, walked as far as it goes.

    ``blocked_by`` is mandatory wherever the route did not deliver. A route that
    stopped for no recorded reason is a route nobody can resume.
    """

    route_id: str
    locator: str
    description: str
    retrieval: RetrievalStatus
    retrieved_utc: str | None
    outcome: RouteOutcome
    what_was_found: str
    blocked_by: str | None

    def __post_init__(self) -> None:
        for name in ("route_id", "locator", "description", "what_was_found"):
            if not str(getattr(self, name)).strip():
                raise IdkitObservationError(f"{self.route_id or '<route>'}: {name} is empty")
        if self.retrieval is RetrievalStatus.RETRIEVED and not self.retrieved_utc:
            raise IdkitObservationError(
                f"{self.route_id}: a retrieved route records when it was retrieved"
            )
        if self.retrieval is not RetrievalStatus.RETRIEVED and self.retrieved_utc:
            raise IdkitObservationError(
                f"{self.route_id}: a route that was not retrieved carries no "
                "retrieval date"
            )
        if self.outcome is RouteOutcome.PACKAGE_DELIVERED and self.blocked_by:
            raise IdkitObservationError(
                f"{self.route_id}: a route that delivered is not also blocked"
            )
        if self.outcome is not RouteOutcome.PACKAGE_DELIVERED and not self.blocked_by:
            raise IdkitObservationError(
                f"{self.route_id}: a route that did not deliver names what stopped it"
            )


#: The day this stage walked the routes below. Every retrieval is stamped with
#: it, so a reader can tell how old the picture is without trusting the prose.
_WALKED_UTC = "2026-08-13"

#: Every official route, in the order they were tried. The order matters: a
#: self-service download would have made the rest unnecessary, and there is no
#: self-service download.
ACQUISITION_ROUTES: tuple[AcquisitionRoute, ...] = (
    AcquisitionRoute(
        route_id="developer_portal",
        locator="https://developers.innovatrics.com/",
        description=(
            "the vendor's public developer portal, checked first because a "
            "self-service package would have settled the gate outright"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        outcome=RouteOutcome.NO_PACKAGE_OFFERED,
        what_was_found=(
            "the portal documents the vendor's platform and toolkit products and "
            "does not list the IDKit fingerprint SDK; it offers documentation and "
            "a contact route rather than a download, and no package registry, "
            "trial archive or evaluation bundle is published on it"
        ),
        blocked_by="no IDKit package is offered here",
    ),
    AcquisitionRoute(
        route_id="public_source_repositories",
        locator="https://github.com/innovatrics",
        description=(
            "the vendor's own public repositories, checked for an officially "
            "published package or a version-matched sample"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        outcome=RouteOutcome.NO_PACKAGE_OFFERED,
        what_was_found=(
            "the organisation publishes samples and integrations for its "
            "onboarding and face products; no repository holds the IDKit "
            "fingerprint SDK, its documentation or a fingerprint 1:1 sample"
        ),
        blocked_by="no IDKit package is published here",
    ),
    AcquisitionRoute(
        route_id="legacy_customer_crm",
        locator="https://crm.innovatrics.com/",
        description=(
            "the customer CRM the vendor's own support material names as the "
            "place SDK packages and licences are obtained"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        outcome=RouteOutcome.RETIRED_BY_VENDOR,
        what_was_found=(
            "the host now serves a notice that the portal has been retired and "
            "is no longer in production, and directs customers to the current "
            "portal or to a sales representative; the support articles that name "
            "it have not been updated, which is the first concrete sign that the "
            "public material is older than the product"
        ),
        blocked_by="the vendor retired this route",
    ),
    AcquisitionRoute(
        route_id="current_customer_portal",
        locator="https://customerportal.innovatrics.com/",
        description=(
            "the current customer and licensing portal, which is where the "
            "vendor's support material says licences are generated"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        outcome=RouteOutcome.AUTHENTICATION_REQUIRED,
        what_was_found=(
            "a sign-in page. No package, documentation or evaluation bundle is "
            "reachable without an account, and no self-registration was offered "
            "on the unauthenticated page. This project holds no account, and "
            "obtaining one is a commercial relationship rather than a download"
        ),
        blocked_by="this project holds no customer-portal account",
    ),
    AcquisitionRoute(
        route_id="learning_portal",
        locator="https://learn.innovatrics.com/courses/innovatrics-sdks",
        description=(
            "the vendor's learning portal, checked because it is the one public "
            "place that names a current IDKit version"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        outcome=RouteOutcome.NO_PACKAGE_OFFERED,
        what_was_found=(
            "course material for IDKit SDK 7.6 — an introduction, a details "
            "module, a documentation module and a quiz — and an email address "
            "for access. No package and no documentation download"
        ),
        blocked_by="a course is not a package",
    ),
    AcquisitionRoute(
        route_id="vendor_sales_or_support_request",
        locator="the vendor's published sales and support contact addresses",
        description=(
            "the route the vendor's own material names for anyone without portal "
            "access: a request to sales or support in the requester's own name"
        ),
        retrieval=RetrievalStatus.NOT_RETRIEVED,
        retrieved_utc=None,
        outcome=RouteOutcome.PERSON_TO_VENDOR_REQUEST_NOT_MADE,
        what_was_found=(
            "the route exists and is documented by the vendor. No request has "
            "been sent from this project. Correspondence with a vendor is a "
            "person-to-vendor exchange made in the maintainer's own name, and it "
            "is not something a preflight performs on their behalf; nothing here "
            "was refused, and nobody was asked"
        ),
        blocked_by="no request has been sent by the maintainer",
    ),
)

#: Routes that were found and are not acquisition. Recorded so that "we could "
#: "not get it" cannot later be read as "there was nowhere to get it": there
#: were places, and every one of them is refused on provenance. A package whose
#: chain of custody runs through a catalogue site is a package nobody can pin to
#: the vendor, whatever its digest turns out to be.
REFUSED_ROUTES: tuple[tuple[str, str], ...] = (
    (
        "software catalogue and freeware sites",
        "several publish an IDKit PC SDK download, some naming versions from the "
        "1.x and 2.x generations. Not the vendor, not current, and not a chain of "
        "custody anything can be pinned to",
    ),
    (
        "reseller and distributor storefronts",
        "at least one biometrics reseller lists IDKit PC and Mobile SDKs for "
        "purchase. A commercial route through a third party is still not the "
        "vendor handing over a package",
    ),
    (
        "third-party mirrors of vendor documents",
        "an IDKit datasheet is mirrored on an unrelated integrator's host. It may "
        "even be the vendor's own PDF, and it is still a document this project "
        "did not receive from the vendor",
    ),
)

#: Where the attempt actually stands. Not ``NOT_ATTEMPTED``: five official routes
#: were walked and one was found to be retired by the vendor. Not
#: ``REQUEST_SENT``: nobody has written to the vendor. Not ``ACCESS_REFUSED``:
#: nothing has been refused, because nothing has been asked (docs/adr/0108).
OBSERVED_ACQUISITION_STATUS = AcquisitionStatus.PORTAL_ACCESS_REQUIRED

ACQUISITION_STATUS_BASIS = (
    "Innovatrics distributes the IDKit SDK through its customer portal. Five "
    "official routes were retrieved: the developer portal and the public "
    "repositories offer no IDKit package, the legacy CRM has been retired by the "
    "vendor, the current portal ends at a sign-in this project has no account "
    "for, and the learning portal offers a course rather than a download. The "
    "sixth route — a request to the vendor in the maintainer's own name — has not "
    "been walked. Nothing was refused and no package was shown not to exist."
)

#: The two things that would move this state, and nothing else does. Neither is
#: something the preflight can do for itself, which is exactly why the state is
#: pending rather than failed.
WHAT_WOULD_CHANGE_THE_STATUS: tuple[str, ...] = (
    "the maintainer signs in to the customer portal with an account of their own "
    "and places the delivered package in the local artifact store, which moves "
    "the state to PACKAGE_OBTAINED",
    "the maintainer sends an evaluation request to the vendor in their own name, "
    "which moves the state to REQUEST_SENT and then to whatever the vendor "
    "replies — including ACCESS_REFUSED, which would be a finding and would fail "
    "the gate honestly",
)


@dataclass(frozen=True, slots=True)
class PublicObservation:
    """One statement Innovatrics publishes, and what it is good for.

    ``freezes_a_value`` is always ``False`` and is a field rather than a comment
    so that the claim is inspectable in the published document. There is no way
    to record a public statement as an authority through this class, which is the
    only way to be sure none of them ends up being one (docs/adr/0110).
    """

    observation_id: str
    locator: str
    subject: str
    statement: str
    retrieval: RetrievalStatus
    retrieved_utc: str
    what_it_tells_this_stage_to_check: str
    freezes_a_value: bool = False

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "locator",
            "subject",
            "statement",
            "what_it_tells_this_stage_to_check",
        ):
            if not str(getattr(self, name)).strip():
                raise IdkitObservationError(
                    f"{self.observation_id or '<observation>'}: {name} is empty"
                )
        if self.retrieval is not RetrievalStatus.RETRIEVED:
            raise IdkitObservationError(
                f"{self.observation_id}: a statement is recorded only where the "
                "locator behind it was actually retrieved"
            )
        if not str(self.retrieved_utc).strip():
            raise IdkitObservationError(
                f"{self.observation_id}: a retrieved statement is dated"
            )
        if self.freezes_a_value:
            raise IdkitObservationError(
                f"{self.observation_id}: a public statement never freezes a "
                "Stage 12A value. The delivered package is the only authority "
                "about the delivered package"
            )


_SUPPORT = "https://support.innovatrics.com/support/solutions/articles/"

#: Everything retrieved about the product, each with the locator it came from.
#: They are the questions the package will be asked, in the order the gates ask
#: them.
PUBLIC_OBSERVATIONS: tuple[PublicObservation, ...] = (
    PublicObservation(
        observation_id="product_family_is_distinct_from_ansi_iso",
        locator=(
            _SUPPORT + "5000662509-what-s-the-difference-between-idkit-sdk-and-"
            "ansi-iso-sdk-"
        ),
        subject="which product this candidate is",
        statement=(
            "IDKit is described as generating the vendor's proprietary "
            "fingerprint templates and supporting 1:1 verification as well as 1:N "
            "identification, while the ANSI&ISO SDK is described as a separate "
            "product for standardised templates supporting only 1:1. IDKit is "
            "described as able to export to the standard formats, with import of "
            "ANSI&ISO templates into IDKit not supported"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "that the delivered package resolves to the IDKit family and not to "
            "the ANSI&ISO SDK, IDKit Multi, an enrolment SDK or a mobile SDK — "
            "and that the compared representation is the proprietary template "
            "rather than a standard export chosen because it is easier to handle"
        ),
    ),
    PublicObservation(
        observation_id="image_input_is_bmp_or_raw",
        locator=(
            _SUPPORT + "5000662525-how-do-i-acquire-images-from-fingerprint-"
            "scanners-readers-for-use-in-idkit-"
        ),
        subject="the container the SDK accepts",
        statement=(
            "the SDKs are described as fingerprint-scanner independent, and IDKit "
            "is described as accepting fingerprint images as BMP or raw images, "
            "in memory or in files. PNG is not named"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "whether the delivered package reads the benchmark's PNG directly. If "
            "it does not, the permitted route is a deterministic lossless decode "
            "into the identical gray8 matrix and then the official raw buffer "
            "API — and the identity of every pixel has to be proved, not assumed"
        ),
    ),
    PublicObservation(
        observation_id="dpi_is_set_before_extraction",
        locator=(
            _SUPPORT + "5000662526-why-is-dpi-a-global-setting-how-can-we-use-"
            "fingerprints-from-different-sources-"
        ),
        subject="when the resolution has to be declared",
        statement=(
            "the DPI setting is described as affecting extraction and neither 1:1 "
            "verification nor 1:N identification, as needing to be set to the "
            "correct value before extraction, and as being remembered by the "
            "extracted template so that search is DPI-independent"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "that the delivered API is told 500 DPI *before* each extraction and "
            "not after it. Setting it afterwards would set it for the next "
            "template and leave the one already built carrying whatever was in "
            "force at the time"
        ),
    ),
    PublicObservation(
        observation_id="images_are_resampled_to_500_dpi_internally",
        locator=(
            _SUPPORT + "5000662532-can-we-match-two-fingerprint-images-with-"
            "different-dpi-"
        ),
        subject="what the SDK does to the pixels by itself",
        statement=(
            "input images are described as internally resampled to 500 dpi before "
            "template extraction, with the resulting templates using 500 dpi "
            "coordinates so they can be matched independently of the input "
            "resolution"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "nothing that fpbench must do. It is the vendor's own internal "
            "processing, which is part of the algorithm under test, and at 500 "
            "PPI in it is a resample to the resolution the image already has. It "
            "is recorded so that a later reader does not mistake it for a "
            "resize this project performed"
        ),
    ),
    PublicObservation(
        observation_id="consolidated_multi_finger_score_exists",
        locator=(
            _SUPPORT + "5000662178-how-is-it-that-the-consolidated-score-is-not-"
            "equal-to-maximum-score-and-it-is-entirely-unrelated-to-a"
        ),
        subject="what a score means when a record holds several fingerprints",
        statement=(
            "for records holding several fingerprints, the consolidated score is "
            "described as grouping the similarity scores by finger position, "
            "taking the maximum within each position and summing those maxima "
            "across positions, with older versions instead taking a maximum minus "
            "a correction that depends on how many fingerprints were compared"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "the single most dangerous thing about this candidate. A sum of "
            "per-position maxima is not a single-finger similarity and cannot be "
            "recovered from one, so if the delivered API scores only whole user "
            "records, each record must hold exactly one fingerprint — and if that "
            "cannot be guaranteed, the extraction and matcher gates fail"
        ),
    ),
    PublicObservation(
        observation_id="matching_is_not_commutative",
        locator=(
            _SUPPORT + "5000662513-why-do-i-get-different-score-depending-on-"
            "which-way-i-compare-templates-"
        ),
        subject="whether score(A, B) equals score(B, A)",
        statement=(
            "the matching algorithm is described as not symmetrical and the "
            "operation as not commutative, with the outcome depending on which "
            "side is the probe and which the gallery"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "that there is no symmetry to discover and nothing to normalise. The "
            "protocol binding — pair.left to probe, pair.right to gallery — is "
            "fixed in advance, both orderings are run once in qualification to "
            "publish that they can differ, and neither a maximum nor an average "
            "of them ever enters a benchmark score"
        ),
    ),
    PublicObservation(
        observation_id="score_and_threshold_are_separate",
        locator=_SUPPORT + "13000044306-idkit-sdk-verification-score-threshold",
        subject="the shape of the number the matcher returns",
        statement=(
            "the verification score is described on a scale normalised roughly by "
            "-10*log10(FAR), with a published correspondence between score levels "
            "and false-accept rates, and with the matching decision described as "
            "resting on a threshold the integrator chooses rather than on a "
            "vendor default. The scale is described as logarithmic and not to be "
            "treated as a linear indicator of the match"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "that the delivered API returns the scalar independently of the "
            "decision. A vendor scale that is already a transformation of a FAR "
            "is still a raw score and is passed through untouched; what is "
            "refused is fpbench applying a second transformation, and reading "
            "scores by pushing the threshold to zero"
        ),
    ),
    PublicObservation(
        observation_id="a_template_size_control_exists",
        locator=_SUPPORT + "5000662159-what-is-the-template-size-",
        subject="settings that can change the template",
        statement=(
            "an IDKit single-finger template is described as under 2 KB "
            "typically and 4 KB at most, and a configuration parameter for a "
            "maximum template size is described as available to cap it"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "that a template-size control exists somewhere in the delivered "
            "package and has to be found and recorded with its delivered value. "
            "It does not tell this stage what to set it to, and no value here may "
            "be chosen because it produced fewer failures on this project's "
            "fingerprints"
        ),
    ),
    PublicObservation(
        observation_id="a_valid_license_is_required",
        locator=(
            _SUPPORT + "5000662197-how-do-i-deploy-my-application-do-i-have-to-"
            "install-and-run-your-licensemanager-"
        ),
        subject="what the SDK needs before it will run",
        statement=(
            "deployment is described as installing the SDK together with a "
            "licence manager, with licence installation being a file copy or an "
            "in-memory buffer, with a hardware identifier obtainable either "
            "programmatically or from the licence manager, and with licences "
            "generated through the customer portal or through a documented REST "
            "interface"
        ),
        retrieval=RetrievalStatus.RETRIEVED,
        retrieved_utc=_WALKED_UTC,
        what_it_tells_this_stage_to_check=(
            "that a licence is a real precondition and that it is bound to a "
            "machine. Nothing about it is bypassed, and the harness is built and "
            "compiled before any licence is generated, so that a clock is not "
            "started to discover a build error. No hardware identifier, licence "
            "byte or portal credential ever reaches this repository"
        ),
    ),
)

#: What the public material advertises the product to be. Recorded as an
#: advertisement, which is what it is.
ADVERTISED_PRODUCT_FAMILY = ProductFamily.IDKIT_SDK
ADVERTISED_VERSION_INDICATION = "7.6"
ADVERTISED_VERSION_IS_NOT_AUTHORITATIVE = True


def observation(observation_id: str) -> PublicObservation:
    """One recorded observation, by id."""
    for item in PUBLIC_OBSERVATIONS:
        if item.observation_id == observation_id:
            return item
    raise IdkitObservationError(f"no Stage 12A observation named {observation_id!r}")


def observation_rows() -> tuple[Mapping[str, Any], ...]:
    """The observations as published rows."""
    return tuple(
        {
            "observation_id": item.observation_id,
            "subject": item.subject,
            "locator": item.locator,
            "retrieval": item.retrieval.value,
            "retrieved_utc": item.retrieved_utc,
            "statement": item.statement,
            "what_it_tells_this_stage_to_check": (
                item.what_it_tells_this_stage_to_check
            ),
            "freezes_a_value": item.freezes_a_value,
        }
        for item in PUBLIC_OBSERVATIONS
    )


def route_rows() -> tuple[Mapping[str, Any], ...]:
    """The acquisition routes as published rows."""
    return tuple(
        {
            "route_id": item.route_id,
            "locator": item.locator,
            "description": item.description,
            "retrieval": item.retrieval.value,
            "retrieved_utc": item.retrieved_utc,
            "outcome": item.outcome.value,
            "what_was_found": item.what_was_found,
            "blocked_by": item.blocked_by,
        }
        for item in ACQUISITION_ROUTES
    )


def observations_fingerprint() -> str:
    """The identity of everything this module recorded.

    Covers the routes and the statements together, because they are one picture
    of one day: a reader who re-walks the routes and finds a different answer
    should see a different fingerprint.
    """
    return stable_hash(
        {
            "schema": "stage_12a_observations_v1",
            "walked_utc": _WALKED_UTC,
            "routes": [dict(row) for row in route_rows()],
            "refused_routes": [list(item) for item in REFUSED_ROUTES],
            "acquisition_status": OBSERVED_ACQUISITION_STATUS.value,
            "observations": [dict(row) for row in observation_rows()],
            "advertised_version_indication": ADVERTISED_VERSION_INDICATION,
        },
        length=64,
    )
