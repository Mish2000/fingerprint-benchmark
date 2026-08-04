"""How a finished SourceAFIS run is presented to the shared decision engine.

Stage 5A put the whole derivation in this module. Stage 6B generalised it over
two SourceAFIS runs. Stage 7D moved everything that was not about SourceAFIS
into :mod:`fpbench.experiments.algorithm_decisions`, and what is left here is the
answer to one question:

    **is this SourceAFIS run's evidence chain sound enough to decide?**

Three things go into that answer, and all three already existed:

* the SourceAFIS result-set validator, which knows which recorded failures are
  biometric outcomes and which mean the bridge broke;
* the general research inspection, told which runtime asset is the primary one —
  for this route, the bridge jar;
* the prepared-image set, for a canonical run, which every stored result must
  claim to have been produced from.

Everything downstream of that answer — the threshold, the eligibility rule, the
three views, the receipt, the marker, the status — is shared with every other
algorithm, and stage 7D's comparison depends on it being shared. Two
implementations would mean any difference between two sets of numbers could be a
difference in how they were derived (docs/adr/0056).

The public names stage 5A and stage 6B callers use are all still here and still
mean what they meant. ``SourceAfisDecisionExperimentSpec`` is now an alias for
the neutral spec, because there is nothing SourceAFIS-shaped about it any more.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpbench.adapters.sourceafis_java.config import BRIDGE_JAR_ROLE
from fpbench.core.derivation_models import SourceFinalizationIdentity
from fpbench.core.errors import DecisionDerivationError
from fpbench.core.models import ImageRecord
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.execution.research import inspect_research_run
from fpbench.experiments.algorithm_decisions import (
    REPOSITORY_ROOT,
    VIEW_KINDS,
    AlgorithmDecisionExperimentSpec,
    PreparedDerivation,
    definition_store,
    derive_decisions,
    finalize_decision_derivation,
    inspect_decisions,
    load_decision_source,
    load_non_mated_finger_shift,
    prepare_decision_derivation,
    read_decision_set_pointer,
)
from fpbench.experiments.decision_source_integration import (
    DecisionSourceIntegration,
    PreparationBinding,
    VerifiedDecisionSource,
)
from fpbench.experiments.sourceafis_validation import validate_sourceafis_result_set
from fpbench.storage.manifest_store import ManifestStore
from fpbench.storage.plan_store import PlanStore
from fpbench.storage.result_set_store import ResultSetStore
from fpbench.storage.result_store import ResultStore

__all__ = [
    "SOURCEAFIS_DECISION_INTEGRATION_ID",
    "SourceAfisDecisionExperimentSpec",
    "PreparedDerivation",
    "PreparationBinding",
    "PreparationBindingFactory",
    "sourceafis_decision_integration",
    "build_sourceafis_decision_spec",
    "load_sourceafis_decision_source",
    "load_non_mated_finger_shift",
    "load_decision_source",
    "prepare_decision_derivation",
    "derive_decisions",
    "inspect_decisions",
    "finalize_decision_derivation",
    "read_decision_set_pointer",
    "definition_store",
    "REPOSITORY_ROOT",
    "VIEW_KINDS",
]

SOURCEAFIS_DECISION_INTEGRATION_ID = "sourceafis_java_decision_source_v1"

#: The algorithm this integration is for, as the run declares it. Checked, never
#: branched on.
_ALGORITHM_ID = "sourceafis_java"

#: Historical name. It described a SourceAFIS-only spec; the spec is now neutral,
#: and the name is kept so stage 5A and 6B annotations keep resolving.
SourceAfisDecisionExperimentSpec = AlgorithmDecisionExperimentSpec

#: Builds a :class:`PreparationBinding` from a workspace. ``None`` for a run
#: whose images were passed through untouched — there is no input set to check
#: against, and inventing one would fail 6,000 already-stored native results on a
#: check they were never subject to.
PreparationBindingFactory = Any


def sourceafis_decision_integration(
    preparation_binding_factory: Any = None,
) -> DecisionSourceIntegration:
    """The seam: how to load and re-verify one finished SourceAFIS run."""
    return DecisionSourceIntegration(
        integration_id=SOURCEAFIS_DECISION_INTEGRATION_ID,
        algorithm_id=_ALGORITHM_ID,
        load_verified_source=load_sourceafis_decision_source,
        preparation_binding_factory=preparation_binding_factory,
    )


def build_sourceafis_decision_spec(
    *,
    experiment_id: str,
    source_experiment_id: str,
    protocol_config: Path,
    decision_profile_config: Path,
    evidence_directory: Path,
    expected_decisions: int,
    expected_eligibility_units: int,
    expected_rows_per_view: int,
    expected_units_per_release: int,
    non_mated_finger_shift: int,
    source_experiment_config: Path | None = None,
    preparation_binding: Any = None,
) -> AlgorithmDecisionExperimentSpec:
    """What the shared engine is given for a SourceAFIS derivation.

    ``receipt_schema_version`` is deliberately not a parameter. The four
    SourceAFIS receipts this project has published are schema 1, and a schema-2
    receipt over the same chain would be a different artefact with a different
    digest — which is the one thing stage 7D may not produce (spec section 25).
    """
    return AlgorithmDecisionExperimentSpec(
        experiment_id=experiment_id,
        source_experiment_id=source_experiment_id,
        source_experiment_config=source_experiment_config,
        protocol_config=Path(protocol_config),
        decision_profile_config=Path(decision_profile_config),
        evidence_directory=Path(evidence_directory),
        expected_decisions=expected_decisions,
        expected_eligibility_units=expected_eligibility_units,
        expected_rows_per_view=expected_rows_per_view,
        expected_units_per_release=expected_units_per_release,
        non_mated_finger_shift=non_mated_finger_shift,
        integration=sourceafis_decision_integration(preparation_binding),
    )


def load_sourceafis_decision_source(
    *,
    workspace: Path,
    repository_root: Path,
    run_id: str,
    software: SoftwareProvenance,
    require_ready: bool,
    preparation_binding: PreparationBinding | None,
) -> VerifiedDecisionSource:
    """Re-verify one finished SourceAFIS run, and hand back what it implies.

    The run's own algorithm-evidence validation is re-run here rather than taken
    on trust, because "research ready" is a claim about the current files and a
    derivation is about to rest its entire weight on it.

    ``require_ready`` is not a licence to skip checks. Every check still runs;
    the flag only decides whether an unready run raises here or is reported by
    the caller as a status — which is how ``status`` manages to explain a broken
    chain instead of refusing to look at it.
    """
    workspace = Path(workspace)
    result_store = ResultStore(workspace)
    run = result_store.read_run(run_id)
    plan = PlanStore(workspace).read_plan(run_id)
    result_set, result_set_entries = ResultSetStore(workspace).read_result_set(run_id)

    manifests = ManifestStore(workspace)
    protocol_id = run.protocol_id
    cohort_id = str(run.cohort_id)
    pairs_list = manifests.read_pairs(protocol_id, cohort_id)
    pairs = {pair.pair_id: pair for pair in pairs_list}
    pair_manifest_hash = manifests.pair_manifest_metadata(protocol_id, cohort_id)[
        "pair_manifest_hash"
    ]

    # The dataset the pairs belong to, taken from the pairs themselves rather
    # than from a config that may have moved on since the run was executed.
    dataset_ids = {pair.dataset_id for pair in pairs_list}
    if len(dataset_ids) != 1:
        raise DecisionDerivationError(
            f"the pair manifest spans datasets {sorted(dataset_ids)}; a derivation "
            "covers one"
        )
    dataset_id = dataset_ids.pop()

    images: dict[str, ImageRecord] = {}
    for release in sorted({pair.release for pair in pairs_list}):
        for image in manifests.read_images(dataset_id, release):
            images[image.image_id] = image

    runtime_reference = result_store.read_runtime_reference(run_id)
    validation = validate_sourceafis_result_set(
        run=run,
        plan=plan,
        pairs=pairs,
        images=images,
        result_store=result_store,
        runtime_reference=runtime_reference,
        preparation=preparation_binding.expectations if preparation_binding else None,
    )
    research = inspect_research_run(
        run=run,
        plan=plan,
        result_store=result_store,
        pairs=pairs,
        algorithm_validation=validation,
        primary_asset_role=BRIDGE_JAR_ROLE,
        verifier_software=software,
        preparation_manifest=(
            preparation_binding.manifest if preparation_binding else None
        ),
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
            )
        ),
    )
