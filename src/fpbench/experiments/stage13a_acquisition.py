"""Where the FingerCell trial archive is, what it is, and what it must never be.

Three jobs.

**The store.** Vendor bytes live under ``FPBENCH_THIRD_PARTY_ROOT``, outside the
working tree, in this stage's own prefix. The repository holds descriptions of
them and never the bytes.

**The verification.** An archive is possessed when a declaration describes it and
the file beside it agrees — by size first and digest second, so a truncated
download is named as truncated rather than as "the wrong file". A declaration
with no file, or a file with no declaration, is not possession: an archive nobody
recorded the provenance of cannot be pinned to a vendor, and the identity gate
would have nothing to read.

**The guard.** Every tracked file is checked against the shapes a Neurotechnology
delivery takes. Text may name the product — this stage's source, tests, docs and
evidence do it on every page. A binary or a licence file may not, whatever it is
called.

Nothing here activates a licence, loads a runtime or produces a score. The
downloader is deliberately explicit and refuses to run anywhere that looks like
continuous integration.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.fingercell_preflight_errors import (
    FingerCellAcquisitionError,
    FingerCellSensitiveEvidenceError,
)
from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage13a_fingercell_identity import (
    ARTIFACT_EVIDENCE_FIELDS,
    ARTIFACT_STORE_PREFIX,
    DECLARED_PRODUCT_VERSION,
    PRODUCT_FAMILY,
    Binding,
    ComponentRole,
    LocatorCategory,
    VENDOR_PRODUCT_REVISION_INDICATION,
    VENDOR_REVISION_HASH_INDICATION,
)
from fpbench.third_party import resolve_third_party_root

__all__ = [
    "ARCHIVE_DECLARATION_NAME",
    "UNPACKED_DIRECTORY_NAME",
    "INVENTORY_NAME",
    "ArtifactPresence",
    "ArchiveDeclaration",
    "AcquisitionState",
    "RuntimeComponent",
    "artifact_store_prefix_path",
    "read_archive_declaration",
    "write_archive_declaration",
    "acquisition_state",
    "unpacked_root",
    "hash_component",
    "runtime_closure",
    "runtime_closure_fingerprint",
    "BRIDGE_SOURCE_FILES",
    "bridge_source_fingerprint",
    "bridge_binary_sha256",
    "TrackedByteFinding",
    "TrackedByteAudit",
    "audit_tracked_bytes_against_fingercell_artifacts",
    "require_no_fingercell_bytes_in_git",
    "main",
]

#: What the maintainer writes beside the archive after fetching it.
ARCHIVE_DECLARATION_NAME = "archive-declaration.json"

#: Where the archive is unpacked, inside the store and never inside the tree.
UNPACKED_DIRECTORY_NAME = "unpacked"

#: The runtime inventory a local inspection leaves behind.
INVENTORY_NAME = "runtime-inventory.json"

_HEX = frozenset("0123456789abcdef")


class ArtifactPresence(str, Enum):
    """What is in the store where the trial archive would be."""

    #: The declaration verifies and the file it names matches by size and digest.
    VERIFIED = "VERIFIED"

    #: Nothing at all. The ordinary state of every CI runner, and of every
    #: machine that has not run the acquisition step yet.
    ABSENT = "ABSENT"

    #: Bytes are here and nothing describes them.
    UNDECLARED = "UNDECLARED"

    #: A declaration is here and does not agree with the bytes beside it.
    MISMATCHED = "MISMATCHED"

    #: A declaration is here and is not usable.
    MALFORMED = "MALFORMED"

    @property
    def is_the_delivered_archive(self) -> bool:
        return self is ArtifactPresence.VERIFIED


@dataclass(frozen=True, slots=True)
class ArchiveDeclaration:
    """What was fetched, as the person who fetched it recorded it.

    Every field is required. A declaration with the digest left out would let the
    preflight proceed to gates that are all questions about specific bytes.
    """

    official_locator_category: LocatorCategory
    official_locator: str
    filename: str
    size_bytes: int
    sha256: str
    downloaded_utc: str
    product: str
    product_version: str
    vendor_product_revision: str
    vendor_revision_hash: str
    documentation_obtained: bool

    def __post_init__(self) -> None:
        for name in (
            "official_locator",
            "filename",
            "downloaded_utc",
            "product",
            "product_version",
            "vendor_product_revision",
            "vendor_revision_hash",
        ):
            if not str(getattr(self, name)).strip():
                raise FingerCellAcquisitionError(
                    f"the archive declaration leaves {name} empty; every field of "
                    "the artifact identity is required before anything is executed"
                )
        name = PurePosixPath(self.filename)
        if len(name.parts) != 1 or str(name) != self.filename:
            raise FingerCellAcquisitionError(
                "filename is a plain filename inside the store prefix, not a path"
            )
        if not isinstance(self.size_bytes, int) or self.size_bytes <= 0:
            raise FingerCellAcquisitionError("size_bytes must be a positive integer")
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise FingerCellAcquisitionError(
                "sha256 must be a 64-character hexadecimal digest. The vendor's "
                "40-character revision hash is not one and can never stand in for "
                "it (docs/adr/0113)"
            )
        object.__setattr__(self, "sha256", digest)
        if digest == str(self.vendor_revision_hash).strip().lower():
            raise FingerCellAcquisitionError(
                "the archive digest and the vendor revision hash are the same "
                "value; one of them has been pasted into the wrong field"
            )
        if self.official_locator_category is LocatorCategory.UNRESOLVED:
            raise FingerCellAcquisitionError(
                "a fetched archive came by some route. UNRESOLVED is what the "
                "preflight reports when nothing was fetched"
            )
        lowered = self.official_locator.lower()
        for marker in ("?", "x-amz-signature", "expires=", "token="):
            if marker in lowered:
                raise FingerCellAcquisitionError(
                    "the published locator carries a query, a signature or a "
                    "token. A signed URL is a fact about one fetch and not about "
                    "an artifact; publish the stable vendor locator and let the "
                    "digest do the pinning"
                )

    @property
    def identity_row(self) -> Mapping[str, Any]:
        """The identity, in the frozen field order."""
        values = {
            "official_locator_category": self.official_locator_category.value,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "downloaded_utc": self.downloaded_utc,
            "product": self.product,
            "product_version": self.product_version,
            "vendor_product_revision": self.vendor_product_revision,
            "vendor_revision_hash": self.vendor_revision_hash,
        }
        return {name: values[name] for name in ARTIFACT_EVIDENCE_FIELDS}

    @property
    def revision_agrees_with_release_notes(self) -> bool:
        """Whether the delivered revision is the one the public notes advertised."""
        return (
            self.vendor_product_revision.strip() == VENDOR_PRODUCT_REVISION_INDICATION
            and self.vendor_revision_hash.strip().lower()
            == VENDOR_REVISION_HASH_INDICATION
        )

    @property
    def is_the_expected_product(self) -> bool:
        return (
            self.product.strip() == PRODUCT_FAMILY
            and self.product_version.strip() == DECLARED_PRODUCT_VERSION
        )


@dataclass(frozen=True, slots=True)
class AcquisitionState:
    """Where acquisition actually stands on this machine."""

    presence: ArtifactPresence
    declaration: ArchiveDeclaration | None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.presence.is_the_delivered_archive and self.declaration is None:
            raise FingerCellAcquisitionError(
                "possession is claimed with nothing describing what was fetched"
            )

    @property
    def obtained(self) -> bool:
        return self.presence.is_the_delivered_archive


@dataclass(frozen=True, slots=True)
class RuntimeComponent:
    """One component of the runtime closure, described and never carried."""

    relative_path: str
    component_role: ComponentRole
    size_bytes: int
    sha256: str
    version_or_revision: str | None
    source_archive_member: str

    def __post_init__(self) -> None:
        if self.relative_path.startswith("/") or ":" in self.relative_path:
            raise FingerCellAcquisitionError(
                f"{self.relative_path!r} is not relative to the store; a published "
                "runtime path must never name a machine"
            )
        digest = str(self.sha256).strip().lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise FingerCellAcquisitionError(
                f"{self.relative_path}: sha256 must be a 64-character digest"
            )
        object.__setattr__(self, "sha256", digest)

    @property
    def row(self) -> Mapping[str, Any]:
        return {
            "relative_path": self.relative_path,
            "component_role": self.component_role.value,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "version_or_revision": self.version_or_revision,
            "source_archive_member": self.source_archive_member,
        }


def artifact_store_prefix_path(*, repository_root: Path | None = None) -> Path:
    """Where the trial archive lives, on whatever machine is running.

    Raises:
        FingerCellAcquisitionError: no store is resolvable, or the resolved store
            sits inside the working tree — which would put vendor bytes one
            ``git add -A`` away from a public repository (docs/adr/0083).
    """
    try:
        root = resolve_third_party_root(repository_root=repository_root)
    except Exception as exc:  # pragma: no cover - an unusable store
        raise FingerCellAcquisitionError(
            f"no local artifact store is resolvable here: {exc}"
        ) from exc
    return Path(root) / ARTIFACT_STORE_PREFIX


def unpacked_root(*, repository_root: Path | None = None) -> Path:
    """Where the archive is unpacked."""
    return (
        artifact_store_prefix_path(repository_root=repository_root)
        / UNPACKED_DIRECTORY_NAME
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_component(path: Path) -> tuple[int, str]:
    """Size and digest for one runtime component."""
    return path.stat().st_size, _file_sha256(path)


def _read_guarded_json(path: Path, *, what: str) -> Mapping[str, Any]:
    """Read a store declaration, refusing one that carries a credential.

    Raises:
        FingerCellSensitiveEvidenceError: the file holds something shaped like
            licence material. It is refused at the reader rather than at the
            publisher, so that a machine ID cannot travel from the store into an
            in-memory document some later code path prints.
    """
    from fpbench.experiments.stage13a_preflight import require_no_sensitive_material

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FingerCellAcquisitionError(f"cannot read the {what}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FingerCellAcquisitionError(f"the {what} is not a JSON object")
    require_no_sensitive_material(payload, where=f"the {what} in the artifact store")
    return payload


def read_archive_declaration(
    *, repository_root: Path | None = None
) -> ArchiveDeclaration | None:
    """What the store says was fetched, if anything."""
    try:
        path = artifact_store_prefix_path(repository_root=repository_root)
    except FingerCellAcquisitionError:
        return None
    target = path / ARCHIVE_DECLARATION_NAME
    if not target.is_file():
        return None
    payload = _read_guarded_json(target, what="archive declaration")
    try:
        category = LocatorCategory(
            str(payload.get("official_locator_category", "")).strip()
        )
    except ValueError as exc:
        raise FingerCellAcquisitionError(
            f"the archive declaration names a locator category outside the closed "
            f"set: {exc}"
        ) from exc
    try:
        size = int(payload.get("size_bytes", 0))
    except (TypeError, ValueError) as exc:
        raise FingerCellAcquisitionError("size_bytes is not an integer") from exc
    return ArchiveDeclaration(
        official_locator_category=category,
        official_locator=str(payload.get("official_locator", "")),
        filename=str(payload.get("filename", "")),
        size_bytes=size,
        sha256=str(payload.get("sha256", "")),
        downloaded_utc=str(payload.get("downloaded_utc", "")),
        product=str(payload.get("product", "")),
        product_version=str(payload.get("product_version", "")),
        vendor_product_revision=str(payload.get("vendor_product_revision", "")),
        vendor_revision_hash=str(payload.get("vendor_revision_hash", "")),
        documentation_obtained=bool(payload.get("documentation_obtained", False)),
    )


def write_archive_declaration(
    declaration: ArchiveDeclaration, *, repository_root: Path | None = None
) -> Path:
    """Record what was fetched, beside the bytes and outside the repository."""
    prefix = artifact_store_prefix_path(repository_root=repository_root)
    prefix.mkdir(parents=True, exist_ok=True)
    target = prefix / ARCHIVE_DECLARATION_NAME
    payload = {
        "schema": "stage_13a_archive_declaration_v1",
        "official_locator_category": declaration.official_locator_category.value,
        "official_locator": declaration.official_locator,
        "filename": declaration.filename,
        "size_bytes": declaration.size_bytes,
        "sha256": declaration.sha256,
        "downloaded_utc": declaration.downloaded_utc,
        "product": declaration.product,
        "product_version": declaration.product_version,
        "vendor_product_revision": declaration.vendor_product_revision,
        "vendor_revision_hash": declaration.vendor_revision_hash,
        "documentation_obtained": declaration.documentation_obtained,
    }
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def acquisition_state(*, repository_root: Path | None = None) -> AcquisitionState:
    """Where the archive actually stands, checked rather than declared."""
    try:
        prefix = artifact_store_prefix_path(repository_root=repository_root)
    except FingerCellAcquisitionError as exc:
        return AcquisitionState(
            presence=ArtifactPresence.ABSENT, declaration=None, detail=str(exc)
        )
    if not prefix.is_dir():
        return AcquisitionState(
            presence=ArtifactPresence.ABSENT,
            declaration=None,
            detail="no Stage 13A prefix exists in the local artifact store",
        )
    try:
        declaration = read_archive_declaration(repository_root=repository_root)
    except FingerCellSensitiveEvidenceError:
        raise
    except FingerCellAcquisitionError as exc:
        return AcquisitionState(
            presence=ArtifactPresence.MALFORMED, declaration=None, detail=str(exc)
        )

    archives = tuple(
        sorted(
            item.name
            for item in prefix.iterdir()
            if item.is_file() and item.suffix.lower() == ".zip"
        )
    )
    if declaration is None:
        if archives:
            return AcquisitionState(
                presence=ArtifactPresence.UNDECLARED,
                declaration=None,
                detail=(
                    f"{len(archives)} archive(s) are in the store and nothing "
                    "describes them; an archive nobody recorded the provenance of "
                    "cannot be pinned to a vendor"
                ),
            )
        return AcquisitionState(
            presence=ArtifactPresence.ABSENT,
            declaration=None,
            detail="no trial archive and no declaration are in the store",
        )

    target = prefix / declaration.filename
    if not target.is_file():
        return AcquisitionState(
            presence=ArtifactPresence.MISMATCHED,
            declaration=None,
            detail=(
                f"the declaration names {declaration.filename} and no such file is "
                "in the store"
            ),
        )
    actual_size = target.stat().st_size
    if actual_size != declaration.size_bytes:
        return AcquisitionState(
            presence=ArtifactPresence.MISMATCHED,
            declaration=None,
            detail=(
                f"the declaration says {declaration.size_bytes} bytes and the file "
                f"is {actual_size}; a short file is a truncated download and not a "
                "different artifact"
            ),
        )
    actual_digest = _file_sha256(target)
    if actual_digest != declaration.sha256:
        return AcquisitionState(
            presence=ArtifactPresence.MISMATCHED,
            declaration=None,
            detail=(
                "the file in the store is the declared length and hashes to a "
                "different digest"
            ),
        )
    return AcquisitionState(
        presence=ArtifactPresence.VERIFIED,
        declaration=declaration,
        detail=f"{declaration.filename} verified by size and digest",
    )


# ------------------------------------------------------------ the runtime closure

#: How a delivered file name maps to the part it plays. Ordered: the first
#: matching rule wins, so the algorithm module is classified before the general
#: "anything else Neurotechnology ships" rule can claim it.
_ROLE_RULES: tuple[tuple[str, ComponentRole], ...] = (
    ("fingercell", ComponentRole.FINGERCELL_ALGORITHM),
    ("ncore", ComponentRole.COMMON_RUNTIME),
    ("nmedia", ComponentRole.IMAGE_RUNTIME),
    ("nmediaproc", ComponentRole.IMAGE_RUNTIME),
    ("nlicensing", ComponentRole.LICENSING),
    ("neurotec-core", ComponentRole.LANGUAGE_BINDING),
    ("jna", ComponentRole.LANGUAGE_BINDING),
)


def _role_for(name: str) -> ComponentRole:
    lowered = name.lower()
    for fragment, role in _ROLE_RULES:
        if fragment in lowered:
            return role
    return ComponentRole.SYSTEM_DEPENDENCY


def runtime_closure(
    members: tuple[str, ...], *, repository_root: Path | None = None
) -> tuple[RuntimeComponent, ...]:
    """Describe each named archive member as a runtime component.

    Args:
        members: archive-relative paths beneath the unpacked root.

    Raises:
        FingerCellAcquisitionError: a named member is not in the unpacked tree,
            which means the closure describes something that is not there.
    """
    root = unpacked_root(repository_root=repository_root)
    components: list[RuntimeComponent] = []
    for member in members:
        path = root / PurePosixPath(member)
        if not path.is_file():
            raise FingerCellAcquisitionError(
                f"the runtime closure names {member} and the unpacked archive does "
                "not contain it"
            )
        size, digest = hash_component(path)
        components.append(
            RuntimeComponent(
                relative_path=(
                    PurePosixPath(UNPACKED_DIRECTORY_NAME) / PurePosixPath(member)
                ).as_posix(),
                component_role=_role_for(PurePosixPath(member).name),
                size_bytes=size,
                sha256=digest,
                version_or_revision=None,
                source_archive_member=member,
            )
        )
    return tuple(components)


#: The bridge's own sources, inside this repository. Hashed together so that an
#: edit to either the code or the way it is built moves the fingerprint.
BRIDGE_SOURCE_FILES: tuple[str, ...] = (
    "integrations/fingercell-cpp/src/fpbench_fingercell_bridge.cpp",
    "integrations/fingercell-cpp/Makefile",
)


def bridge_source_fingerprint(*, repository_root: Path | None = None) -> str:
    """One digest over the bridge's source and its build definition.

    Bound into every qualification record, because a bridge is edited far more
    often than an archive is re-downloaded: without this, twenty comparisons that
    qualified one build would go on answering for every later one.
    """
    root = Path(repository_root) if repository_root is not None else Path.cwd()
    entries: dict[str, str] = {}
    for name in BRIDGE_SOURCE_FILES:
        path = root / PurePosixPath(name)
        if not path.is_file():
            raise FingerCellAcquisitionError(
                f"the bridge source {name} is missing, so no run can be bound to it"
            )
        entries[name] = _file_sha256(path)
    return stable_hash(
        {"schema": "stage_13a_bridge_source_v1", "files": entries}, length=64
    )


def bridge_binary_sha256(path: Path) -> str:
    """The digest of the built bridge.

    Separate from the source fingerprint on purpose: identical source rebuilt
    against different headers or libraries produces a different artifact, and it
    is the artifact that produced the scores.
    """
    target = Path(path)
    if not target.is_file():
        raise FingerCellAcquisitionError(
            f"no built bridge at {target.name}; compile it before binding a run to it"
        )
    return _file_sha256(target)


def runtime_closure_fingerprint(components: tuple[RuntimeComponent, ...]) -> str:
    """One digest over the whole closure, so a record can be bound to it."""
    return stable_hash(
        {
            "schema": "stage_13a_runtime_closure_v1",
            "components": [dict(item.row) for item in components],
        },
        length=64,
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


#: Shapes a Neurotechnology delivery takes. The tokens are assembled from parts
#: so that this module's own source does not match the rules it defines.
_VENDOR_NAME_FRAGMENTS = (
    "finger" + "cell",
    "neuro" + "technology",
    "neuro" + "tec",
    "veri" + "finger",
    "mega" + "matcher",
)
_VENDOR_SUFFIXES = (".lic", ".license", ".licence")
_LICENSE_NAME_FRAGMENTS = (
    "licensemanager",
    "license_manager",
    "hardwareid",
    "trialflag",
)

#: Text files that carry no extension at all. A build definition is source, and
#: a bridge's Makefile necessarily sits in a directory named after the product it
#: builds against.
_TEXT_FILENAMES = frozenset(
    {"makefile", "dockerfile", "license", "notice", "readme", ".gitignore"}
)

#: Extensions that would carry a runtime rather than a description of one.
_BINARY_SUFFIXES = (".dll", ".so", ".dylib", ".lib", ".a", ".jar", ".exe", ".zip")

#: Where a vendor's name may legitimately appear. This stage's own source, tests,
#: docs and evidence say it on every page — and so does the *bridge source* the
#: benchmark writes against a vendor API, which is this project's own code and is
#: tracked on purpose. The rule is about bytes: a compiled module or a licence
#: file may never be tracked, and a source file that names a product may.
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
    ".gradle",
    ".properties",
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
        raise FingerCellAcquisitionError(
            f"cannot list tracked files for the Stage 13A byte guard: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise FingerCellAcquisitionError(
            "cannot list tracked files for the Stage 13A byte guard"
            + (f": {detail}" if detail else "")
        )
    return tuple(
        item for item in completed.stdout.decode("utf-8", "replace").split("\0") if item
    )


def audit_tracked_bytes_against_fingercell_artifacts(
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
                        f"a tracked {suffix} file is a licence, and a licence never "
                        "enters a public repository"
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
                    detail=(
                        "a tracked non-text file is named after a vendor component"
                    ),
                )
            )
    return TrackedByteAudit(
        tracked_file_count=len(tracked), findings=tuple(findings)
    )


def require_no_fingercell_bytes_in_git(repository_root: Path) -> TrackedByteAudit:
    """The raising form.

    Raises:
        FingerCellAcquisitionError: a vendor artifact or licence file is tracked.
    """
    audit = audit_tracked_bytes_against_fingercell_artifacts(repository_root)
    if audit.findings:
        listed = ", ".join(f"{item.path} ({item.rule})" for item in audit.findings)
        raise FingerCellAcquisitionError(
            f"vendor bytes or licence material are tracked in Git: {listed}"
        )
    return audit


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage13a_acquisition``.

    ``state`` reports where the archive stands. ``declare`` records an archive
    already present in the store, computing its size and digest rather than
    accepting them. ``guard`` runs the tracked-byte audit.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Stage 13A artifact acquisition")
    parser.add_argument("action", choices=("state", "declare", "guard"), nargs="?", default="state")
    parser.add_argument("--filename", default=None)
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "guard":
        audit = require_no_fingercell_bytes_in_git(root)
        print(
            f"{audit.tracked_file_count} tracked files scanned against the vendor "
            f"artifact and licence rules, {len(audit.findings)} findings"
        )
        return 0

    if arguments.action == "declare":
        if not arguments.filename:
            parser.error("declare needs --filename")
        prefix = artifact_store_prefix_path(repository_root=root)
        target = prefix / arguments.filename
        if not target.is_file():
            raise SystemExit(f"{arguments.filename} is not in the store")
        size, digest = hash_component(target)
        declaration = ArchiveDeclaration(
            official_locator_category=LocatorCategory.VENDOR_DIRECT_DOWNLOAD,
            official_locator=(
                "https://download.neurotechnology.com/" + arguments.filename
            ),
            filename=arguments.filename,
            size_bytes=size,
            sha256=digest,
            downloaded_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            product=PRODUCT_FAMILY,
            product_version=DECLARED_PRODUCT_VERSION,
            vendor_product_revision=VENDOR_PRODUCT_REVISION_INDICATION,
            vendor_revision_hash=VENDOR_REVISION_HASH_INDICATION,
            documentation_obtained=True,
        )
        written = write_archive_declaration(declaration, repository_root=root)
        print(f"declared {arguments.filename} ({size} bytes, {digest})")
        print(written.name)
        return 0

    state = acquisition_state(repository_root=root)
    print(f"presence   {state.presence.value}")
    print(f"obtained   {state.obtained}")
    print(f"detail     {state.detail}")
    if state.declaration is not None:
        for key, value in state.declaration.identity_row.items():
            print(f"  {key:<28s} {value}")
        print(
            "  revision agrees with release notes "
            f"{state.declaration.revision_agrees_with_release_notes}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
