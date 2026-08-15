"""Where the Griaule package stands, and the guard that keeps its bytes out of Git.

Three states matter and the whole stage turns on telling them apart.

``PENDING_ACCESS`` means an official request was sent and nobody has answered.
``ACTION_REQUIRED`` means the routes were walked, none of them hands the package
over, and the request itself has not been sent — a step this project owes, not a
wait. ``REFUSED`` and ``UNAVAILABLE`` mean the vendor answered, and those are the
only two states that turn into a failed stage (docs/adr/0121).

The distinction has a cost this module pays deliberately: the request status is a
frozen constant that a human edits when they perform the act, rather than
something inferred. Nothing else would be honest. A mailbox this code cannot see
is not a state it can derive, and a stage that guessed would eventually publish
"the vendor did not reply" about a message nobody sent.

A delivered package never enters the repository. It goes to the local artifact
store outside the working tree, is hashed there, and only a description of it —
a filename, a size, a digest — is ever published (docs/adr/0083).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.griaule_preflight_errors import (
    GriauleAcquisitionError,
    GriauleSensitiveEvidenceError,
)
from fpbench.experiments.stage14a_griaule_identity import (
    ARTIFACT_STORE_PREFIX,
    LocatorCategory,
)
from fpbench.experiments.stage14a_griaule_observations import (
    OFFICIAL_ROUTES,
    SELF_SERVICE_LOCATOR_FOUND,
    RouteOutcome,
)
from fpbench.third_party import resolve_third_party_root

__all__ = [
    "PACKAGE_DECLARATION_NAME",
    "PACKAGE_INSPECTION_NAME",
    "UNPACKED_DIRECTORY_NAME",
    "RequestStatus",
    "REQUEST_STATUS",
    "REQUEST_SENT_UTC",
    "AcquisitionRequestDraft",
    "REQUEST_DRAFT",
    "ArtifactPresence",
    "AcquisitionStatus",
    "PackageDeclaration",
    "AcquisitionState",
    "artifact_store_prefix_path",
    "unpacked_root",
    "read_package_declaration",
    "write_package_declaration",
    "acquisition_state",
    "package_inspection",
    "TrackedByteFinding",
    "TrackedByteAudit",
    "audit_tracked_bytes_against_griaule_artifacts",
    "require_no_griaule_bytes_in_git",
    "main",
]

#: What the maintainer writes beside the package after obtaining it.
PACKAGE_DECLARATION_NAME = "package-declaration.json"

#: What the maintainer writes after reading the delivered documentation, headers,
#: samples and terms. It is what G2, G3 and G4 are answered from.
PACKAGE_INSPECTION_NAME = "package-inspection.json"

#: Where the package is unpacked, inside the store and never inside the tree.
UNPACKED_DIRECTORY_NAME = "unpacked"

_HEX = frozenset("0123456789abcdef")


class RequestStatus(str, Enum):
    """Where the one official acquisition request stands.

    Deliberately not inferred. Sending a message is an act somebody performs, and
    this constant records whether it happened — so that no document in this stage
    can imply the vendor was asked while the request sits in a draft.
    """

    #: The routes have been walked and the request has not been sent.
    PREPARED_NOT_SENT = "PREPARED_NOT_SENT"

    #: Sent, through a route the vendor publishes, and unanswered.
    SENT_AWAITING_REPLY = "SENT_AWAITING_REPLY"

    #: Answered, and the answer asks for something further.
    REPLY_REQUIRES_FURTHER_STEPS = "REPLY_REQUIRES_FURTHER_STEPS"

    #: Answered with a delivery.
    PACKAGE_DELIVERED = "PACKAGE_DELIVERED"

    #: Answered with a refusal.
    REFUSED = "REFUSED"

    #: Answered by confirming no package is available for this use.
    CONFIRMED_UNAVAILABLE = "CONFIRMED_UNAVAILABLE"

    @property
    def is_sent(self) -> bool:
        return self is not RequestStatus.PREPARED_NOT_SENT

    @property
    def is_a_vendor_answer(self) -> bool:
        return self in (
            RequestStatus.REPLY_REQUIRES_FURTHER_STEPS,
            RequestStatus.PACKAGE_DELIVERED,
            RequestStatus.REFUSED,
            RequestStatus.CONFIRMED_UNAVAILABLE,
        )


#: Where the request stands today. Every official route published by Griaule was
#: retrieved and none of them serves the package; the request the vendor's own
#: documentation points at has been prepared and not sent.
#:
#: This is the single line a maintainer edits when they perform the act, and the
#: gate reads it rather than guessing.
REQUEST_STATUS = RequestStatus.PREPARED_NOT_SENT

#: When the request was sent. ``None`` while it has not been.
REQUEST_SENT_UTC: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionRequestDraft:
    """The publication-safe request a maintainer can send through an official route.

    The three placeholders keep personal material out of Git. Everything else is
    complete, so ``PREPARED_NOT_SENT`` names a real draft rather than an intention
    to write one later.
    """

    recipient_route: str
    subject: str
    body: str
    placeholders_to_fill: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("recipient_route", "subject", "body"):
            if not str(getattr(self, name)).strip():
                raise GriauleAcquisitionError(f"the request draft has no {name}")
        if not self.placeholders_to_fill:
            raise GriauleAcquisitionError(
                "the public request draft must identify the personal fields to fill"
            )
        missing = tuple(
            value for value in self.placeholders_to_fill if value not in self.body
        )
        if missing:
            raise GriauleAcquisitionError(
                f"the request draft does not carry its declared placeholders: {missing}"
            )
        required_statements = (
            "academic",
            "research-only",
            "non-commercial",
            "current official GBS Fingerprint SDK package",
            "raw scalar 1:1 similarity score",
        )
        absent = tuple(value for value in required_statements if value not in self.body)
        if absent:
            raise GriauleAcquisitionError(
                f"the request draft omits required scope: {absent}"
            )

    def as_row(self) -> Mapping[str, Any]:
        """A deterministic, JSON-ready representation with no personal values."""
        return {
            "recipient_route": self.recipient_route,
            "subject": self.subject,
            "body": self.body,
            "placeholders_to_fill": list(self.placeholders_to_fill),
        }


#: A complete request except for the sender's own identity and reply contact.
#: It is evidence that ``PREPARED_NOT_SENT`` means prepared, while still making no
#: claim that a request has been sent or that the vendor has failed to answer.
REQUEST_DRAFT = AcquisitionRequestDraft(
    recipient_route=(
        "one official sales or support route published by the vendor for SDK "
        "acquisition requests"
    ),
    subject=(
        "Academic research request for the current GBS Fingerprint SDK package "
        "and trial"
    ),
    body=(
        "Hello,\n\n"
        "I maintain an academic fingerprint benchmark and am evaluating the "
        "Griaule GBS Fingerprint SDK for academic, research-only and "
        "non-commercial use.\n\n"
        "Please provide the current official GBS Fingerprint SDK package and its "
        "currently offered trial, or tell me the official acquisition steps. The "
        "evaluation is a bounded technical preflight to determine whether the SDK "
        "supports direct single-finger 500 x 500 pixel, 500 ppi grayscale image "
        "input without benchmark-side cropping or segmentation; single-finger "
        "template extraction; a raw scalar 1:1 similarity score before any "
        "thresholded decision; and an authoritative inventory of every setting or "
        "route choice that can affect that score.\n\n"
        "Please also confirm the current product version and build, supported "
        "platforms, the applicable academic and research-use terms, redistribution "
        "terms, trial duration and activation requirements, and any further steps. "
        "No biometric images, templates or scores will be sent as part of this "
        "request.\n\n"
        "Thank you,\n"
        "[maintainer name]\n"
        "[institutional affiliation]\n"
        "[reply contact]"
    ),
    placeholders_to_fill=(
        "[maintainer name]",
        "[institutional affiliation]",
        "[reply contact]",
    ),
)


class ArtifactPresence(str, Enum):
    """What is in the store where the package would be."""

    #: The declaration verifies and the file it names matches by size and digest.
    VERIFIED = "VERIFIED"

    #: Nothing at all. The ordinary state of every CI runner.
    ABSENT = "ABSENT"

    #: Bytes are here and nothing describes them.
    UNDECLARED = "UNDECLARED"

    #: A declaration is here and does not agree with the bytes beside it.
    MISMATCHED = "MISMATCHED"

    #: A declaration is here and is not usable.
    MALFORMED = "MALFORMED"

    @property
    def is_the_delivered_package(self) -> bool:
        return self is ArtifactPresence.VERIFIED


class AcquisitionStatus(str, Enum):
    """The acquisition question, answered.

    Four of these are not failures and two of them are. The split is what the
    gate reads to choose between ``PASS``, ``PENDING_ACCESS``,
    ``ACTION_REQUIRED`` and ``FAIL``.
    """

    #: The package is here, hashed, and its declaration verifies.
    OBTAINED = "OBTAINED"

    #: Every official route was walked, none serves the package, and the one
    #: request this project owes has not been sent.
    REQUEST_NOT_SENT = "REQUEST_NOT_SENT"

    #: Sent and unanswered.
    REQUEST_PENDING = "REQUEST_PENDING"

    #: Answered, and the answer asks for something further before a package can
    #: be delivered.
    FURTHER_STEPS_REQUIRED = "FURTHER_STEPS_REQUIRED"

    #: The vendor declined.
    ACCESS_REFUSED = "ACCESS_REFUSED"

    #: The vendor confirmed no package is available for this use.
    PACKAGE_UNAVAILABLE = "PACKAGE_UNAVAILABLE"

    #: Bytes are in the store and the declaration does not describe them.
    DECLARATION_REQUIRED = "DECLARATION_REQUIRED"

    @property
    def is_pending(self) -> bool:
        """Whether somebody outside this project has to move next."""
        return self in (
            AcquisitionStatus.REQUEST_PENDING,
            AcquisitionStatus.FURTHER_STEPS_REQUIRED,
        )

    @property
    def is_a_local_action(self) -> bool:
        """Whether the next move is this project's own."""
        return self in (
            AcquisitionStatus.REQUEST_NOT_SENT,
            AcquisitionStatus.DECLARATION_REQUIRED,
        )

    @property
    def is_refusal(self) -> bool:
        """Whether the vendor settled the question in the negative."""
        return self in (
            AcquisitionStatus.ACCESS_REFUSED,
            AcquisitionStatus.PACKAGE_UNAVAILABLE,
        )


