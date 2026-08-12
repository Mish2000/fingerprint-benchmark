"""The production adapter's own smoke, on inputs that are not SD300.

Stage 11A qualified VeriFinger with a harness built for asking questions. This
pass exercises the thing that will actually produce six thousand benchmark
results — the registered adapter, the pinned bridge jar, the verified runtime
closure — and it does so before SD300 is opened (spec section 23).

Seven claims, and every one of them is a fact about the production route rather
than about the SDK:

.. code-block:: text

    environment READY               the closure verifies and the licence is granted
    vendor fixture pair             a score is produced
    the same pair twice             the same integer, in two separate JVMs
    A,B and B,A                     both orderings run, and the contract holds
    SELF(A,A)                       two independent sides, and a score
    a bad fixture                   a structured failure, and no score
    restart                         a fresh adapter, and the same integer

At most twenty scores. It is a proof that the production adapter works, not a
second qualification, and a pass that grew into one would be the extra research
stage this stage exists to avoid (spec sections 23 and 24).

**No SD300 image is opened and no SD300 score exists.** The fixtures are the ones
Stage 11A already used: this project's synthetic ridge fields, and — when the
extractor will not accept those, which is what Stage 11A observed — upstream's
own sample prints out of the pinned archive. Neither is anybody's finger, and
neither leaves the local artifact store.

**Score values are recorded.** Unlike Stage 11A, which published only digests
because it was examining a candidate under evaluation, this pass compares
integers from vendor fixtures. They are not benchmark scores, they are not SD300
scores, and equality between them is the whole point of the determinism claims.
"""

from __future__ import annotations

import datetime as _dt
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.enums import ChecksumStatus, ExecutionStatus
from fpbench.core.execution_models import ComparisonContext, PreparedImage, RawMatchResult
from fpbench.core.serialization import stable_hash
from fpbench.core.verifinger_errors import Stage11BSmokeError
from fpbench.experiments import stage11b_identity as frozen
from fpbench.adapters.verifinger_java import identity

__all__ = [
    "SMOKE_SCHEMA",
    "SmokeCase",
    "SmokeReport",
    "run_production_smoke",
    "main",
]

SMOKE_SCHEMA = "stage_11b_production_adapter_smoke_v1"

#: A synthetic job id. Sixteen hex characters, like the runner's own, so nothing
#: about this pass exercises a code path the real run will not.
_JOB_IDS = (
    "5b0000000000a001",
    "5b0000000000a002",
    "5b0000000000a003",
    "5b0000000000a004",
    "5b0000000000a005",
    "5b0000000000a006",
    "5b0000000000a007",
)


@dataclass(frozen=True, slots=True)
class SmokeCase:
    """One comparison the smoke performed, and what came back."""

    name: str
    left: str
    right: str
    status: str
    score: int | None = None
    engine_status: str | None = None
    failure_code: str | None = None
    failure_stage: str | None = None
    extraction_count: int | None = None
    elapsed_seconds: float | None = None

    def as_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "case": self.name,
            "left_fixture": self.left,
            "right_fixture": self.right,
            "status": self.status,
        }
        for key, value in (
            ("score", self.score),
            ("engine_status", self.engine_status),
            ("failure_code", self.failure_code),
            ("failure_stage", self.failure_stage),
            ("extraction_count", self.extraction_count),
            ("elapsed_seconds", self.elapsed_seconds),
        ):
            if value is not None:
                document[key] = value
        return document


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """The seven claims, and whether every one of them holds."""

    outcome: str
    fixture_kind: str
    environment_status: str
    implementation_version: str
    runtime_manifest_fingerprint: str
    algorithm_profile_fingerprint: str
    cases: tuple[SmokeCase, ...]
    claims: Mapping[str, bool]
    scores_produced: int
    sd300_used: bool = False
    benchmark_scores_produced: int = 0
    performed_utc: str = field(default_factory=lambda: _utc_now())

    @property
    def passed(self) -> bool:
        return all(self.claims.values()) and self.outcome == "PASS"

    @property
    def fingerprint(self) -> str:
        return stable_hash(self.as_document(exclude_timestamp=True), length=64)

    def as_document(self, *, exclude_timestamp: bool = False) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema": SMOKE_SCHEMA,
            "outcome": self.outcome,
            "algorithm_id": identity.ALGORITHM_ID,
            "adapter_id": identity.ADAPTER_ID,
            "implementation_version": self.implementation_version,
            "environment_status": self.environment_status,
            "fixture_kind": self.fixture_kind,
            "fixtures_are_sd300": False,
            "sd300_used": self.sd300_used,
            "benchmark_scores_produced": self.benchmark_scores_produced,
            "scores_produced": self.scores_produced,
            "scores_permitted": frozen.SMOKE_MAX_SCORES,
            "runtime_manifest_fingerprint": self.runtime_manifest_fingerprint,
            "algorithm_profile_fingerprint": self.algorithm_profile_fingerprint,
            "claims": dict(sorted(dict(self.claims).items())),
            "cases": [case.as_document() for case in self.cases],
        }
        if not exclude_timestamp:
            document["performed_utc"] = self.performed_utc
        return document


