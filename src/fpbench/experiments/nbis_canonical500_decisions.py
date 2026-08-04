"""Applying NIST's documented ``score > 40`` to the 6,000 NBIS scores.

    python -m fpbench.experiments.nbis_canonical500_decisions prepare
    python -m fpbench.experiments.nbis_canonical500_decisions derive
    python -m fpbench.experiments.nbis_canonical500_decisions status
    python -m fpbench.experiments.nbis_canonical500_decisions finalize

The NBIS sibling of ``sourceafis_canonical500_decisions``, and a wrapper of the
same size for the same reason: the work happens in
:mod:`fpbench.experiments.algorithm_decisions`, shared with both SourceAFIS
chains, so the two algorithms' decisions cannot differ in *how* they were
derived. That is not a tidiness argument. Stage 7D ends in a comparison, and a
comparison between two sets of numbers produced by two implementations would be
a comparison of the implementations as much as of the algorithms.

What this module adds is the answer to one question — **is this NBIS run's
evidence chain sound enough to decide?** — and for NBIS that answer has a part
SourceAFIS's does not:

* the general research chain must be ``RESEARCH_READY``;
* the NBIS result-set validator must be clean;
* **Stage 7C's alignment must still hold**, re-derived from the manifests rather
  than read back, and its finalization marker must still be the one this
  workspace computes.

The last of those is what makes the run comparable at all. Being aligned row by
row with ``run_4c59fa02a6ab`` — same 6,000 pair ids, same order, same 3,000
prepared PNGs — is the property the whole of stage 7D rests on, and it lives in
Stage 7C's marker rather than in the general research chain (docs/adr/0054).

**The threshold is not chosen here and could not be.** It is read from
``configs/decisions/nbis_mindtct_bozorth3_5_0_0_nistir7391_gt40_canonical500_v1.yaml``,
which is a function of its own text and of the algorithm's fingerprint and of
nothing else. No score is read while it is loaded, no distribution is inspected,
and the comparator is ``greater_than`` because NIST wrote "greater than"
(docs/adr/0057, spec sections 10 and 11).

No NBIS executable runs. This module reads the 6,000 scores stage 7C stored and
does not modify them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from fpbench.core.derivation_models import (
    DecisionDerivationReceipt,
    DecisionDerivationState,
    SourceFinalizationIdentity,
)
from fpbench.core.errors import (
    ConfigurationError,
    DecisionProfileError,
    DerivationError,
    PreflightError,
    ResearchPreflightError,
)
from fpbench.core.models import ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.serialization import to_plain
from fpbench.eligibility.self_mapping import SelfIndependenceRequirement
from fpbench.experiments.algorithm_decisions import (
    AlgorithmDecisionExperimentSpec,
    PreparedDerivation,
    derive_decisions,
    finalize_decision_derivation,
    inspect_decisions,
    load_non_mated_finger_shift,
    prepare_decision_derivation,
)
from fpbench.experiments.decision_source_integration import (
    DecisionSourceIntegration,
    PreparationBinding,
    VerifiedDecisionSource,
)
from fpbench.experiments.nbis_validation import (
    SD300_CANONICAL500_INPUT_SET,
    validate_nbis_result_set,
)
from fpbench.experiments.sd300_inputs import (
    EXPECTED_JOBS,
    EXPECTED_PER_STAGE,
    EXPECTED_SUBJECTS,
)
from fpbench.execution.research import inspect_research_run
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "DEFAULT_DECISION_CONFIG",
    "NBIS_DECISION_INTEGRATION_ID",
    "EXPECTED_RUN_ID",
    "EXPECTED_RESULT_SET_ID",
    "EXPECTED_STAGE_7C_FINALIZATION_FINGERPRINT",
    "EXPECTED_ALIGNMENT_FINGERPRINT",
    "NBIS_SELF_INDEPENDENCE",
    "nbis_decision_integration",
    "load_nbis_decision_spec",
    "load_nbis_decision_source",
    "prepare_nbis_decision_derivation",
    "derive_nbis_decisions",
    "inspect_nbis_decisions",
    "finalize_nbis_decision_derivation",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

EXPERIMENT_ID = "nbis_canonical500_decisions_v1"

NBIS_DECISION_INTEGRATION_ID = "nbis_mindtct_bozorth3_decision_source_v1"

#: The algorithm this integration is for, as the run declares it.
_ALGORITHM_ID = "nbis_mindtct_bozorth3"

DEFAULT_DECISION_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "decisions"
    / "nbis_mindtct_bozorth3_5_0_0_nistir7391_gt40_canonical500_v1.yaml"
)

#: One committed file per NBIS decision set, kept apart from the SourceAFIS ones
#: so that neither can overwrite the other's evidence (spec section 37).
EVIDENCE_DIRECTORY = Path("evidence") / "nbis-canonical500-decisions"

# ------------------------------------------------------------ the fixed source
#
# Every one of these is written down here rather than discovered, and each is
# checked before a definition exists. A derivation that silently followed a
# pointer to a different run would be a derivation of something else with this
# experiment's name on it (spec section 27).

EXPECTED_RUN_ID = "run_f0468f28ffba"
EXPECTED_RESULT_SET_ID = "resultset_73a9d93a8528"
EXPECTED_STAGE_7C_FINALIZATION_FINGERPRINT = (
    "76a678adefef2c070161d15ccae1e1689ac85cefcbc83700fdbd36e7d906fb7e"
)
EXPECTED_ALIGNMENT_FINGERPRINT = (
    "d25b52159d251c2998bc55577d2e40f7a287d869b134dbe6aabbd3a3baa91686"
)

EXPECTED_DECISIONS = EXPECTED_JOBS  # 6,000
EXPECTED_ELIGIBILITY_UNITS = EXPECTED_PER_STAGE  # 1,500
EXPECTED_UNITS_PER_RELEASE = EXPECTED_SUBJECTS * 10  # 500
EXPECTED_VIEW_ROWS = EXPECTED_PER_STAGE  # 1,500

#: The kind name Stage 7C's marker carries, repeated here so the receipt records
#: *which* stage marker it bound rather than an anonymous digest.
STAGE_7C_FINALIZATION_KIND = "stage_7c_finalization"

#: What an NBIS SELF result must prove. Four keys rather than the default three:
#: the NBIS route records template *persistence* separately from template
#: caching, and a requirement that checked only the caching key would pass a
#: route that wrote templates to disk and reused them (spec section 32).
NBIS_SELF_INDEPENDENCE = SelfIndependenceRequirement(
    required_metadata={
        "extraction_policy": "independent_both_sides",
        "extraction_count": "2",
        "template_cache": "disabled",
        "template_persistence": "disabled",
    }
)


# ------------------------------------------------------------------ the seam


def _nbis_preparation_binding(workspace: Path) -> PreparationBinding:
    """The verified input set this derivation rests on, produced once.

    Built lazily, from the workspace, because it needs the prepared-image set's
    entries — and building it eagerly would make merely *importing* this module
    require a materialised set. Built once per invocation because the preflight
    behind it re-reads and re-decodes 3,000 canonical PNGs.
    """
    from fpbench.experiments.nbis_canonical500_full import (
        build_nbis_canonical500_spec,
        load_nbis_canonical500_config,
    )
    from fpbench.experiments.prepared_input_validation import (
        PreparedInputExpectations,
    )
    from fpbench.imaging.canonical500 import Canonical500ImagePreparer
    from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

    config = load_nbis_canonical500_config()
    spec = build_nbis_canonical500_spec(config)
    preparer = Canonical500ImagePreparer(
        store=PreparedImageSetStore(Path(workspace)),
        preparation_set_id=str(spec.preparation_set_id),
        preparation_set_fingerprint=str(spec.preparation_set_fingerprint),
    )
    preparer.preflight()
    return PreparationBinding(
        expectations=PreparedInputExpectations(
            execution_profile_id=spec.execution_profile.profile_id,
            preparer_id=preparer.preparer_id,
            preparer_version=preparer.preparer_version,
            runner_metadata_schema=preparer.runner_metadata_schema,
            preparation_set_id=str(spec.preparation_set_id),
            preparation_set_fingerprint=str(spec.preparation_set_fingerprint),
            transform_profile_id=str(spec.transform_profile_id),
            transform_profile_fingerprint=str(spec.transform_profile_fingerprint),
            transform_runtime_fingerprint=str(
                preparer.run_metadata()["transform_runtime_fingerprint"]
            ),
            target_ppi=int(spec.execution_profile.parameters["target_ppi"]),
            entries=preparer.prepared_entries(),
            expected_source_ppi=dict(spec.expected_source_ppi),
        ),
        manifest=preparer.prepared_manifest(),
    )


def nbis_decision_integration() -> DecisionSourceIntegration:
    """The seam: how to load and re-verify the finished Stage 7C run."""
    return DecisionSourceIntegration(
        integration_id=NBIS_DECISION_INTEGRATION_ID,
        algorithm_id=_ALGORITHM_ID,
        load_verified_source=load_nbis_decision_source,
        preparation_binding_factory=_nbis_preparation_binding,
    )


def load_nbis_decision_source(
    *,
    workspace: Path,
    repository_root: Path,
    run_id: str,
    software: SoftwareProvenance,
    require_ready: bool,
    preparation_binding: PreparationBinding | None,
) -> VerifiedDecisionSource:
    """Re-verify the Stage 7C run, alignment included, before anything is decided.

    Order matters, and each step is a place the whole thing stops
    (spec section 27):

    1. this is ``run_f0468f28ffba`` and no other run;
    2. its result set is ``resultset_73a9d93a8528``;
    3. the plan holds 6,000 jobs and the result set holds 6,000 results;
    4. the NBIS validator finds 6,000 successes and zero blocking failures;
    5. the general research chain re-verifies to ``RESEARCH_READY``;
    6. Stage 7C's alignment is re-derived from the manifests and is clean, and
       still fingerprints to what the committed evidence says;
    7. Stage 7C's finalization marker is the one this workspace computes.

    Steps 6 and 7 are not optional under ``require_ready=False``. A status
    reading over a run whose alignment has silently changed is not a status; the
    two runs would no longer be comparisons of the same inputs, and every number
    above them would mean something else.
    """
    workspace = Path(workspace)
    if run_id != EXPECTED_RUN_ID:
        raise ResearchPreflightError(
            f"this experiment decides run {EXPECTED_RUN_ID}; the workspace "
            f"resolved {run_id}. A different run is a different derivation and "
            "needs its own experiment"
        )

    result_store = ResultStore(workspace)
    run = result_store.read_run(run_id)
    plan = PlanStore(workspace).read_plan(run_id)
    result_set, result_set_entries = ResultSetStore(workspace).read_result_set(run_id)

    if result_set.result_set_id != EXPECTED_RESULT_SET_ID:
        raise ResearchPreflightError(
            f"run {run_id} now holds result set {result_set.result_set_id}; this "
            f"experiment is defined over {EXPECTED_RESULT_SET_ID}"
        )
    if plan.total_jobs != EXPECTED_DECISIONS:
        raise ResearchPreflightError(
            f"the plan holds {plan.total_jobs} jobs, expected {EXPECTED_DECISIONS}"
        )
    if len(result_set_entries) != EXPECTED_DECISIONS:
        raise ResearchPreflightError(
            f"the result set holds {len(result_set_entries)} results, expected "
            f"{EXPECTED_DECISIONS}"
        )

    manifests = ManifestStore(workspace)
    protocol_id = run.protocol_id
    cohort_id = str(run.cohort_id)
    pairs_list = manifests.read_pairs(protocol_id, cohort_id)
    pairs = {pair.pair_id: pair for pair in pairs_list}
    pair_manifest_hash = manifests.pair_manifest_metadata(protocol_id, cohort_id)[
        "pair_manifest_hash"
    ]

    dataset_ids = {pair.dataset_id for pair in pairs_list}
    if len(dataset_ids) != 1:
        raise ResearchPreflightError(
            f"the pair manifest spans datasets {sorted(dataset_ids)}; a derivation "
            "covers one"
        )
    dataset_id = dataset_ids.pop()
    images: dict[str, ImageRecord] = {}
    for release in sorted({pair.release for pair in pairs_list}):
        for image in manifests.read_images(dataset_id, release):
            images[image.image_id] = image

    runtime_reference = result_store.read_runtime_reference(run_id)
    validation = validate_nbis_result_set(
        run=run,
        plan=plan,
        pairs=pairs,
        images=images,
        result_store=result_store,
        runtime_reference=runtime_reference,
        preparation=preparation_binding.expectations if preparation_binding else None,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    if validation.total_results != EXPECTED_DECISIONS:
        raise ResearchPreflightError(
            f"the NBIS validator saw {validation.total_results} results, expected "
            f"{EXPECTED_DECISIONS}"
        )
    if validation.successful_results != EXPECTED_DECISIONS:
        raise ResearchPreflightError(
            f"{validation.successful_results} of {EXPECTED_DECISIONS} NBIS "
            "comparisons succeeded; stage 7C recorded 6,000 successes and a "
            "derivation over fewer would be a derivation over a different run"
        )
    if validation.blocking_failures:
        raise ResearchPreflightError(
            f"the NBIS run carries {validation.blocking_failures} blocking "
            "failure(s); a blocking failure is a broken harness, not an outcome"
        )

    research = inspect_research_run(
        run=run,
        plan=plan,
        result_store=result_store,
        pairs=pairs,
        algorithm_validation=validation,
        primary_asset_role=_primary_runtime_asset_role(),
        verifier_software=software,
        preparation_manifest=(
            preparation_binding.manifest if preparation_binding else None
        ),
    )

    stage_finalization = _require_stage_7c(
        workspace=workspace,
        repository_root=Path(repository_root),
        run_id=run_id,
    )

    return VerifiedDecisionSource(
        research_status=research.status,
        run=run,
        plan=plan,
        pairs=pairs,
        images=images,
        pair_manifest_hash=pair_manifest_hash,
        result_set=result_set,
        result_set_entries=result_set_entries,
        algorithm_validation_fingerprint=validation.validation_fingerprint,
        preparation_binding=preparation_binding,
        source_finalization=SourceFinalizationIdentity(
            research_finalization_fingerprint=(
                result_store.read_research_finalization(run_id).finalization_fingerprint
            ),
            stage_finalization_kind=STAGE_7C_FINALIZATION_KIND,
            stage_finalization_fingerprint=stage_finalization,
        ),
    )


def _primary_runtime_asset_role() -> str:
    """Which pinned file the research chain treats as this route's primary one.

    Read from the adapter's own declaration rather than repeated, so that the
    role name has one definition (docs/adr/0042).
    """
    from fpbench.adapters.nbis.adapter import PRIMARY_RUNTIME_ASSET_ROLE

    return PRIMARY_RUNTIME_ASSET_ROLE


def _require_stage_7c(
    *, workspace: Path, repository_root: Path, run_id: str
) -> str:
    """Re-derive Stage 7C's alignment and marker, and require both to hold.

    Returns:
        The Stage 7C finalization fingerprint, for the receipt to bind.

    Raises:
        ResearchPreflightError: the alignment is not clean, does not fingerprint
            to what the committed evidence records, or the stored marker is not
            the one this workspace derives.
    """
    from fpbench.experiments.nbis_canonical500_full import (
        STAGE_7C_FINALIZATION_NAME,
        verify_nbis_canonical500_alignment,
    )
    from fpbench.core.serialization import read_json

    report = verify_nbis_canonical500_alignment(
        workspace=workspace,
        repository_root=repository_root,
        run_id=run_id,
        require_clean=True,
    )
    if report.alignment_fingerprint != EXPECTED_ALIGNMENT_FINGERPRINT:
        raise ResearchPreflightError(
            "the Stage 7C alignment this workspace derives is "
            f"{report.alignment_fingerprint[:12]}..., but stage 7D is defined "
            f"against {EXPECTED_ALIGNMENT_FINGERPRINT[:12]}...; the two runs are "
            "no longer comparisons of the same inputs"
        )

    path = ResultStore(workspace).derived_path(run_id, STAGE_7C_FINALIZATION_NAME)
    if not path.is_file():
        raise ResearchPreflightError(
            f"run {run_id} carries no Stage 7C finalization marker; without it the "
            "alignment proof is not bound to the run's evidence (docs/adr/0054)"
        )
    stored = read_json(path)
    fingerprint = str(stored.get("stage_7c_finalization_fingerprint") or "")
    if fingerprint != EXPECTED_STAGE_7C_FINALIZATION_FINGERPRINT:
        raise ResearchPreflightError(
            f"the stored Stage 7C finalization is {fingerprint[:12]}..., but stage "
            f"7D is defined against {EXPECTED_STAGE_7C_FINALIZATION_FINGERPRINT[:12]}"
            "...; a re-finalised Stage 7C is a different source"
        )
    if str(stored.get("alignment_fingerprint")) != report.alignment_fingerprint:
        raise ResearchPreflightError(
            "the stored Stage 7C marker names a different alignment than the one "
            "this workspace now derives"
        )
    return fingerprint


# ------------------------------------------------------------------ the spec


def _decision_profile_evidence(prepared: PreparedDerivation, _set_id: str) -> Any:
    """The profile, as stored, for the evidence directory.

    A copy of the artefact the workspace already holds and already verified.
    Nothing is recomputed: the fingerprint in this file is the one the decisions
    were derived under, or the derivation would not have reached this point
    (spec section 37).
    """
    return to_plain(prepared.profile)


def _decision_finalization_evidence(prepared: PreparedDerivation, set_id: str) -> Any:
    """The finalization marker, as stored."""
    return to_plain(
        prepared.decision_store.read_finalization(prepared.run.run_id, set_id)
    )


def load_nbis_decision_spec(
    *,
    decision_profile_config: Path = DEFAULT_DECISION_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> AlgorithmDecisionExperimentSpec:
    """What the shared engine is given for the NBIS derivation."""
    from fpbench.experiments.nbis_canonical500_full import (
        DEFAULT_EXPERIMENT_CONFIG,
        load_nbis_canonical500_config,
    )

    source = load_nbis_canonical500_config(repository_root=repository_root)
    return AlgorithmDecisionExperimentSpec(
        experiment_id=EXPERIMENT_ID,
        source_experiment_id=source.experiment_id,
        source_experiment_config=Path(DEFAULT_EXPERIMENT_CONFIG),
        protocol_config=Path(source.protocol_config),
        decision_profile_config=Path(decision_profile_config),
        evidence_directory=EVIDENCE_DIRECTORY,
        expected_decisions=EXPECTED_DECISIONS,
        expected_eligibility_units=EXPECTED_ELIGIBILITY_UNITS,
        expected_rows_per_view=EXPECTED_VIEW_ROWS,
        expected_units_per_release=EXPECTED_UNITS_PER_RELEASE,
        non_mated_finger_shift=load_non_mated_finger_shift(source.protocol_config),
        integration=nbis_decision_integration(),
        self_independence=NBIS_SELF_INDEPENDENCE,
        # Schema 2, because this receipt binds Stage 7C's marker, the derivation
        # definition and the derivation software identity. The SourceAFIS
        # receipts stay schema 1 and stay byte-identical (spec sections 25, 36).
        receipt_schema_version="2",
        extra_evidence={
            "decision-profile.json": _decision_profile_evidence,
            "decision-finalization.json": _decision_finalization_evidence,
        },
    )


# ------------------------------------------------------------------ commands


def prepare_nbis_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: AlgorithmDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> PreparedDerivation:
    return prepare_decision_derivation(
        spec=config or load_nbis_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )


def derive_nbis_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: AlgorithmDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> str:
    return derive_decisions(
        spec=config or load_nbis_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )


def inspect_nbis_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: AlgorithmDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationState:
    return inspect_decisions(
        spec=config or load_nbis_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        decision_set_id=decision_set_id,
    )


def finalize_nbis_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: AlgorithmDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationReceipt:
    return finalize_decision_derivation(
        spec=config or load_nbis_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        decision_set_id=decision_set_id,
    )


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.nbis_canonical500_decisions",
        description=(
            "Apply NIST's documented BOZORTH3 rule of thumb - score greater than "
            "40 - to the finished NBIS canonical 500 ppi run. Produces decisions, "
            "SELF eligibility and evaluation views; calibrates nothing, computes "
            "no metric, and equates no operating point."
        ),
    )
    parser.add_argument("command", choices=("prepare", "derive", "status", "finalize"))
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_DECISION_CONFIG)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--decision-set-id", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        config = load_nbis_decision_spec(decision_profile_config=arguments.profile)
        shared = {"workspace": arguments.workspace, "config": config}

        if arguments.command == "prepare":
            prepared = prepare_nbis_decision_derivation(
                **shared, run_id=arguments.run_id
            )
            print(f"run          {prepared.run.run_id}")
            print(f"result set   {prepared.result_set.result_set_id}")
            print(f"profile      {prepared.profile.profile_id}")
            print(
                f"threshold    {prepared.profile.threshold} "
                f"({prepared.profile.comparator.value}, "
                f"{prepared.profile.origin.value}, schema "
                f"{prepared.profile.schema_version})"
            )
            print(
                "stage 7C     "
                f"{prepared.source_finalization.stage_finalization_fingerprint[:12]}..."
            )
            print(f"definition   {prepared.definition.definition_id}")
            print(f"units        {len(prepared.units)}")
            return 0

        if arguments.command == "derive":
            set_id = derive_nbis_decisions(**shared, run_id=arguments.run_id)
            print(f"decision set {set_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_nbis_decisions(
                **shared,
                run_id=arguments.run_id,
                decision_set_id=arguments.decision_set_id,
            )
            print(f"run          {state.run_id}")
            print(f"decision set {state.decision_set_id or '-'}")
            print(f"status       {state.status.value}")
            print(
                "source       "
                f"{'research_ready' if state.source_research_ready else 'not ready'}"
            )
            print(
                f"decisions    {state.total_decisions} "
                f"({state.decided_count} decided, "
                f"{state.undecidable_count} undecidable) "
                f"{'valid' if state.decision_set_valid else 'unverified'}"
            )
            print(
                f"eligibility  {state.total_eligibility_units} units "
                f"{'valid' if state.eligibility_valid else 'unverified'}"
            )
            print(f"views        {state.views_valid} of 3 valid")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            print(f"finalized    {'valid' if state.finalization_valid else 'no'}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        receipt = finalize_nbis_decision_derivation(
            **shared,
            run_id=arguments.run_id,
            decision_set_id=arguments.decision_set_id,
        )
        print(f"run          {receipt.run_id}")
        print(f"decision set {receipt.decision_set_id}")
        print(
            f"eligibility  {receipt.eligibility_set_id} "
            f"({receipt.total_eligibility_units} units)"
        )
        print(
            f"decisions    {receipt.total_decisions} "
            f"({receipt.decided_count} decided, "
            f"{receipt.undecidable_count} undecidable)"
        )
        for kind, rows in sorted(receipt.view_total_rows.items()):
            print(f"  view       {kind}: {rows} rows")
        print(
            "stage 7C     "
            f"{str(receipt.source_stage_finalization_fingerprint)[:12]}..."
        )
        print(
            f"receipt      evidence/nbis-canonical500-decisions/"
            f"{receipt.decision_set_id}.json"
        )
        print(receipt.statement)
        return 0
    except (
        PreflightError,
        ConfigurationError,
        DecisionProfileError,
        DerivationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
