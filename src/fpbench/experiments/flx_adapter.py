"""The flx route, wrapped in the contract every algorithm is wrapped in.

It lives here rather than under ``fpbench.adapters`` or inside ``fpbench.flx``,
and both halves of that are forced.

An adapter may import ``fpbench.core`` and other adapters and nothing else, so
that no adapter can ever reach the pair manifest (docs/adr/0001).  This module
has to drive :mod:`fpbench.flx`, so it cannot be one.

``fpbench.flx`` is Stage 8B's published verifier authority: its evidence
verification runs ``git diff`` over that directory against the commit the
qualification was published from, so a file added there would break the
committed Stage 8B chain permanently rather than transiently.  Stage 8C does not
edit a finished stage's authority to make room for itself.

What is left is ``fpbench.experiments``, which is where every other
algorithm-to-benchmark seam already lives.

The whole adapter is one method with five operations in it:

    left bytes  -> preprocess -> extract -> left representation
    right bytes -> preprocess -> extract -> right representation
    left representation + right representation -> compare -> raw score

Everything else here exists to make that sequence honest.

**Both sides are always independent.** A SELF pair points at one PNG, and it is
still read twice, preprocessed twice and extracted twice. There is no cache by
image id, by content digest, by pair id or by anything else, no representation
survives the call that produced it, and no handle to a tensor is kept. Skipping
the second side for SELF would make it the one pair kind that takes a different
code path, which is exactly the path a bug hides in (spec section 9).

**The 299x299 tensor is a model input, not an artefact.** It is built inside the
worker, crosses back only so that extraction can be a separate operation, and is
never written to the workspace, never given a manifest and never shared between
comparisons (spec section 7).

**A runtime that moved is not a comparison failure.** An artifact digest that no
longer matches, a lock that no longer describes what is installed, or a worker
that reached the network are all re-raised as ``RuntimeDriftError`` and stored
nowhere. A timeout, a PNG the transform rejects, an extraction that fails its
own invariants and a comparison that produces no usable score are recorded
outcomes with no score (docs/adr/0018, spec section 16).
"""

from __future__ import annotations

import atexit
import hashlib
from decimal import Decimal
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Mapping

from dataclasses import dataclass

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.core.enums import EnvironmentStatus, FailureStage, ScoreDirection
from fpbench.core.errors import RuntimeDriftError
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
)
from fpbench.core.flx_errors import FlxError
from fpbench.flx import identity
from fpbench.flx.artifacts import FlxRuntimeBundle
from fpbench.experiments.flx_failure_mapping import classify, raise_if_blocking
from fpbench.flx.integration import FlxLearnedFingerprintIntegration, build_adapter_profile
from fpbench.flx.preprocessing import build_preprocessing_profile
from fpbench.flx.representation import build_representation_profile
from fpbench.flx.score import build_score_profile, canonical_decimal_text

__all__ = [
    "ADAPTER_ID",
    "FlxAdapter",
    "FlxConfig",
    "RAW_SCORE_DECIMAL_METADATA_KEY",
    "WORKER_SCRIPT_ROLE",
    "RUNTIME_LOCK_ROLE",
    "RUNTIME_POLICY_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
]

ADAPTER_ID = identity.ADAPTER_ID

WORKER_SCRIPT_ROLE = "flx_worker_script"
RUNTIME_LOCK_ROLE = "flx_runtime_lock"
RUNTIME_POLICY_ROLE = "flx_runtime_policy"
RUNTIME_ASSET_ROLES = (WORKER_SCRIPT_ROLE, RUNTIME_LOCK_ROLE, RUNTIME_POLICY_ROLE)
PRIMARY_RUNTIME_ASSET_ROLE = WORKER_SCRIPT_ROLE

#: Where the canonical 17-significant-digit text of the score is stored beside
#: the IEEE double the general schema holds. Seventeen digits always recovers a
#: double exactly, so the two are the same number and nothing is truncated; the
#: validator proves they agree for every stored success (docs/adr/0077).
RAW_SCORE_DECIMAL_METADATA_KEY = "flx.raw_score_decimal"

_MAX_MESSAGE_CHARS = 400
_NS_PER_MS = 1_000_000