def run_production_smoke(
    *,
    repository_root: Path = Path("."),
    installation: Path | None = None,
    fixtures: Path | None = None,
) -> SmokeReport:
    """Exercise the registered production adapter over vendor fixtures.

    Raises:
        Stage11BSmokeError: the environment is not READY, or a fixture that must
            score does not. A smoke that cannot establish its claims must fail
            loudly rather than publish a report full of ``false``.
    """
    from fpbench.adapters.registry import create_adapter

    root = Path(repository_root)
    fixture_directory = _resolve_fixtures(root, fixtures)
    from fpbench.experiments.verifinger_runtime_manifest import default_installation

    configuration: dict[str, object] = {
        "installation": str(
            Path(installation)
            if installation is not None
            else default_installation(repository_root=root)
        )
    }
    adapter = create_adapter(identity.ADAPTER_ID, configuration)

    report = adapter.validate_environment()
    if not report.is_ready:
        raise Stage11BSmokeError(
            "the production VeriFinger adapter is not READY, so nothing can be "
            f"smoked: {report.message}"
        )
    manifest = getattr(adapter, "runtime_manifest", None)
    if manifest is None:  # pragma: no cover - READY implies a verified closure
        raise Stage11BSmokeError("the adapter reported READY with no runtime closure")

    left_name, right_name, fixture_kind = _choose_fixtures(adapter, fixture_directory)
    bad_name = "fixture_blank.png"

    cases: list[SmokeCase] = []
    with tempfile.TemporaryDirectory(prefix="fpbench-verifinger-smoke-") as scratch:
        sandbox = Path(scratch)
        forward = _compare(
            adapter, fixture_directory, left_name, right_name, sandbox, _JOB_IDS[0],
            name="forward",
        )
        repeat = _compare(
            adapter, fixture_directory, left_name, right_name, sandbox, _JOB_IDS[1],
            name="forward_repeated",
        )
        reverse = _compare(
            adapter, fixture_directory, right_name, left_name, sandbox, _JOB_IDS[2],
            name="reversed",
        )
        self_case = _compare(
            adapter, fixture_directory, left_name, left_name, sandbox, _JOB_IDS[3],
            name="self",
        )
        bad = _compare(
            adapter, fixture_directory, left_name, bad_name, sandbox, _JOB_IDS[4],
            name="bad_fixture",
        )
        cases.extend([forward, repeat, reverse, self_case, bad])

        # A second adapter, built from scratch: the whole restart claim is that
        # nothing survives between processes, and reusing the first adapter's
        # resolved environment would test rather less than that.
        restarted_adapter = create_adapter(identity.ADAPTER_ID, configuration)
        restarted_report = restarted_adapter.validate_environment()
        if not restarted_report.is_ready:
            raise Stage11BSmokeError(
                "the restarted adapter is not READY: " f"{restarted_report.message}"
            )
        restart = _compare(
            restarted_adapter,
            fixture_directory,
            left_name,
            right_name,
            sandbox,
            _JOB_IDS[5],
            name="restart",
        )
        cases.append(restart)

    for required in (forward, repeat, reverse, self_case, restart):
        if required.status != "success":
            raise Stage11BSmokeError(
                f"the {required.name!r} case produced no score "
                f"({required.failure_code}); the production adapter cannot be "
                "smoked on these fixtures"
            )

    claims = {
        "environment_ready": True,
        "vendor_fixture_pair_scores": forward.status == "success",
        "same_pair_twice_same_score": forward.score == repeat.score,
        "both_orderings_run": reverse.status == "success",
        "self_produces_a_score_from_two_independent_sides": (
            self_case.status == "success"
            and self_case.extraction_count == identity.REQUIRED_EXTRACTION_COUNT
        ),
        "bad_fixture_is_a_structured_failure_with_no_score": (
            bad.status == "failure" and bad.score is None and bool(bad.failure_code)
        ),
        "restart_reproduces_the_same_score": forward.score == restart.score,
        "every_success_carries_two_extractions": all(
            case.extraction_count == identity.REQUIRED_EXTRACTION_COUNT
            for case in cases
            if case.status == "success"
        ),
    }
    scores = sum(1 for case in cases if case.status == "success")
    if scores > frozen.SMOKE_MAX_SCORES:  # pragma: no cover - six cases, twenty allowed
        raise Stage11BSmokeError(
            f"the smoke produced {scores} scores and is permitted "
            f"{frozen.SMOKE_MAX_SCORES}"
        )

    return SmokeReport(
        outcome="PASS" if all(claims.values()) else "FAIL",
        fixture_kind=fixture_kind,
        environment_status=report.status.value,
        implementation_version=report.implementation_version,
        runtime_manifest_fingerprint=manifest.fingerprint,
        algorithm_profile_fingerprint=identity.algorithm_profile_fingerprint(),
        cases=tuple(cases),
        claims=claims,
        scores_produced=scores,
    )


