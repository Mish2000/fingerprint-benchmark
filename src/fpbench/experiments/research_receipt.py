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

from fpbench.core.atomic_write import replace_bytes
from fpbench.core.errors import ResultConflictError, RunIntegrityError
from fpbench.core.execution_plan_models import ExecutionPlan
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.imaging_models import PreparedImageSetManifest
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.research_models import (
    LegacyResearchFinalizationMarker,
    LegacyResearchRunReceipt,
    NO_CONCLUSION_STATEMENT,
    RESEARCH_FINALIZATION_SCHEMA_VERSION,
    RESEARCH_RECEIPT_SCHEMA_VERSION,
    ResearchFinalization,
    ResearchFinalizationMarker,
    ResearchReceipt,
    ResearchRunReceipt,
    research_finalization_fingerprint,
    research_receipt_content_hash,
    research_receipt_fingerprint,
)
from fpbench.core.result_models import RunDefinition
from fpbench.core.result_set_models import ResultSetManifest
from fpbench.core.run_state_models import RunAuditReport, RunCompletion
from fpbench.core.runtime_models import RunRuntimeReference
from fpbench.core.serialization import to_plain
from fpbench.experiments.research_integration import AlgorithmValidationReport

__all__ = [
    "build_research_finalization_marker",
    "build_research_receipt",
    "verify_research_finalization_marker",
    "verify_research_receipt",
    "write_evidence_copy",
    "EVIDENCE_DIRECTORY",
    "LEGACY_PRIMARY_ASSET_ROLE",
]

#: Where a committed copy lives, relative to the repository root. One file per
#: run id, so two runs of the same experiment never overwrite each other.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-native-full"

#: The role the two finished runs' receipts were written against, before an
#: integration declared its roles explicitly. A literal rather than an import
#: from an adapter package: this module builds receipts for any algorithm, and
#: it should not have to know that one of them ships a jar. Every current caller
#: passes the role it means; this is what a caller written before they did gets.
LEGACY_PRIMARY_ASSET_ROLE = "sourceafis_bridge_jar"