@dataclass(frozen=True, slots=True)
class FlxConfig:
    """One flx route, fully addressed.

    The bundle root is a fact about a machine — 2.06 GB of virtual environment,
    extracted source and checkpoint that cannot live in a repository — so it
    arrives explicitly and is never searched for. The lock and the policy are
    paths because a run drives the *pinned* copies of them, not the
    repository's.

    ``research_mode`` changes nothing about what is computed. It says the caller
    intends the results to be citable, and it is recorded so that a stored
    result can be told apart from a development one.
    """

    bundle_root: Path
    worker_script: Path
    runtime_lock: Path
    runtime_policy: Path
    research_mode: bool = False

    def __post_init__(self) -> None:
        for name in ("bundle_root", "worker_script", "runtime_lock", "runtime_policy"):
            path = Path(getattr(self, name))
            if not path.is_absolute():
                raise FlxError(
                    f"{name} must be an absolute path; a relative one means "
                    "whatever directory the caller happened to be in"
                )
            object.__setattr__(self, name, path)

    @property
    def bundle(self) -> FlxRuntimeBundle:
        return FlxRuntimeBundle(self.bundle_root)

    def runtime_assets(self) -> dict[str, Path]:
        """The three files a runtime bundle pins, by role.

        The source archive and the 875 MB checkpoint are deliberately absent.
        They are pinned by frozen digest in :mod:`fpbench.flx.identity` and
        re-hashed in full before every model load; copying licence-unresolved
        weights into a workspace would be a redistribution nobody has
        established permission for (docs/adr/0077, docs/adr/0068).
        """
        return {
            WORKER_SCRIPT_ROLE: self.worker_script,
            RUNTIME_LOCK_ROLE: self.runtime_lock,
            RUNTIME_POLICY_ROLE: self.runtime_policy,
        }


