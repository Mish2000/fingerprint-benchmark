from __future__ import annotations

import os
import json
import socket
import tracemalloc
from decimal import Decimal
from pathlib import Path

import pytest

from fpbench.core.errors import QualificationError
from fpbench.modern_matchers.offline import NetworkAccessBlocked
from fpbench.modern_matchers.probe import (
    IsolatedRestartObservation,
    RestartProbeChallenge,
    _representation_hash,
    run_smoke_qualification,
)
from stage8aworld import (
    make_candidate,
    make_manifest,
    make_registry,
    make_representation,
    make_score,
    rebuild,
    write_artifact_files,
)

pytestmark = pytest.mark.stage8a_contract

REPRESENTATION_PROFILE = make_representation()
SCORE_PROFILE = rebuild(
    make_score(),
    score_range="fixture range [-100, 100]",
    score_minimum="-100",
    score_maximum="100",
)


class FixtureTensor:
    shape = (512,)
    dtype = "float32"

    def __init__(self, values) -> None:
        values = tuple(values)
        self.values = values + (0,) * (512 - len(values))

    def __iter__(self):
        return iter(self.values)

    def tolist(self):
        return list(self.values)

    def tobytes(self):
        return json.dumps(self.values, separators=(",", ":")).encode("ascii")


def _fixture_manifest(tmp_path: Path):
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    write_artifact_files(
        tmp_path,
        manifest,
        {
            "source_bundle": b"source-bundle",
            "model_checkpoint": b"model-checkpoint",
            "threshold_documentation": b"threshold-document",
        },
    )
    return manifest


def _isolated_restart(
    challenge: RestartProbeChallenge,
    left: bytes,
    right: bytes,
    *,
    score: Decimal = Decimal("11"),
) -> IsolatedRestartObservation:
    left_representation = FixtureTensor(left)
    right_representation = FixtureTensor(right)
    return IsolatedRestartObservation(
        challenge_fingerprint=challenge.fingerprint,
        raw_score=score,
        left_representation_hash=_representation_hash(left_representation),
        right_representation_hash=_representation_hash(right_representation),
        process_id=os.getpid() + 1,
        parent_process_id=os.getpid(),
        network_isolation_method="windows_firewall_block",
        isolation_attestation_bytes=b"synthetic signed firewall audit",
    )


class FixtureIntegration:
    def __init__(
        self,
        *,
        score_value=None,
        metadata=None,
        runtime_metadata=None,
        write_path: Path | None = None,
    ) -> None:
        self.score_value = score_value
        self.metadata = (
            metadata
            if metadata is not None
            else {
                "representation_profile_fingerprint": (
                    REPRESENTATION_PROFILE.fingerprint
                ),
                "score_profile_fingerprint": SCORE_PROFILE.fingerprint,
            }
        )
        self.runtime_metadata = runtime_metadata or {
            "runtime_kind": "CPU",
            "runtime_version": "fixture-runtime-1",
            "driver_version": None,
            "device_class": "test-cpu",
        }
        self.write_path = write_path
        self.offline_environment_seen = (
            os.environ.get("HF_HUB_OFFLINE") == "1"
            and os.environ.get("TRANSFORMERS_OFFLINE") == "1"
        )

    def load_runtime(self) -> None:
        return None

    def validate_runtime(self):
        return self.runtime_metadata

    def describe_operation(self):
        return self.metadata

    def preprocess(self, image_bytes: bytes):
        return tuple(image_bytes)

    def extract(self, model_input):
        if self.write_path is not None:
            self.write_path.write_bytes(b"persisted-representation")
        return FixtureTensor(model_input)

    def compare(self, left, right):
        if self.score_value is not None:
            return self.score_value
        return sum(Decimal(a) * Decimal(b) for a, b in zip(left, right))


