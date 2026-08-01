"""Loading two finished chains, and proving they differ in exactly one thing.

This is where the comparison earns the right to attribute anything. Before a
single pair is joined, twelve properties are checked for equality across the two
runs — dataset, protocol, cohort, cohort fingerprint, pair manifest, algorithm
id and fingerprint, implementation version, adapter id and version, bridge jar,
runtime bundle, pair count — and one property is checked for *in*equality: the
execution profile.

That asymmetry is the whole design. If everything matched, the two runs would be
the same run and there would be nothing to compare. If more than the execution
profile differed, a change in the numbers would be the sum of several causes and
attributing it to image preparation would be wrong (spec section 6).

The environment fingerprint is deliberately *not* required to match. It covers
the execution profile and the prepared inputs, so requiring it would be
requiring the two runs to be identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.enums import DecisionDerivationStatus
from fpbench.core.errors import PairedSourceMismatchError, StorageError
from fpbench.core.identifiers import PairId
from fpbench.core.models import ComparisonPair
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.experiments.sourceafis_decisions import (
    SourceAfisDecisionExperimentSpec,
    load_decision_source,
)
from fpbench.experiments.sourceafis_evaluation import (
    SourceAfisEvaluationExperimentSpec,
    inspect_evaluation_experiment,
)
from fpbench.storage.decision_set_store import DecisionSetStore
from fpbench.storage.eligibility_set_store import EligibilitySetStore
from fpbench.storage.evaluation_view_store import EvaluationViewStore
from fpbench.storage.metric_set_store import MetricSetStore

__all__ = ["PairedSide", "load_paired_side", "require_comparable_runs"]

NATIVE_EXECUTION_PROFILE_ID = "native_identity_60s_v1"
CANONICAL_EXECUTION_PROFILE_ID = "canonical_500_lanczos3_60s_v1"

# These are the only execution-profile parameters allowed to differ. They all
# describe the input artefact handed to the unchanged matcher. Every operational
# parameter (including a future retry/parallelism knob) must compare equal.
_PREPARATION_PARAMETER_KEYS = frozenset(
    {
        "resolution_mode",
        "shared_resampling",
        "target_ppi",
        "preparation_set_id",
        "preparation_set_fingerprint",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "output_media_type",
        "output_pixel_format",
        "output_ppi_metadata_policy",
    }
)


@dataclass(frozen=True, slots=True)
class PairedSide:
    """One finished chain: run, results, decisions, eligibility, metrics."""

    label: str

    run: Any
    plan: Any
    result_set: Any
    pairs: Mapping[PairId, ComparisonPair]
    pair_manifest_hash: str
    units: tuple

    decision_profile: Any
    decision_manifest: Any
    decision_records: tuple
    eligibility_manifest: Any
    eligibility_records: tuple
    metric_manifest: Any

    decision_status: DecisionDerivationStatus
    research_status: Any

    result_store: Any

    @property
    def jobs_by_pair(self) -> Mapping[str, str]:
        return {
            str(planned.job.pair_id): planned.job.job_id for planned in self.plan.jobs
        }

    @property
    def decisions_by_job(self) -> Mapping[str, Any]:
        return {record.job_id: record for record in self.decision_records}

    @property
    def eligibility_by_unit(self) -> Mapping[str, Any]:
        return {
            record.eligibility_unit_id: record for record in self.eligibility_records
        }


def load_paired_side(
    *,
    label: str,
    spec: SourceAfisDecisionExperimentSpec,
    evaluation_spec: SourceAfisEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path,
    run_id: str,
    decision_set_id: str,
    metric_set_id: str,
    software: SoftwareProvenance,
) -> PairedSide:
    """Read one chain and revalidate it end to end.

    Every stage is re-derived rather than trusted, because "decision ready" and
    "evaluation ready" are claims about the current files and this comparison is
    about to rest its entire weight on both of them.
    """
    prepared = load_decision_source(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        software=software,
        require_expected_shape=True,
        require_definition=False,
    )
    if prepared.run.run_id != run_id:
        raise PairedSourceMismatchError(
            f"{label}: the workspace resolved run {prepared.run.run_id}, but this "
            f"comparison names {run_id}"
        )

    decision_store = DecisionSetStore(workspace)
    if not decision_store.has_decision_set(run_id, decision_set_id):
        raise PairedSourceMismatchError(
            f"{label}: run {run_id} holds no decision set {decision_set_id}; this "
            "comparison names one exact set and will not fall back to another"
        )
    decision_profile, decision_manifest, decision_records = (
        decision_store.read_decision_set(run_id, decision_set_id)
    )
    eligibility_manifest, eligibility_records = EligibilitySetStore(
        workspace
    ).read_eligibility_set(run_id, decision_set_id)

    metric_store = MetricSetStore(workspace)
    if not metric_store.has_metric_set(run_id, metric_set_id):
        raise PairedSourceMismatchError(
            f"{label}: run {run_id} holds no metric set {metric_set_id}"
        )
    metric_manifest = metric_store.read_manifest(run_id, metric_set_id)
    if metric_manifest.decision_set_id != decision_set_id:
        raise PairedSourceMismatchError(
            f"{label}: metric set {metric_set_id} was computed over decision set "
            f"{metric_manifest.decision_set_id}, not {decision_set_id}"
        )

    from fpbench.derivations import inspect_decision_derivation
    from fpbench.experiments.sourceafis_decisions import definition_store

    decision_state = inspect_decision_derivation(
        run=prepared.run,
        plan=prepared.plan,
        pairs=prepared.pairs,
        units=prepared.units,
        result_set=prepared.result_set,
        result_set_entries=prepared.result_set_entries,
        result_store=prepared.result_store,
        research_status=prepared.research_status,
        decision_profile=prepared.profile,
        definition=definition_store(workspace, spec.experiment_id).read_active(run_id),
        decision_set_id=decision_set_id,
        pair_manifest_hash=prepared.pair_manifest_hash,
        non_mated_finger_shift=spec.non_mated_finger_shift,
        workspace=workspace,
    )
    if not decision_state.is_decision_ready:
        raise PairedSourceMismatchError(
            f"{label}: decision set {decision_set_id} is "
            f"{decision_state.status.value}, not decision_ready "
            f"{list(decision_state.issues)[:3]}"
        )

    _require_evaluation_ready(
        label=label,
        spec=evaluation_spec,
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        metric_set_id=metric_set_id,
    )

    # Views are read to confirm they exist and verify; the paired layer derives
    # its own populations from the decisions and the eligibility set, so it does
    # not consume the view rows themselves.
    view_store = EvaluationViewStore(workspace)
    from fpbench.experiments.sourceafis_decisions import VIEW_KINDS

    for kind in VIEW_KINDS:
        try:
            view_store.read_view(run_id, decision_set_id, kind)
        except StorageError as exc:
            raise PairedSourceMismatchError(f"{label}: {exc}") from exc

    return PairedSide(
        label=label,
        run=prepared.run,
        plan=prepared.plan,
        result_set=prepared.result_set,
        pairs=prepared.pairs,
        pair_manifest_hash=prepared.pair_manifest_hash,
        units=prepared.units,
        decision_profile=decision_profile,
        decision_manifest=decision_manifest,
        decision_records=tuple(decision_records),
        eligibility_manifest=eligibility_manifest,
        eligibility_records=tuple(eligibility_records),
        metric_manifest=metric_manifest,
        decision_status=decision_state.status,
        research_status=prepared.research_status,
        result_store=prepared.result_store,
    )


def _require_evaluation_ready(
    *,
    label: str,
    spec: SourceAfisEvaluationExperimentSpec,
    workspace: Path,
    repository_root: Path,
    run_id: str,
    metric_set_id: str,
) -> None:
    """Require the source evaluation's complete, freshly rebuilt ready state."""
    state = inspect_evaluation_experiment(
        spec=spec,
        workspace=workspace,
        repository_root=repository_root,
        metric_set_id_override=metric_set_id,
    )
    if state.run_id != run_id:
        raise PairedSourceMismatchError(
            f"{label}: evaluation spec resolved run {state.run_id}, not the pinned "
            f"source run {run_id}"
        )
    if state.metric_set_id != metric_set_id:
        raise PairedSourceMismatchError(
            f"{label}: evaluation spec resolved metric set {state.metric_set_id}, "
            f"not the pinned source metric set {metric_set_id}"
        )
    if not state.is_evaluation_ready:
        raise PairedSourceMismatchError(
            f"{label}: source evaluation {metric_set_id} is "
            f"{state.status.value}, not evaluation_ready "
            f"{list(state.issues)[:3]}"
        )


