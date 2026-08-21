"""A resumed run must be resumed with the preparer that produced its results.

The reviewer's reproduction: a real preparer at version 2 that reported version
1 through ``run_metadata()``, resumed under a version-1 preparer, and accepted.
The version field existed to make a behaviour change visible and was the field
being overwritten.

Three separate holes, each with its own test below:

* the check read the *first* stored result only, so a preparer swapped at
  comparison 3,000 was invisible;
* a result whose metadata lacked the fields was skipped rather than refused;
* ``run_metadata()`` was applied *over* the runner's own record, so a preparer
  could name its own version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from fpbench.core.errors import PreflightError
from fpbench.core.execution_models import ExecutionProfile, PreparedImage
from fpbench.core.models import ImageRecord
from fpbench.imaging.base import ImagePreparer

from runworld import build_world


class _VersionedPreparer(ImagePreparer):
    """The identity preparer, with a version and an over-reaching declaration.

    ``declares`` is what the preparer returns from ``run_metadata()``. A real
    preparer returns provenance about the *input set*; this one is allowed to
    return whatever a test needs, which is how the reviewer's version-1
    declaration is reproduced.
    """

    def __init__(
        self,
        delegate: ImagePreparer,
        *,
        version: str = "1",
        declares: Mapping[str, str] | None = None,
    ) -> None:
        self._delegate = delegate
        self._version = version
        self._declares = dict(declares or {})

    @property
    def preparer_id(self) -> str:
        return self._delegate.preparer_id

    @property
    def preparer_version(self) -> str:
        return self._version

    @property
    def runner_metadata_schema(self) -> str:
        return self._delegate.runner_metadata_schema

    def run_metadata(self) -> Mapping[str, str]:
        return dict(self._delegate.run_metadata()) | self._declares

    def side_metadata(self, prepared: PreparedImage) -> Mapping[str, str]:
        return self._delegate.side_metadata(prepared)

    def preflight(self) -> None:
        self._delegate.preflight()

    def prepare(
        self, image: ImageRecord, dataset_root: Path, profile: ExecutionProfile
    ) -> PreparedImage:
        return self._delegate.prepare(image, dataset_root, profile)


def _world(tmp_path: Path, preparer_factory=None):
    world = build_world(tmp_path / "world")
    if preparer_factory is not None:
        world.preparer = preparer_factory(world.preparer)
    return world


def _execute_some(world, count: int) -> None:
    runner = world.job_runner()
    planned = list(world.plan.jobs)[:count]
    for item in planned:
        runner.execute(item.job, world.pair_index[item.job.pair_id])


def test_a_preparer_may_not_restate_the_runners_own_record(tmp_path: Path) -> None:
    """The reviewer's exploit: a version-2 preparer filing results as version 1."""
    world = _world(
        tmp_path,
        lambda base: _VersionedPreparer(
            base, version="2", declares={"preparer_version": "1"}
        ),
    )
    with pytest.raises(PreflightError, match="preparer_version"):
        _execute_some(world, 1)


@pytest.mark.parametrize(
    "key", ["runner", "preparer_id", "preparer_version", "runner_metadata_schema"]
)
def test_every_reserved_key_is_refused(tmp_path: Path, key: str) -> None:
    world = _world(
        tmp_path, lambda base: _VersionedPreparer(base, declares={key: "anything"})
    )
    with pytest.raises(PreflightError, match=key):
        _execute_some(world, 1)


def test_an_honest_declaration_still_reaches_the_stored_result(
    tmp_path: Path,
) -> None:
    """Refusing the reserved four must not refuse a preparer's real provenance."""
    world = _world(
        tmp_path,
        lambda base: _VersionedPreparer(base, declares={"transform_profile_id": "p1"}),
    )
    _execute_some(world, 1)
    stored = world.result_store.stored_job_ids(world.run.run_id)
    result = world.result_store.read_raw_result(world.run.run_id, stored[0])
    assert result.runner_metadata["transform_profile_id"] == "p1"
    assert result.runner_metadata["preparer_version"] == "1"


def test_a_preparer_swapped_mid_run_is_refused_on_resume(tmp_path: Path) -> None:
    """Not just at result zero: the check has to read all of them."""
    world = _world(tmp_path, lambda base: _VersionedPreparer(base, version="1"))
    _execute_some(world, 3)

    # Same world, same stored results, a preparer whose behaviour changed.
    world.preparer = _VersionedPreparer(world.preparer._delegate, version="2")
    with pytest.raises(PreflightError, match="preparer_version"):
        world.job_runner()


def test_the_check_reads_past_the_first_result(tmp_path: Path) -> None:
    """A result produced by another preparer *later* in the run is still caught.

    This is the shape the old check could not see: result zero agrees with the
    current preparer, and one further in does not. Reading ``stored[0]`` and
    stopping passed it.
    """
    import dataclasses

    world = _world(tmp_path, lambda base: _VersionedPreparer(base, version="1"))
    _execute_some(world, 3)

    stored = world.result_store.stored_job_ids(world.run.run_id)
    assert len(stored) >= 3

    # Rewrite a *later* result as though a different preparer had produced it,
    # leaving result zero exactly as it was.
    divergent = stored[2]
    result = world.result_store.read_raw_result(world.run.run_id, divergent)
    world.result_store.raw_result_path(world.run.run_id, divergent).unlink()
    world.result_store.write_raw_result(
        dataclasses.replace(
            result,
            runner_metadata=dict(result.runner_metadata) | {"preparer_version": "9"},
        )
    )

    first = world.result_store.read_raw_result(world.run.run_id, stored[0])
    assert first.runner_metadata["preparer_version"] == "1", "result zero is clean"

    with pytest.raises(PreflightError, match="preparer_version"):
        world.job_runner()


def test_a_result_with_no_preparer_metadata_is_refused(tmp_path: Path) -> None:
    """Skipping a result that cannot account for itself is not a check."""
    world = _world(tmp_path)
    _execute_some(world, 1)

    stored = world.result_store.stored_job_ids(world.run.run_id)
    result = world.result_store.read_raw_result(world.run.run_id, stored[0])
    stripped = {
        key: value
        for key, value in result.runner_metadata.items()
        if key != "preparer_version"
    }
    import dataclasses

    world.result_store.raw_result_path(world.run.run_id, stored[0]).unlink()
    world.result_store.write_raw_result(
        dataclasses.replace(result, runner_metadata=stripped)
    )

    with pytest.raises(PreflightError, match="preparer_version"):
        world.job_runner()