def _run(
    tmp_path: Path,
    *,
    factory=None,
    restart_score: Decimal = Decimal("11"),
    tolerance: Decimal = Decimal("0"),
    representation_profile=REPRESENTATION_PROFILE,
    restart_callback=None,
    batch_callback=None,
):
    manifest = _fixture_manifest(tmp_path)
    instances: list[FixtureIntegration] = []

    def default_factory():
        instance = FixtureIntegration(
            metadata={
                "representation_profile_fingerprint": (
                    representation_profile.fingerprint
                ),
                "score_profile_fingerprint": SCORE_PROFILE.fingerprint,
            }
        )
        instances.append(instance)
        return instance

    result = run_smoke_qualification(
        integration_factory=factory or default_factory,
        artifact_manifest=manifest,
        artifact_root=tmp_path,
        representation_profile=representation_profile,
        score_profile=SCORE_PROFILE,
        left_image_bytes=b"\x01\x02",
        right_image_bytes=b"\x03\x04",
        runtime_kind="CPU",
        runtime_version="fixture-runtime-1",
        driver_version=None,
        device_class="test-cpu",
        max_projected_12000_extractions_seconds=Decimal("100000"),
        max_projected_6000_comparisons_seconds=Decimal("100000"),
        max_peak_ram_bytes=100_000_000,
        max_peak_vram_bytes=0,
        max_artifact_disk_bytes=1024,
        inspected_utc="2026-08-04T12:00:00+00:00",
        restart_probe=(
            restart_callback
            or (
                lambda challenge, left, right: _isolated_restart(
                    challenge, left, right, score=restart_score
                )
            )
        ),
        batch_probe=(
            batch_callback
            or (
                lambda integration, model_inputs: [
                    integration.extract(model_input)
                    for model_input in model_inputs
                ]
            )
        ),
        watched_roots=(tmp_path,),
        numeric_tolerance=tolerance,
    )
    return result, instances


def test_fixture_probe_is_offline_independent_and_publishes_only_hashes(
    tmp_path: Path,
) -> None:
    result, instances = _run(tmp_path)

    assert instances[0].offline_environment_seen
    assert result.extraction_calls == 4
    assert result.comparison_calls == 3
    assert result.determinism_report.bitwise_equal
    assert result.determinism_report.decision_safe
    assert result.process_restart_isolated
    assert result.offline_execution_proven
    assert result.no_representation_persistence
    assert len(result.left_score_hash) == 64
    assert not hasattr(result, "left_score")


def test_factory_and_callbacks_cannot_open_a_network_connection(
    tmp_path: Path,
) -> None:
    def downloading_factory():
        socket.create_connection(("127.0.0.1", 9))
        raise AssertionError("network guard did not stop the constructor")

    tracing_before = tracemalloc.is_tracing()
    with pytest.raises(NetworkAccessBlocked):
        _run(tmp_path, factory=downloading_factory)
    assert tracemalloc.is_tracing() is tracing_before


def test_an_os_isolated_child_attestation_opens_the_positive_probe_path(
    tmp_path: Path,
) -> None:
    result, _instances = _run(tmp_path)

    assert result.process_restart_isolated
    assert result.offline_execution_proven
    assert result.isolation_evidence_fingerprint is not None


@pytest.mark.parametrize("score", [True, 1.5, Decimal("NaN"), Decimal("Infinity")])
def test_boolean_float_and_nonfinite_scores_are_rejected(
    tmp_path: Path, score
) -> None:
    with pytest.raises(QualificationError, match=r"compare\(\)"):
        _run(tmp_path, factory=lambda: FixtureIntegration(score_value=score))


def test_persistent_representation_write_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "representation.bin"
    with pytest.raises(QualificationError, match="persistent representation"):
        _run(
            tmp_path,
            factory=lambda: FixtureIntegration(write_path=target),
        )


def test_numeric_drift_is_recorded_against_the_predeclared_tolerance(
    tmp_path: Path,
) -> None:
    accepted, _ = _run(
        tmp_path,
        restart_score=Decimal("11.01"),
        tolerance=Decimal("0.02"),
    )
    assert not accepted.determinism_report.bitwise_equal
    assert accepted.determinism_report.maximum_observed_score_drift == "0.01"
    assert accepted.determinism_report.within_predeclared_tolerance
    assert accepted.determinism_report.decision_safe is False

    rejected, _ = _run(
        tmp_path,
        restart_score=Decimal("11.01"),
        tolerance=Decimal("0.001"),
    )
    assert rejected.determinism_report.within_predeclared_tolerance is False
    assert rejected.determinism_report.decision_safe is False


def test_numeric_equality_is_not_misreported_as_bitwise_score_equality(
    tmp_path: Path,
) -> None:
    result, _ = _run(
        tmp_path,
        restart_score=Decimal("11.0"),
        tolerance=Decimal("0"),
    )

    assert result.determinism_report.maximum_observed_score_drift == "0"
    assert result.determinism_report.within_predeclared_tolerance
    assert not result.determinism_report.bitwise_equal
    assert not result.determinism_report.decision_safe
    assert result.left_score_hash != result.restarted_score_hash


