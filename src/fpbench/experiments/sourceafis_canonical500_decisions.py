"""Applying the same threshold 40 to the 6,000 canonical SourceAFIS scores.

    python -m fpbench.experiments.sourceafis_canonical500_decisions prepare
    python -m fpbench.experiments.sourceafis_canonical500_decisions derive
    python -m fpbench.experiments.sourceafis_canonical500_decisions status
    python -m fpbench.experiments.sourceafis_canonical500_decisions finalize

The canonical sibling of ``sourceafis_native_decisions``, and it is a wrapper of
the same size for the same reason: the work happens in
:mod:`fpbench.experiments.sourceafis_decisions`, shared with the native
derivation, so the two sets of decisions cannot differ in how they were derived.

Four things differ from the native wrapper, and all four are data:

* the run pointer it reads — the canonical experiment's, not the native one's;
* the decision profile — ``..._canonical500_v1``, whose scope is
  ``canonical_500_lanczos3_60s_v1`` and nothing else;
* the evidence directory;
* the preparation expectations, which is the one thing the canonical derivation
  checks that the native one has nothing to check: every stored result must name
  the exact prepared-image set it was produced from, and every claim it makes
  about that set must match the set's own entries.

**The threshold is not re-chosen.** 40 is transferred unchanged, which is what
makes the paired comparison in the last part of stage 6B a comparison of one
variable. Nothing here calibrates anything and nothing here may (spec section 9).

No Java is run. This module reads the 6,000 scores stage 6A produced and does not
modify them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from fpbench.core.derivation_models import (
    DecisionDerivationReceipt,
    DecisionDerivationState,
)
from fpbench.core.errors import (
    ConfigurationError,
    DecisionProfileError,
    DerivationError,
    PreflightError,
)
from fpbench.experiments.sd300_inputs import (
    EXPECTED_JOBS,
    EXPECTED_PER_STAGE,
    EXPECTED_SUBJECTS,
)
from fpbench.experiments.sourceafis_decisions import (
    PreparedDerivation,
    SourceAfisDecisionExperimentSpec,
    derive_decisions,
    finalize_decision_derivation,
    inspect_decisions,
    load_non_mated_finger_shift,
    prepare_decision_derivation,
)

__all__ = [
    "EXPERIMENT_ID",
    "EVIDENCE_DIRECTORY",
    "DEFAULT_DECISION_CONFIG",
    "load_canonical_decision_spec",
    "prepare_canonical_decision_derivation",
    "derive_canonical_decisions",
    "inspect_canonical_decisions",
    "finalize_canonical_decision_derivation",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"

EXPERIMENT_ID = "sourceafis_canonical500_decisions_v1"

DEFAULT_DECISION_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "decisions"
    / "sourceafis_java_3_18_1_documented_40_canonical500_v1.yaml"
)

#: One committed file per canonical decision set, kept apart from the native
#: ones so that neither can overwrite the other's evidence.
EVIDENCE_DIRECTORY = Path("evidence") / "sourceafis-canonical500-decisions"

EXPECTED_DECISIONS = EXPECTED_JOBS  # 6,000
EXPECTED_ELIGIBILITY_UNITS = EXPECTED_PER_STAGE  # 1,500
EXPECTED_UNITS_PER_RELEASE = EXPECTED_SUBJECTS * 10  # 500
EXPECTED_VIEW_ROWS = EXPECTED_PER_STAGE  # 1,500


def _canonical_preparation_expectations(workspace: Path):
    """What every canonical result must claim about the input set it used.

    Built lazily, from the workspace, because it needs the prepared-image set's
    entries — and building it eagerly would make merely *importing* this module
    require a materialised set.
    """
    from fpbench.experiments.sourceafis_canonical500_full import (
        canonical_preparer_factory,
        load_canonical_experiment_config,
    )
    from fpbench.experiments.sourceafis_validation import (
        CanonicalPreparationExpectations,
    )

    config = load_canonical_experiment_config()
    spec = config.to_spec()
    preparer = canonical_preparer_factory(Path(workspace), spec)
    preparer.preflight()
    return CanonicalPreparationExpectations(
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
    )


def load_canonical_decision_spec(
    *,
    decision_profile_config: Path = DEFAULT_DECISION_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> SourceAfisDecisionExperimentSpec:
    """What the shared engine is given for the canonical derivation."""
    from fpbench.experiments.sourceafis_canonical500_full import (
        DEFAULT_EXPERIMENT_CONFIG,
        load_canonical_experiment_config,
    )

    source = load_canonical_experiment_config(repository_root=repository_root)
    return SourceAfisDecisionExperimentSpec(
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
        preparation_expectations=_canonical_preparation_expectations,
    )


# ------------------------------------------------------------------ commands


def prepare_canonical_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> PreparedDerivation:
    return prepare_decision_derivation(
        spec=config or load_canonical_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )


def derive_canonical_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> str:
    return derive_decisions(
        spec=config or load_canonical_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )


def inspect_canonical_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationState:
    return inspect_decisions(
        spec=config or load_canonical_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        decision_set_id=decision_set_id,
    )


def finalize_canonical_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationReceipt:
    return finalize_decision_derivation(
        spec=config or load_canonical_decision_spec(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        decision_set_id=decision_set_id,
    )


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_canonical500_decisions",
        description=(
            "Apply SourceAFIS's documented threshold 40, transferred unchanged, to "
            "the finished canonical 500 ppi run. Produces decisions, SELF "
            "eligibility and evaluation views; calibrates nothing and computes no "
            "metric."
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
        config = load_canonical_decision_spec(
            decision_profile_config=arguments.profile
        )
        shared = {"workspace": arguments.workspace, "config": config}

        if arguments.command == "prepare":
            prepared = prepare_canonical_decision_derivation(
                **shared, run_id=arguments.run_id
            )
            print(f"run          {prepared.run.run_id}")
            print(f"result set   {prepared.result_set.result_set_id}")
            print(f"profile      {prepared.profile.profile_id}")
            print(f"threshold    {prepared.profile.threshold} "
                  f"({prepared.profile.comparator.value}, "
                  f"{prepared.profile.origin.value})")
            print(f"transferred  from "
                  f"{prepared.profile.metadata.get('transfer.source_profile_id')} "
                  f"(unchanged)")
            print(f"definition   {prepared.definition.definition_id}")
            print(f"units        {len(prepared.units)}")
            return 0

        if arguments.command == "derive":
            set_id = derive_canonical_decisions(**shared, run_id=arguments.run_id)
            print(f"decision set {set_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_canonical_decisions(
                **shared,
                run_id=arguments.run_id,
                decision_set_id=arguments.decision_set_id,
            )
            print(f"run          {state.run_id}")
            print(f"decision set {state.decision_set_id or '-'}")
            print(f"status       {state.status.value}")
            print(f"source       "
                  f"{'research_ready' if state.source_research_ready else 'not ready'}")
            print(f"decisions    {state.total_decisions} "
                  f"({state.decided_count} decided, "
                  f"{state.undecidable_count} undecidable) "
                  f"{'valid' if state.decision_set_valid else 'unverified'}")
            print(f"eligibility  {state.total_eligibility_units} units "
                  f"{'valid' if state.eligibility_valid else 'unverified'}")
            print(f"views        {state.views_valid} of 3 valid")
            print(f"receipt      {'valid' if state.receipt_valid else 'no'}")
            print(f"finalized    {'valid' if state.finalization_valid else 'no'}")
            for issue in state.issues:
                print(f"  issue      {issue}")
            return 0

        receipt = finalize_canonical_decision_derivation(
            **shared,
            run_id=arguments.run_id,
            decision_set_id=arguments.decision_set_id,
        )
        print(f"run          {receipt.run_id}")
        print(f"decision set {receipt.decision_set_id}")
        print(f"eligibility  {receipt.eligibility_set_id} "
              f"({receipt.total_eligibility_units} units)")
        print(f"decisions    {receipt.total_decisions} "
              f"({receipt.decided_count} decided, "
              f"{receipt.undecidable_count} undecidable)")
        for kind, rows in sorted(receipt.view_total_rows.items()):
            print(f"  view       {kind}: {rows} rows")
        print(f"receipt      evidence/sourceafis-canonical500-decisions/"
              f"{receipt.decision_set_id}.json")
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
