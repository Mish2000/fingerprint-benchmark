"""An adapter writes inside the two directories it was given, or it does not write.

The containment rules are worth testing individually rather than through an
adapter, because each of them corresponds to a different way of getting out:
an absolute name, a ``..``, a symlinked subdirectory, a published file that came
from somewhere else entirely (spec sections 33 and 34).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from fpbench.adapters.support.workspace import (
    AdapterJobWorkspace,
    WorkspaceContainmentError,
)
from fpbench.core.execution_models import ComparisonContext

pytestmark = pytest.mark.adapter_contract

RUN_ID = "run_abc123def456"
JOB_ID = "job_0123456789abcdef"


@pytest.fixture
def context(tmp_path: Path) -> ComparisonContext:
    """The runner's own layout, so the workspace root is derivable."""
    working = tmp_path / "work" / RUN_ID / JOB_ID
    artifacts = tmp_path / "artifacts" / RUN_ID / JOB_ID
    working.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    return ComparisonContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt=1,
        working_directory=working,
        artifact_directory=artifacts,
        timeout_seconds=10.0,
        deterministic_seed=0,
    )


@pytest.fixture
def workspace(context: ComparisonContext) -> AdapterJobWorkspace:
    return AdapterJobWorkspace.from_context(context)


# ---------------------------------------------------------------------- paths


def test_a_work_path_lands_under_the_working_directory(workspace, context):
    path = workspace.work_path("left-template.xyt")
    assert path.parent == Path(context.working_directory).resolve()


def test_an_artifact_path_lands_under_the_artifact_directory(workspace, context):
    path = workspace.artifact_path("matcher-output.txt")
    assert path.parent == Path(context.artifact_directory).resolve()


def test_nested_names_have_their_parents_created(workspace):
    path = workspace.work_path("stage-one/left-template.xyt")
    assert path.parent.is_dir()


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "C:\\Windows\\system32\\drivers\\etc\\hosts",
        "../escape.txt",
        "nested/../../escape.txt",
        "./here.txt",
        "",
        "   ",
        "spaced name.txt",
        "weird|name.txt",
    ],
)
def test_a_name_that_could_escape_is_refused(workspace, name):
    with pytest.raises(WorkspaceContainmentError):
        workspace.work_path(name)


@pytest.mark.parametrize(
    "name",
    [
        "subject_00001000.xyt",
        "left-finger-02.xyt",
        "genuine-pair.txt",
        "sd300a-left.pgm",
        "00001000.xyt",
    ],
)
def test_a_name_that_knows_too_much_is_refused(workspace, name):
    """The adapter has no subject, no finger and no pair (docs/adr/0010).

    A file name that carries one of them means somebody smuggled it in, and the
    check fires on the smuggling rather than on the consequences.
    """
    with pytest.raises(WorkspaceContainmentError, match="cannot know|identifier"):
        workspace.work_path(name)


