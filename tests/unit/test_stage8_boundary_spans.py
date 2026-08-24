"""Stage 8B, 8C and 8D audit their own spans, and no document moves the ends.

ADR 0067 settled this for Stage 8A: a boundary audit compares the commit that
opened the stage with the commit that published it, both constants. Stage 8B and
Stage 8C were written afterwards and did it differently — they read the span's
end from the published marker's ``verifier_source_commit``, so that a later stage
could exist without editing them.

That worked for the case it was designed for and failed for a case nobody had
reached yet. ``verifier_source_commit`` legitimately *moves* when a stage's
authority source is re-published, and the audited span moved with it: publishing
Stage 8B's marker at a current commit widened
``STAGE8B_BASELINE_COMMIT..span_end`` to include every stage committed since, and
the audit refused with fifteen stages of somebody else's work listed as having
"changed during Stage 8B".

There were two questions and one field. What a stage is answerable for is a fact
about history and cannot move; which source is pinned byte-for-byte is a claim
that can be re-made. The direction that matters most is the one below in
:func:`test_no_published_marker_can_move_the_audited_span` — a span end read from
the audited document could be *narrowed* by it, not only widened.

Stage 8D carried the same shape and never hit it — nothing pins its sources by
*commit*, so its ``verifier_source_commit`` never had to move. That made it a
debt rather than a bug, and it is included here because a debt nobody can see is
one nobody pays.

These are Stage 8A's own span tests applied to the three stages that drifted from
it, both directions locked: work inside the span is still refused, and work
committed after the publication is still not theirs to permit or forbid.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Callable, Sequence

import pytest

from fpbench.core.calibration_errors import Stage8DFinalizationError
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.flx_errors import Stage8BFinalizationError
from fpbench.experiments import stage8c_finalization as stage8c
from fpbench.experiments import stage8d_finalization as stage8d
from fpbench.flx import finalization as stage8b

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _Stage:
    """One stage's audit, and the names this file needs to reach it."""

    def __init__(
        self,
        *,
        label: str,
        module,
        audit: Callable[[Path], None],
        baseline: str,
        publication: str,
        error: type[Exception],
        marker: str,
        forbidden_path: str,
        owned_path: str,
        later_path: str,
    ) -> None:
        self.label = label
        self.module = module
        self.audit = audit
        self.baseline = baseline
        self.publication = publication
        self.error = error
        self.marker = marker
        self.forbidden_path = forbidden_path
        self.owned_path = owned_path
        self.later_path = later_path

    def __repr__(self) -> str:  # pragma: no cover - test ids
        return self.label


_STAGES = (
    _Stage(
        label="8B",
        module=stage8b,
        audit=stage8b.verify_stage8b_workspace_boundaries,
        baseline=stage8b.STAGE8B_BASELINE_COMMIT,
        publication=stage8b.STAGE8B_PUBLICATION_COMMIT,
        error=Stage8BFinalizationError,
        marker="evidence/stage8b-flx-runtime-qualification/stage-8b-finalization.json",
        forbidden_path="src/fpbench/execution/planner.py",
        owned_path="src/fpbench/flx/extra.py",
        later_path="src/fpbench/experiments/stage20b_finalization.py",
    ),
    _Stage(
        label="8C",
        module=stage8c,
        audit=stage8c.verify_stage8c_workspace_boundaries,
        baseline=stage8c.STAGE_8C_BASELINE_COMMIT,
        publication=stage8c.STAGE_8C_PUBLICATION_COMMIT,
        error=ResearchPreflightError,
        marker="evidence/flx-canonical500-raw/stage-8c-finalization.json",
        forbidden_path="src/fpbench/execution/planner.py",
        owned_path="evidence/flx-canonical500-raw/notes.json",
        later_path="src/fpbench/experiments/stage20b_finalization.py",
    ),
    _Stage(
        label="8D",
        module=stage8d,
        audit=stage8d.verify_stage8d_workspace_boundaries,
        baseline=stage8d.STAGE_8D_BASELINE_COMMIT,
        publication=stage8d.STAGE_8D_PUBLICATION_COMMIT,
        error=Stage8DFinalizationError,
        marker=(
            "evidence/stage8d-calibration-infrastructure/stage-8d-finalization.json"
        ),
        forbidden_path="src/fpbench/execution/planner.py",
        owned_path="evidence/stage8d-calibration-infrastructure/notes.json",
        later_path="src/fpbench/experiments/stage20b_finalization.py",
    ),
)


