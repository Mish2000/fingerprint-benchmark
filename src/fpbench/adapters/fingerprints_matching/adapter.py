"""The production adapter: two prepared images in, one raw outcome out.

Everything this class is allowed to know is in its signature. It receives two
:class:`~fpbench.core.execution_models.PreparedImage` values and a context; it
does not receive the pair, the protocol stage, the release, the subject, the
finger or the ground truth, and it has no way to ask for them. It returns a raw
score or a structured failure, and it cannot return a decision — there is no
threshold anywhere in this file and no code path that could apply one.

What it does with the two images is hand their paths to the frozen runtime.
That is the entire integration. The upstream entry point decodes, greyscales,
binarises, segments, builds features twice and matches; this adapter contributes
no crop, resize, ROI, segmentation, enhancement, threshold, alignment or score
transform, and it does not reimplement the matching formula. Those refusals are
not comments — the route is checked against a published contract by G2, and the
adapter reaches upstream only through the top-level function.

**Left is the first argument and right is the second, fixed.** ``match``
normalises by ``len(minutiae1)``, so the ordering is part of what is being
measured. There is no reversal, no maximum of the two orderings, and no
averaging (docs/adr/0109).

**A failure is never a score.** Upstream raising on a print it cannot process is
an algorithmic failure with no number attached; the benchmark already represents
those, and inventing a zero for one would put a similarity into the record that
the algorithm never computed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.fingerprints_matching.bridge_client import (
    BridgeResponse,
    BridgeWorker,
    bridge_script_path,
)
from fpbench.core.enums import (
    EnvironmentStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
)
from fpbench.core.stage15a_errors import Stage15AAdapterError
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_runtime as runtime

__all__ = ["FingerprintsMatchingAdapter", "ALGORITHMIC_FAILURE_CODES"]

#: The upstream refusals this adapter knows how to name, and what each one is.
#: Every one of them is the algorithm declining a print, and every one is mapped
#: without changing the algorithm: no denominator fallback, no invented score for
#: an empty feature set, no retry with different parameters.
ALGORITHMIC_FAILURE_CODES: dict[str, tuple[FailureCode, FailureStage]] = {
    # cv2.convexityDefects refuses a contour whose hull indices are not
    # monotonous. A property of the binarised ridge structure of that print.
    "CONVEXITY_DEFECTS_REFUSED_CONTOUR": (
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
    ),
    # match divides by len(minutiae1) and the first side produced no features.
    "NO_FEATURES_ON_FIRST_SIDE": (
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
    ),
    "IMAGE_NOT_DECODABLE": (
        FailureCode.IMAGE_DECODE_FAILED,
        FailureStage.EXTRACTION,
    ),
    "OPENCV_REFUSED_INPUT": (
        FailureCode.TEMPLATE_EXTRACTION_FAILED,
        FailureStage.EXTRACTION,
    ),
    "UPSTREAM_RAISED": (FailureCode.MATCHING_FAILED, FailureStage.MATCHING),
}


class FingerprintsMatchingAdapter(FingerprintAlgorithmAdapter):
    """``fingerprints-matching`` 0.1.0 over the frozen runtime."""

    def __init__(
        self,
        *,
        repository_root: Path | None = None,
        timeout_seconds: float = float(frozen.JOB_DEADLINE_SECONDS),
        runtime_manifest_fingerprint: str | None = None,
    ) -> None:
        self._repository_root = Path(repository_root or ".")
        self._timeout = float(timeout_seconds)
        self._runtime_fingerprint = runtime_manifest_fingerprint
        self._worker = BridgeWorker(
            interpreter=runtime.runtime_python(repository_root=self._repository_root),
            script=bridge_script_path(repository_root=self._repository_root),
            timeout_seconds=self._timeout,
        )
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=frozen.PRODUCTION_ALGORITHM_ID,
            display_name="fingerprints-matching 0.1.0",
            adapter_id=frozen.ADAPTER_ID,
            adapter_version=frozen.ADAPTER_VERSION,
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=frozen.PACKAGE_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
            metadata={
                "package": frozen.PACKAGE_REQUIREMENT,
                "license": frozen.LICENSE,
                "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
                "wheel_sha256": frozen.RUNTIME_ARTIFACT_SHA256,
                "numpy": frozen.PINNED_NUMPY,
                "opencv_python": frozen.PINNED_OPENCV,
                "entry_point": frozen.ENTRY_QUALNAME,
                "left_argument": frozen.LEFT_ARGUMENT,
                "right_argument": frozen.RIGHT_ARGUMENT,
                "score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
            },
        )

    @classmethod
    def from_config(
        cls, config: Mapping[str, object] | None = None
    ) -> "FingerprintsMatchingAdapter":
        settings = dict(config or {})
        forbidden = sorted(
            key for key in settings if key.lower() in frozen.FORBIDDEN_CONFIG_KEYS
        )
        if forbidden:
            raise Stage15AAdapterError(
                "this adapter refuses decision-shaped configuration: "
                + ", ".join(forbidden)
            )
        root = settings.get("repository_root")
        timeout = settings.get("timeout_seconds", frozen.JOB_DEADLINE_SECONDS)
        return cls(
            repository_root=Path(str(root)) if root else None,
            timeout_seconds=float(timeout),  # type: ignore[arg-type]
            runtime_manifest_fingerprint=(
                str(settings["runtime_manifest_fingerprint"])
                if settings.get("runtime_manifest_fingerprint")
                else None
            ),
        )

    # ------------------------------------------------------------------ contract

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    def validate_environment(self) -> EnvironmentReport:
        """Whether the frozen runtime is present, and whether it is the frozen one."""
        try:
            closure = runtime.build_runtime_closure(
                repository_root=self._repository_root
            )
        except Exception as exc:  # noqa: BLE001 - an absent runtime is a report
            return EnvironmentReport(
                status=EnvironmentStatus.UNAVAILABLE,
                implementation_version=frozen.PACKAGE_VERSION,
                message=f"the frozen runtime could not be inspected: {exc}"[:300],
            )
        if closure.gate_state != "PASS":
            details = list(closure.version_mismatches) + list(closure.module_mismatches)
            return EnvironmentReport(
                status=EnvironmentStatus.UNAVAILABLE,
                implementation_version=frozen.PACKAGE_VERSION,
                message=(
                    f"the frozen runtime is {closure.gate_state}: "
                    + ("; ".join(details) if details else "not built or not verified")
                )[:300],
            )
        observed = closure.observed
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=frozen.PACKAGE_VERSION,
            runtime={
                "python_version": str(observed.get("python_version")),
                "platform": str(observed.get("platform")),
                "machine": str(observed.get("machine")),
            },
            dependencies={
                "numpy": str(observed.get("numpy")),
                "opencv-python": str(observed.get("opencv")),
                "cv2": str(observed.get("cv2_library")),
                "fingerprints-matching": frozen.PACKAGE_VERSION,
            },
        )

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Hand both prepared files to the upstream entry point, in that order."""
        # The one check this adapter performs on the inputs, and it is not about
        # fingerprints: a canonical file that is not on disk is the benchmark's
        # plumbing being wrong, and upstream would report it as an undecodable
        # image — which would quietly turn a broken workspace into 6,000
        # algorithmic failures.
        for side, image in (("left", left), ("right", right)):
            if not Path(image.local_path).exists():
                raise Stage15AAdapterError(
                    f"the {side} prepared image is not on disk: {image.image_id}"
                )

        response = self._worker.compare(left.local_path, right.local_path)
        return self._to_result(response, left=left, right=right)

    # -------------------------------------------------------------------- mapping

    def _metadata(self, response: BridgeResponse) -> dict[str, str]:
        metadata = {
            "entry_point": frozen.ENTRY_QUALNAME,
            "left_argument": frozen.LEFT_ARGUMENT,
            "right_argument": frozen.RIGHT_ARGUMENT,
            "logical_extractions": "2",
            "score_transformation": frozen.FPBENCH_SCORE_TRANSFORMATION,
        }
        if self._runtime_fingerprint:
            metadata["runtime_manifest_fingerprint"] = self._runtime_fingerprint
        native = response.payload.get("native_type")
        if native:
            metadata["upstream_native_type"] = str(native)
        score_hex = response.payload.get("score_hex")
        if score_hex:
            metadata["score_hex"] = str(score_hex)
        return metadata

    def _to_result(
        self, response: BridgeResponse, *, left: PreparedImage, right: PreparedImage
    ) -> RawMatchResult:
        timing = {}
        elapsed = response.payload.get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            timing["upstream_ms"] = float(elapsed)

        if response.is_score:
            return RawMatchResult.success(
                raw_score=response.score,
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                timing_components_ms=timing,
                metadata=self._metadata(response),
            )

        if response.is_algorithmic_failure:
            code, stage = ALGORITHMIC_FAILURE_CODES.get(
                response.code, (FailureCode.MATCHING_FAILED, FailureStage.MATCHING)
            )
            return RawMatchResult.failed(
                failure=FailureInfo(
                    code=code,
                    stage=stage,
                    message=(
                        f"upstream declined the comparison: {response.code}"
                    ),
                    retryable=False,
                    details={
                        "upstream_code": response.code,
                        "exception_type": str(
                            response.payload.get("exception_type", "unknown")
                        ),
                        "outcome_class": "ALGORITHMIC_FAILURE",
                    },
                ),
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                timing_components_ms=timing,
                metadata=self._metadata(response),
            )

        # Everything else is the machine, and it stops the run rather than
        # becoming a 6,001st kind of biometric outcome.
        raise Stage15AAdapterError(
            "the frozen runtime failed at infrastructure level while comparing "
            f"{left.image_id} against {right.image_id}: {response.code} "
            f"({response.payload.get('message', '')})"[:400]
        )

    # ------------------------------------------------------------------ lifecycle

    def restart_runtime(self) -> None:
        """A fresh process, for the qualification case that requires one."""
        self._worker.restart()

    def close(self) -> None:
        self._worker.close()

    def __enter__(self) -> "FingerprintsMatchingAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
