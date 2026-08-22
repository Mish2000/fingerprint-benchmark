"""A binding that does not close over its content must not construct."""

from __future__ import annotations

import dataclasses

import pytest

from fpbench.core.content_closure import (
    ContentClosureBinding,
    ContentClosureError,
    NativeDependency,
    PreparerIdentity,
    RuntimeAssetBinding,
    SourceIdentity,
    current_interpreter_identity,
)

DIGEST = "a" * 64
COMMIT = "b" * 40


def _binding(**overrides: object) -> ContentClosureBinding:
    parts: dict = {
        "subject": "run_0123456789ab",
        "code": {"src/fpbench/execution/runner.py": DIGEST},
        "preparer": PreparerIdentity("canonical_500", "3", "canonical_preparation_v2"),
        "interpreter": current_interpreter_identity(),
        "native_dependencies": (NativeDependency("mindtct", DIGEST, "5.0.0"),),
        "runtime_assets": RuntimeAssetBinding(
            (NativeDependency("mindtct", DIGEST),), rechecked_per_comparison=True
        ),
        "source_identity": SourceIdentity(COMMIT, True),
    }
    parts.update(overrides)
    return ContentClosureBinding(**parts)  # type: ignore[arg-type]


def test_a_complete_closure_binds_and_fingerprints_itself() -> None:
    binding = _binding()
    assert len(binding.closure_fingerprint) == 64
    assert _binding().closure_fingerprint == binding.closure_fingerprint


def test_a_closure_with_no_code_is_refused() -> None:
    with pytest.raises(ContentClosureError, match="name the code that ran"):
        _binding(code={})


def test_a_runtime_asset_binding_with_no_assets_is_refused() -> None:
    with pytest.raises(ContentClosureError, match="at least one asset"):
        RuntimeAssetBinding((), rechecked_per_comparison=True)


def test_a_repeated_asset_role_is_refused() -> None:
    with pytest.raises(ContentClosureError, match="named twice"):
        RuntimeAssetBinding(
            (NativeDependency("mindtct", DIGEST), NativeDependency("mindtct", "c" * 64)),
            rechecked_per_comparison=True,
        )


def test_a_path_is_not_an_identity() -> None:
    """``NativeDependency`` has no path field, and that is deliberate."""
    fields = {f.name for f in dataclasses.fields(NativeDependency)}
    assert "path" not in fields and "local_path" not in fields


@pytest.mark.parametrize(
    "bad", ["", "not a digest", "a" * 63, "g" * 64, "A" * 63 + "!"]
)
def test_a_digest_that_is_not_one_is_refused(bad: str) -> None:
    with pytest.raises(ContentClosureError):
        NativeDependency("mindtct", bad)


def test_a_commit_that_is_not_one_is_refused() -> None:
    with pytest.raises(ContentClosureError, match="Git object name"):
        SourceIdentity("main", True)


def test_an_interpreter_without_a_version_is_refused() -> None:
    with pytest.raises(ContentClosureError, match="missing"):
        _binding(interpreter={"implementation": "CPython"})


def test_the_preparer_version_is_inside_the_fingerprint() -> None:
    """The gap this type exists for: an id names a role, a version names behaviour."""
    one = _binding(preparer=PreparerIdentity("canonical_500", "3", "schema_v2"))
    two = _binding(preparer=PreparerIdentity("canonical_500", "4", "schema_v2"))
    assert one.closure_fingerprint != two.closure_fingerprint


def test_whether_drift_was_rechecked_is_inside_the_fingerprint() -> None:
    """Stage 19A and 19B both ran with the re-check off and said so nowhere."""
    checked = _binding(
        runtime_assets=RuntimeAssetBinding(
            (NativeDependency("mindtct", DIGEST),), rechecked_per_comparison=True
        )
    )
    unchecked = _binding(
        runtime_assets=RuntimeAssetBinding(
            (NativeDependency("mindtct", DIGEST),), rechecked_per_comparison=False
        )
    )
    assert checked.closure_fingerprint != unchecked.closure_fingerprint


def test_a_stored_fingerprint_that_does_not_cover_the_binding_is_refused() -> None:
    with pytest.raises(ContentClosureError, match="does not cover"):
        _binding(closure_fingerprint="f" * 64)


def test_the_fingerprint_does_not_move_with_the_clock() -> None:
    """Two runs of one closure are one closure."""
    assert (
        _binding(metadata={"run": "first"}).closure_fingerprint
        != _binding(metadata={"run": "second"}).closure_fingerprint
    )
    assert _binding().closure_fingerprint == _binding().closure_fingerprint


# ------------------------------------------------- consumed, not just defined


