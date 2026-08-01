"""Where an adapter is allowed to put its scratch files, and nowhere else.

A two-stage adapter has to write things down: a converted input, a template per
side, whatever the matcher prints. The contract already says where — under
``context.working_directory`` and ``context.artifact_directory`` — and until now
"where" was enforced by each adapter remembering. That is the kind of rule that
holds until the day somebody writes ``Path(name)`` where ``name`` came from a
config file.

So the rule is enforced here instead, once:

* a name is relative, or it is refused;
* a name containing ``..`` is refused before it is joined to anything;
* the joined path is resolved and must still be inside the directory it was
  built from — which is what catches a symlinked subdirectory pointing out of
  the job;
* a target that is already a symlink is refused rather than followed;
* an artefact is copied, never hardlinked, so that a later rewrite of the source
  cannot reach through into published evidence;
* an artefact never silently overwrites another artefact.

**Names carry no meaning.** ``left-template.xyt`` is a good name;
``subject_0001_finger_02_genuine.xyt`` is refused. The adapter has no way to know
any of those things — ``ComparisonContext`` deliberately carries no pair, no
subject, no finger and no stage (docs/adr/0010) — so a name that contained them
would mean somebody had smuggled them in. The check is cheap, and it fires on
the smuggling rather than on the consequences.

This helper is deliberately not given a ``ComparisonPair``. It could not use one,
and having one available is precisely the state of affairs the contract is
arranged to prevent.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from fpbench.adapters.errors import AdapterContractViolation
from fpbench.core.execution_models import ArtifactReference, ComparisonContext

__all__ = ["AdapterJobWorkspace", "WorkspaceContainmentError"]

_READ_CHUNK = 1 << 20

#: One path segment: lowercase-ish, no spaces, no surprises. Deliberately strict
#: — an adapter picks these names in its own source, so there is no reason to
#: accommodate anything exotic.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: Substrings that would mean a name knows something the adapter is not allowed
#: to know. Matched case-insensitively against the whole relative name.
_FORBIDDEN_NAME_TOKENS: tuple[str, ...] = (
    "subject",
    "finger",
    "frgp",
    "pair",
    "genuine",
    "impostor",
    "mated",
    "sd300",
)

#: SD300 subject identifiers are eight digits. A run of that many digits in an
#: intermediate file name is not a coincidence worth allowing.
_LONG_DIGIT_RUN = re.compile(r"\d{8,}")

#: The runner's layout: ``<workspace>/artifacts/<run_id>/<job_id>``. Recognised
#: so a published artefact can carry a workspace-relative path, which is what
#: makes it findable on a machine other than the one that wrote it.
_ARTIFACTS_DIRECTORY_NAME = "artifacts"


class WorkspaceContainmentError(AdapterContractViolation):
    """An adapter asked for a path outside the directories it was given."""


@dataclass(frozen=True, slots=True)
class AdapterJobWorkspace:
    """The two directories one comparison may write in."""

    working_directory: Path
    artifact_directory: Path

    #: The workspace root, when the artefact directory follows the runner's
    #: layout. ``None`` when it does not — a bare adapter test, say — in which
    #: case published paths are relative to the artefact directory instead.
    workspace_root: Path | None = None

    def __post_init__(self) -> None:
        for name in ("working_directory", "artifact_directory"):
            path = Path(getattr(self, name))
            if not path.is_absolute():
                raise WorkspaceContainmentError(
                    f"{name} must be absolute, got {path}"
                )
            object.__setattr__(self, name, path.resolve())
        if self.workspace_root is not None:
            object.__setattr__(
                self, "workspace_root", Path(self.workspace_root).resolve()
            )

    @classmethod
    def from_context(cls, context: ComparisonContext) -> "AdapterJobWorkspace":
        """The workspace implied by one :class:`ComparisonContext`."""
        artifacts = Path(context.artifact_directory).resolve()
        return cls(
            working_directory=Path(context.working_directory).resolve(),
            artifact_directory=artifacts,
            workspace_root=_workspace_root_of(artifacts, context),
        )

    # -------------------------------------------------------------- paths

    def work_path(self, relative_name: str) -> Path:
        """A scratch path under the working directory. Parents are created.

        Nothing is written and nothing is checked for existence: the normal flow
        is to name a file, hand the name to a subprocess, and read it back.
        """
        return self._resolve(self.working_directory, relative_name)

    def artifact_path(self, relative_name: str) -> Path:
        """A path under the artefact directory. Parents are created."""
        return self._resolve(self.artifact_directory, relative_name)

    # ---------------------------------------------------------- artefacts

    def publish_artifact(
        self,
        *,
        artifact_id: str,
        kind: str,
        source: Path,
        relative_name: str | None = None,
        media_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactReference:
        """Turn a file this job produced into a verifiable reference.

        The file must already be inside the working or the artefact directory —
        an adapter cannot publish something it found elsewhere on the machine.
        A file in the working directory is copied (never hardlinked) into the
        artefact directory first, because ``work/`` is disposable by design.

        Raises:
            WorkspaceContainmentError: the source is outside the job, the target
                would be, or an artefact is already published under that name.
        """
        source_raw = Path(source)
        if not source_raw.is_absolute():
            source_raw = self.working_directory / source_raw
        source_raw = Path(os.path.abspath(source_raw))
        source_base: Path | None = None
        for base in (self.artifact_directory, self.working_directory):
            if source_raw.is_relative_to(base):
                source_base = base
                break
        if source_base is None:
            raise WorkspaceContainmentError(
                f"artefact source {source_raw.name!r} is outside this job's "
                "directories"
            )
        _reject_symlink_components(source_base, source_raw)
        try:
            source = source_raw.resolve(strict=True)
            source_stat = source.lstat()
        except (FileNotFoundError, OSError):
            raise WorkspaceContainmentError(
                f"artefact source {source_raw.name!r} is not a regular file"
            )
        if not stat.S_ISREG(source_stat.st_mode):
            raise WorkspaceContainmentError(
                f"artefact source {source.name!r} is not a regular file"
            )
        if source_stat.st_nlink != 1:
            raise WorkspaceContainmentError(
                f"artefact source {source.name!r} has multiple hard links; "
                "published evidence must have exclusive ownership"
            )
        inside_artifacts = source_base == self.artifact_directory

        target = (
            source
            if inside_artifacts and relative_name is None
            else self.artifact_path(relative_name or source.name)
        )
        if target != source:
            if target.exists() or target.is_symlink():
                raise WorkspaceContainmentError(
                    f"an artefact is already published as {target.name!r}; "
                    "publishing must not overwrite"
                )
            # The exclusive create produces a fresh inode owned by this job.
            # It also makes an appearance between the containment check and the
            # write a conflict instead of an overwrite.
            try:
                with source.open("rb") as source_stream, target.open("xb") as target_stream:
                    shutil.copyfileobj(source_stream, target_stream, _READ_CHUNK)
            except FileExistsError as exc:
                raise WorkspaceContainmentError(
                    f"an artefact is already published as {target.name!r}; "
                    "publishing must not overwrite"
                ) from exc

        _require_exclusive_regular_file(target, label="published artefact")

        digest, size = _digest_file(target)
        return ArtifactReference(
            artifact_id=artifact_id,
            kind=kind,
            relative_path=self._reference_path(target),
            sha256=digest,
            size_bytes=size,
            media_type=media_type,
            metadata=dict(metadata or {}),
        )

    # ---------------------------------------------------------- internals

    def _resolve(self, base: Path, relative_name: str) -> Path:
        _require_safe_name(relative_name)
        raw_candidate = base / relative_name
        _reject_symlink_components(base, raw_candidate)
        candidate = raw_candidate.resolve(strict=False)
        if not candidate.is_relative_to(base):
            raise WorkspaceContainmentError(
                f"{relative_name!r} resolves outside the directory it was built "
                "from; a job may not write past its own boundary"
            )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(base, raw_candidate)
        return candidate

    def _reference_path(self, target: Path) -> str:
        """Where a stored result should say the artefact is.

        Workspace-relative when the layout allows it, so the reference survives
        being read on another machine; artefact-relative otherwise. Never
        absolute, in either case.
        """
        base = self.workspace_root or self.artifact_directory
        return target.relative_to(base).as_posix()


def _workspace_root_of(artifacts: Path, context: ComparisonContext) -> Path | None:
    """``<root>/artifacts/<run_id>/<job_id>`` -> ``<root>``, or ``None``.

    Verified rather than assumed: the two directory names must actually be this
    run's and this job's, and the grandparent must actually be ``artifacts``.
    """
    if artifacts.name != context.job_id:
        return None
    parent = artifacts.parent
    if parent.name != context.run_id:
        return None
    if parent.parent.name != _ARTIFACTS_DIRECTORY_NAME:
        return None
    return parent.parent.parent


def _require_safe_name(relative_name: str) -> None:
    if not isinstance(relative_name, str) or not relative_name.strip():
        raise WorkspaceContainmentError("a file name must be a non-empty string")
    name = relative_name.strip()

    if PurePosixPath(name).is_absolute() or PureWindowsPath(name).is_absolute():
        raise WorkspaceContainmentError(
            f"{name!r} is absolute; a job names files relative to its own directory"
        )
    # Split the text, not the ``PurePosixPath``: pathlib normalises ``./x`` to
    # ``x``, so a check against ``.parts`` would silently accept a name that had
    # a segment in it the caller did not intend to write.
    parts = [segment for segment in name.replace("\\", "/").split("/")]
    if any(part in ("..", ".", "") for part in parts):
        raise WorkspaceContainmentError(
            f"{name!r} must not contain '..', '.' or an empty path segment"
        )
    for part in parts:
        if not _SEGMENT.match(part):
            raise WorkspaceContainmentError(
                f"{name!r} has an unusable path segment {part!r}; use plain "
                "ASCII names such as 'left-template.xyt'"
            )

    lowered = name.lower()
    present = [token for token in _FORBIDDEN_NAME_TOKENS if token in lowered]
    if present:
        raise WorkspaceContainmentError(
            f"{name!r} names something an adapter cannot know ({present}); "
            "intermediate files carry no research meaning (docs/adr/0010)"
        )
    if _LONG_DIGIT_RUN.search(name):
        raise WorkspaceContainmentError(
            f"{name!r} embeds a long digit run that looks like a dataset "
            "identifier; intermediate files carry no research meaning"
        )


def _reject_symlink_components(base: Path, candidate: Path) -> None:
    """Inspect every existing component with ``lstat`` before resolving it."""
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise WorkspaceContainmentError(
            f"{candidate.name!r} is outside this job's directory"
        ) from exc
    current = base
    for component in relative.parts:
        current = current / component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise WorkspaceContainmentError(
                f"cannot safely inspect path component {component!r}"
            ) from exc
        if stat.S_ISLNK(mode):
            raise WorkspaceContainmentError(
                f"path component {component!r} is a symlink and may redirect "
                "outside the job; a job's files must own their bytes"
            )


def _require_exclusive_regular_file(path: Path, *, label: str) -> None:
    try:
        info = path.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise WorkspaceContainmentError(f"{label} is not a regular file") from exc
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceContainmentError(f"{label} is not a regular file")
    if info.st_nlink != 1:
        raise WorkspaceContainmentError(
            f"{label} has multiple hard links; evidence must have exclusive ownership"
        )


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
