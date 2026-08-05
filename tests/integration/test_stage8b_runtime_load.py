"""The real runtime, the real checkpoint, loaded the way qualification will.

Marked ``flx_runtime`` because it needs the built bundle.  It is skipped, not
faked, where the bundle is absent: an invented checkpoint load would prove
nothing about the artifact this stage exists to qualify.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.flx_errors import FlxArtifactError, FlxWorkerError
from fpbench.flx import identity
from fpbench.flx.artifacts import FlxRuntimeBundle, verify_bundle_artifacts
from fpbench.flx.lock import load_runtime_lock
from fpbench.flx.policy import load_runtime_policy
from fpbench.flx.runtime import build_runtime_manifest
from fpbench.flx.worker import FlxWorkerSession

pytestmark = pytest.mark.flx_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"
POLICY_PATH = REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"
NOW = "2026-08-05T12:00:00+03:00"


@pytest.fixture(scope="module")
def bundle() -> FlxRuntimeBundle:
    candidate = FlxRuntimeBundle.from_environment()
    try:
        verify_bundle_artifacts(candidate)
    except FlxArtifactError as exc:
        pytest.skip(f"no verified flx runtime bundle: {exc}")
    if not candidate.venv_python.exists():
        pytest.skip("the flx runtime bundle has no interpreter")
    return candidate


@pytest.fixture(scope="module")
def policy():
    return load_runtime_policy(POLICY_PATH)


@pytest.fixture(scope="module")
def session(bundle: FlxRuntimeBundle, policy):
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as worker:
        yield worker


def test_the_installed_runtime_is_exactly_the_lock(session, policy) -> None:
    report = session.validate_runtime(
        deadline_seconds=float(policy.max_worker_startup_seconds)
    )
    lock = load_runtime_lock(LOCK_PATH)

    manifest = build_runtime_manifest(report, lock=lock, created_utc=NOW)

    assert manifest.os_name == "Linux"
    assert manifest.cpu_architecture == "x86_64"
    assert manifest.device == "cpu"
    assert manifest.cuda_available is False
    assert manifest.torch_num_threads == 1
    assert manifest.torch_num_interop_threads == 1
    assert manifest.torch_version == lock.require_version("torch")
    # Compared canonically: importlib.metadata reports "Jinja2" where the wheel
    # filename says "jinja2", and a lock that disagreed would be unusable.
    lock.verify_installed(report["distributions"])


def test_the_checkpoint_loads_as_pure_tensors_into_the_identified_variant(
    session, policy
) -> None:
    result = session.load_runtime(
        deadline_seconds=float(policy.max_model_load_seconds)
    )

    # weights_only=True succeeded, so nothing in the file could execute.
    assert result["loaded"] is True
    # strict=True with no allowance: the variant is exactly what Stage 8A said.
    assert result["missing_state_dict_keys"] == []
    assert result["unexpected_state_dict_keys"] == []
    assert result["state_dict_entries"] > 0
    assert result["training_mode"] is False
    assert result["gradients_enabled"] is False
    assert float(result["load_seconds"]) <= float(policy.max_model_load_seconds)


def test_the_worker_refuses_an_unknown_operation(session, policy) -> None:
    with pytest.raises(FlxWorkerError, match="UNKNOWN_OPERATION"):
        session.request(
            "extract_everything", deadline_seconds=float(policy.compare_deadline_seconds)
        )


def test_a_checkpoint_whose_bytes_moved_is_refused(bundle, policy, tmp_path) -> None:
    # The digest is re-checked inside the worker, on every load, so a swapped
    # file cannot be laundered by a parent that verified the right one earlier.
    impostor = tmp_path / identity.CHECKPOINT_FILENAME
    impostor.write_bytes(b"\0" * identity.CHECKPOINT_SIZE_BYTES)
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as worker:
        with pytest.raises(FlxWorkerError, match="CHECKPOINT_DIGEST_MISMATCH"):
            worker.request(
                "load_runtime",
                deadline_seconds=float(policy.max_model_load_seconds),
                source_tree=str(bundle.source_tree),
                checkpoint=str(impostor),
            )


def test_a_truncated_checkpoint_is_refused_before_it_is_opened(
    bundle, policy, tmp_path
) -> None:
    truncated = tmp_path / identity.CHECKPOINT_FILENAME
    truncated.write_bytes(b"\0" * 1024)
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as worker:
        with pytest.raises(FlxWorkerError, match="CHECKPOINT_SIZE_MISMATCH"):
            worker.request(
                "load_runtime",
                deadline_seconds=float(policy.max_model_load_seconds),
                source_tree=str(bundle.source_tree),
                checkpoint=str(truncated),
            )


def test_an_operation_that_misses_its_deadline_kills_the_worker(bundle, policy) -> None:
    # There is no retry: a worker that missed a deadline cannot be trusted to
    # answer the next question about the right input.
    from fpbench.core.flx_errors import FlxWorkerTimeout

    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as worker:
        with pytest.raises(FlxWorkerTimeout, match="no response within"):
            worker.request("load_runtime", deadline_seconds=0.001,
                           source_tree=str(bundle.source_tree),
                           checkpoint=str(bundle.checkpoint))
        with pytest.raises(FlxWorkerError, match="not running"):
            worker.validate_runtime(deadline_seconds=5)


def test_the_worker_reaches_the_network_from_nowhere(bundle, policy) -> None:
    with FlxWorkerSession(
        bundle, startup_deadline_seconds=float(policy.max_worker_startup_seconds)
    ) as worker:
        response = worker.request(
            "validate_runtime", deadline_seconds=float(policy.max_worker_startup_seconds)
        )
        assert response["network_attempts"] == 0
        environment = response["result"]["environment"]
        assert environment["HF_HOME"].endswith("offline-cache")
        assert environment["TORCH_HOME"].endswith("offline-cache")