def test_a_symlinked_subdirectory_does_not_become_a_way_out(workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = Path(workspace.working_directory) / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform will not create symlinks without privileges")
    with pytest.raises(WorkspaceContainmentError, match="outside"):
        workspace.work_path("escape/leak.txt")


@pytest.mark.parametrize("points_inside", [True, False])
def test_a_final_symlink_is_refused_even_when_it_points_inside(
    workspace, tmp_path, points_inside
):
    target = (
        workspace.work_path("ordinary.txt")
        if points_inside
        else tmp_path / "outside-final.txt"
    )
    target.write_bytes(b"target")
    link = Path(workspace.working_directory) / "linked.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    with pytest.raises(WorkspaceContainmentError, match="symlink"):
        workspace.work_path("linked.txt")


@pytest.mark.parametrize("points_inside", [True, False])
def test_an_intermediate_symlink_is_always_refused(workspace, tmp_path, points_inside):
    target = (
        Path(workspace.working_directory) / "real-directory"
        if points_inside
        else tmp_path / "outside-directory"
    )
    target.mkdir()
    link = Path(workspace.working_directory) / "linked-directory"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    with pytest.raises(WorkspaceContainmentError, match="symlink"):
        workspace.work_path("linked-directory/output.txt")


# ----------------------------------------------------------------- artefacts


def test_publishing_copies_out_of_the_disposable_working_directory(workspace):
    source = workspace.work_path("left-template.xyt")
    source.write_bytes(b"template-bytes")

    reference = workspace.publish_artifact(
        artifact_id="left_template",
        kind="template",
        source=source,
        relative_name="left-template.xyt",
    )

    published = Path(workspace.artifact_directory) / "left-template.xyt"
    assert published.is_file()
    assert reference.sha256 == hashlib.sha256(b"template-bytes").hexdigest()
    assert reference.size_bytes == len(b"template-bytes")


def test_a_published_artefact_owns_its_bytes(workspace):
    """A copy, never a hardlink: rewriting the scratch file must not reach in."""
    source = workspace.work_path("left-template.xyt")
    source.write_bytes(b"original")
    workspace.publish_artifact(
        artifact_id="left_template",
        kind="template",
        source=source,
        relative_name="left-template.xyt",
    )
    source.write_bytes(b"replaced-after-publication")

    published = Path(workspace.artifact_directory) / "left-template.xyt"
    assert published.read_bytes() == b"original"


def test_the_reference_path_is_workspace_relative(workspace, tmp_path):
    source = workspace.work_path("left-template.xyt")
    source.write_bytes(b"x")
    reference = workspace.publish_artifact(
        artifact_id="left_template",
        kind="template",
        source=source,
        relative_name="left-template.xyt",
    )
    assert reference.relative_path == (
        f"artifacts/{RUN_ID}/{JOB_ID}/left-template.xyt"
    )
    assert not Path(reference.relative_path).is_absolute()
    assert ".." not in Path(reference.relative_path).parts


def test_publishing_twice_under_one_name_is_refused(workspace):
    first = workspace.work_path("out-a.txt")
    first.write_bytes(b"a")
    second = workspace.work_path("out-b.txt")
    second.write_bytes(b"b")
    workspace.publish_artifact(
        artifact_id="a", kind="output", source=first, relative_name="matcher-output.txt"
    )
    with pytest.raises(WorkspaceContainmentError, match="already published"):
        workspace.publish_artifact(
            artifact_id="b",
            kind="output",
            source=second,
            relative_name="matcher-output.txt",
        )


def test_a_file_from_outside_the_job_cannot_be_published(workspace, tmp_path):
    stray = tmp_path / "elsewhere" / "secret.txt"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"not mine")
    with pytest.raises(WorkspaceContainmentError, match="outside this job"):
        workspace.publish_artifact(
            artifact_id="stray", kind="output", source=stray
        )


def test_a_missing_source_is_not_an_artefact(workspace):
    with pytest.raises(WorkspaceContainmentError, match="regular file"):
        workspace.publish_artifact(
            artifact_id="absent",
            kind="output",
            source=workspace.work_path("never-written.txt"),
        )


def test_an_artifact_source_symlink_is_refused(workspace):
    target = workspace.work_path("real-output.txt")
    target.write_bytes(b"output")
    link = Path(workspace.working_directory) / "linked-output.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    with pytest.raises(WorkspaceContainmentError, match="symlink"):
        workspace.publish_artifact(artifact_id="linked", kind="output", source=link)


def test_an_artifact_target_symlink_is_refused(workspace, tmp_path):
    source = workspace.work_path("output.txt")
    source.write_bytes(b"output")
    outside = tmp_path / "outside-target.txt"
    outside.write_bytes(b"outside")
    target = Path(workspace.artifact_directory) / "published.txt"
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    with pytest.raises(WorkspaceContainmentError, match="symlink"):
        workspace.publish_artifact(
            artifact_id="output",
            kind="output",
            source=source,
            relative_name="published.txt",
        )


def test_a_hardlinked_artifact_source_is_refused(workspace):
    original = workspace.work_path("original.txt")
    original.write_bytes(b"shared inode")
    linked = workspace.work_path("linked.txt")
    try:
        os.link(original, linked)
    except OSError:  # pragma: no cover - filesystem policy
        pytest.skip("this filesystem will not create hard links")
    with pytest.raises(WorkspaceContainmentError, match="hard links"):
        workspace.publish_artifact(
            artifact_id="linked", kind="output", source=linked
        )


# -------------------------------------------------------------- construction


def test_a_layout_the_runner_did_not_produce_falls_back_to_artifact_relative(tmp_path):
    """A bare adapter test has no workspace root, and says so rather than guessing."""
    working = tmp_path / "w"
    artifacts = tmp_path / "a"
    working.mkdir()
    artifacts.mkdir()
    context = ComparisonContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt=1,
        working_directory=working,
        artifact_directory=artifacts,
        timeout_seconds=10.0,
        deterministic_seed=0,
    )
    workspace = AdapterJobWorkspace.from_context(context)
    assert workspace.workspace_root is None

    source = workspace.work_path("out.txt")
    source.write_bytes(b"x")
    reference = workspace.publish_artifact(
        artifact_id="out", kind="output", source=source, relative_name="out.txt"
    )
    assert reference.relative_path == "out.txt"


def test_relative_directories_are_refused_outright(tmp_path):
    with pytest.raises(WorkspaceContainmentError, match="absolute"):
        AdapterJobWorkspace(
            working_directory=Path("work"), artifact_directory=tmp_path
        )