def require_comparable_runs(
    *, native: PairedSide, canonical: PairedSide
) -> None:
    """Prove the two runs differ in the execution profile and nothing else.

    Raises:
        PairedSourceMismatchError: any of the twelve equalities fails, or the
            two execution profiles are the same.
    """
    checks: tuple[tuple[str, Any, Any], ...] = (
        ("protocol id", native.run.protocol_id, canonical.run.protocol_id),
        ("cohort id", str(native.run.cohort_id), str(canonical.run.cohort_id)),
        (
            "pair manifest hash",
            native.run.pair_manifest_hash,
            canonical.run.pair_manifest_hash,
        ),
        (
            "resolved pair manifest hash",
            native.pair_manifest_hash,
            canonical.pair_manifest_hash,
        ),
        (
            "algorithm id",
            native.run.algorithm.algorithm_id,
            canonical.run.algorithm.algorithm_id,
        ),
        (
            "algorithm fingerprint",
            native.run.algorithm_fingerprint,
            canonical.run.algorithm_fingerprint,
        ),
        (
            "implementation version",
            native.run.algorithm.implementation_version,
            canonical.run.algorithm.implementation_version,
        ),
        (
            "adapter id",
            native.run.algorithm.adapter_id,
            canonical.run.algorithm.adapter_id,
        ),
        (
            "adapter version",
            native.run.algorithm.adapter_version,
            canonical.run.algorithm.adapter_version,
        ),
        (
            "score direction",
            native.run.algorithm.score_direction,
            canonical.run.algorithm.score_direction,
        ),
        ("pair count", len(native.pairs), len(canonical.pairs)),
        ("planned jobs", native.plan.total_jobs, canonical.plan.total_jobs),
    )
    for label, left, right in checks:
        if left != right:
            raise PairedSourceMismatchError(
                f"the two runs disagree about {label}: {left!r} versus {right!r}. "
                "A paired comparison needs them to differ in the image preparation "
                "path and in nothing else"
            )

    _require_same_runtime(native, canonical)
    _require_same_threshold_rule(native, canonical)
    _require_only_preparation_profile_difference(native, canonical)
    if native.run.run_fingerprint == canonical.run.run_fingerprint:
        raise PairedSourceMismatchError(
            "both runs have the same fingerprint; there is nothing to compare"
        )