def test_a_research_run_builds_its_closure_before_the_first_comparison(
    tmp_path,
) -> None:
    """The type was defined and never constructed, which is the same as absent.

    A research run forms one at preflight, so a run whose provenance has a hole
    stops here rather than after six thousand comparisons — and publishes it
    against the run, so a resume has something to disagree with. Building it and
    dropping it proved the provenance was whole on the day the run started and
    nothing after that.
    """
    from runworld import build_world

    world = build_world(tmp_path / "world", research=True)
    runner = world.job_runner()

    closure = runner._adapter.content_closure(world.preparer)
    assert len(closure.closure_fingerprint) == 64
    assert closure.native_dependencies, "a research run pins runtime assets"
    assert closure.preparer.preparer_id == world.preparer.preparer_id
    assert closure.source_identity.commit


def test_a_run_that_cannot_state_its_closure_does_not_start(tmp_path) -> None:
    from runworld import build_world
    from fpbench.core.errors import PreflightError

    world = build_world(tmp_path / "world", research=True)

    class _Holed:
        """A research adapter whose provenance is missing its runtime assets."""

        def __init__(self, delegate):
            self._delegate = delegate
            self.descriptor = delegate.descriptor

        def validate_environment(self):
            return self._delegate.validate_environment()

        def compare(self, *args, **kwargs):  # pragma: no cover - never reached
            return self._delegate.compare(*args, **kwargs)

        def content_closure(self, preparer):
            raise ContentClosureError("this bundle names no runtime asset")

    world.adapter = _Holed(world.adapter)
    with pytest.raises(PreflightError, match="cannot state the content"):
        world.job_runner()


# --------------------------------------------------- published, not just built


def test_the_closure_is_published_against_the_run(tmp_path) -> None:
    """Preflight leaves a record a resume can be checked against."""
    from runworld import build_world

    world = build_world(tmp_path / "world", research=True)
    world.job_runner()

    store = world.result_store
    assert store.has_closure_binding(world.run.run_id)
    bound = store.read_closure_binding(world.run.run_id)
    closure = world.adapter.content_closure(world.preparer)
    assert bound["closure_fingerprint"] == closure.closure_fingerprint
    assert bound["source_commit"] == closure.source_identity.commit
    assert bound["preparer_id"] == world.preparer.preparer_id


def test_resuming_the_same_run_under_the_same_closure_is_allowed(tmp_path) -> None:
    """Idempotence: a resume is the normal case and must not be a conflict."""
    from runworld import build_world

    world = build_world(tmp_path / "world", research=True)
    world.job_runner()
    world.job_runner()


class _Moved:
    """A research adapter whose closure names a different commit.

    The shape of every real divergence — an interpreter upgraded, a native
    library replaced, a commit checked out — reduced to one field, because the
    binding compares the whole closure and any one part is enough.
    """

    def __init__(self, delegate, commit: str):
        self._delegate = delegate
        self._commit = commit
        self.descriptor = delegate.descriptor

    def validate_environment(self):
        return self._delegate.validate_environment()

    def compare(self, *args, **kwargs):  # pragma: no cover - never reached
        return self._delegate.compare(*args, **kwargs)

    def content_closure(self, preparer):
        from dataclasses import replace

        closure = self._delegate.content_closure(preparer)
        return ContentClosureBinding(
            subject=closure.subject,
            code=closure.code,
            preparer=closure.preparer,
            interpreter=closure.interpreter,
            native_dependencies=closure.native_dependencies,
            runtime_assets=closure.runtime_assets,
            source_identity=replace(closure.source_identity, commit=self._commit),
            metadata=closure.metadata,
        )


def test_a_run_resumed_under_a_different_closure_does_not_start(tmp_path) -> None:
    """The hole the reviewer named: the closure was built and thrown away.

    It proved the provenance was whole on the day the run started. A resume
    under a different commit built a *different* closure, which was equally
    whole, and every result already stored went on standing under the first
    one. Nothing compared them, because nothing kept the first.
    """
    from fpbench.core.errors import PreflightError
    from runworld import build_world

    world = build_world(tmp_path / "world", research=True)
    world.job_runner()

    world.adapter = _Moved(world.adapter, "0" * 40)
    with pytest.raises(PreflightError, match="different content"):
        world.job_runner()


def test_the_refusal_names_the_part_that_moved(tmp_path) -> None:
    """A reader is told the commit moved, not that two digests differ."""
    from fpbench.core.errors import PreflightError
    from runworld import build_world

    world = build_world(tmp_path / "world", research=True)
    world.job_runner()

    world.adapter = _Moved(world.adapter, "0" * 40)
    with pytest.raises(PreflightError) as refusal:
        world.job_runner()
    assert "source_commit" in str(refusal.value)
    assert "closure_fingerprint" in str(refusal.value)