def _install_git(
    monkeypatch: pytest.MonkeyPatch,
    stage: _Stage,
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
            if len(arguments) > 1 and ":" in arguments[1]:
                # A historical-repair blob lookup; hand back what is expected so
                # the span questions stay the subject of this file.
                _, _, path = arguments[1].partition(":")
                return (stage.module._HISTORICAL_REPAIR_BLOBS[path],)
            return (str(REPOSITORY_ROOT),)
        if arguments[:1] == ("merge-base",):
            return ()
        if arguments[:1] == ("diff",):
            return tuple(changed)
        if arguments[:1] == ("rev-list",):
            # Stage 8D walks its span commit by commit; one synthetic revision
            # is enough to carry the changed paths through that walk.
            return ("0" * 40,)
        if arguments[:1] == ("diff-tree",):
            return tuple(changed)
        if arguments[:1] == ("ls-files",):
            return tuple(untracked)
        raise AssertionError(f"unexpected git invocation {arguments}")

    monkeypatch.setattr(stage.module, "_git_output", fake_git_output)
    monkeypatch.setattr(stage.module, "_audit_source_boundaries", lambda _root: None)


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_the_audited_span_is_two_fixed_commits_and_never_head(
    monkeypatch: pytest.MonkeyPatch, stage: _Stage
) -> None:
    calls: list[tuple[str, ...]] = []
    _install_git(monkeypatch, stage, calls=calls)

    stage.audit(REPOSITORY_ROOT)

    # Stage 8B and 8C diff two commits; Stage 8D walks the span with rev-list.
    # The property is the same either way and is asserted on the shape rather
    # than on which Git verb a given stage happens to use.
    spanning = [
        arguments
        for arguments in calls
        if stage.baseline in arguments and stage.publication in arguments
    ]
    assert spanning, (
        f"Stage {stage.label} never asked Git about its own span: {calls}"
    )
    reaching_head = [
        arguments
        for arguments in calls
        if "HEAD" in arguments and arguments[0] != "merge-base"
    ]
    assert not reaching_head, (
        f"Stage {stage.label}'s span reaches HEAD: {reaching_head}"
    )


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_both_span_endpoints_must_remain_in_the_current_history(
    monkeypatch: pytest.MonkeyPatch, stage: _Stage
) -> None:
    calls: list[tuple[str, ...]] = []
    _install_git(monkeypatch, stage, calls=calls)

    stage.audit(REPOSITORY_ROOT)

    ancestry = [arguments for arguments in calls if arguments[0] == "merge-base"]
    assert ancestry == [
        ("merge-base", "--is-ancestor", stage.baseline, stage.publication),
        ("merge-base", "--is-ancestor", stage.publication, "HEAD"),
    ]


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_no_published_marker_can_move_the_audited_span(
    monkeypatch: pytest.MonkeyPatch, stage: _Stage
) -> None:
    """The regression this file exists for: re-issuing a marker cannot move the span.

    The direct form — change ``verifier_source_commit`` and check the ``git diff``
    range did not move — is vacuous *because* of the fix, since the audit no
    longer reads that field at all, and a test that cannot fail is not a test.
    So the same property is stated two ways that can both fail.

    The audit takes no commit, so there is no argument through which a document
    could name its own boundary; and the commit the published marker *does* name
    appears nowhere in the Git questions the audit asks. The second half keeps
    meaning something if somebody adds a parameter back.
    """
    parameters = inspect.signature(stage.audit).parameters
    assert list(parameters) == ["repository_root"], (
        f"Stage {stage.label}'s audit takes {list(parameters)}. A span endpoint "
        "passed in by a caller is one the audited document can choose"
    )

    published = json.loads(
        (REPOSITORY_ROOT / stage.marker).read_text(encoding="utf-8")
    )["verifier_source_commit"]
    assert published != stage.publication, (
        "this test is only meaningful while the pinned source commit and the "
        "publication commit are different values"
    )

    calls: list[tuple[str, ...]] = []
    _install_git(monkeypatch, stage, calls=calls)
    stage.audit(REPOSITORY_ROOT)

    named = {argument for arguments in calls for argument in arguments}
    assert published not in named, (
        f"Stage {stage.label} asked Git about {published[:12]}, which is the "
        "commit its own marker names. The span a stage is answerable for is not "
        "the marker's to choose"
    )


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_a_foreign_path_changed_inside_the_span_still_fails_closed(
    monkeypatch: pytest.MonkeyPatch, stage: _Stage
) -> None:
    _install_git(monkeypatch, stage, changed=(stage.forbidden_path,))

    with pytest.raises(stage.error, match="during Stage 8"):
        stage.audit(REPOSITORY_ROOT)


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_a_later_stage_path_committed_after_the_publication_is_not_audited(
    monkeypatch: pytest.MonkeyPatch, stage: _Stage
) -> None:
    """The same path passes outside the span and fails inside it.

    The audit is about when a change happened, not about what the file is
    called — which is the whole difference between a closed span and ``HEAD``.
    """
    _install_git(monkeypatch, stage, untracked=(stage.later_path,))
    stage.audit(REPOSITORY_ROOT)

    _install_git(monkeypatch, stage, changed=(stage.later_path,))
    with pytest.raises(stage.error):
        stage.audit(REPOSITORY_ROOT)


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_uncommitted_material_the_stage_owns_is_refused(
    monkeypatch: pytest.MonkeyPatch, stage: _Stage
) -> None:
    _install_git(monkeypatch, stage, untracked=(stage.owned_path,))

    with pytest.raises(stage.error, match="outside its publication"):
        stage.audit(REPOSITORY_ROOT)


@pytest.mark.parametrize("stage", _STAGES, ids=lambda stage: stage.label)
def test_the_real_span_still_passes_the_real_audit(stage: _Stage) -> None:
    """No fakes: the constants describe a span this repository actually has.

    A span whose endpoints were mistyped, or taken from a commit that predates
    the marker it belongs to, would pass every test above and refuse the next
    publication.
    """
    stage.audit(REPOSITORY_ROOT)
