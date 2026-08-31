from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.core.enums import (
    ChecksumStatus,
    EnvironmentStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    EnvironmentReport,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
    descriptor_fingerprint,
    environment_fingerprint,
)
from fpbench.core.identifiers import ImageId
from fpbench.core.serialization import stable_hash
from fpbench.stage21b.adapters import FailureDisposition
from fpbench.stage21b.models import (
    FrozenRunSpec,
    PlannedPair,
    PreparationReference,
    ordered_pair_plan_fingerprint,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_pairs(count: int, *, variant_at: int | None = None) -> tuple[PlannedPair, ...]:
    pairs: list[PlannedPair] = []
    for ordinal in range(count):
        release = ("SD300A", "SD300B", "SD300C")[ordinal % 3]
        pair_id = f"pair_{ordinal:04d}"
        if variant_at == ordinal:
            pair_id = f"pair_variant_{ordinal:04d}"
        left = f"left_{ordinal:04d}"
        right = f"right_{ordinal:04d}"
        pairs.append(
            PlannedPair(
                ordinal=ordinal,
                pair_id=pair_id,
                release=release,
                left_image_id=left,
                right_image_id=right,
                ground_truth="NON_MATED",
                left_preparation=make_reference(left),
                right_preparation=make_reference(right),
            )
        )
    return tuple(pairs)


def make_reference(image_id: str) -> PreparationReference:
    return PreparationReference(
        preparation_set_id="prepset_test_v1",
        preparation_set_fingerprint=digest("prep-set"),
        preparation_profile_id="canonical_test_500ppi_v1",
        preparation_profile_fingerprint=digest("prep-profile"),
        preparation_entry_hash=digest(f"entry:{image_id}"),
        encoded_sha256=digest(f"encoded:{image_id}"),
        pixel_sha256=digest(f"pixels:{image_id}"),
        width=16,
        height=20,
        effective_ppi=500,
    )


class SyntheticPreparedInputs:
    def __init__(self, root: Path, pairs: Iterable[PlannedPair]) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.images: dict[str, PreparedImage] = {}
        for pair in pairs:
            for image_id, reference in (
                (pair.left_image_id, pair.left_preparation),
                (pair.right_image_id, pair.right_preparation),
            ):
                if image_id in self.images:
                    continue
                path = self.root / f"{image_id}.bin"
                payload = f"synthetic:{image_id}".encode("utf-8")
                path.write_bytes(payload)
                self.images[image_id] = PreparedImage(
                    image_id=ImageId(image_id),
                    local_path=path.resolve(),
                    effective_ppi=500,
                    media_type="application/octet-stream",
                    expected_sha256=digest(f"source:{image_id}"),
                    checksum_status=ChecksumStatus.VERIFIED,
                    preparation_profile_id=reference.preparation_profile_id,
                    preparation_hash=reference.preparation_entry_hash,
                    source_effective_ppi=1000,
                    prepared_sha256=reference.encoded_sha256,
                    prepared_size_bytes=len(payload),
                    preparation_set_id=reference.preparation_set_id,
                    preparation_set_fingerprint=reference.preparation_set_fingerprint,
                    preparation_entry_hash=reference.preparation_entry_hash,
                    pixel_sha256=reference.pixel_sha256,
                    pixel_width=reference.width,
                    pixel_height=reference.height,
                )

    def resolve_pair(self, pair: PlannedPair) -> tuple[PreparedImage, PreparedImage]:
        left = self.images[pair.left_image_id]
        right = self.images[pair.right_image_id]
        if left.preparation_entry_hash != pair.left_preparation.preparation_entry_hash:
            raise ValueError("wrong left preparation hash")
        if right.preparation_entry_hash != pair.right_preparation.preparation_entry_hash:
            raise ValueError("wrong right preparation hash")
        return left, right


class ScriptedAdapter(FingerprintAlgorithmAdapter):
    def __init__(
        self,
        algorithm_id: str,
        *,
        outcomes: list[float | str] | None = None,
        failure_every: int | None = None,
        interrupt_at: int | None = None,
    ) -> None:
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=algorithm_id,
            display_name=algorithm_id,
            adapter_id=f"adapter_{algorithm_id}",
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version="synthetic-v1",
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
        )
        self.outcomes = list(outcomes or [])
        self.failure_every = failure_every
        self.interrupt_at = interrupt_at
        self.interrupted = False
        self.calls = 0
        self.seen_image_ids: list[tuple[str, str]] = []

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version="synthetic-v1",
            runtime={"synthetic": "1"},
            dependencies={},
        )

    def compare(self, left, right, context) -> RawMatchResult:
        index = self.calls
        self.calls += 1
        self.seen_image_ids.append((str(left.image_id), str(right.image_id)))
        if self.interrupt_at == index and not self.interrupted:
            self.interrupted = True
            raise RuntimeError("synthetic host interruption")
        scripted: float | str
        if index < len(self.outcomes):
            scripted = self.outcomes[index]
        elif self.failure_every and index % self.failure_every == 0:
            scripted = "failure"
        else:
            scripted = float(index) - 10.5
        if scripted == "failure":
            return RawMatchResult.failed(
                failure=FailureInfo(
                    code=FailureCode.TEMPLATE_EXTRACTION_FAILED,
                    stage=FailureStage.EXTRACTION,
                    message="synthetic template refusal",
                    retryable=False,
                    details={"synthetic": "true"},
                ),
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
            )
        if scripted == "infrastructure":
            return RawMatchResult.failed(
                failure=FailureInfo(
                    code=FailureCode.INTERNAL_ERROR,
                    stage=FailureStage.ENVIRONMENT,
                    message="synthetic runtime outage",
                ),
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
            )
        return RawMatchResult.success(
            raw_score=float(scripted),
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            timing_components_ms={"synthetic_adapter": 0.01},
            metadata={"synthetic": "true"},
        )