@dataclass(frozen=True, slots=True)
class PackageDeclaration:
    """What was obtained, as the person who obtained it recorded it.

    Every field is required. A declaration with the digest left out would let the
    preflight proceed to three gates that are all questions about specific bytes.
    """

    official_locator_category: LocatorCategory
    official_locator: str
    filename: str
    size_bytes: int
    sha256: str
    obtained_utc: str
    product: str
    product_version: str
    build_or_revision: str
    platform: str
    documentation_obtained: bool
    license_obtained: bool
    bundled_trial_present: bool

    def __post_init__(self) -> None:
        if not self.official_locator_category.is_official:
            raise GriauleAcquisitionError(
                f"{self.official_locator_category.value} is not an official "
                "delivery channel. A package whose chain of custody does not run "
                "to the vendor is a package nothing can pin"
            )
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise GriauleAcquisitionError(
                "a declared package carries the SHA-256 of its own bytes, "
                "computed here"
            )
        object.__setattr__(self, "sha256", digest)
        if int(self.size_bytes) <= 0:
            raise GriauleAcquisitionError("a declared package has a positive size")
        for name in (
            "official_locator",
            "filename",
            "obtained_utc",
            "product",
            "product_version",
            "build_or_revision",
            "platform",
        ):
            if not str(getattr(self, name)).strip():
                raise GriauleAcquisitionError(
                    f"{name} is empty, and a package identity assembled from "
                    "blanks would identify nothing"
                )
        if "?" in self.official_locator or "&" in self.official_locator:
            raise GriauleAcquisitionError(
                "the official locator carries a query string, which usually means "
                "a signed or session-scoped URL. Such a locator names one fetch "
                "rather than the artifact, and it must never be published"
            )

    def as_row(self) -> Mapping[str, Any]:
        return {
            "official_locator_category": self.official_locator_category.value,
            "official_locator": self.official_locator,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "obtained_utc": self.obtained_utc,
            "product": self.product,
            "product_version": self.product_version,
            "build_or_revision": self.build_or_revision,
            "platform": self.platform,
            "documentation_obtained": self.documentation_obtained,
            "license_obtained": self.license_obtained,
            "bundled_trial_present": self.bundled_trial_present,
        }