class FlxAdapter(FingerprintAlgorithmAdapter):
    """One flx route, driving one isolated worker at a time."""

    def __init__(self, config: FlxConfig) -> None:
        self._config = config
        self._integration: FlxLearnedFingerprintIntegration | None = None
        self._descriptor: AlgorithmDescriptor | None = None
        # A worker holds 1.2 GB and its own process group. Nothing in the engine
        # calls close(), so the interpreter exiting has to be enough.
        atexit.register(self._release_quietly)

    # ------------------------------------------------------------- identity

    @property
    def config(self) -> FlxConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        """Identity and versions, stable for the lifetime of the adapter.

        The four Stage 8B profile fingerprints are in ``metadata`` and therefore
        inside ``descriptor_fingerprint``. A run is attributed to the transform,
        the representation and the comparator it actually used, so a profile
        that moved makes the run refuse to resume rather than quietly meaning
        something else (docs/adr/0077).
        """
        if self._descriptor is None:
            self._descriptor = AlgorithmDescriptor(
                algorithm_id=identity.ALGORITHM_ID,
                display_name="flx DeepPrint TexMinu 512 (without localization)",
                adapter_id=identity.ADAPTER_ID,
                adapter_version=str(identity.ADAPTER_VERSION),
                adapter_contract_version=ADAPTER_CONTRACT_VERSION,
                # What is executed is one pinned upstream commit, so that commit
                # is the implementation version. A release number would be a
                # claim upstream never made (docs/adr/0069).
                implementation_version=identity.SOURCE_COMMIT,
                # "higher_is_more_similar" on the flx scale is the general
                # taxonomy's "higher_is_better". The two names describe the same
                # ordering; a threshold still needs a stage that has one.
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                deterministic=True,
                capabilities=("extract_then_match", "learned_representation"),
                metadata={
                    "runtime_profile_id": identity.RUNTIME_PROFILE_ID,
                    "preprocessing_profile_id": identity.PREPROCESSING_PROFILE_ID,
                    "representation_profile_id": identity.REPRESENTATION_PROFILE_ID,
                    "score_profile_id": identity.SCORE_PROFILE_ID,
                    "score_serialization_profile_id": (
                        identity.SCORE_SERIALIZATION_PROFILE_ID
                    ),
                    "preprocessing_profile_fingerprint": (
                        build_preprocessing_profile().fingerprint
                    ),
                    "representation_profile_fingerprint": (
                        build_representation_profile().fingerprint
                    ),
                    "score_profile_fingerprint": build_score_profile().fingerprint,
                    "adapter_profile_fingerprint": build_adapter_profile().fingerprint,
                    "source_commit": identity.SOURCE_COMMIT,
                    "source_archive_sha256": identity.SOURCE_ARCHIVE_SHA256,
                    "checkpoint_sha256": identity.CHECKPOINT_SHA256,
                    "inference_batch_rows": str(identity.INFERENCE_BATCH_ROWS),
                    "inference_batch_rule": identity.INFERENCE_BATCH_RULE,
                    "represented_row": str(identity.REPRESENTED_ROW),
                    "implementation_origin": identity.IMPLEMENTATION_ORIGIN,
                    "weights_license_status": identity.WEIGHTS_LICENSE_STATUS,
                },
            )
        return self._descriptor

    # ------------------------------------------------------------ lifecycle

    def _open(self) -> FlxLearnedFingerprintIntegration:
        """Start the worker and load the model once, or reuse the open one."""
        if self._integration is None:
            integration = FlxLearnedFingerprintIntegration(
                self._config.bundle,
                lock_path=self._config.runtime_lock,
                policy_path=self._config.runtime_policy,
            )
            integration.load_runtime()
            self._integration = integration
        return self._integration

    def close(self) -> None:
        """End the worker, and prove it ended.

        Cleanup failure is a blocking failure: a worker that outlives its run
        holds the checkpoint, the memory and a pipe nobody is reading, and the
        next run would be measuring a machine that is still busy
        (spec section 16.2).
        """
        integration = self._integration
        self._integration = None
        atexit.unregister(self._release_quietly)
        if integration is None:
            return
        try:
            integration.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not be silent
            raise RuntimeDriftError(
                f"the flx worker could not be shut down cleanly: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _release_quietly(self) -> None:  # pragma: no cover - interpreter teardown
        """Last-resort cleanup. Never raises: there is nobody left to tell."""
        integration = self._integration
        self._integration = None
        if integration is not None:
            try:
                integration.close()
            except Exception:
                pass

    def __enter__(self) -> "FlxAdapter":
        self._open()
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Prove the pinned runtime is present, intact and loadable.

        Loads the checkpoint. That is the point: a truncated 875 MB file, a
        torch that no longer matches the lock or a model that will not populate
        its state dict must be one fault of the run rather than 6,000 identical
        per-pair failures.

        The session opened here is closed again unless one was already open, so
        that preflight never leaves a second 1.2 GB worker alongside the one
        execution is about to start.
        """
        already_open = self._integration is not None
        try:
            integration = self._open()
            report = integration.validate_runtime()
        except FlxError as exc:
            self._safe_close(already_open)
            return EnvironmentReport(
                status=EnvironmentStatus.UNAVAILABLE,
                implementation_version=identity.SOURCE_COMMIT,
                message=_sanitise(f"{type(exc).__name__}: {exc}"),
            )
        except OSError as exc:
            self._safe_close(already_open)
            return EnvironmentReport(
                status=EnvironmentStatus.UNAVAILABLE,
                implementation_version=identity.SOURCE_COMMIT,
                message=_sanitise(f"the pinned flx runtime is not usable: {exc}"),
            )

        loaded = bool(report.get("checkpoint_loaded"))
        eval_mode = bool(report.get("model_in_eval_mode"))
        gradients_off = bool(report.get("gradients_disabled"))
        unexpected = tuple(report.get("unexpected_state_dict_keys") or ())
        missing = tuple(report.get("missing_state_dict_keys") or ())
        ready = loaded and eval_mode and gradients_off and not unexpected and not missing

        environment = EnvironmentReport(
            status=EnvironmentStatus.READY if ready else EnvironmentStatus.UNAVAILABLE,
            implementation_version=identity.SOURCE_COMMIT,
            runtime=self._runtime_facts(report),
            dependencies=self._dependency_facts(report),
            message=(
                None
                if ready
                else (
                    "the checkpoint did not load into the identified variant: "
                    f"loaded={loaded} eval={eval_mode} no_grad={gradients_off} "
                    f"missing={len(missing)} unexpected={len(unexpected)}"
                )
            ),
        )
        self._safe_close(already_open)
        return environment

    def _safe_close(self, already_open: bool) -> None:
        if not already_open:
            self.close()

    def _runtime_facts(self, report: Mapping[str, Any]) -> dict[str, str]:
        """Facts that must not change between preparing a run and executing it.

        Everything here is stable on one machine and moves when the machine
        does, which is what the engine's environment fingerprint is for. Nothing
        volatile — no timestamp, no process id, no path.
        """
        return {
            "flx.runtime_profile_id": str(report["runtime_profile_id"]),
            "flx.runtime_manifest_fingerprint": str(
                report["runtime_manifest_fingerprint"]
            ),
            "flx.os_version": str(report["os_version"]),
            "flx.cpu_architecture": str(report["cpu_architecture"]),
            "flx.python_version": str(report["python_version"]),
            "flx.device": str(report["device"]),
            "flx.cuda_available": str(bool(report["cuda_available"])).lower(),
            "flx.torch_num_threads": str(int(report["torch_num_threads"])),
            "flx.torch_num_interop_threads": str(
                int(report["torch_num_interop_threads"])
            ),
            "flx.network_attempts": str(int(report.get("network_attempts", 0))),
            "flx.inference_batch_rows": str(identity.INFERENCE_BATCH_ROWS),
            "flx.inference_batch_rule": identity.INFERENCE_BATCH_RULE,
            "flx.represented_row": str(identity.REPRESENTED_ROW),
            "flx.research_mode": str(self._config.research_mode).lower(),
        }

    def _dependency_facts(self, report: Mapping[str, Any]) -> dict[str, str]:
        return {
            "flx.torch_version": str(report["torch_version"]),
            "flx.torchvision_version": str(report["torchvision_version"]),
            "flx.numpy_version": str(report["numpy_version"]),
            "flx.blas_implementation": str(report["blas_implementation"]),
            "flx.mkldnn_version": str(report["mkldnn_version"]),
            "flx.dependency_lock_sha256": str(report["dependency_lock_sha256"]),
            "flx.source_archive_sha256": identity.SOURCE_ARCHIVE_SHA256,
            "flx.checkpoint_sha256": identity.CHECKPOINT_SHA256,
            "flx.checkpoint_size_bytes": str(identity.CHECKPOINT_SIZE_BYTES),
            "flx.preprocessing_profile_fingerprint": (
                build_preprocessing_profile().fingerprint
            ),
            "flx.representation_profile_fingerprint": (
                build_representation_profile().fingerprint
            ),
            "flx.score_profile_fingerprint": build_score_profile().fingerprint,
            "flx.adapter_profile_fingerprint": build_adapter_profile().fingerprint,
        }

    # ------------------------------------------------------------- compare

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Two independent sides, one comparison, one raw score or one failure."""
        direction = self.descriptor.score_direction
        timings: dict[str, float] = {}
        stage = FailureStage.ADAPTER
        left_input = right_input = None
        left_representation = right_representation = None
        try:
            integration = self._open()
            before = (
                integration.preprocess_calls,
                integration.extract_calls,
                integration.compare_calls,
            )

            stage = FailureStage.INPUT
            left_bytes = _read_prepared(left)
            stage = FailureStage.PREPARATION
            left_input = _timed(timings, "left_preprocess_ms", integration.preprocess, left_bytes)
            del left_bytes
            stage = FailureStage.EXTRACTION
            left_representation = _timed(
                timings, "left_extract_ms", integration.extract, left_input
            )
            left_input = None

            # The second side starts from the file again. Even when `right` is
            # the same PNG as `left`, nothing computed above is reused: no
            # bytes, no tensor, no representation (spec section 9).
            stage = FailureStage.INPUT
            right_bytes = _read_prepared(right)
            stage = FailureStage.PREPARATION
            right_input = _timed(
                timings, "right_preprocess_ms", integration.preprocess, right_bytes
            )
            del right_bytes
            stage = FailureStage.EXTRACTION
            right_representation = _timed(
                timings, "right_extract_ms", integration.extract, right_input
            )
            right_input = None

            if left_representation is right_representation:
                raise RuntimeDriftError(
                    "the two sides of a comparison returned the same "
                    "representation object; a cache has been introduced "
                    "(spec section 9)"
                )

            stage = FailureStage.MATCHING
            score = _timed(
                timings,
                "compare_ms",
                integration.compare,
                left_representation,
                right_representation,
            )
            after = (
                integration.preprocess_calls,
                integration.extract_calls,
                integration.compare_calls,
            )
        except RuntimeDriftError:
            # Deliberately first. The runtime moved under the run, and no result
            # is written for this job (docs/adr/0018).
            raise
        except Exception as exc:  # noqa: BLE001 - classified, then recorded
            # KeyboardInterrupt, SystemExit and GeneratorExit derive from
            # BaseException and keep propagating, exactly as they do in the
            # runner. An artifact or identity error becomes drift and is
            # re-raised; everything else is one recorded comparison failure.
            raise_if_blocking(exc)
            code, failure_stage = classify(exc, stage=stage)
            return RawMatchResult.failed(
                failure=FailureInfo(
                    code=code,
                    stage=failure_stage,
                    message=_sanitise(f"{type(exc).__name__}: {exc}"),
                    details={"exception_type": type(exc).__name__},
                ),
                score_direction=direction,
                timing_components_ms=timings,
                metadata=self._failure_metadata(stage),
            )
        finally:
            # Nothing derived from an image survives the call that produced it,
            # on any path (spec section 10).
            del left_input, right_input
            del left_representation, right_representation

        return RawMatchResult.success(
            raw_score=float(score),
            score_direction=direction,
            timing_components_ms=timings,
            metadata=self._success_metadata(score, before=before, after=after),
        )

    # ------------------------------------------------------------ metadata

    def _operation_metadata(self) -> dict[str, str]:
        """What every stored flx result says about how it was produced."""
        return {
            "flx.algorithm_id": identity.ALGORITHM_ID,
            "flx.adapter_id": identity.ADAPTER_ID,
            "flx.adapter_version": str(identity.ADAPTER_VERSION),
            "flx.runtime_profile_id": identity.RUNTIME_PROFILE_ID,
            "flx.preprocessing_profile_id": identity.PREPROCESSING_PROFILE_ID,
            "flx.preprocessing_profile_fingerprint": (
                build_preprocessing_profile().fingerprint
            ),
            "flx.representation_profile_id": identity.REPRESENTATION_PROFILE_ID,
            "flx.representation_profile_fingerprint": (
                build_representation_profile().fingerprint
            ),
            "flx.score_profile_id": identity.SCORE_PROFILE_ID,
            "flx.score_profile_fingerprint": build_score_profile().fingerprint,
            "flx.score_serialization_profile_id": (
                identity.SCORE_SERIALIZATION_PROFILE_ID
            ),
            "flx.inference_batch_rows": str(identity.INFERENCE_BATCH_ROWS),
            "flx.inference_batch_rule": identity.INFERENCE_BATCH_RULE,
            "flx.represented_row": str(identity.REPRESENTED_ROW),
            "flx.side_independence": "separate_preprocess_and_extract_per_side",
        }

    def _success_metadata(
        self,
        score: Decimal,
        *,
        before: tuple[int, int, int],
        after: tuple[int, int, int],
    ) -> dict[str, str]:
        """The canonical score text, and how many operations produced it.

        The counts are measured from the integration's own counters rather than
        asserted, so a result carries what actually happened. Two preprocess
        calls and two logical extractions per comparison, whatever the pair kind
        — which is how SELF independence is proved by observation
        (spec section 9, docs/adr/0075).
        """
        preprocess_calls = after[0] - before[0]
        logical_extractions = after[1] - before[1]
        comparison_calls = after[2] - before[2]
        metadata = self._operation_metadata()
        metadata.update(
            {
                RAW_SCORE_DECIMAL_METADATA_KEY: canonical_decimal_text(float(score)),
                "flx.preprocess_calls": str(preprocess_calls),
                "flx.logical_extraction_calls": str(logical_extractions),
                "flx.physical_forward_rows": str(
                    logical_extractions * identity.INFERENCE_BATCH_ROWS
                ),
                "flx.comparison_calls": str(comparison_calls),
            }
        )
        return metadata

    def _failure_metadata(self, stage: FailureStage) -> dict[str, str]:
        metadata = self._operation_metadata()
        metadata["flx.failed_at"] = stage.value
        return metadata


# ----------------------------------------------------------------- helpers


def _read_prepared(prepared: PreparedImage) -> bytes:
    """Read the prepared PNG and prove it is the file the set declares.

    A digest that no longer matches is drift, not a comparison outcome: the
    immutable input set changed underneath the run, and nothing after this point
    can be attributed to the set the run names (docs/adr/0033, docs/adr/0018).
    """
    raw = Path(prepared.local_path).read_bytes()
    expected = prepared.prepared_sha256
    if expected:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise RuntimeDriftError(
                f"prepared image {prepared.image_id} hashes to {actual[:12]}... but "
                f"the input set declares {expected[:12]}...; the bytes changed "
                "under the run"
            )
    return raw


def _timed(timings: dict[str, float], name: str, operation, *arguments):
    start = perf_counter_ns()
    try:
        return operation(*arguments)
    finally:
        timings[name] = (perf_counter_ns() - start) / _NS_PER_MS


def _sanitise(message: str) -> str:
    text = str(message).strip() or "no detail given"
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[: _MAX_MESSAGE_CHARS - 3] + "..."
    return text