def make_spec(
    adapter: ScriptedAdapter,
    pairs: tuple[PlannedPair, ...],
    *,
    created_utc: str = "2026-01-01T00:00:00+00:00",
    pair_manifest_hash: str | None = None,
) -> FrozenRunSpec:
    environment = adapter.validate_environment()
    pair_ids_hash = stable_hash([pair.pair_id for pair in pairs], length=64)
    runtime_fingerprint = digest(f"runtime:{adapter.descriptor.algorithm_id}")
    return FrozenRunSpec.create(
        created_utc=created_utc,
        stage21a_finalization_fingerprint=digest("stage21a-final"),
        stage21a_source_fingerprint=digest("stage21a-source"),
        high_resolution_reservation_fingerprint=digest("reservation"),
        roster_id="synthetic_roster_v1",
        roster_fingerprint=digest("roster"),
        algorithm_id=adapter.descriptor.algorithm_id,
        adapter_id=adapter.descriptor.adapter_id,
        integration_id=None,
        implementation_version=adapter.descriptor.implementation_version,
        adapter_descriptor_fingerprint=descriptor_fingerprint(adapter.descriptor),
        runtime_identity_fingerprint=runtime_fingerprint,
        runtime_binding={
            "environment_fingerprint": environment_fingerprint(environment),
            "assets": [{"role": "synthetic", "sha256": digest("asset"), "size_bytes": 1}],
        },
        predecessor_finalization_fingerprint=digest("predecessor"),
        score_direction=adapter.descriptor.score_direction.value,
        protocol_id="synthetic_cross_subject_v1",
        protocol_config_sha256=digest("protocol-config"),
        pair_manifest_hash=pair_manifest_hash or digest("pair-manifest"),
        pair_ids_sha256=pair_ids_hash,
        planned_pair_input_fingerprint=ordered_pair_plan_fingerprint(pairs),
        pair_count=len(pairs),
        preparation_set_id=pairs[0].left_preparation.preparation_set_id,
        preparation_set_fingerprint=pairs[0].left_preparation.preparation_set_fingerprint,
        preparation_profile_id=pairs[0].left_preparation.preparation_profile_id,
        preparation_profile_fingerprint=pairs[0].left_preparation.preparation_profile_fingerprint,
        execution_source_fingerprint=digest(f"source:{adapter.descriptor.algorithm_id}"),
        execution_source_revision="synthetic-revision",
        algorithm_execution_config_sha256=digest("algorithm-config"),
        private_adapter_config_sha256=digest("private-adapter-config"),
        expected_attempts=len(pairs),
        timeout_seconds=10.0,
        concurrency=1,
        execution_strategy="sequential_single_worker",
        metrics_allowed=False,
        calibration_allowed=False,
        threshold_allowed=False,
        score_transform_allowed=False,
        orchestrator_algorithm_retries=0,
        infrastructure_resume_allowed=True,
    )


def algorithm_failure_classifier(_failure: Any) -> FailureDisposition:
    return FailureDisposition.ALGORITHM


def split_classifier(failure: Any) -> FailureDisposition:
    return (
        FailureDisposition.INFRASTRUCTURE
        if failure.code is FailureCode.INTERNAL_ERROR
        else FailureDisposition.ALGORITHM
    )