@dataclass(frozen=True, slots=True)
class AcquisitionState:
    """Where the package actually stands on this machine."""

    status: AcquisitionStatus
    presence: ArtifactPresence
    declaration: PackageDeclaration | None
    detail: str

    @property
    def obtained(self) -> bool:
        """The package is here and its declaration verifies against the bytes."""
        return (
            self.status is AcquisitionStatus.OBTAINED
            and self.presence.is_the_delivered_package
            and self.declaration is not None
        )


def artifact_store_prefix_path(*, repository_root: Path | None = None) -> Path:
    """Where a delivered package would live, on whatever machine is running.

    Raises:
        GriauleAcquisitionError: no store is resolvable, or the resolved store
            sits inside the working tree — which would put vendor bytes one
            ``git add -A`` away from a public repository (docs/adr/0083).
    """
    try:
        root = resolve_third_party_root(repository_root=repository_root)
    except Exception as exc:  # pragma: no cover - an unusable store
        raise GriauleAcquisitionError(
            f"no local artifact store is resolvable here: {exc}"
        ) from exc
    return Path(root) / ARTIFACT_STORE_PREFIX


def unpacked_root(*, repository_root: Path | None = None) -> Path:
    """Where the package would be unpacked."""
    return (
        artifact_store_prefix_path(repository_root=repository_root)
        / UNPACKED_DIRECTORY_NAME
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_guarded_json(path: Path, *, what: str) -> Mapping[str, Any]:
    """Read a store document, refusing to hand licence material to a caller.

    The store sits on a machine that also holds licence files and machine
    identifiers. A record read out of it travels into code paths that publish, so
    it is checked on the way in rather than on the way out.
    """
    from fpbench.experiments.stage14a_preflight import require_no_sensitive_material

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GriauleAcquisitionError(f"cannot read the {what}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GriauleAcquisitionError(f"the {what} is not a JSON object")
    require_no_sensitive_material(payload, where=f"the {what} in the artifact store")
    return payload


def read_package_declaration(
    *, repository_root: Path | None = None
) -> PackageDeclaration | None:
    """What the store says was obtained, if anything."""
    try:
        prefix = artifact_store_prefix_path(repository_root=repository_root)
    except GriauleAcquisitionError:
        return None
    target = prefix / PACKAGE_DECLARATION_NAME
    if not target.is_file():
        return None
    payload = _read_guarded_json(target, what="package declaration")
    try:
        category = LocatorCategory(
            str(payload.get("official_locator_category", "")).strip()
        )
    except ValueError as exc:
        raise GriauleAcquisitionError(
            "the package declaration names a locator category outside the closed "
            f"set: {exc}"
        ) from exc
    try:
        size = int(payload.get("size_bytes", 0))
    except (TypeError, ValueError) as exc:
        raise GriauleAcquisitionError("size_bytes is not an integer") from exc
    return PackageDeclaration(
        official_locator_category=category,
        official_locator=str(payload.get("official_locator", "")),
        filename=str(payload.get("filename", "")),
        size_bytes=size,
        sha256=str(payload.get("sha256", "")),
        obtained_utc=str(payload.get("obtained_utc", "")),
        product=str(payload.get("product", "")),
        product_version=str(payload.get("product_version", "")),
        build_or_revision=str(payload.get("build_or_revision", "")),
        platform=str(payload.get("platform", "")),
        documentation_obtained=bool(payload.get("documentation_obtained", False)),
        license_obtained=bool(payload.get("license_obtained", False)),
        bundled_trial_present=bool(payload.get("bundled_trial_present", False)),
    )


def write_package_declaration(
    declaration: PackageDeclaration, *, repository_root: Path | None = None
) -> Path:
    """Record what was obtained, beside the bytes and outside the repository."""
    prefix = artifact_store_prefix_path(repository_root=repository_root)
    prefix.mkdir(parents=True, exist_ok=True)
    target = prefix / PACKAGE_DECLARATION_NAME
    payload = {"schema": "stage_14a_package_declaration_v1", **declaration.as_row()}
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def _presence(
    prefix: Path, declaration: PackageDeclaration | None
) -> tuple[ArtifactPresence, str]:
    """What is actually in the store, checked rather than declared."""
    if not prefix.is_dir():
        return ArtifactPresence.ABSENT, "the artifact store holds no Griaule directory"
    bookkeeping = {PACKAGE_DECLARATION_NAME, PACKAGE_INSPECTION_NAME}
    payloads = [
        item
        for item in prefix.iterdir()
        if item.is_file() and item.name not in bookkeeping
    ]
    if declaration is None:
        if payloads:
            return (
                ArtifactPresence.UNDECLARED,
                f"{len(payloads)} file(s) are in the store and nothing describes them",
            )
        return ArtifactPresence.ABSENT, "the store is empty"
    target = prefix / declaration.filename
    if not target.is_file():
        return (
            ArtifactPresence.MISMATCHED,
            f"the declaration names {declaration.filename} and it is not here",
        )
    size = target.stat().st_size
    if size != declaration.size_bytes:
        return (
            ArtifactPresence.MISMATCHED,
            f"the declared size is {declaration.size_bytes} and the file is {size}",
        )
    if _file_sha256(target) != declaration.sha256:
        return (
            ArtifactPresence.MISMATCHED,
            "the file's digest does not match the declaration; these are not the "
            "declared bytes",
        )
    return ArtifactPresence.VERIFIED, "the declared package is present and verifies"


def acquisition_state(*, repository_root: Path | None = None) -> AcquisitionState:
    """Where acquisition actually stands: the store first, the request second.

    The store wins where it can. A verified package makes the request status
    irrelevant — however it arrived, it is here — and everything else is decided
    by what the request has done.
    """
    try:
        prefix = artifact_store_prefix_path(repository_root=repository_root)
    except GriauleAcquisitionError as exc:
        prefix = None
        store_detail = str(exc)
    else:
        store_detail = ""

    declaration: PackageDeclaration | None = None
    presence = ArtifactPresence.ABSENT
    if prefix is not None:
        try:
            declaration = read_package_declaration(repository_root=repository_root)
        except (GriauleAcquisitionError, GriauleSensitiveEvidenceError) as exc:
            return AcquisitionState(
                status=AcquisitionStatus.DECLARATION_REQUIRED,
                presence=ArtifactPresence.MALFORMED,
                declaration=None,
                detail=str(exc),
            )
        presence, store_detail = _presence(prefix, declaration)

    if presence is ArtifactPresence.VERIFIED and declaration is not None:
        return AcquisitionState(
            status=AcquisitionStatus.OBTAINED,
            presence=presence,
            declaration=declaration,
            detail=store_detail,
        )
    if presence in (
        ArtifactPresence.UNDECLARED,
        ArtifactPresence.MISMATCHED,
        ArtifactPresence.MALFORMED,
    ):
        return AcquisitionState(
            status=AcquisitionStatus.DECLARATION_REQUIRED,
            presence=presence,
            declaration=declaration,
            detail=store_detail,
        )

    status = {
        RequestStatus.PREPARED_NOT_SENT: AcquisitionStatus.REQUEST_NOT_SENT,
        RequestStatus.SENT_AWAITING_REPLY: AcquisitionStatus.REQUEST_PENDING,
        RequestStatus.REPLY_REQUIRES_FURTHER_STEPS: (
            AcquisitionStatus.FURTHER_STEPS_REQUIRED
        ),
        RequestStatus.PACKAGE_DELIVERED: AcquisitionStatus.DECLARATION_REQUIRED,
        RequestStatus.REFUSED: AcquisitionStatus.ACCESS_REFUSED,
        RequestStatus.CONFIRMED_UNAVAILABLE: AcquisitionStatus.PACKAGE_UNAVAILABLE,
    }[REQUEST_STATUS]
    detail = {
        AcquisitionStatus.REQUEST_NOT_SENT: (
            "every official route was walked and none of them serves the package; "
            "the one request this project owes has not been sent"
        ),
        AcquisitionStatus.REQUEST_PENDING: (
            "an official request was sent and no reply has arrived"
        ),
        AcquisitionStatus.FURTHER_STEPS_REQUIRED: (
            "the vendor replied and the reply asks for something further before a "
            "package can be delivered"
        ),
        AcquisitionStatus.DECLARATION_REQUIRED: (
            "the vendor delivered a package and it has not been placed in the "
            "store, hashed and declared"
        ),
        AcquisitionStatus.ACCESS_REFUSED: "the vendor declined",
        AcquisitionStatus.PACKAGE_UNAVAILABLE: (
            "the vendor confirmed no package is available for this use"
        ),
    }[status]
    return AcquisitionState(
        status=status, presence=presence, declaration=declaration, detail=detail
    )


def package_inspection(
    *, repository_root: Path | None = None
) -> Mapping[str, Any] | None:
    """The inspection record beside the unpacked package, or ``None``.

    This is what G2, G3 and G4 are answered from: what the delivered headers,
    samples, documentation and terms actually say. It exists only after somebody
    has read them.
    """
    state = acquisition_state(repository_root=repository_root)
    if not state.obtained:
        return None
    try:
        path = (
            artifact_store_prefix_path(repository_root=repository_root)
            / PACKAGE_INSPECTION_NAME
        )
    except GriauleAcquisitionError:  # pragma: no cover - an unusable store
        return None
    if not path.is_file():
        return None
    return _read_guarded_json(path, what="package inspection record")


# ------------------------------------------------------------- the byte guard


@dataclass(frozen=True, slots=True)
class TrackedByteFinding:
    """One tracked file that looks like a vendor artifact or a licence."""

    path: str
    rule: str
    detail: str


@dataclass(frozen=True, slots=True)
class TrackedByteAudit:
    """What the repository holds, checked against what it may never hold."""

    tracked_file_count: int
    findings: tuple[TrackedByteFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


#: Shapes a Griaule delivery takes. The tokens are assembled from parts so that
#: this module's own source does not match the rules it defines.
_VENDOR_NAME_FRAGMENTS = (
    "gri" + "aule",
    "gbsfinger" + "print",
    "gr" + "finger",
)

#: A licence file, whatever it is called and whoever made it.
_VENDOR_SUFFIXES = (".lic", ".license", ".licence")
_LICENSE_NAME_FRAGMENTS = ("licensemanager", "license_manager", "hardwareid")

#: Text files that carry no extension at all.
_TEXT_FILENAMES = frozenset(
    {"makefile", "dockerfile", "license", "notice", "readme", ".gitignore"}
)

#: Extensions that would carry a runtime rather than a description of one.
_BINARY_SUFFIXES = (
    ".dll",
    ".so",
    ".dylib",
    ".lib",
    ".a",
    ".jar",
    ".exe",
    ".msi",
    ".zip",
    ".tar",
    ".gz",
    ".deb",
    ".rpm",
)

#: Where a vendor's name may legitimately appear: this stage's own source, tests,
#: docs and evidence say it on every page. The rule is about bytes, not names.
_TEXT_SUFFIXES = (
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".cfg",
    ".toml",
    ".java",
    ".cs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".xml",
    ".sh",
    ".bat",
    ".ps1",
    ".mk",
    ".in",
    ".rst",
    ".csv",
    ".ini",
)


def _tracked_files(repository_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "ls-files", "-z"),
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GriauleAcquisitionError(
            f"cannot list tracked files for the Stage 14A byte guard: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise GriauleAcquisitionError(
            "cannot list tracked files for the Stage 14A byte guard"
            + (f": {detail}" if detail else "")
        )
    return tuple(
        item for item in completed.stdout.decode("utf-8", "replace").split("\0") if item
    )


def audit_tracked_bytes_against_griaule_artifacts(
    repository_root: Path,
) -> TrackedByteAudit:
    """Every tracked file, checked against the shapes a delivery takes.

    A text file may name the product — this stage's own source, tests, docs and
    evidence do it on every page. A binary or a licence file may not, whatever it
    is called.
    """
    findings: list[TrackedByteFinding] = []
    tracked = _tracked_files(repository_root)
    for relative in tracked:
        lowered = relative.lower()
        pure = PurePosixPath(lowered)
        suffix = pure.suffix
        name = pure.name
        if suffix in _VENDOR_SUFFIXES:
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    rule="licence_file_suffix",
                    detail=(
                        f"a tracked {suffix} file is a licence, and a licence "
                        "never enters a public repository"
                    ),
                )
            )
            continue
        if any(fragment in name for fragment in _LICENSE_NAME_FRAGMENTS):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    rule="licence_file_name",
                    detail="a tracked file is named like licensing material",
                )
            )
            continue
        if suffix in _BINARY_SUFFIXES and any(
            fragment in lowered for fragment in _VENDOR_NAME_FRAGMENTS
        ):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    rule="vendor_binary",
                    detail=(
                        "a tracked binary is named after a vendor component; "
                        "vendor bytes stay in the local artifact store"
                    ),
                )
            )
            continue
        if (
            suffix not in _TEXT_SUFFIXES
            and name not in _TEXT_FILENAMES
            and any(fragment in lowered for fragment in _VENDOR_NAME_FRAGMENTS)
        ):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    rule="vendor_named_non_text",
                    detail="a tracked non-text file is named after a vendor component",
                )
            )
    return TrackedByteAudit(tracked_file_count=len(tracked), findings=tuple(findings))