def _require_only_preparation_profile_difference(
    native: PairedSide, canonical: PairedSide
) -> None:
    """Allow only the named native/canonical image-preparation differences."""
    left = native.run.execution_profile
    right = canonical.run.execution_profile
    expected_ids = (
        ("native", left.profile_id, NATIVE_EXECUTION_PROFILE_ID),
        ("canonical", right.profile_id, CANONICAL_EXECUTION_PROFILE_ID),
    )
    for label, actual, expected in expected_ids:
        if actual != expected:
            raise PairedSourceMismatchError(
                f"the {label} run must use execution profile {expected!r}, got "
                f"{actual!r}"
            )

    for label, a, b in (
        ("timeout_seconds", left.timeout_seconds, right.timeout_seconds),
        ("deterministic_seed", left.deterministic_seed, right.deterministic_seed),
        ("replicate_index", native.run.replicate_index, canonical.run.replicate_index),
    ):
        if a != b:
            raise PairedSourceMismatchError(
                f"the execution profiles differ in {label}: {a!r} versus {b!r}. "
                "Only image preparation may differ"
            )

    left_operational = {
        key: value
        for key, value in dict(left.parameters).items()
        if key not in _PREPARATION_PARAMETER_KEYS
    }
    right_operational = {
        key: value
        for key, value in dict(right.parameters).items()
        if key not in _PREPARATION_PARAMETER_KEYS
    }
    if left_operational != right_operational:
        differing = sorted(
            key
            for key in set(left_operational) | set(right_operational)
            if left_operational.get(key) != right_operational.get(key)
        )
        raise PairedSourceMismatchError(
            "the execution profiles differ outside image preparation; "
            f"operational parameter(s): {differing}"
        )

    if any(planned.job.attempt != 1 for planned in (*native.plan.jobs, *canonical.plan.jobs)):
        raise PairedSourceMismatchError(
            "a paired run contains a retry attempt; stage 6B requires the same "
            "single-attempt policy on both sides"
        )


def _require_same_runtime(native: PairedSide, canonical: PairedSide) -> None:
    """Same bridge jar, same runtime bundle.

    A Maven shaded jar is not byte-reproducible, so two runs built from the same
    source can carry different jars. That difference is small and real, and it
    would sit inside any number this comparison produced.
    """
    for key in ("bridge.jar.sha256", "runtime.bundle.fingerprint"):
        left = native.run.environment.dependencies.get(key)
        right = canonical.run.environment.dependencies.get(key)
        if left is None or right is None:
            raise PairedSourceMismatchError(
                f"a run does not record {key}; the two executables cannot be "
                "compared"
            )
        if left != right:
            raise PairedSourceMismatchError(
                f"the two runs used different {key}: {str(left)[:12]}... versus "
                f"{str(right)[:12]}.... Rebuild is not reproducible, so pin the "
                "earlier run's jar with --build-jar rather than comparing two "
                "builds"
            )


def _require_same_threshold_rule(native: PairedSide, canonical: PairedSide) -> None:
    """Same threshold, same comparator, same origin — and two different profiles.

    Two different profile *ids* is expected and required: each one's scope names
    exactly one execution profile, so a single profile could not cover both runs.
    What must not differ is the rule itself.
    """
    left = native.decision_profile
    right = canonical.decision_profile
    for label, a, b in (
        ("threshold", left.threshold, right.threshold),
        ("comparator", left.comparator.value, right.comparator.value),
        ("threshold origin", left.origin.value, right.origin.value),
        ("score direction", left.score_direction.value, right.score_direction.value),
        (
            "algorithm fingerprint",
            left.algorithm_fingerprint,
            right.algorithm_fingerprint,
        ),
    ):
        if a != b:
            raise PairedSourceMismatchError(
                f"the two derivations used a different {label}: {a!r} versus {b!r}. "
                "The threshold is transferred unchanged precisely so that it is not "
                "a second variable"
            )
    if left.profile_id == right.profile_id:
        raise PairedSourceMismatchError(
            f"both derivations used decision profile {left.profile_id!r}. Each "
            "profile's scope names one execution profile, so one profile cannot "
            "legitimately cover both runs"
        )
    if left.calibration_performed or right.calibration_performed:
        raise PairedSourceMismatchError(
            "a decision profile reports a calibration; stage 6B compares two "
            "transfers of one documented threshold and has no calibrated side"
        )
