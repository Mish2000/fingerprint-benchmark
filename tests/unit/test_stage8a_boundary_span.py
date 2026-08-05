"""The Stage 8A boundary audit covers Stage 8A's span, and only its span.

These tests exist because the audit originally compared its baseline against
``HEAD``.  That silently turned "Stage 8A did not touch prior stages" into
"nobody has added a file outside Stage 8A's allowlist since Stage 7D", which
the first commit of any later stage falsifies.  Both directions are locked
here so the repair cannot be read as a loosening: work inside the span is
still refused, and work after the publication is still not Stage 8A's to
permit or forbid (docs/adr/0067).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from fpbench.core.errors import Stage8AFinalizationError
from fpbench.modern_matchers import finalization as finalization_module
from fpbench.modern_matchers.finalization import (
    STAGE8A_BASELINE_COMMIT,
    STAGE8A_PUBLICATION_COMMIT,
    verify_stage8a_workspace_boundaries,
)

pytestmark = pytest.mark.stage8a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# A path a later stage would add.  It is deliberately shaped like real Stage 8B
# work rather than like a scratch file, because that is the case that broke.
LATER_STAGE_PATH = "src/fpbench/flx/runtime.py"
PRIOR_STAGE_PATH = "src/fpbench/execution/planner.py"


def _install_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    changed: Sequence[str] = (),
    untracked: Sequence[str] = (),
    calls: list[tuple[str, ...]] | None = None,
) -> None:
    """Answer the audit's Git questions without inventing a repository."""

    def fake_git_output(repository_root: Path, *arguments: str) -> tuple[str, ...]:
        if calls is not None:
            calls.append(arguments)
        if arguments[:1] == ("rev-parse",):
            return (str(REPOSITORY_ROOT),)
        if arguments[:1] == ("merge-base",):
            return ()
        if arguments[:1] == ("diff",):
            return tuple(changed)
        if arguments[:1] == ("ls-files",):
            return tuple(untracked)
        raise AssertionError(f"unexpected git invocation {arguments}")

    monkeypatch.setattr(finalization_module, "_git_output", fake_git_output)


def test_the_audited_span_is_two_fixed_commits_and_never_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    _install_git(monkeypatch, calls=calls)

    verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)

    diff = next(arguments for arguments in calls if arguments[0] == "diff")
    assert diff == (
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        STAGE8A_BASELINE_COMMIT,
        STAGE8A_PUBLICATION_COMMIT,
        "--",
    )
    assert "HEAD" not in diff


def test_both_span_endpoints_must_remain_in_the_current_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    _install_git(monkeypatch, calls=calls)

    verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)

    ancestry = [arguments for arguments in calls if arguments[0] == "merge-base"]
    assert ancestry == [
        ("merge-base", "--is-ancestor", STAGE8A_BASELINE_COMMIT, STAGE8A_PUBLICATION_COMMIT),
        ("merge-base", "--is-ancestor", STAGE8A_PUBLICATION_COMMIT, "HEAD"),
    ]


def test_a_prior_stage_path_changed_inside_the_span_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_git(monkeypatch, changed=(PRIOR_STAGE_PATH,))

    with pytest.raises(
        Stage8AFinalizationError,
        match="prior-stage paths changed during Stage 8A",
    ):
        verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)


def test_a_later_stage_path_committed_after_the_publication_is_not_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same path that fails inside the span passes outside it: the audit is
    # about when the change happened, not about the file's name.
    _install_git(monkeypatch, untracked=(LATER_STAGE_PATH,))

    verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)

    _install_git(monkeypatch, changed=(LATER_STAGE_PATH,))
    with pytest.raises(Stage8AFinalizationError):
        verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)


def test_a_later_stage_evidence_tree_is_not_stage8a_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_git(
        monkeypatch,
        untracked=(
            "evidence/stage8b-flx-runtime-qualification/qualification-report.json",
            "docs/adr/0068-some-later-decision.md",
            "tests/stage8bworld.py",
        ),
    )

    verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)


@pytest.mark.parametrize(
    "path",
    [
        "src/fpbench/modern_matchers/extra.py",
        "configs/modern-matchers/another.yaml",
        "integrations/modern-matchers/manifests/fourth.json",
        "evidence/stage8a-modern-matcher-selection/notes.json",
        "tests/unit/test_stage8a_something.py",
        "src/fpbench/core/modern_matcher_models.py",
    ],
)
def test_uncommitted_stage8a_material_is_refused(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    _install_git(monkeypatch, untracked=(path,))

    with pytest.raises(
        Stage8AFinalizationError,
        match="Stage 8A material exists outside its publication",
    ):
        verify_stage8a_workspace_boundaries(REPOSITORY_ROOT)


def test_every_owned_path_is_also_an_allowed_change() -> None:
    # Anything Stage 8A owns must be something Stage 8A was allowed to write;
    # otherwise the two rules could disagree about the same file.
    owned = (
        "src/fpbench/modern_matchers/loading.py",
        "configs/modern-matchers/stage8a_candidates_v1.yaml",
        "integrations/modern-matchers/manifests/flx_fixed_length_extractor.json",
        "evidence/stage8a-modern-matcher-selection/README.md",
        "tests/stage8aworld.py",
        "src/fpbench/storage/modern_matcher_store.py",
        "src/fpbench/experiments/stage8a_modern_matcher_selection.py",
        "src/fpbench/core/modern_matcher_models.py",
    )
    for path in owned:
        assert finalization_module._is_stage8a_owned_path(path), path
        assert finalization_module._is_allowed_stage8a_change(path), path


def test_shared_files_are_allowed_but_not_owned() -> None:
    # Stage 8A edited these, but it does not own them, so an uncommitted edit
    # to one of them is the current author's business and not a Stage 8A fault.
    for path in ("README.md", "Makefile", "pyproject.toml", "docs/adr/README.md"):
        assert finalization_module._is_allowed_stage8a_change(path), path
        assert not finalization_module._is_stage8a_owned_path(path), path