def require_no_griaule_bytes_in_git(repository_root: Path) -> TrackedByteAudit:
    """The raising form.

    Raises:
        GriauleAcquisitionError: a vendor artifact or licence file is tracked.
    """
    audit = audit_tracked_bytes_against_griaule_artifacts(repository_root)
    if audit.findings:
        listed = ", ".join(f"{item.path} ({item.rule})" for item in audit.findings)
        raise GriauleAcquisitionError(
            f"vendor bytes or licence material are tracked in Git: {listed}"
        )
    return audit


def _validate_module() -> None:
    """Checked at import: the request status has to agree with the routes.

    A ``PREPARED_NOT_SENT`` request is only coherent while no route hands the
    package over. If a self-service locator were ever found, the outstanding act
    would be a download rather than a request, and this constant would be
    describing work nobody needs to do.
    """
    offered = any(
        route.outcome is RouteOutcome.PACKAGE_OFFERED for route in OFFICIAL_ROUTES
    )
    if offered != SELF_SERVICE_LOCATOR_FOUND:  # pragma: no cover - observations check
        raise GriauleAcquisitionError("the route table and its own summary disagree")
    if SELF_SERVICE_LOCATOR_FOUND and REQUEST_STATUS is RequestStatus.PREPARED_NOT_SENT:
        raise GriauleAcquisitionError(
            "a self-service package is available and the outstanding act is "
            "recorded as an unsent request. The act would be a download"
        )
    if REQUEST_SENT_UTC and not REQUEST_STATUS.is_sent:
        raise GriauleAcquisitionError(
            "a send date is recorded for a request that has not been sent"
        )
    if REQUEST_STATUS.is_sent and not REQUEST_SENT_UTC:
        raise GriauleAcquisitionError(
            "a sent request records when it was sent; a vendor wait with no start "
            "date cannot be reasoned about"
        )