def build_research_receipt(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    software: SoftwareProvenance,
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    audit: RunAuditReport,
    validation: AlgorithmValidationReport,
    completion: RunCompletion,
    dataset_id: str,
    preparation_manifest: PreparedImageSetManifest | None = None,
    primary_asset_role: str = LEGACY_PRIMARY_ASSET_ROLE,
    timing_summary: Mapping[str, str] | None = None,
    created_utc: str | None = None,
) -> ResearchReceipt:
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

    integration_claims = _integration_claims(run)

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

    preparation_claims = _preparation_claims(run, preparation_manifest)

    common: dict[str, Any] = dict(
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
        result_set_id=result_set.result_set_id,
        result_set_fingerprint=result_set.result_set_fingerprint,
        audit_fingerprint=audit.audit_fingerprint,
        completion_id=completion.completion_id,
        completion_fingerprint=completion.completion_fingerprint,
        planned_jobs=plan.total_jobs,
        stored_results=validation.total_results,
        success_count=validation.successful_results,
        algorithmic_failure_count=validation.algorithmic_failures,
        blocking_failure_count=validation.blocking_failures,
        **preparation_claims,
        failure_counts=dict(validation.failure_counts),
        release_counts=release_counts,
        stage_counts=stage_counts,
        timing_summary=dict(timing_summary or {}),
        statement=NO_CONCLUSION_STATEMENT,
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    if integration_claims is None:
        primary_sha = dict(runtime_reference.asset_sha256s).get(primary_asset_role)
        if primary_sha is None:
            raise RunIntegrityError(
                f"the runtime reference for {run.run_id} holds no "
                f"{primary_asset_role!r} asset; there is no executable to "
                "attribute these results to"
            )
        return LegacyResearchRunReceipt(
            schema_version="2",
            bridge_jar_sha256=primary_sha,
            sourceafis_validation_fingerprint=validation.validation_fingerprint,
            **common,
        )
    return ResearchRunReceipt(
        schema_version=RESEARCH_RECEIPT_SCHEMA_VERSION,
        **integration_claims,
        runtime_asset_sha256s=dict(runtime_reference.asset_sha256s),
        algorithm_validation_fingerprint=validation.validation_fingerprint,
        **common,
    )


def verify_research_receipt(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    pairs: Mapping[PairId, ComparisonPair],
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    current_audit: RunAuditReport,
    current_algorithm_validation: AlgorithmValidationReport,
    completion: RunCompletion,
    receipt: ResearchReceipt,
    preparation_manifest: PreparedImageSetManifest | None = None,
    primary_asset_role: str = LEGACY_PRIMARY_ASSET_ROLE,
) -> None:
    """Re-derive every load-bearing receipt claim from current evidence.

    The receipt is never its own proof.  This verifier intentionally compares
    fields one by one rather than relying on the receipt fingerprint: a forged
    receipt can be internally self-consistent while contradicting the run it
    purports to summarize.

    Raises:
        RunIntegrityError: any receipt field disagrees with the current chain.
    """
    _require_consistent(
        run=run,
        plan=plan,
        runtime_reference=runtime_reference,
        result_set=result_set,
        audit=current_audit,
        validation=current_algorithm_validation,
        completion=completion,
    )

    release_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    dataset_ids: set[str] = set()
    for planned in plan.jobs:
        pair = pairs.get(planned.job.pair_id)
        if pair is None:
            raise RunIntegrityError(
                f"pair {planned.job.pair_id} is planned but absent from the pair "
                "manifest"
            )
        dataset_ids.add(pair.dataset_id)
        release_counts[pair.release] = release_counts.get(pair.release, 0) + 1
        stage = pair.protocol_stage.value
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    if len(dataset_ids) != 1:
        raise RunIntegrityError(
            f"the planned pairs name {sorted(dataset_ids)!r} datasets, expected one"
        )

    source_commit = run.environment.runtime.get("fpbench.source.revision")
    source_clean = run.environment.runtime.get("fpbench.source.clean") == "true"
    expected: dict[str, Any] = {
        "source_commit": source_commit,
        "source_tree_clean": source_clean,
        "dataset_id": next(iter(dataset_ids)),
        "cohort_id": str(run.cohort_id),
        "pair_manifest_hash": run.pair_manifest_hash,
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.definition.plan_fingerprint,
        "environment_fingerprint": run.environment_fingerprint,
        "runtime_bundle_id": runtime_reference.bundle_id,
        "runtime_bundle_fingerprint": runtime_reference.bundle_fingerprint,
        "result_set_id": result_set.result_set_id,
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "audit_fingerprint": current_audit.audit_fingerprint,
        "completion_id": completion.completion_id,
        "completion_fingerprint": completion.completion_fingerprint,
        "planned_jobs": plan.total_jobs,
        "stored_results": current_algorithm_validation.total_results,
        "success_count": current_algorithm_validation.successful_results,
        "algorithmic_failure_count": (
            current_algorithm_validation.algorithmic_failures
        ),
        "blocking_failure_count": current_algorithm_validation.blocking_failures,
        "failure_counts": dict(current_algorithm_validation.failure_counts),
        "release_counts": dict(sorted(release_counts.items())),
        "stage_counts": dict(sorted(stage_counts.items())),
        **_preparation_claims(run, preparation_manifest),
    }
    if isinstance(receipt, LegacyResearchRunReceipt):
        primary_sha = dict(runtime_reference.asset_sha256s).get(primary_asset_role)
        if primary_sha is None:
            raise RunIntegrityError(
                f"the runtime reference holds no {primary_asset_role!r} asset"
            )
        expected.update(
            schema_version=(
                "1"
                if preparation_manifest is None and receipt.schema_version == "1"
                else "2"
            ),
            bridge_jar_sha256=primary_sha,
            sourceafis_validation_fingerprint=(
                current_algorithm_validation.validation_fingerprint
            ),
        )
    else:
        integration_claims = _integration_claims(run)
        if integration_claims is None:
            raise RunIntegrityError(
                "a generic research receipt cannot verify a legacy run without "
                "integration identity"
            )
        expected.update(
            schema_version=RESEARCH_RECEIPT_SCHEMA_VERSION,
            **integration_claims,
            runtime_asset_sha256s=dict(runtime_reference.asset_sha256s),
            algorithm_validation_fingerprint=(
                current_algorithm_validation.validation_fingerprint
            ),
        )
    for field_name, expected_value in expected.items():
        actual = getattr(receipt, field_name)
        if isinstance(actual, Mapping):
            actual = dict(actual)
        if actual != expected_value:
            raise RunIntegrityError(
                f"research receipt field {field_name} is {actual!r}, expected "
                f"{expected_value!r}"
            )


def build_research_finalization_marker(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    audit: RunAuditReport,
    validation: AlgorithmValidationReport,
    completion: RunCompletion,
    receipt: ResearchReceipt,
    verifier_software: SoftwareProvenance,
    created_utc: str | None = None,
) -> ResearchFinalization:
    """Build the last-written authority over an already verified chain."""
    if not verifier_software.is_research_grade:
        raise RunIntegrityError(
            "research finalization requires a committed, clean verifier revision"
        )
    claims: dict[str, Any] = {
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.definition.plan_fingerprint,
        "environment_fingerprint": run.environment_fingerprint,
        "runtime_reference_fingerprint": (
            runtime_reference.runtime_reference_fingerprint
        ),
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "audit_fingerprint": audit.audit_fingerprint,
        "completion_fingerprint": completion.completion_fingerprint,
        "receipt_fingerprint": research_receipt_fingerprint(receipt),
        "receipt_content_hash": research_receipt_content_hash(receipt),
        "verifier_source_commit": verifier_software.source_revision,
        "verifier_source_tree_clean": verifier_software.source_tree_clean,
    }
    if isinstance(receipt, LegacyResearchRunReceipt):
        claims.update(
            schema_version="3",
            sourceafis_validation_fingerprint=validation.validation_fingerprint,
        )
        marker_type = LegacyResearchFinalizationMarker
    else:
        integration_claims = _integration_claims(run)
        if integration_claims is None:
            raise RunIntegrityError(
                "a generic finalization marker requires integration identity"
            )
        claims.update(
            schema_version=RESEARCH_FINALIZATION_SCHEMA_VERSION,
            **integration_claims,
            algorithm_validation_fingerprint=validation.validation_fingerprint,
        )
        marker_type = ResearchFinalizationMarker
    fingerprint = research_finalization_fingerprint(claims)
    return marker_type(
        **claims,
        finalization_id=f"finalization_{fingerprint[:12]}",
        finalization_fingerprint=fingerprint,
        created_utc=created_utc or _dt.datetime.now(_dt.timezone.utc).isoformat(),
    )


def verify_research_finalization_marker(
    *,
    marker: ResearchFinalization,
    run: RunDefinition,
    plan: ExecutionPlan,
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    current_audit: RunAuditReport,
    current_algorithm_validation: AlgorithmValidationReport,
    completion: RunCompletion,
    receipt: ResearchReceipt,
) -> None:
    """Confirm the final marker still names every current durable artefact."""
    expected = {
        "run_id": run.run_id,
        "run_fingerprint": run.run_fingerprint,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.definition.plan_fingerprint,
        "environment_fingerprint": run.environment_fingerprint,
        "runtime_reference_fingerprint": (
            runtime_reference.runtime_reference_fingerprint
        ),
        "result_set_fingerprint": result_set.result_set_fingerprint,
        "audit_fingerprint": current_audit.audit_fingerprint,
        "completion_fingerprint": completion.completion_fingerprint,
        "receipt_fingerprint": research_receipt_fingerprint(receipt),
        "receipt_content_hash": research_receipt_content_hash(receipt),
    }
    if isinstance(marker, LegacyResearchFinalizationMarker):
        if not isinstance(receipt, LegacyResearchRunReceipt):
            raise RunIntegrityError(
                "a legacy finalization marker cannot authorize a generic receipt"
            )
        expected["sourceafis_validation_fingerprint"] = (
            current_algorithm_validation.validation_fingerprint
        )
    else:
        if isinstance(receipt, LegacyResearchRunReceipt):
            raise RunIntegrityError(
                "a generic finalization marker cannot authorize a legacy receipt"
            )
        integration_claims = _integration_claims(run)
        if integration_claims is None:
            raise RunIntegrityError(
                "a generic finalization marker requires integration identity"
            )
        expected.update(
            **integration_claims,
            algorithm_validation_fingerprint=(
                current_algorithm_validation.validation_fingerprint
            ),
        )
    for field_name, expected_value in expected.items():
        actual = getattr(marker, field_name)
        if actual != expected_value:
            raise RunIntegrityError(
                f"research finalization field {field_name} is {actual!r}, "
                f"expected {expected_value!r}"
            )


def write_evidence_copy(
    receipt: ResearchReceipt,
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
    import json
    import os

    path = Path(repository_root) / directory / f"{receipt.run_id}.json"
    rendered = (
        json.dumps(to_plain(receipt), indent=2, ensure_ascii=False, sort_keys=False)
        + "\n"
    )
    # LF on every platform. These bytes are compared against the committed
    # copy and, in several stages, hashed into a marker; translating them to
    # the writer's native line ending made one document into two, depending
    # on which machine happened to write it (docs/adr/0139).
    payload = rendered.encode("utf-8")
    if path.is_file():
        if path.read_bytes() != payload:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing = {}
            current = dict(to_plain(receipt))
            shared_claims_match = all(
                key in current and value == current[key]
                for key, value in existing.items()
                if key not in {"schema_version", "created_utc"}
            )
            if (
                str(existing.get("schema_version")) == "1"
                and receipt.schema_version == "2"
                and shared_claims_match
            ):
                replace_bytes(path, payload, what="research receipt")
                return path
            raise ResultConflictError(
                f"{path} already contains a different evidence receipt; refusing "
                "to overwrite committed evidence"
            )
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} appeared with different content; refusing to overwrite it"
            )
    return path


