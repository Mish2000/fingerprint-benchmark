"""Reading this repository's own identity out of git.

Everything here is a fact about the *harness*, not about the data or the
algorithm: which commit, whether anything is uncommitted, which interpreter,
which versions of the two libraries that touch persistence.

``git`` is invoked as a subprocess rather than through a library. There is no
git dependency in this project and adding one to read two values would be a
poor trade; ``argv`` is a list, ``shell`` is never used, and the repository path
is passed with ``-C`` rather than by changing anyone's working directory.

Dependency rule: ``provenance`` imports ``core`` and the standard library, and
nothing else from the project except the package version. It is imported by
``execution`` and by the experiment entry points.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from fpbench.core.errors import ResearchPreflightError
from fpbench.core.provenance_models import (
    PROVENANCE_KIND_GIT,
    PROVENANCE_KIND_UNAVAILABLE,
    TRACKED_DEPENDENCIES,
    SoftwareProvenance,
    software_provenance_fingerprint,
)

__all__ = [
    "capture_software_provenance",
    "software_provenance_fingerprint",
    "SoftwareProvenance",
    "dependency_versions",
    "GIT_TIMEOUT_SECONDS",
]

#: Generous. ``rev-parse`` is instant; ``status --porcelain`` on a cold cache
#: over a large tree is not, and a slow answer is better than a wrong one.
GIT_TIMEOUT_SECONDS = 120.0

_UNKNOWN_VERSION = "unknown"


class _GitUnavailable(Exception):
    """No usable git metadata here. Fatal for research, fine for development."""


def dependency_versions() -> dict[str, str]:
    """Installed versions of the packages that can change a stored result.

    A package that cannot be found reports ``unknown`` rather than being
    omitted: a fingerprint that silently loses a term when an environment is
    unusual would make two different environments look identical.
    """
    from importlib.metadata import PackageNotFoundError, version

    resolved: dict[str, str] = {}
    for name in TRACKED_DEPENDENCIES:
        try:
            resolved[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - unusual install
            resolved[name] = _UNKNOWN_VERSION
    return resolved


def capture_software_provenance(
    *,
    repository_root: Path,
    require_clean: bool,
) -> SoftwareProvenance:
    """Describe the fpbench build running in this process.

    Args:
        repository_root: The directory to ask git about. Never stored — only
            what git says about it is.
        require_clean: Research mode. The tree must be a git repository, it
            must report a commit, and it must have nothing uncommitted.
            Development mode reports whatever it finds, including no git at all.

    Raises:
        ResearchPreflightError: ``require_clean`` is set and either git cannot
            answer or the tree has uncommitted changes. There is no override:
            code that was never committed cannot be recovered from a receipt
            written later, so recording ``dirty = true`` and continuing would
            produce evidence that cannot be acted on (docs/adr/0017).
    """
    root = Path(repository_root)

    try:
        revision = _revision(root)
        clean = _is_clean(root)
        kind = PROVENANCE_KIND_GIT
    except _GitUnavailable as exc:
        if require_clean:
            raise ResearchPreflightError(
                f"a research run needs a committed source revision: {exc}"
            ) from None
        revision = PROVENANCE_KIND_UNAVAILABLE
        clean = False
        kind = PROVENANCE_KIND_UNAVAILABLE

    if require_clean and not clean:
        raise ResearchPreflightError(
            "the working tree has uncommitted changes; commit them before "
            "starting a research run. Recording the tree as dirty is not an "
            "option, because the uncommitted code could not be recovered from "
            "the resulting receipt (docs/adr/0017)"
        )

    from fpbench import __version__

    return SoftwareProvenance(
        provenance_kind=kind,
        source_revision=revision,
        source_tree_clean=clean,
        package_version=__version__,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        dependency_versions=dependency_versions(),
    )


# ----------------------------------------------------------------- internals


def _git(root: Path, *arguments: str) -> str:
    if not Path(root).is_dir():
        raise _GitUnavailable(f"{root.name} is not a directory")
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        raise _GitUnavailable("git is not installed") from None
    except (OSError, subprocess.SubprocessError) as exc:
        raise _GitUnavailable(f"git could not be run ({type(exc).__name__})") from None

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        raise _GitUnavailable(
            f"git {arguments[0]} failed: {detail[0] if detail else 'no detail given'}"
        )
    return completed.stdout


def _revision(root: Path) -> str:
    revision = _git(root, "rev-parse", "HEAD").strip().lower()
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise _GitUnavailable(f"git reported an unusable revision {revision!r}")
    return revision


def _is_clean(root: Path) -> bool:
    """Whether the tree has anything uncommitted.

    ``--porcelain`` covers staged, unstaged and untracked files. Untracked
    files count: a module that exists only in the working directory is code
    that ran and cannot be recovered from the commit.
    """
    return not _git(root, "status", "--porcelain").strip()
