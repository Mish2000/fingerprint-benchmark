"""Applying threshold 40 to the 6,000 native SourceAFIS scores, in four commands.

    python -m fpbench.experiments.sourceafis_native_decisions prepare
    python -m fpbench.experiments.sourceafis_native_decisions derive
    python -m fpbench.experiments.sourceafis_native_decisions status
    python -m fpbench.experiments.sourceafis_native_decisions finalize

Since stage 6B the work happens in
:mod:`fpbench.experiments.sourceafis_decisions`, shared with the canonical
derivation. This module is what that engine is given: the native run's
experiment id, the native decision profile, the native evidence directory, and
the shape stage 4B's run implies.

The extraction was deliberate and it is load-bearing. If the two derivations were
two files, a difference between the native and canonical numbers could be a
difference in how they were derived. It cannot be, because there is one
derivation engine and both wrappers call it.

Nothing about this derivation's identity changed when the code moved. Same
profile, same run, same result set, same derivation-definition fingerprint, and
therefore the same `decisionset_0122544e71b1`, the same
`eligibilityset_77dbf75cdc76` and the same three view fingerprints — which a
regression test asserts rather than assumes (spec section 4).

What it does *not* do bears repeating, because a file called "native_decisions"
invites the assumption: it computes no rate, no distribution, and no accuracy
figure of any kind. It says which comparisons crossed a documented threshold and
which fingers are usable for conditional reporting (docs/adr/0003).
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
    ResearchPreflightError,
)
from fpbench.derivations.receipt import EVIDENCE_DIRECTORY
from fpbench.experiments.sd300_inputs import (
    EXPECTED_JOBS,
    EXPECTED_PER_STAGE,
    EXPECTED_SUBJECTS,
)
from fpbench.experiments.sourceafis_decisions import (
    PreparedDerivation,
    SourceAfisDecisionExperimentSpec,
    build_sourceafis_decision_spec,
    derive_decisions,
    finalize_decision_derivation,
    inspect_decisions,
    load_decision_source,
    load_non_mated_finger_shift,
    prepare_decision_derivation,
    read_decision_set_pointer,
)

__all__ = [
    "DecisionExperimentConfig",
    "PreparedDerivation",
    "EXPERIMENT_ID",
    "load_decision_experiment_config",
    "load_decision_source",
    "prepare_native_decision_derivation",
    "derive_native_decisions",
    "inspect_sourceafis_native_decisions",
    "finalize_native_decision_derivation",
    "EXPECTED_DECISIONS",
    "EXPECTED_ELIGIBILITY_UNITS",
    "EXPECTED_VIEW_ROWS",
    "main",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE = REPOSITORY_ROOT / "workspace"
DEFAULT_DECISION_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "decisions"
    / "sourceafis_java_3_18_1_documented_40_v1.yaml"
)

EXPERIMENT_ID = "sourceafis_native_decisions_v1"

#: The shape stage 4B's run implies. Asserted in this module rather than in the
#: shared engine, for the same reason the 6,000-job counts live in the run's
#: experiment module: they are true of this protocol, not of derivations.
EXPECTED_DECISIONS = EXPECTED_JOBS  # 6,000
EXPECTED_ELIGIBILITY_UNITS = EXPECTED_PER_STAGE  # 1,500
EXPECTED_UNITS_PER_RELEASE = EXPECTED_SUBJECTS * 10  # 500
EXPECTED_VIEW_ROWS = EXPECTED_PER_STAGE  # 1,500

#: Kept as an alias so that stage 5A/5B callers importing the old name still
#: work. The spec object *is* the configuration now.
DecisionExperimentConfig = SourceAfisDecisionExperimentSpec


def load_decision_experiment_config(
    *,
    decision_profile_config: Path = DEFAULT_DECISION_CONFIG,
    repository_root: Path = REPOSITORY_ROOT,
) -> SourceAfisDecisionExperimentSpec:
    """Assemble the native derivation's specification.

    Reading the native run's experiment config here — rather than in the shared
    engine — is what keeps the engine free of any dependency on either run
    module (spec section 12).
    """
    from fpbench.experiments.sourceafis_native_full import (
        DEFAULT_EXPERIMENT_CONFIG,
        load_experiment_config,
    )

    source = load_experiment_config(repository_root=repository_root)
    return build_sourceafis_decision_spec(
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
        # The native run materialised nothing, so there is no input set for its
        # results to be checked against.
        preparation_binding=None,
    )


# ------------------------------------------------------------------ commands


def prepare_native_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> PreparedDerivation:
    return prepare_decision_derivation(
        spec=config or load_decision_experiment_config(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )


def derive_native_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    require_expected_shape: bool = True,
) -> str:
    return derive_decisions(
        spec=config or load_decision_experiment_config(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        require_expected_shape=require_expected_shape,
    )


def inspect_sourceafis_native_decisions(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationState:
    return inspect_decisions(
        spec=config or load_decision_experiment_config(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        decision_set_id=decision_set_id,
    )


def finalize_native_decision_derivation(
    *,
    workspace: Path = DEFAULT_WORKSPACE,
    config: SourceAfisDecisionExperimentSpec | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    run_id: str | None = None,
    decision_set_id: str | None = None,
) -> DecisionDerivationReceipt:
    return finalize_decision_derivation(
        spec=config or load_decision_experiment_config(repository_root=repository_root),
        workspace=Path(workspace),
        repository_root=repository_root,
        run_id=run_id,
        decision_set_id=decision_set_id,
    )


#: Historical names, kept so that stage 5A/5B tests and callers keep working.
prepare_decision_derivation_native = prepare_native_decision_derivation


# --------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpbench.experiments.sourceafis_native_decisions",
        description=(
            "Apply a documented threshold to the finished native SourceAFIS run. "
            "Produces decisions, SELF eligibility and evaluation views; computes "
            "no metric and makes no accuracy claim."
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
        config = load_decision_experiment_config(
            decision_profile_config=arguments.profile
        )
        shared = {"workspace": arguments.workspace, "config": config}

        if arguments.command == "prepare":
            prepared = prepare_native_decision_derivation(
                **shared, run_id=arguments.run_id
            )
            print(f"run          {prepared.run.run_id}")
            print(f"result set   {prepared.result_set.result_set_id}")
            print(f"profile      {prepared.profile.profile_id}")
            print(f"threshold    {prepared.profile.threshold} "
                  f"({prepared.profile.comparator.value}, "
                  f"{prepared.profile.origin.value})")
            print(f"definition   {prepared.definition.definition_id}")
            print(f"units        {len(prepared.units)}")
            return 0

        if arguments.command == "derive":
            set_id = derive_native_decisions(**shared, run_id=arguments.run_id)
            print(f"decision set {set_id}")
            print("next         finalize")
            return 0

        if arguments.command == "status":
            state = inspect_sourceafis_native_decisions(
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

        receipt = finalize_native_decision_derivation(
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
        print(f"receipt      evidence/sourceafis-native-decisions/"
              f"{receipt.decision_set_id}.json")
        print(receipt.statement)
        return 0
    except (
        ResearchPreflightError,
        ConfigurationError,
        DecisionProfileError,
        DerivationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
