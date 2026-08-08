"""Where third-party bytes live, described without naming any machine.

The repository knows four things about an artifact: what role it plays, which
bytes it must be, how many of them there are, and which upstream thing they came
from. It does not know where they are. That is not a gap — it is what makes one
manifest work on the project owner's Windows checkout, in WSL, and on a runner
that will never have the file at all (docs/adr/0083).

The store's root is resolved at runtime, in this order:

1. ``FPBENCH_THIRD_PARTY_ROOT``, if it is set;
2. otherwise ``~/.cache/fpbench/third_party``.

and the resolver refuses a root inside the working tree, because a store there
is a store one ``git add -A`` away from publishing a checkpoint.

Nothing in this module downloads anything. Acquisition belongs to the integration
that needs the artifact — this is the part that says whether what arrived is what
was expected, and it does that by size first and digest second, so a truncated
download is named as truncated rather than as "the wrong file".
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from fpbench.core.third_party_errors import ThirdPartyArtifactError
from fpbench.core.third_party_models import (
    ArtifactStorageClass,
    LocalArtifactPlacement,
    ThirdPartyComponentKind,
    UpstreamIdentity,
)

__all__ = [
    "THIRD_PARTY_ROOT_ENV",
    "DEFAULT_STORE_RELATIVE",
    "ArtifactVerification",
    "default_third_party_root",
    "resolve_third_party_root",
    "resolve_placement_path",
    "build_placement",
    "file_sha256",
    "verify_placed_artifact",
    "require_store_is_outside",
]

#: The one environment variable. Named rather than discovered, so that "where
#: does this machine keep its artifacts?" has exactly one answer to grep for.
THIRD_PARTY_ROOT_ENV = "FPBENCH_THIRD_PARTY_ROOT"

#: The default, under the user's home rather than under the project. Every
#: integration gets its own directory beneath it — ``sourceafis/``, ``nbis/``,
#: ``flx/``, and whatever algorithm 4 turns out to be.
DEFAULT_STORE_RELATIVE = PurePosixPath(".cache") / "fpbench" / "third_party"


def default_third_party_root() -> Path:
    return Path.home() / Path(DEFAULT_STORE_RELATIVE)


def resolve_third_party_root(
    environ: Mapping[str, str] | None = None,
    *,
    repository_root: Path | None = None,
) -> Path:
    """The store root for this machine, checked before it is returned.

    Args:
        environ: the environment to read, defaulting to the process's own.
            Injectable so a test can exercise both branches without touching
            ``os.environ``.
        repository_root: when given, the resolved root must lie outside it.

    Raises:
        ThirdPartyArtifactError: the variable is set to something that is not an
            absolute path, or the root would sit inside the working tree.
    """
    source = os.environ if environ is None else environ
    raw = str(source.get(THIRD_PARTY_ROOT_ENV, "")).strip()
    if raw:
        root = Path(raw)
        if not root.is_absolute():
            raise ThirdPartyArtifactError(
                f"{THIRD_PARTY_ROOT_ENV}={raw!r} is not an absolute path. A "
                "relative store root would resolve differently depending on which "
                "directory a command was run from"
            )
    else:
        root = default_third_party_root()
    if repository_root is not None:
        require_store_is_outside(root, repository_root)
    return root


def require_store_is_outside(root: Path, repository_root: Path) -> None:
    """Refuse a store inside the working tree.

    The repository is public and this project's whole artifact policy is that
    upstream bytes never enter Git. A store under the checkout would leave that
    holding only for as long as nobody ran ``git add -A`` (docs/adr/0083).
    """
    try:
        resolved_root = Path(root).expanduser().resolve()
        resolved_repository = Path(repository_root).expanduser().resolve()
    except OSError as exc:  # pragma: no cover - unreadable path
        raise ThirdPartyArtifactError(
            f"cannot resolve the third-party store root: {exc}"
        ) from exc
    if resolved_root == resolved_repository or resolved_repository in resolved_root.parents:
        raise ThirdPartyArtifactError(
            f"the third-party artifact store {resolved_root} is inside the "
            f"repository at {resolved_repository}. Third-party bytes live outside "
            "the working tree (docs/adr/0083)"
        )


def build_placement(
    *,
    placement_id: str,
    component_role: str,
    component_kind: ThirdPartyComponentKind,
    relative_location: str,
    expected_sha256: str,
    expected_size_bytes: int,
    upstream_identity: UpstreamIdentity,
) -> LocalArtifactPlacement:
    """A placement, with its identity derived rather than supplied."""
    return LocalArtifactPlacement(
        placement_id=placement_id,
        component_role=component_role,
        component_kind=component_kind,
        relative_location=relative_location,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
        upstream_identity=upstream_identity,
        storage_class=ArtifactStorageClass.LOCAL_ARTIFACT_STORE,
    )


def resolve_placement_path(placement: LocalArtifactPlacement, *, root: Path) -> Path:
    """Turn a machine-independent placement into a path on this machine.

    The only function in the project that produces an absolute path for a
    third-party artifact, and it does so from a root the caller resolved and a
    relative location the manifest froze. The result is checked to be *under* the
    root, so a location that escaped it — through a symlink, or through a
    component the model's own validation did not anticipate — is a refusal rather
    than a read somewhere else on the disk.
    """
    if not isinstance(placement, LocalArtifactPlacement):
        raise ThirdPartyArtifactError("resolve_placement_path needs a placement")
    base = Path(root).expanduser()
    candidate = base.joinpath(*PurePosixPath(placement.relative_location).parts)
    try:
        resolved_base = base.resolve()
        resolved = candidate.resolve()
    except OSError as exc:  # pragma: no cover - unreadable path
        raise ThirdPartyArtifactError(
            f"{placement.placement_id}: cannot resolve the artifact path: {exc}"
        ) from exc
    if resolved != resolved_base and resolved_base not in resolved.parents:
        raise ThirdPartyArtifactError(
            f"{placement.placement_id}: {placement.relative_location!r} resolves "
            f"outside the artifact store at {resolved_base}"
        )
    return candidate


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise ThirdPartyArtifactError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactVerification:
    """What was found where a placement said to look.

    Returned rather than raised for the *absent* case, because "this machine does
    not have the artifact" is an ordinary state — it is true of every CI runner
    by design — while "this machine has different bytes under that name" is not.
    """

    placement_id: str
    present: bool
    size_matches: bool
    digest_matches: bool
    observed_size_bytes: int | None = None
    observed_sha256: str | None = None

    @property
    def verified(self) -> bool:
        return self.present and self.size_matches and self.digest_matches


def verify_placed_artifact(
    placement: LocalArtifactPlacement, *, root: Path
) -> ArtifactVerification:
    """Check the bytes on this machine against the bytes the manifest expects.

    Size first, then digest. Both are needed and the order is the useful part: a
    truncated or partial download is reported as the wrong *size*, which says
    what happened, rather than as the wrong digest, which says only that
    something is wrong.
    """
    path = resolve_placement_path(placement, root=root)
    if not path.is_file():
        return ArtifactVerification(
            placement_id=placement.placement_id,
            present=False,
            size_matches=False,
            digest_matches=False,
        )
    size = path.stat().st_size
    size_matches = size == placement.expected_size_bytes
    digest = file_sha256(path)
    return ArtifactVerification(
        placement_id=placement.placement_id,
        present=True,
        size_matches=size_matches,
        digest_matches=digest == placement.expected_sha256,
        observed_size_bytes=size,
        observed_sha256=digest,
    )