def test_representation_shape_must_match_the_frozen_profile(
    tmp_path: Path,
) -> None:
    branch = rebuild(
        REPRESENTATION_PROFILE.branches[0],
        shape=(256,),
    )
    mismatched = rebuild(
        REPRESENTATION_PROFILE,
        representation_shape=(256,),
        branches=(branch,),
    )

    with pytest.raises(QualificationError, match="representation shape"):
        _run(tmp_path, representation_profile=mismatched)


def test_batch_probe_is_bound_to_observed_batch_outputs(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        batch_callback=lambda _integration, _inputs: (
            FixtureTensor(b"different"),
            FixtureTensor(b"outputs"),
        ),
    )

    assert not result.determinism_report.single_image_vs_batch_equal
    assert not result.determinism_report.within_predeclared_tolerance


def test_restart_probe_must_answer_the_fresh_child_challenge(
    tmp_path: Path,
) -> None:
    with pytest.raises(QualificationError, match="isolated child-process"):
        _run(
            tmp_path,
            restart_callback=lambda _challenge, _left, _right: Decimal("11"),
        )


def test_operational_feasibility_is_derived_from_predeclared_resource_limits(
    tmp_path: Path,
) -> None:
    manifest = _fixture_manifest(tmp_path)
    result = run_smoke_qualification(
        integration_factory=FixtureIntegration,
        artifact_manifest=manifest,
        artifact_root=tmp_path,
        representation_profile=REPRESENTATION_PROFILE,
        score_profile=SCORE_PROFILE,
        left_image_bytes=b"\x01\x02",
        right_image_bytes=b"\x03\x04",
        runtime_kind="CPU",
        runtime_version="fixture-runtime-1",
        driver_version=None,
        device_class="test-cpu",
        max_projected_12000_extractions_seconds=Decimal("0"),
        max_projected_6000_comparisons_seconds=Decimal("0"),
        max_peak_ram_bytes=0,
        max_peak_vram_bytes=0,
        max_artifact_disk_bytes=122,
        inspected_utc="2026-08-04T12:00:00+00:00",
        restart_probe=_isolated_restart,
        batch_probe=lambda integration, model_inputs: [
            integration.extract(model_input) for model_input in model_inputs
        ],
        watched_roots=(tmp_path,),
    )

    assert result.determinism_report.decision_safe
    assert result.operational_report.operationally_feasible is False


@pytest.mark.parametrize(
    "runtime_metadata",
    (
        {
            "runtime_kind": "CUDA",
            "runtime_version": "fixture-runtime-1",
            "driver_version": None,
            "device_class": "test-cpu",
        },
        {
            "runtime_kind": "CPU",
            "runtime_version": "different-runtime",
            "driver_version": None,
            "device_class": "test-cpu",
        },
        {
            "runtime_kind": "CPU",
            "runtime_version": "fixture-runtime-1",
            "driver_version": None,
            "device_class": "test-cpu",
            "unbound_gpu_backend": "cuda",
        },
    ),
)
def test_loaded_runtime_must_exactly_match_the_predeclared_runtime(
    tmp_path: Path,
    runtime_metadata,
) -> None:
    with pytest.raises(QualificationError, match="validate_runtime"):
        _run(
            tmp_path,
            factory=lambda: FixtureIntegration(
                runtime_metadata=runtime_metadata
            ),
        )


def test_nested_label_or_threshold_metadata_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(QualificationError, match="forbidden threshold"):
        _run(
            tmp_path,
            factory=lambda: FixtureIntegration(
                metadata={"nested": {"threshold": "hidden"}}
            ),
        )


def test_probe_refuses_vacuous_persistence_observation(tmp_path: Path) -> None:
    manifest = _fixture_manifest(tmp_path)
    with pytest.raises(QualificationError, match="persistence root"):
        run_smoke_qualification(
            integration_factory=FixtureIntegration,
            artifact_manifest=manifest,
            artifact_root=tmp_path,
            representation_profile=REPRESENTATION_PROFILE,
            score_profile=SCORE_PROFILE,
            left_image_bytes=b"left",
            right_image_bytes=b"right",
            runtime_kind="CPU",
            runtime_version="fixture-runtime-1",
            driver_version=None,
            device_class="test-cpu",
            max_projected_12000_extractions_seconds=Decimal("1"),
            max_projected_6000_comparisons_seconds=Decimal("1"),
            max_peak_ram_bytes=1,
            max_peak_vram_bytes=0,
            max_artifact_disk_bytes=1,
            inspected_utc="2026-08-04T12:00:00+00:00",
            restart_probe=_isolated_restart,
            batch_probe=lambda integration, model_inputs: [
                integration.extract(model_input) for model_input in model_inputs
            ],
            watched_roots=(),
        )
