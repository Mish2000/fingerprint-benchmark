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