_validate_module()


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage14a_acquisition``.

    ``state`` reports where the package stands. ``declare`` records a package
    already present in the store, computing its size and digest rather than
    accepting them. ``guard`` runs the tracked-byte audit.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Stage 14A acquisition")
    parser.add_argument("action", choices=("state", "declare", "guard"))
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--filename")
    parser.add_argument("--locator")
    parser.add_argument(
        "--locator-category",
        choices=[item.value for item in LocatorCategory if item.is_official],
    )
    parser.add_argument("--product-version")
    parser.add_argument("--build")
    parser.add_argument("--platform")
    parser.add_argument("--obtained-utc")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "guard":
        audit = require_no_griaule_bytes_in_git(root)
        print(
            f"{audit.tracked_file_count} tracked files scanned against the vendor "
            f"artifact and licence name rules, {len(audit.findings)} findings"
        )
        return 0

    if arguments.action == "state":
        state = acquisition_state(repository_root=root)
        print(f"request   {REQUEST_STATUS.value}")
        print(f"status    {state.status.value}")
        print(f"presence  {state.presence.value}")
        print(f"detail    {state.detail}")
        for route in OFFICIAL_ROUTES:
            print(f"  {route.outcome.value:<24s} {route.route_id}")
        return 0

    required = (
        "filename",
        "locator",
        "locator_category",
        "product_version",
        "build",
        "platform",
        "obtained_utc",
    )
    missing = [name for name in required if not getattr(arguments, name)]
    if missing:
        raise SystemExit(
            f"declaring a package needs {missing}; every one of them is a "
            "property of the artifact, and a declaration assembled from blanks "
            "would identify nothing"
        )
    prefix = artifact_store_prefix_path(repository_root=root)
    target = prefix / arguments.filename
    if not target.is_file():
        raise SystemExit(f"{arguments.filename} is not in the artifact store")
    declaration = PackageDeclaration(
        official_locator_category=LocatorCategory(arguments.locator_category),
        official_locator=arguments.locator,
        filename=arguments.filename,
        size_bytes=target.stat().st_size,
        sha256=_file_sha256(target),
        obtained_utc=arguments.obtained_utc,
        product="GBS Fingerprint SDK",
        product_version=arguments.product_version,
        build_or_revision=arguments.build,
        platform=arguments.platform,
        documentation_obtained=False,
        license_obtained=False,
        bundled_trial_present=False,
    )
    written = write_package_declaration(declaration, repository_root=root)
    print(f"declared {declaration.filename} at {declaration.sha256}")
    print(f"written to the artifact store as {written.name}")
    print(
        "documentation, licence and bundled-trial flags start false and are set "
        "by inspecting what actually arrived"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