# ----------------------------------------------------------------- internals


def _resolve_fixtures(repository_root: Path, override: Path | None) -> Path:
    if override is not None:
        return Path(override).resolve()
    from fpbench.experiments.stage11a_artifacts import artifact_store_prefix_path

    directory = artifact_store_prefix_path(repository_root=repository_root) / "fixtures"
    if not directory.is_dir():
        raise Stage11BSmokeError(
            "the Stage 11A fixture directory is not on this machine; run the "
            "qualification's fixture step first. Nothing here generates a "
            "fingerprint and nothing here reads SD300"
        )
    return directory


def _choose_fixtures(adapter, directory: Path) -> tuple[str, str, str]:
    """Synthetic first, upstream's own sample as the named fallback.

    The same order Stage 11A used and for the same reason: a fixture this
    project generated is certainly nobody's finger, and a vendor sample is the
    documented fallback for exactly the case Stage 11A hit — the extractor
    rejecting the synthetic pair (spec section 23).
    """
    with tempfile.TemporaryDirectory(prefix="fpbench-verifinger-probe-") as scratch:
        probe = _compare(
            adapter,
            directory,
            "fixture_a.png",
            "fixture_b.png",
            Path(scratch),
            _JOB_IDS[6],
            name="fixture_selection",
        )
    if probe.status == "success":
        return "fixture_a.png", "fixture_b.png", "SYNTHETIC_RIDGE_LIKE"
    for name in ("vendor_a.png", "vendor_b.png"):
        if not (directory / name).is_file():
            raise Stage11BSmokeError(
                "the synthetic fixture pair produced no score "
                f"({probe.failure_code}) and no vendor sample fixture is present"
            )
    return "vendor_a.png", "vendor_b.png", "VENDOR_OFFICIAL_SAMPLE"


def _compare(
    adapter,
    directory: Path,
    left: str,
    right: str,
    sandbox: Path,
    job_id: str,
    *,
    name: str,
) -> SmokeCase:
    import hashlib
    import time

    work = sandbox / job_id / "work"
    artifacts = sandbox / job_id / "artifacts"
    work.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    context = ComparisonContext(
        run_id="run_stage11bsmoke",
        job_id=job_id,
        attempt=1,
        working_directory=work.resolve(),
        artifact_directory=artifacts.resolve(),
        timeout_seconds=float(frozen.JOB_DEADLINE_SECONDS),
        deterministic_seed=0,
    )

    def image(name_on_disk: str) -> PreparedImage:
        path = (directory / name_on_disk).resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return PreparedImage(
            image_id=f"smoke_{hashlib.sha256(name_on_disk.encode()).hexdigest()[:12]}",
            local_path=path,
            effective_ppi=identity.REQUIRED_EFFECTIVE_PPI,
            media_type="image/png",
            expected_sha256=digest,
            checksum_status=ChecksumStatus.VERIFIED,
            preparation_profile_id="stage11b_smoke_identity_v1",
            preparation_hash=hashlib.sha256(b"stage11b-smoke").hexdigest(),
        )

    started = time.monotonic()
    result: RawMatchResult = adapter.compare(image(left), image(right), context)
    elapsed = round(time.monotonic() - started, 3)
    metadata = dict(result.metadata)
    prefix = identity.METADATA_PREFIX
    count = metadata.get(f"{prefix}extraction_count")
    return SmokeCase(
        name=name,
        left=left,
        right=right,
        status="success" if result.status is ExecutionStatus.SUCCESS else "failure",
        score=int(result.raw_score) if result.raw_score is not None else None,
        engine_status=metadata.get(f"{prefix}engine_status"),
        failure_code=result.failure.code.value if result.failure else None,
        failure_stage=result.failure.stage.value if result.failure else None,
        extraction_count=int(count) if count is not None else None,
        elapsed_seconds=elapsed,
    )


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    """``python -m fpbench.experiments.verifinger_smoke``."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Stage 11B production adapter smoke")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--installation", default=None)
    parser.add_argument("--out", default=None, help="write the report here as JSON")
    arguments = parser.parse_args(argv)

    report = run_production_smoke(
        repository_root=Path(arguments.repository_root).resolve(),
        installation=Path(arguments.installation) if arguments.installation else None,
    )
    document = report.as_document()
    if arguments.out:
        Path(arguments.out).parent.mkdir(parents=True, exist_ok=True)
        Path(arguments.out).write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(document, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