# ----------------------------------------------------------------- internals


def _integration_claims(run: RunDefinition) -> dict[str, str] | None:
    integration_id = run.environment.runtime.get("fpbench.integration.id")
    integration_fingerprint = run.environment.runtime.get(
        "fpbench.integration.fingerprint"
    )
    if integration_id is None and integration_fingerprint is None:
        return None
    if integration_id is None or integration_fingerprint is None:
        raise RunIntegrityError(
            "research environment contains an incomplete integration identity"
        )
    return {
        "integration_id": integration_id,
        "integration_fingerprint": integration_fingerprint,
    }


def _preparation_claims(
    run: RunDefinition,
    manifest: PreparedImageSetManifest | None,
) -> dict[str, str | None]:
    """Derive public prepared-set claims from the run profile and set manifest."""
    names = (
        "preparation_set_id",
        "preparation_set_fingerprint",
        "transform_profile_id",
        "transform_profile_fingerprint",
    )
    parameters = run.execution_profile.parameters
    if manifest is None:
        if any(parameters.get(name) is not None for name in names):
            raise RunIntegrityError(
                "the run execution profile names a prepared set but no verified "
                "PreparedImageSetManifest was supplied"
            )
        return {
            "preparation_set_id": None,
            "preparation_set_fingerprint": None,
            "transform_profile_id": None,
            "transform_profile_fingerprint": None,
            "transform_runtime_fingerprint": None,
        }

    expected = {
        "preparation_set_id": manifest.preparation_set_id,
        "preparation_set_fingerprint": manifest.preparation_set_fingerprint,
        "transform_profile_id": manifest.transform_profile_id,
        "transform_profile_fingerprint": manifest.transform_profile_fingerprint,
    }
    for field_name, expected_value in expected.items():
        if parameters.get(field_name) != expected_value:
            raise RunIntegrityError(
                f"the run execution profile's {field_name} does not match the "
                "verified PreparedImageSetManifest"
            )
    return {
        **expected,
        "transform_runtime_fingerprint": manifest.transform_runtime_fingerprint,
    }


def _require_consistent(
    *,
    run: RunDefinition,
    plan: ExecutionPlan,
    runtime_reference: RunRuntimeReference,
    result_set: ResultSetManifest,
    audit: RunAuditReport,
    validation: AlgorithmValidationReport,
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
            f"run {run.run_id} failed algorithm validation: "
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
