"""The adapter: image bytes in, a representation or a score out.

This is the whole public surface of the flx route.  It implements the six
operations Stage 8A froze as ``LearnedFingerprintIntegration`` and knows
nothing else.  In particular it has no idea what a pair is, which subject an
image belongs to, which release it came from, whether the pair is mated, what
decision anyone expects, what threshold exists, or what SourceAFIS and NBIS
said.  Those are not fields it hides; they are fields it never receives.

Everything expensive happens in another process.  Nothing derived from an image
survives a call: no preprocessed tensor, no representation, no score, and no
map from an image digest to any of them (spec section 13).
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.flx_errors import FlxError, FlxRuntimeError
from fpbench.core.flx_models import STAGE8B_SCHEMA_VERSION, FlxAdapterProfile
from fpbench.flx import identity
from fpbench.flx.artifacts import FlxRuntimeBundle, verify_bundle_artifacts
from fpbench.flx.lock import RuntimeLock, load_runtime_lock
from fpbench.flx.policy import load_runtime_policy
from fpbench.flx.preprocessing import build_preprocessing_profile
from fpbench.flx.representation import (
    FlxRepresentation,
    ModelInput,
    build_representation_profile,
)
from fpbench.flx.runtime import build_runtime_manifest
from fpbench.flx.score import build_score_profile, score_from_worker
from fpbench.flx.worker import FlxWorkerSession

__all__ = [
    "FORBIDDEN_INPUTS",
    "FlxLearnedFingerprintIntegration",
    "build_adapter_profile",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOCK = REPOSITORY_ROOT / "configs" / "flx" / "flx_runtime_lock_v1.txt"
DEFAULT_POLICY = REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"

#: Named so the exclusion is auditable rather than merely true today.
FORBIDDEN_INPUTS = (
    "subject_id",
    "finger_position",
    "release",
    "pair_kind",
    "mated",
    "expected_decision",
    "threshold",
    "sourceafis_result",
    "nbis_result",
)


def build_adapter_profile() -> FlxAdapterProfile:
    return FlxAdapterProfile.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        adapter_id=identity.ADAPTER_ID,
        adapter_version=identity.ADAPTER_VERSION,
        algorithm_id=identity.ALGORITHM_ID,
        process_model=(
            "one isolated worker process per adapter, with a deadline on every "
            "operation and no automatic retry"
        ),
        protocol="one JSON request per line on stdin, one JSON response per line on stdout",
        operations=(
            "load_runtime",
            "preprocess",
            "extract",
            "compare",
            "validate_runtime",
            "describe_operation",
        ),
        forbidden_inputs=FORBIDDEN_INPUTS,
        caches_representations=False,
        persists_representations=False,
        retries_failed_operations=False,
        loads_torch_in_parent=False,
        training_only_checkpoint_keys=identity.TRAINING_ONLY_CHECKPOINT_KEYS,
        runtime_profile_id=identity.RUNTIME_PROFILE_ID,
        preprocessing_profile_id=identity.PREPROCESSING_PROFILE_ID,
        representation_profile_id=identity.REPRESENTATION_PROFILE_ID,
        score_profile_id=identity.SCORE_PROFILE_ID,
        score_serialization_profile_id=identity.SCORE_SERIALIZATION_PROFILE_ID,
    )


class FlxLearnedFingerprintIntegration:
    """One flx route, bound to one bundle, one lock and one policy."""

    def __init__(
        self,
        bundle: FlxRuntimeBundle | None = None,
        *,
        lock_path: Path | None = None,
        policy_path: Path | None = None,
    ) -> None:
        self.bundle = bundle or FlxRuntimeBundle.from_environment()
        self.lock: RuntimeLock = load_runtime_lock(lock_path or DEFAULT_LOCK)
        self.policy = load_runtime_policy(policy_path or DEFAULT_POLICY)
        self._session: FlxWorkerSession | None = None
        self._runtime_report: Mapping[str, Any] | None = None
        self._load_result: Mapping[str, Any] | None = None
        #: Counters, not caches.  They exist so SELF independence can be
        #: proved by observation rather than asserted (spec section 14).
        self.preprocess_calls = 0
        self.extract_calls = 0
        self.compare_calls = 0

    # ------------------------------------------------------------- lifecycle

    def load_runtime(self) -> None:
        """Verify the artifacts, start the worker, and load the model once."""
        if self._session is not None:
            raise FlxError("this integration has already loaded its runtime")
        verify_bundle_artifacts(self.bundle)
        session = FlxWorkerSession(
            self.bundle,
            startup_deadline_seconds=float(self.policy.max_worker_startup_seconds),
        )
        session.start()
        try:
            report = session.validate_runtime(
                deadline_seconds=float(self.policy.max_worker_startup_seconds)
            )
            # Judged before the model is loaded: an unlocked runtime should not
            # get as far as touching the weights.
            build_runtime_manifest(report, lock=self.lock, created_utc="1970-01-01T00:00:00+00:00")
            self._load_result = session.load_runtime(
                deadline_seconds=float(self.policy.max_model_load_seconds)
            )
        except Exception:
            session.close()
            raise
        self._session = session
        self._runtime_report = report

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "FlxLearnedFingerprintIntegration":
        self.load_runtime()
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def _require_session(self) -> FlxWorkerSession:
        if self._session is None:
            raise FlxRuntimeError("load_runtime() must succeed before any operation")
        return self._session

    # ------------------------------------------------------------ operations

    def preprocess(self, image_bytes: bytes) -> ModelInput:
        if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
            raise FlxError(
                f"preprocess takes image bytes, not {type(image_bytes).__name__}"
            )
        session = self._require_session()
        self.preprocess_calls += 1
        return session.preprocess(
            bytes(image_bytes),
            deadline_seconds=float(self.policy.preprocess_deadline_seconds),
        )

    def extract(self, model_input: ModelInput) -> FlxRepresentation:
        if not isinstance(model_input, ModelInput):
            raise FlxError(f"extract takes a ModelInput, not {type(model_input).__name__}")
        session = self._require_session()
        self.extract_calls += 1
        return session.extract(
            model_input, deadline_seconds=float(self.policy.extract_deadline_seconds)
        )

    def compare(self, left: FlxRepresentation, right: FlxRepresentation) -> Decimal:
        for name, value in (("left", left), ("right", right)):
            if not isinstance(value, FlxRepresentation):
                raise FlxError(
                    f"compare takes representations; {name} is {type(value).__name__}"
                )
        session = self._require_session()
        self.compare_calls += 1
        payload = session.request(
            "compare",
            deadline_seconds=float(self.policy.compare_deadline_seconds),
            left=left.as_request(),
            right=right.as_request(),
        )["result"]
        return score_from_worker(payload)

    # -------------------------------------------------------------- metadata

    def validate_runtime(self) -> Mapping[str, Any]:
        """Descriptive and verificational only: what is actually running."""
        session = self._require_session()
        report = session.validate_runtime(
            deadline_seconds=float(self.policy.max_worker_startup_seconds)
        )
        manifest = build_runtime_manifest(
            report, lock=self.lock, created_utc="1970-01-01T00:00:00+00:00"
        )
        loaded = dict(self._load_result or {})
        return {
            "runtime_profile_id": identity.RUNTIME_PROFILE_ID,
            "runtime_manifest_fingerprint": manifest.fingerprint,
            "os_version": manifest.os_version,
            "cpu_architecture": manifest.cpu_architecture,
            "python_version": manifest.python_version,
            "torch_version": manifest.torch_version,
            "torchvision_version": manifest.torchvision_version,
            "numpy_version": manifest.numpy_version,
            "blas_implementation": manifest.blas_implementation,
            "mkldnn_version": manifest.mkldnn_version,
            "torch_num_threads": manifest.torch_num_threads,
            "torch_num_interop_threads": manifest.torch_num_interop_threads,
            "device": manifest.device,
            "cuda_available": manifest.cuda_available,
            "dependency_lock_sha256": self.lock.sha256,
            "checkpoint_loaded": bool(loaded.get("loaded", False)),
            "model_in_eval_mode": loaded.get("training_mode") is False,
            "gradients_disabled": loaded.get("gradients_enabled") is False,
            "missing_state_dict_keys": tuple(loaded.get("missing_state_dict_keys", ())),
            "unexpected_state_dict_keys": tuple(loaded.get("unexpected_state_dict_keys", ())),
            "network_attempts": int(
                session.request(
                    "validate_runtime",
                    deadline_seconds=float(self.policy.max_worker_startup_seconds),
                ).get("network_attempts", 0)
            ),
        }

    def describe_operation(self) -> Mapping[str, Any]:
        """Fixed identity metadata.  No threshold, no decision, no dataset."""
        return {
            "algorithm_id": identity.ALGORITHM_ID,
            "adapter_id": identity.ADAPTER_ID,
            "adapter_version": identity.ADAPTER_VERSION,
            "source_commit": identity.SOURCE_COMMIT,
            "checkpoint_sha256": identity.CHECKPOINT_SHA256,
            "runtime_profile_id": identity.RUNTIME_PROFILE_ID,
            "preprocessing_profile_id": identity.PREPROCESSING_PROFILE_ID,
            "representation_profile_id": identity.REPRESENTATION_PROFILE_ID,
            "score_profile_id": identity.SCORE_PROFILE_ID,
            "score_serialization_profile_id": identity.SCORE_SERIALIZATION_PROFILE_ID,
            "implementation_origin": identity.IMPLEMENTATION_ORIGIN,
            "upstream_study": identity.UPSTREAM_STUDY,
            "score_direction": identity.SCORE_DIRECTION,
            "nominal_score_range": [identity.SCORE_MINIMUM, identity.SCORE_MAXIMUM],
            "inference_batch_rule": identity.INFERENCE_BATCH_RULE,
            "inference_batch_rows": identity.INFERENCE_BATCH_ROWS,
            "weights_license_status": identity.WEIGHTS_LICENSE_STATUS,
            "preprocessing_profile_fingerprint": build_preprocessing_profile().fingerprint,
            "representation_profile_fingerprint": build_representation_profile().fingerprint,
            "score_profile_fingerprint": build_score_profile().fingerprint,
            "adapter_profile_fingerprint": build_adapter_profile().fingerprint,
        }


def offline_environment_findings() -> Mapping[str, tuple[str, ...]]:
    """Which network-shaped variables are set in *this* process's environment.

    The worker neutralizes its own copy; this reports what it was handed, so a
    proxy inherited from a developer's shell shows up in the evidence instead
    of being quietly overwritten (spec section 15).
    """
    proxies = tuple(
        name
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
        if os.environ.get(name)
    )
    hubs = tuple(
        name
        for name in ("HF_HOME", "TORCH_HOME", "HUGGINGFACE_HUB_CACHE", "XDG_CACHE_HOME")
        if os.environ.get(name)
    )
    return {"proxy_variables_present": proxies, "model_hub_variables_present": hubs}
