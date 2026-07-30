"""A research run may only be built from code that exists in a commit.

Every test here creates its own throwaway git repository in a temp directory.
Asking the repository the suite happens to be running inside would make the
outcome depend on whether the developer had saved a file — which is precisely
the condition under test, and precisely the thing a test must not be at the
mercy of.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from fpbench.core.errors import ResearchPreflightError
from fpbench.core.provenance_models import (
    PROVENANCE_KIND_GIT,
    PROVENANCE_KIND_UNAVAILABLE,
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.provenance.software import capture_software_provenance

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A one-commit git repository with nothing uncommitted."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "fpbench tests")
    (root / "module.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "first")
    return root


def _provenance(**overrides) -> SoftwareProvenance:
    settings = {
        "provenance_kind": PROVENANCE_KIND_GIT,
        "source_revision": "a" * 40,
        "source_tree_clean": True,
        "package_version": "0.1.0",
        "python_version": "3.12.0",
        "python_implementation": "CPython",
        "dependency_versions": {"pyarrow": "15.0.0", "pyyaml": "6.0"},
    }
    settings.update(overrides)
    return SoftwareProvenance(**settings)


# ------------------------------------------------------------------- capture


def test_a_clean_repository_is_accepted(repository: Path):
    provenance = capture_software_provenance(
        repository_root=repository, require_clean=True
    )
    assert provenance.provenance_kind == PROVENANCE_KIND_GIT
    assert provenance.source_tree_clean
    assert provenance.is_research_grade
    assert len(provenance.source_revision) == 40


def test_a_modified_file_makes_the_repository_unusable_for_research(repository: Path):
    (repository / "module.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(ResearchPreflightError, match="uncommitted"):
        capture_software_provenance(repository_root=repository, require_clean=True)


def test_an_untracked_file_also_makes_it_unusable(repository: Path):
    """Untracked counts. A module that exists only on disk still ran."""
    (repository / "scratch.py").write_text("print(1)\n", encoding="utf-8")
    with pytest.raises(ResearchPreflightError):
        capture_software_provenance(repository_root=repository, require_clean=True)


def test_development_mode_reports_a_dirty_tree_without_refusing(repository: Path):
    (repository / "module.py").write_text("value = 2\n", encoding="utf-8")
    provenance = capture_software_provenance(
        repository_root=repository, require_clean=False
    )
    assert provenance.provenance_kind == PROVENANCE_KIND_GIT
    assert not provenance.source_tree_clean
    assert not provenance.is_research_grade


def test_missing_git_metadata_is_rejected_in_research_mode(tmp_path: Path):
    plain = tmp_path / "exported"
    plain.mkdir()
    (plain / "module.py").write_text("value = 1\n", encoding="utf-8")
    with pytest.raises(ResearchPreflightError):
        capture_software_provenance(repository_root=plain, require_clean=True)


def test_missing_git_metadata_is_tolerated_in_development(tmp_path: Path):
    plain = tmp_path / "exported"
    plain.mkdir()
    provenance = capture_software_provenance(
        repository_root=plain, require_clean=False
    )
    assert provenance.provenance_kind == PROVENANCE_KIND_UNAVAILABLE
    assert not provenance.source_tree_clean


def test_no_repository_path_is_kept(repository: Path):
    """Where the checkout lives says nothing about the experiment."""
    provenance = capture_software_provenance(
        repository_root=repository, require_clean=True
    )
    assert str(repository) not in repr(provenance)


def test_the_dependency_versions_that_touch_persistence_are_recorded(
    repository: Path,
):
    provenance = capture_software_provenance(
        repository_root=repository, require_clean=True
    )
    assert set(provenance.dependency_versions) == {"pyarrow", "pyyaml"}


# --------------------------------------------------------------- fingerprint


def test_a_different_commit_changes_the_fingerprint():
    first = software_provenance_fingerprint(_provenance())
    second = software_provenance_fingerprint(_provenance(source_revision="b" * 40))
    assert first != second


def test_a_package_version_change_changes_the_fingerprint():
    first = software_provenance_fingerprint(_provenance())
    second = software_provenance_fingerprint(_provenance(package_version="0.2.0"))
    assert first != second


def test_a_dependency_version_change_changes_the_fingerprint():
    first = software_provenance_fingerprint(_provenance())
    second = software_provenance_fingerprint(
        _provenance(dependency_versions={"pyarrow": "16.0.0", "pyyaml": "6.0"})
    )
    assert first != second


def test_capturing_the_same_repository_twice_is_stable(repository: Path):
    """No timestamp reaches the fingerprint."""
    first = capture_software_provenance(
        repository_root=repository, require_clean=True
    )
    second = capture_software_provenance(
        repository_root=repository, require_clean=True
    )
    assert software_provenance_fingerprint(first) == software_provenance_fingerprint(
        second
    )


# ------------------------------------------------------------------ invariants


def test_a_git_provenance_needs_a_full_commit_sha():
    with pytest.raises(ValueError, match="40-character"):
        _provenance(source_revision="abc1234")


def test_a_tree_with_no_revision_cannot_claim_to_be_clean():
    with pytest.raises(ValueError, match="clean source tree"):
        _provenance(
            provenance_kind=PROVENANCE_KIND_UNAVAILABLE,
            source_revision="unavailable",
            source_tree_clean=True,
        )


def test_dependency_versions_are_frozen():
    provenance = _provenance()
    with pytest.raises(TypeError):
        provenance.dependency_versions["pyarrow"] = "0"  # type: ignore[index]
