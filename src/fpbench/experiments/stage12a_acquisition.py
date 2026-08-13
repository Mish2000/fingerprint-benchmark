"""Where the package is, and what this machine may say about it.

Stage 11A could hash its way to an answer: Neurotechnology publishes a direct
locator, so "is the artifact here" was a question about bytes. Innovatrics does
not, and the two facts that decide this gate — *a vendor delivered this package*
and *this project may ask them for one* — are not properties of any file. They
are things the maintainer knows and this module records.

So the store may hold two small declarations beside the package, neither of them
in Git:

.. code-block:: text

    <store>/innovatrics-idkit/acquisition-state.json     where the exchange stands
    <store>/innovatrics-idkit/package-declaration.json   what was delivered

**Neither is inferred.** A refusal is never guessed from an empty directory, and
possession is never guessed from bytes with no declaration behind them. The
seven-state machine is closed, ``ACCESS_REFUSED`` is a claim only a person can
make, and the ordinary state of a machine that has not been given a package is
the one the observations module recorded from walking the routes
(docs/adr/0108).

**Every reading is guarded.** Both declarations are run through the secret guard
before anything is returned, because they are written by hand on a machine that
also holds licence material, and the one thing that must never happen is a
hardware ID travelling from the store into a published document.

Nothing here downloads, activates, or reaches the network.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.idkit_preflight_errors import (
    IdkitAcquisitionError,
    IdkitSensitiveEvidenceError,
)
from fpbench.experiments.stage12a_idkit_identity import (
    ARTIFACT_STORE_PREFIX,
    PACKAGE_IDENTITY_FIELDS,
    AcquisitionStatus,
    DeliveryChannel,
    ProductFamily,
)
from fpbench.experiments.stage12a_idkit_observations import (
    ACQUISITION_STATUS_BASIS,
    OBSERVED_ACQUISITION_STATUS,
)
from fpbench.third_party import resolve_third_party_root

__all__ = [
    "ACQUISITION_STATE_NAME",
    "PACKAGE_DECLARATION_NAME",
    "DECLARABLE_STATES",
    "PackagePresence",
    "PackageDeclaration",
    "DeclaredState",
    "AcquisitionState",
    "artifact_store_prefix_path",
    "read_declared_state",
    "read_package_declaration",
    "acquisition_state",
    "TrackedByteFinding",
    "TrackedByteAudit",
    "audit_tracked_bytes_against_idkit_artifacts",
    "require_no_idkit_bytes_in_git",
]

#: What the maintainer writes to say where the vendor exchange stands. Absent on
#: an ordinary machine, and absent means "whatever walking the public routes
#: found", not "nothing has been tried".
ACQUISITION_STATE_NAME = "acquisition-state.json"

#: What the maintainer writes when a package has actually been delivered.
PACKAGE_DECLARATION_NAME = "package-declaration.json"

#: The states a person may declare. ``PACKAGE_OBTAINED`` is not among them: it is
#: not a claim, it is a file that verifies against a declaration, and letting it
#: be asserted would make the one state with consequences the one state nobody
#: checks.
DECLARABLE_STATES: tuple[AcquisitionStatus, ...] = (
    AcquisitionStatus.NOT_ATTEMPTED,
    AcquisitionStatus.PORTAL_ACCESS_REQUIRED,
    AcquisitionStatus.REQUEST_SENT,
    AcquisitionStatus.REQUEST_PENDING,
    AcquisitionStatus.ACCESS_REFUSED,
    AcquisitionStatus.PACKAGE_UNAVAILABLE_FOR_TARGET,
)

_HEX = frozenset("0123456789abcdef")


class PackagePresence(str, Enum):
    """What is in the store where a delivered package would be."""

    #: The declaration verifies and the file it names matches by size and digest.
    VERIFIED = "VERIFIED"

    #: Nothing at all. The ordinary state of every machine that was not given a
    #: package, and of every CI runner.
    ABSENT = "ABSENT"

    #: Bytes are here and nothing describes them. Not possession: a package
    #: nobody recorded the provenance of is a package that cannot be pinned to a
    #: vendor, and G2 would have nothing to read.
    UNDECLARED = "UNDECLARED"

    #: A declaration is here and does not agree with the bytes beside it.
    MISMATCHED = "MISMATCHED"

    #: A declaration is here and is not usable.
    MALFORMED = "MALFORMED"

    @property
    def is_the_delivered_package(self) -> bool:
        return self is PackagePresence.VERIFIED


@dataclass(frozen=True, slots=True)
class PackageDeclaration:
    """What was delivered, as the person who received it recorded it.

    Every field is required. A declaration with the version left out would let
    the preflight proceed to gates that are all questions about a version, and
    the honest answer to "which version" is not "the one on the course page"
    (docs/adr/0110).
    """

    exact_product_name: str
    product_family: ProductFamily
    implementation_version: str
    package_build: str
    package_filename: str
    package_size_bytes: int
    package_sha256: str
    delivery_channel: DeliveryChannel
    operating_system: str
    architecture: str
    documentation_obtained: bool
    licensing_route_available: bool
    received_utc: str

    def __post_init__(self) -> None:
        for name in (
            "exact_product_name",
            "implementation_version",
            "package_build",
            "package_filename",
            "operating_system",
            "architecture",
            "received_utc",
        ):
            if not str(getattr(self, name)).strip():
                raise IdkitAcquisitionError(
                    f"the package declaration leaves {name} empty; every field of "
                    "the package identity is required before anything is executed"
                )
        name = PurePosixPath(self.package_filename)
        if len(name.parts) != 1 or str(name) != self.package_filename:
            raise IdkitAcquisitionError(
                "package_filename is a plain filename inside the store prefix, "
                "not a path"
            )
        if not isinstance(self.package_size_bytes, int) or self.package_size_bytes <= 0:
            raise IdkitAcquisitionError("package_size_bytes must be a positive integer")
        digest = str(self.package_sha256).strip().lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise IdkitAcquisitionError(
                "package_sha256 must be a 64-character hexadecimal digest"
            )
        object.__setattr__(self, "package_sha256", digest)
        if self.product_family is ProductFamily.UNRESOLVED:
            raise IdkitAcquisitionError(
                "a delivered package resolves to a product family. UNRESOLVED is "
                "what the preflight reports when nothing was delivered, not "
                "something a delivery may declare"
            )

    @property
    def identity_row(self) -> Mapping[str, Any]:
        """The identity, in the frozen field order."""
        values = {
            "exact_product_name": self.exact_product_name,
            "product_family": self.product_family.value,
            "implementation_version": self.implementation_version,
            "package_build": self.package_build,
            "package_filename": self.package_filename,
            "package_size_bytes": self.package_size_bytes,
            "package_sha256": self.package_sha256,
            "delivery_channel": self.delivery_channel.value,
            "operating_system": self.operating_system,
            "architecture": self.architecture,
        }
        return {name: values[name] for name in PACKAGE_IDENTITY_FIELDS}


@dataclass(frozen=True, slots=True)
class DeclaredState:
    """A state the maintainer declared, with the reason they gave."""

    status: AcquisitionStatus
    basis: str
    declared_utc: str

    def __post_init__(self) -> None:
        if self.status not in DECLARABLE_STATES:
            raise IdkitAcquisitionError(
                f"{self.status.value} is not a state a person may declare; "
                f"possession is established by a verified package, not asserted"
            )
        if not str(self.basis).strip():
            raise IdkitAcquisitionError(
                "a declared acquisition state names what happened. A refusal with "
                "no reason behind it is a refusal nobody can act on"
            )
        if not str(self.declared_utc).strip():
            raise IdkitAcquisitionError("a declared acquisition state is dated")


@dataclass(frozen=True, slots=True)
class AcquisitionState:
    """Where the acquisition actually stands on this machine."""

    status: AcquisitionStatus
    presence: PackagePresence
    basis: str
    declaration: PackageDeclaration | None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status.is_obtained and not self.presence.is_the_delivered_package:
            raise IdkitAcquisitionError(
                "possession is claimed and no verified package is present"
            )
        if self.status.is_obtained and self.declaration is None:
            raise IdkitAcquisitionError(
                "possession is claimed with nothing describing what was delivered"
            )
        if not self.status.is_obtained and self.declaration is not None:
            raise IdkitAcquisitionError(
                "a package declaration is present and the state is not "
                "PACKAGE_OBTAINED; one of the two is wrong and the preflight will "
                "not choose between them"
            )

    @property
    def obtained(self) -> bool:
        return self.status.is_obtained

    @property
    def is_pending(self) -> bool:
        return self.status.is_pending

    @property
    def is_refusal(self) -> bool:
        return self.status.is_refusal


def artifact_store_prefix_path(*, repository_root: Path | None = None) -> Path:
    """Where a delivered package would live, on whatever machine is running.

    Raises:
        IdkitAcquisitionError: no store is resolvable, or the resolved store sits
            inside the working tree — which would put vendor bytes one
            ``git add -A`` away from a public repository (docs/adr/0083).
    """
    try:
        root = resolve_third_party_root(repository_root=repository_root)
    except Exception as exc:  # pragma: no cover - an unusable store
        raise IdkitAcquisitionError(
            f"no local artifact store is resolvable here: {exc}"
        ) from exc
    return Path(root) / ARTIFACT_STORE_PREFIX


def _read_guarded_json(path: Path, *, what: str) -> Mapping[str, Any]:
    """Read a store declaration, refusing one that carries a credential.

    Raises:
        IdkitSensitiveEvidenceError: the file holds something shaped like licence
            material. It is refused at the reader rather than at the publisher,
            so that a hardware ID cannot travel from the store into an
            in-memory document that some later code path prints.
    """
    from fpbench.experiments.stage12a_preflight import require_no_sensitive_material

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IdkitAcquisitionError(f"cannot read the {what}: {exc}") from exc
    if not isinstance(payload, dict):
        raise IdkitAcquisitionError(f"the {what} is not a JSON object")
    require_no_sensitive_material(payload, where=f"the {what} in the artifact store")
    return payload


def read_declared_state(*, repository_root: Path | None = None) -> DeclaredState | None:
    """The maintainer's declaration of where the vendor exchange stands, if any.

    Returns:
        ``None`` where no declaration exists, which is the ordinary case and is
        not an error: the public routes were walked and their result stands.
    """
    try:
        path = artifact_store_prefix_path(repository_root=repository_root)
    except IdkitAcquisitionError:
        return None
    target = path / ACQUISITION_STATE_NAME
    if not target.is_file():
        return None
    payload = _read_guarded_json(target, what="declared acquisition state")
    raw = str(payload.get("status", "")).strip()
    try:
        status = AcquisitionStatus(raw)
    except ValueError as exc:
        raise IdkitAcquisitionError(
            f"{raw!r} is not one of the {len(AcquisitionStatus)} acquisition "
            "states; the machine is closed on purpose"
        ) from exc
    return DeclaredState(
        status=status,
        basis=str(payload.get("basis", "")),
        declared_utc=str(payload.get("declared_utc", "")),
    )


def read_package_declaration(
    *, repository_root: Path | None = None
) -> PackageDeclaration | None:
    """What the store says was delivered, if anything."""
    try:
        path = artifact_store_prefix_path(repository_root=repository_root)
    except IdkitAcquisitionError:
        return None
    target = path / PACKAGE_DECLARATION_NAME
    if not target.is_file():
        return None
    payload = _read_guarded_json(target, what="package declaration")
    try:
        family = ProductFamily(str(payload.get("product_family", "")).strip())
        channel = DeliveryChannel(str(payload.get("delivery_channel", "")).strip())
    except ValueError as exc:
        raise IdkitAcquisitionError(
            "the package declaration names a product family or delivery channel "
            f"outside the closed sets: {exc}"
        ) from exc
    try:
        size = int(payload.get("package_size_bytes", 0))
    except (TypeError, ValueError) as exc:
        raise IdkitAcquisitionError("package_size_bytes is not an integer") from exc
    return PackageDeclaration(
        exact_product_name=str(payload.get("exact_product_name", "")),
        product_family=family,
        implementation_version=str(payload.get("implementation_version", "")),
        package_build=str(payload.get("package_build", "")),
        package_filename=str(payload.get("package_filename", "")),
        package_size_bytes=size,
        package_sha256=str(payload.get("package_sha256", "")),
        delivery_channel=channel,
        operating_system=str(payload.get("operating_system", "")),
        architecture=str(payload.get("architecture", "")),
        documentation_obtained=bool(payload.get("documentation_obtained", False)),
        licensing_route_available=bool(payload.get("licensing_route_available", False)),
        received_utc=str(payload.get("received_utc", "")),
    )


def _store_entries(path: Path) -> tuple[str, ...]:
    """What is in the store prefix, excluding the two declarations."""
    if not path.is_dir():
        return ()
    return tuple(
        sorted(
            item.name
            for item in path.iterdir()
            if item.name not in (ACQUISITION_STATE_NAME, PACKAGE_DECLARATION_NAME)
        )
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _presence(
    declaration: PackageDeclaration | None, path: Path
) -> tuple[PackagePresence, str]:
    """Check the declaration against the bytes beside it, size before digest."""
    entries = _store_entries(path)
    if declaration is None:
        if entries:
            return (
                PackagePresence.UNDECLARED,
                f"{len(entries)} entries are in the store under this stage's "
                "prefix and no package declaration describes them. A package "
                "nobody recorded a provenance for cannot be pinned to a vendor",
            )
        return (
            PackagePresence.ABSENT,
            "nothing is in the local artifact store under this stage's prefix",
        )
    target = path / declaration.package_filename
    if not target.is_file():
        return (
            PackagePresence.MISMATCHED,
            f"the declaration names {declaration.package_filename!r} and no such "
            "file is in the store",
        )
    try:
        size = target.stat().st_size
    except OSError as exc:  # pragma: no cover - a file that cannot be stat'ed
        return (PackagePresence.MALFORMED, f"the declared package is unreadable: {exc}")
    if size != declaration.package_size_bytes:
        return (
            PackagePresence.MISMATCHED,
            f"the declared package is {declaration.package_size_bytes} bytes and "
            f"the file is {size}; an interrupted transfer looks exactly like this",
        )
    try:
        digest = _file_sha256(target)
    except OSError as exc:  # pragma: no cover - a file that cannot be read
        return (PackagePresence.MALFORMED, f"the declared package is unreadable: {exc}")
    if digest != declaration.package_sha256:
        return (
            PackagePresence.MISMATCHED,
            "the declared package digest does not match the file beside it, which "
            "means the bytes are not the bytes that were described",
        )
    if not declaration.documentation_obtained:
        return (
            PackagePresence.MISMATCHED,
            "the package is here and the declaration says its matching "
            "documentation is not. A package whose own documentation is missing "
            "cannot settle a settings inventory, and the gate wants all three: "
            "package, documentation, licensing route",
        )
    if not declaration.licensing_route_available:
        return (
            PackagePresence.MISMATCHED,
            "the package is here and the declaration says no legitimate licensing "
            "route exists for it. Nothing is executed without one",
        )
    return (PackagePresence.VERIFIED, "")


def acquisition_state(*, repository_root: Path | None = None) -> AcquisitionState:
    """Where the acquisition stands, from the store and the walked routes.

    The order is deliberate. A verified package settles it. Otherwise a declared
    state settles it, because only a person knows whether a vendor was written to
    and what they said. Otherwise the state is what walking the public routes
    found, which is a pending state and never a refusal (docs/adr/0108).
    """
    try:
        path = artifact_store_prefix_path(repository_root=repository_root)
    except IdkitAcquisitionError as exc:
        return AcquisitionState(
            status=OBSERVED_ACQUISITION_STATUS,
            presence=PackagePresence.ABSENT,
            basis=ACQUISITION_STATUS_BASIS,
            declaration=None,
            detail=str(exc),
        )

    declaration = read_package_declaration(repository_root=repository_root)
    presence, detail = _presence(declaration, path)
    if presence.is_the_delivered_package and declaration is not None:
        return AcquisitionState(
            status=AcquisitionStatus.PACKAGE_OBTAINED,
            presence=presence,
            basis=(
                f"{declaration.exact_product_name} "
                f"{declaration.implementation_version} was delivered through "
                f"{declaration.delivery_channel.value} on "
                f"{declaration.received_utc}, its matching documentation was "
                "obtained, a legitimate licensing route exists, and the file in "
                "the store matches the declared size and digest"
            ),
            declaration=declaration,
        )

    declared = read_declared_state(repository_root=repository_root)
    if declared is not None:
        return AcquisitionState(
            status=declared.status,
            presence=presence,
            basis=f"declared on {declared.declared_utc}: {declared.basis}",
            declaration=None,
            detail=detail,
        )
    return AcquisitionState(
        status=OBSERVED_ACQUISITION_STATUS,
        presence=presence,
        basis=ACQUISITION_STATUS_BASIS,
        declaration=None,
        detail=detail,
    )


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


#: Shapes an Innovatrics delivery takes. Checked by shape rather than by digest
#: because there is no digest yet: the package has not been delivered, and the
#: file this guard most needs to catch is the one nobody has hashed. The tokens
#: are assembled from parts so that this module's own source does not match the
#: rules it defines.
_VENDOR_NAME_FRAGMENTS = ("id" + "kit", "inno" + "vatrics", "iengine")
_VENDOR_SUFFIXES = (".lic", ".license", ".licence")
_LICENSE_NAME_FRAGMENTS = ("licensemanager", "license_manager", "hardwareid", "id.txt")

#: Extensions that would carry a runtime rather than a description of one.
_BINARY_SUFFIXES = (".dll", ".so", ".dylib", ".lib", ".a", ".jar", ".exe")

#: Where this stage's own words are allowed to say those things: its source, its
#: tests, its documentation and its evidence all name the product constantly.
_TEXT_SUFFIXES = (".py", ".md", ".yml", ".yaml", ".json", ".txt", ".cfg", ".toml")


def _tracked_files(repository_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "ls-files", "-z"),
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IdkitAcquisitionError(
            f"cannot list tracked files for the Stage 12A byte guard: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise IdkitAcquisitionError(
            "cannot list tracked files for the Stage 12A byte guard"
            + (f": {detail}" if detail else "")
        )
    return tuple(
        item
        for item in completed.stdout.decode("utf-8", "replace").split("\0")
        if item
    )


def audit_tracked_bytes_against_idkit_artifacts(
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
        suffix = PurePosixPath(lowered).suffix
        name = PurePosixPath(lowered).name
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
                    rule="licence_material_name",
                    detail="a tracked file is named like licence material",
                )
            )
            continue
        if suffix in _BINARY_SUFFIXES and any(
            fragment in lowered for fragment in _VENDOR_NAME_FRAGMENTS
        ):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    rule="vendor_runtime_binary",
                    detail=(
                        "a tracked binary is named after the vendor or its "
                        "engine; vendor bytes live in the local artifact store"
                    ),
                )
            )
            continue
        if suffix not in _TEXT_SUFFIXES and any(
            fragment in lowered for fragment in _VENDOR_NAME_FRAGMENTS
        ):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    rule="vendor_named_non_text_file",
                    detail=(
                        "a tracked non-text file is named after the vendor. If it "
                        "is a description rather than a delivery, give it a text "
                        "extension so it can be read in a diff"
                    ),
                )
            )
    return TrackedByteAudit(
        tracked_file_count=len(tracked), findings=tuple(findings)
    )


def require_no_idkit_bytes_in_git(repository_root: Path) -> TrackedByteAudit:
    """The raising form, for the publisher and for CI.

    Raises:
        IdkitSensitiveEvidenceError: a vendor artifact or licence is tracked. The
            publisher stops rather than removing it: a byte that reached a public
            history is not taken back by a later commit, and somebody has to
            decide what to do about it.
    """
    audit = audit_tracked_bytes_against_idkit_artifacts(repository_root)
    if audit.findings:
        raise IdkitSensitiveEvidenceError(
            "vendor or licence material is tracked in this repository: "
            + "; ".join(f"{item.path} ({item.rule})" for item in audit.findings)
        )
    return audit
