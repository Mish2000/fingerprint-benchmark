"""Assembling the one file from a run that is meant to leave the workspace.

Results stay in a workspace; a receipt goes into version control. That single
difference decides everything about this module: it collects identifiers,
fingerprints and counts from every link in the chain, refuses to build anything
if a link is missing, and hands the result to
:func:`~fpbench.core.research_models.require_sanitised` before it can be
written.

The counts are re-derived here rather than accepted from a caller. A receipt
that repeated numbers somebody passed in would be a summary of a summary, and
the whole point of the artefact is that a reader who has only this file can
check it against a workspace they were given later.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.errors import RunIntegrityError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import (
    NO_CONCLUSION_STATEMENT,
    RESEARCH_RECEIPT_SCHEMA_VERSION,
    ResearchRunReceipt,
)
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetManifest
from fpbench.core.run_state_models import RunAuditReport, RunCompletion
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import write_json
from fpbench.adapters.sourceafis_java.config import BRIDGE_JAR_ROLE
from fpbench.experiments.sourceafis_validation import SourceAfisValidationReport

__all__ = [
    "build_research_receipt",
    "write_evidence_copy",
    "EVIDENCE_DIRECTORY",
]

#: Where a committed copy lives, relative to the repository root. One file per
#: run id, so two runs of the same experiment never overwrite each other.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-native-full"


def build_research_receipt(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    software: SoftwareProvenance,
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    audit: RunAuditReport,
    validation: SourceAfisValidationReport,
    completion: RunCompletion,
    dataset_id: str,
    primary_asset_role: str = BRIDGE_JAR_ROLE,
    timing_summary: Mapping[str, str] | None = None,
    created_utc: str | None = None,
) -> ResearchRunReceipt:
    """Derive the sanitised receipt for a finished, verified research run.

    Args:
        primary_asset_role: Which of the bundle's assets the receipt records as
            the executable. A SourceAFIS run has exactly one and it is the
            default; the parameter exists so that the 6,000-job structural test
            can exercise this code at scale without pretending its stand-in file
            is a SourceAFIS jar.

    Raises:
        RunIntegrityError: the links do not agree with one another. The receipt
            is the last thing written and the first thing read; a receipt built
            over an inconsistency would be worse than no receipt at all.
    """
    _require_consistent(
        run=run,
        plan=plan,
        runtime_reference=runtime_reference,
        result_set=result_set,
        audit=audit,
        validation=validation,
        completion=completion,
    )

    bridge_jar_sha256 = dict(runtime_reference.asset_sha256s).get(primary_asset_role)
    if bridge_jar_sha256 is None:
        raise RunIntegrityError(
            f"the runtime reference for {run.run_id} holds no "
            f"{primary_asset_role!r} asset; there is no executable to attribute "
            "these results to"
        )

    release_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    for planned in plan.jobs:
        pair = pairs.get(planned.job.pair_id)
        if pair is None:
            raise RunIntegrityError(
                f"pair {planned.job.pair_id} is planned but absent from the pair "
                "manifest; the receipt's counts would be incomplete"
            )
        release_counts[pair.release] = release_counts.get(pair.release, 0) + 1
        stage = pair.protocol_stage.value
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    return ResearchRunReceipt(
        schema_version=RESEARCH_RECEIPT_SCHEMA_VERSION,
        source_commit=software.source_revision,
        source_tree_clean=software.source_tree_clean,
        dataset_id=dataset_id,
        cohort_id=str(run.cohort_id),
        pair_manifest_hash=run.pair_manifest_hash,
        run_id=run.run_id,
        run_fingerprint=run.run_fingerprint,
        plan_id=plan.plan_id,
        plan_fingerprint=plan.definition.plan_fingerprint,
        environment_fingerprint=run.environment_fingerprint,
        runtime_bundle_id=runtime_reference.bundle_id,
        runtime_bundle_fingerprint=runtime_reference.bundle_fingerprint,
        bridge_jar_sha256=bridge_jar_sha256,
        result_set_id=result_set.result_set_id,
        result_set_fingerprint=result_set.result_set_fingerprint,
        audit_fingerprint=audit.audit_fingerprint,
        sourceafis_validation_fingerprint=validation.validation_fingerprint,
        completion_id=completion.completion_id,
        completion_fingerprint=completion.completion_fingerprint,
        planned_jobs=plan.total_jobs,
        stored_results=validation.total_results,
        success_count=validation.successful_results,
        algorithmic_failure_count=validation.algorithmic_failures,
        blocking_failure_count=validation.blocking_failures,
        failure_counts=dict(validation.failure_counts),
        release_counts=release_counts,
        stage_counts=stage_counts,
        timing_summary=dict(timing_summary or {}),
        statement=NO_CONCLUSION_STATEMENT,
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def write_evidence_copy(
    receipt: ResearchRunReceipt,
    *,
    repository_root: Path,
    directory: Path = EVIDENCE_DIRECTORY,
) -> Path:
    """Write the committable copy under ``evidence/``.

    Writing it makes the working tree dirty, which is why it is the *last* step
    of finalisation: every provenance check has already passed by the time this
    runs, and the next research run will require the receipt to be committed
    before it can start (docs/adr/0017).
    """
    path = Path(repository_root) / directory / f"{receipt.run_id}.json"
    return write_json(path, receipt)


# ----------------------------------------------------------------- internals


def _require_consistent(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    audit: RunAuditReport,
    validation: SourceAfisValidationReport,
    completion: RunCompletion,
) -> None:
    checks: list[tuple[str, Any, Any]] = [
        ("plan run id", plan.definition.run_id, run.run_id),
        ("plan run fingerprint", plan.definition.run_fingerprint, run.run_fingerprint),
        ("runtime reference run", runtime_reference.run_id, run.run_id),
        (
            "runtime reference run fingerprint",
            runtime_reference.run_fingerprint,
            run.run_fingerprint,
        ),
        (
            "runtime reference environment",
            runtime_reference.environment_fingerprint,
            run.environment_fingerprint,
        ),
        ("result set run", result_set.run_id, run.run_id),
        ("result set run fingerprint", result_set.run_fingerprint, run.run_fingerprint),
        (
            "result set plan fingerprint",
            result_set.plan_fingerprint,
            plan.definition.plan_fingerprint,
        ),
        (
            "result set runtime bundle",
            result_set.runtime_bundle_fingerprint,
            runtime_reference.bundle_fingerprint,
        ),
        ("audit run", audit.run_id, run.run_id),
        ("audit plan", audit.plan_id, plan.plan_id),
        ("validation run", validation.run_id, run.run_id),
        ("validation plan", validation.plan_id, plan.plan_id),
        ("completion run", completion.run_id, run.run_id),
        ("completion plan", completion.plan_id, plan.plan_id),
        (
            "completion audit fingerprint",
            completion.audit_fingerprint,
            audit.audit_fingerprint,
        ),
    ]
    for label, actual, expected in checks:
        if actual != expected:
            raise RunIntegrityError(
                f"a research receipt cannot be built: {label} is {actual!r}, "
                f"expected {expected!r}"
            )

    if not audit.is_clean:
        raise RunIntegrityError(
            f"run {run.run_id} did not audit cleanly; no receipt may be issued"
        )
    if not validation.is_clean:
        raise RunIntegrityError(
            f"run {run.run_id} failed SourceAFIS validation: "
            f"{[issue.code.value for issue in validation.errors][:5]}"
        )
    if validation.total_results != plan.total_jobs:
        raise RunIntegrityError(
            f"validation saw {validation.total_results} results for "
            f"{plan.total_jobs} planned jobs"
        )
    if result_set.total_results != plan.total_jobs:
        raise RunIntegrityError(
            f"the result set holds {result_set.total_results} results for "
            f"{plan.total_jobs} planned jobs"
        )
    if completion.planned_jobs != plan.total_jobs:
        raise RunIntegrityError(
            f"the completion manifest covers {completion.planned_jobs} jobs, not "
            f"{plan.total_jobs}"
        )
