"""What is on this machine, checked against what Stage 11A froze.

Two jobs, and they pull in opposite directions on purpose.

**Verification.** The frozen record in
:mod:`fpbench.experiments.stage11a_verifinger_observations` says which bytes the
official artifacts are. This module looks for them in the local store and checks
size first and digest second, so a half-finished transfer is reported as
truncated rather than as "the wrong file". An artifact that is absent is absent —
that is the ordinary state of every CI runner and it is reported, not raised.

**Refusal.** The same digests are what the repository is audited against. A
vendor byte inside a public checkout is the one failure this project cannot take
back, so the guard checks tracked files by exact digest *and* by the shapes a
Neurotechnology artifact takes — the archive's own name, a ``.ndf`` data file, a
``.lic`` licence, an ``N*.dll`` native library — because a file this stage never
hashed is exactly the file that would slip through a digest-only rule
(docs/adr/0083).

Nothing here downloads anything. Acquisition is a person running ``make
stage11a-acquire``, or the equivalent by hand; this module is the part that says
whether what arrived is what was expected.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Mapping

from fpbench.core.verifinger_preflight_errors import (
    Stage11AFinalizationError,
    VeriFingerAcquisitionError,
)
from fpbench.experiments.stage11a_verifinger_identity import (
    ARTIFACT_STORE_PREFIX,
    AcquisitionStatus,
    PossessionStatus,
)
from fpbench.experiments.stage11a_verifinger_observations import (
    ACQUIRED_ARTIFACTS,
    CITED_ARCHIVE_MEMBERS,
    FINGER_DATA_FILES,
    JAVA_BINDING_JARS,
    WINDOWS_X64_NATIVE_LIBRARIES,
    AcquiredArtifact,
)
from fpbench.third_party import resolve_third_party_root

__all__ = [
    "ArtifactPresence",
    "LocalArtifactState",
    "AcquisitionState",
    "QualificationRunState",
    "QUALIFICATION_RUN_RECORD_NAME",
    "qualification_run_state",
    "TrackedByteFinding",
    "TrackedByteAudit",
    "artifact_store_prefix_path",
    "inspect_local_artifact",
    "acquisition_state",
    "verifinger_artifact_digests",
    "audit_tracked_bytes_against_verifinger_artifacts",
    "require_no_verifinger_bytes_in_git",
]


class ArtifactPresence(str, Enum):
    """What was found where a frozen artifact should be.

    ``SIZE_MISMATCH`` and ``DIGEST_MISMATCH`` are separate because they mean
    different things: the first is almost always an interrupted transfer, and the
    second is a different file wearing the right name.
    """

    VERIFIED = "VERIFIED"
    ABSENT = "ABSENT"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    UNREADABLE = "UNREADABLE"

    @property
    def is_the_frozen_artifact(self) -> bool:
        return self is ArtifactPresence.VERIFIED


@dataclass(frozen=True, slots=True)
class LocalArtifactState:
    """One frozen artifact, and what is on this machine in its place.

    ``observed_size_bytes`` and ``observed_sha256`` are published only when they
    disagree with the frozen record. Republishing a digest that matched would
    invite a reader to compare two identical strings and conclude something from
    it; the status is the conclusion.
    """

    artifact_id: str
    filename: str
    expected_size_bytes: int
    expected_sha256: str
    presence: ArtifactPresence
    observed_size_bytes: int | None = None
    observed_sha256: str | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.presence.is_the_frozen_artifact and (
            self.observed_sha256 is not None or self.observed_size_bytes is not None
        ):
            raise VeriFingerAcquisitionError(
                f"{self.artifact_id}: a verified artifact publishes no second "
                "copy of the digest it matched"
            )


def artifact_store_prefix_path(*, repository_root: Path | None = None) -> Path:
    """Where this stage's artifacts live, on whatever machine is running.

    Raises:
        VeriFingerAcquisitionError: no store is resolvable, or the resolved store
            sits inside the working tree — which would put vendor bytes one
            ``git add -A`` away from a public repository (docs/adr/0083).
    """
    try:
        root = resolve_third_party_root(repository_root=repository_root)
    except Exception as exc:  # pragma: no cover - an unusable store
        raise VeriFingerAcquisitionError(
            f"no local artifact store is resolvable here: {exc}"
        ) from exc
    return Path(root) / ARTIFACT_STORE_PREFIX


def inspect_local_artifact(
    artifact: AcquiredArtifact, *, repository_root: Path | None = None
) -> LocalArtifactState:
    """Check one frozen artifact against the file in the store.

    Size before digest, deliberately: hashing four and a half gigabytes to
    discover that only three of them arrived is a slow way to learn something the
    file length already said.
    """
    try:
        path = artifact_store_prefix_path(repository_root=repository_root)
    except VeriFingerAcquisitionError as exc:
        return LocalArtifactState(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            expected_size_bytes=artifact.size_bytes,
            expected_sha256=artifact.sha256,
            presence=ArtifactPresence.ABSENT,
            detail=str(exc),
        )

    target = path / artifact.filename
    if not target.is_file():
        return LocalArtifactState(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            expected_size_bytes=artifact.size_bytes,
            expected_sha256=artifact.sha256,
            presence=ArtifactPresence.ABSENT,
            detail=(
                "not in the local artifact store under this stage's prefix; "
                "acquire it from the official locator recorded in the "
                "acquisition manifest"
            ),
        )
    try:
        size = target.stat().st_size
    except OSError as exc:  # pragma: no cover - a file that cannot be stat'ed
        return LocalArtifactState(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            expected_size_bytes=artifact.size_bytes,
            expected_sha256=artifact.sha256,
            presence=ArtifactPresence.UNREADABLE,
            detail=str(exc),
        )
    if size != artifact.size_bytes:
        return LocalArtifactState(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            expected_size_bytes=artifact.size_bytes,
            expected_sha256=artifact.sha256,
            presence=ArtifactPresence.SIZE_MISMATCH,
            observed_size_bytes=size,
            detail=(
                "the file is the wrong length, which is what an interrupted "
                "transfer looks like; fetch it again rather than hashing it"
            ),
        )
    digest = hashlib.sha256()
    try:
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:  # pragma: no cover - a file that cannot be read
        return LocalArtifactState(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            expected_size_bytes=artifact.size_bytes,
            expected_sha256=artifact.sha256,
            presence=ArtifactPresence.UNREADABLE,
            detail=str(exc),
        )
    found = digest.hexdigest()
    if found != artifact.sha256:
        return LocalArtifactState(
            artifact_id=artifact.artifact_id,
            filename=artifact.filename,
            expected_size_bytes=artifact.size_bytes,
            expected_sha256=artifact.sha256,
            presence=ArtifactPresence.DIGEST_MISMATCH,
            observed_sha256=found,
            detail=(
                "the right length and the wrong bytes: this is a different file "
                "under the same name, and no conclusion in this stage holds over "
                "it"
            ),
        )
    return LocalArtifactState(
        artifact_id=artifact.artifact_id,
        filename=artifact.filename,
        expected_size_bytes=artifact.size_bytes,
        expected_sha256=artifact.sha256,
        presence=ArtifactPresence.VERIFIED,
    )


@dataclass(frozen=True, slots=True)
class AcquisitionState:
    """Every frozen artifact, and whether this machine holds it.

    ``inspection_was_performed`` is separate from ``obtained``. The gate's
    conclusions about what is *inside* the archive were reached by opening it,
    and they are only worth anything if the archive whose digest they were reached
    over is the archive the record names.
    """

    states: tuple[LocalArtifactState, ...]
    status: AcquisitionStatus
    possession: PossessionStatus
    inspection_was_performed: bool

    @property
    def obtained(self) -> bool:
        return self.status.opens_inspection

    @property
    def unverified(self) -> tuple[LocalArtifactState, ...]:
        return tuple(
            item for item in self.states if not item.presence.is_the_frozen_artifact
        )

    def state(self, artifact_id: str) -> LocalArtifactState:
        for item in self.states:
            if item.artifact_id == artifact_id:
                return item
        raise KeyError(artifact_id)


def acquisition_state(*, repository_root: Path | None = None) -> AcquisitionState:
    """Look for every frozen artifact, without requiring one to be here.

    Absence is a reportable state rather than an error: the public CI has none of
    these files by design, and a stage that raised on a runner would be a stage
    nobody could check.
    """
    states = tuple(
        inspect_local_artifact(artifact, repository_root=repository_root)
        for artifact in ACQUIRED_ARTIFACTS
    )
    verified = all(item.presence.is_the_frozen_artifact for item in states)
    if verified:
        return AcquisitionState(
            states=states,
            status=AcquisitionStatus.OBTAINED,
            possession=PossessionStatus.OBTAINED,
            inspection_was_performed=True,
        )
    truncated = any(
        item.presence is ArtifactPresence.SIZE_MISMATCH for item in states
    )
    return AcquisitionState(
        states=states,
        status=(
            AcquisitionStatus.TRANSFER_INCOMPLETE
            if truncated
            else AcquisitionStatus.NOT_ATTEMPTED_HERE
        ),
        possession=PossessionStatus.NOT_OBTAINED,
        inspection_was_performed=False,
    )


# -------------------------------------------------- what only running can answer

#: Where a local qualification harness would leave its record. Beside the
#: artifacts and outside the repository, because it would carry timings and
#: engine defaults read from a licensed runtime, and because a stage that read
#: its own conclusions out of the working tree could be made to conclude anything.
QUALIFICATION_RUN_RECORD_NAME = "qualification-run.json"


@dataclass(frozen=True, slots=True)
class QualificationRunState:
    """Whether a licensed engine was ever run on this machine, and what it left.

    Seven of the seventeen gates cannot be answered by reading files. The
    delivered runtime defaults of every setting the manual leaves undocumented,
    the two orderings of a pair, SELF as two independent extractions, determinism
    across a restart, what each failure class actually returns, and the latency
    and memory of the route — every one of those is a fact about a running
    licensed engine, and no amount of documentation substitutes for it.

    This class is how the preflight asks. It never runs anything: activating a
    licence is a person's decision about their own machine, taken once, with a
    30-day clock attached (spec section 32).
    """

    performed: bool
    record_present: bool
    reason: str

    @property
    def answers_execution_gates(self) -> bool:
        return self.performed and self.record_present


def qualification_run_state(
    *, repository_root: Path | None = None
) -> QualificationRunState:
    """Look for a local qualification record, without requiring one.

    Absent is the ordinary state and the published one: no licence has been
    activated from this project, so nothing has run.
    """
    try:
        prefix = artifact_store_prefix_path(repository_root=repository_root)
    except VeriFingerAcquisitionError:
        prefix = None
    present = bool(prefix is not None and (prefix / QUALIFICATION_RUN_RECORD_NAME).is_file())
    if present:
        return QualificationRunState(
            performed=True,
            record_present=True,
            reason=(
                "a local qualification record is present in the artifact store; "
                "the gates that need a running engine read their facts from it"
            ),
        )
    return QualificationRunState(
        performed=False,
        record_present=False,
        reason=(
            "no licence has been activated from this project and nothing has "
            "been executed, so no qualification record exists. The SDK's own "
            "ReadMe defines installation as extracting the archive and then "
            "activating the licensing software, and the second step starts a "
            "30-day trial bound to one machine — a decision that belongs to the "
            "maintainer rather than to a preflight (spec section 32)"
        ),
    )


# ------------------------------------------------------------- the byte guard


@dataclass(frozen=True, slots=True)
class TrackedByteFinding:
    """One tracked file that is, or looks like, a Neurotechnology artifact."""

    path: str
    component_role: str
    basis: str


@dataclass(frozen=True, slots=True)
class TrackedByteAudit:
    """Every tracked file, checked against what this stage knows about the vendor."""

    tracked_file_count: int
    known_digest_count: int
    findings: tuple[TrackedByteFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


#: File shapes that are vendor artifacts whatever their bytes turn out to be. The
#: digest list below covers what this stage actually hashed; these cover the
#: 8,600-odd members it did not cite, which is where a stray file would come
#: from.
#:
#: **These match vendor artifacts, not writing about them.** An earlier version of
#: this table matched the bare word ``verifinger`` and refused the repository over
#: this stage's own source files, its ADRs and its workflow — the same shape of
#: mistake as a stage gate auditing itself. A guard that cannot tell a native
#: library from a document about one is a guard nobody can leave switched on.
_VENDOR_ARTIFACT_SUFFIXES = (".ndf", ".lic", ".id3nn", ".chm")

#: Distribution archives and the extracted tree they produce, by the exact naming
#: Neurotechnology uses.
#: ``neurotec-`` covers the Java bindings, which are hyphenated where the
#: distribution archives are not. No file this project writes begins with it, and
#: the test suite asserts that in both directions.
_VENDOR_ARTIFACT_NAME_PREFIXES = (
    "neurotec_biometric_",
    "neurotec_ai_",
    "neurotec-",
    "megamatcher_",
)

#: The vendor's native libraries, matched on the stem so that the Windows,
#: Linux and macOS builds are all covered by one entry each.
_VENDOR_LIBRARY_STEMS = (
    "nbiometrics",
    "nbiometricclient",
    "ncore",
    "nmedia",
    "nlicensing",
    "ntemplates",
    "nimages",
)
_VENDOR_LIBRARY_SUFFIXES = (".dll", ".so", ".dylib", ".jar", ".lib", ".a")

#: Exact file names that are vendor material wherever they appear.
_VENDOR_ARTIFACT_EXACT_NAMES = (
    "neurotechnology.id",
    "activationwizard.exe",
    "trialflag.txt",
    "sdk license.html",
)


def _looks_like_a_vendor_artifact(relative: str) -> bool:
    """Whether one tracked path is a Neurotechnology artifact by its shape.

    Checked against the file name and against the extracted archive's own root
    directory, so an unpacked SDK anywhere under the tree is caught even where
    none of its individual members was ever hashed by this stage.
    """
    lowered = PurePosixPath(relative).name.lower()
    if lowered.endswith(_VENDOR_ARTIFACT_SUFFIXES):
        return True
    if lowered in _VENDOR_ARTIFACT_EXACT_NAMES:
        return True
    if lowered.startswith(_VENDOR_ARTIFACT_NAME_PREFIXES):
        return True
    stem, _, suffix = lowered.rpartition(".")
    if stem in _VENDOR_LIBRARY_STEMS and f".{suffix}" in _VENDOR_LIBRARY_SUFFIXES:
        return True
    parts = [part.lower() for part in PurePosixPath(relative).parts[:-1]]
    return any(part.startswith(_VENDOR_ARTIFACT_NAME_PREFIXES) for part in parts)


def verifinger_artifact_digests() -> Mapping[str, tuple[str, str]]:
    """Every exact digest Stage 11A knows, keyed by digest.

    The two acquired artifacts, the archive members this stage quotes, the
    fingerprint data files, the native libraries and the Java jars. A tracked
    file matching one would mean upstream bytes had entered a public repository
    that promises to hold none, even where the bytes are freely downloadable
    elsewhere (docs/adr/0083).
    """
    known: dict[str, tuple[str, str]] = {}
    for artifact in ACQUIRED_ARTIFACTS:
        known[artifact.sha256] = (
            artifact.artifact_id,
            f"an acquired vendor artifact: {artifact.filename}",
        )
    for member in (
        *CITED_ARCHIVE_MEMBERS,
        *FINGER_DATA_FILES,
        *JAVA_BINDING_JARS,
    ):
        known[member.sha256] = (
            member.relative_path,
            f"a member of the pinned vendor archive: {member.relative_path}",
        )
    for library in WINDOWS_X64_NATIVE_LIBRARIES:
        known[library.sha256] = (
            library.relative_path,
            f"a pinned vendor native library: {library.relative_path}",
        )
    return known


def _tracked_files(repository_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "ls-files", "-z"),
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage11AFinalizationError(
            f"cannot list tracked files for the Stage 11A byte guard: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise Stage11AFinalizationError(
            "cannot list tracked files for the Stage 11A byte guard: "
            + completed.stderr.decode("utf-8", "replace").strip()
        )
    return tuple(
        name
        for name in completed.stdout.decode("utf-8", "replace").split("\0")
        if name
    )


def audit_tracked_bytes_against_verifinger_artifacts(
    repository_root: Path,
) -> TrackedByteAudit:
    """Hash every tracked file, and check every tracked name."""
    repository_root = Path(repository_root)
    known = verifinger_artifact_digests()
    findings: list[TrackedByteFinding] = []
    tracked = _tracked_files(repository_root)
    for relative in tracked:
        if _looks_like_a_vendor_artifact(relative):
            findings.append(
                TrackedByteFinding(
                    path=relative,
                    component_role=(
                        "a vendor archive, data file, licence or native library"
                    ),
                    basis="name",
                )
            )
            continue
        path = repository_root / PurePosixPath(relative)
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
        except OSError:  # pragma: no cover - a tracked file that cannot be read
            continue
        found = known.get(digest.hexdigest())
        if found is not None:
            findings.append(
                TrackedByteFinding(
                    path=relative, component_role=found[1], basis="digest"
                )
            )
    return TrackedByteAudit(
        tracked_file_count=len(tracked),
        known_digest_count=len(known),
        findings=tuple(sorted(findings, key=lambda item: item.path)),
    )


def require_no_verifinger_bytes_in_git(repository_root: Path) -> TrackedByteAudit:
    """The raising form, for a gate.

    Raises:
        Stage11AFinalizationError: a tracked file is a vendor artifact by name or
            byte-for-byte one this stage pinned.
    """
    audit = audit_tracked_bytes_against_verifinger_artifacts(repository_root)
    if not audit.clean:
        detail = "; ".join(
            f"{finding.path} is {finding.component_role} (by {finding.basis})"
            for finding in audit.findings
        )
        raise Stage11AFinalizationError(
            f"Neurotechnology material is tracked in this public repository: "
            f"{detail}"
        )
    return audit
