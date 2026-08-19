"""What Stage 20B is, and the one verdict the code refuses to reach on its own.

Stage 20B runs the candidate Stage 20A qualified — ``MINDTCT → official MCC SDK
v2.0`` — over the same 6,000 comparisons the other algorithms ran, with no
threshold, no decision, no calibration and no metric.

TWO QUESTIONS, DELIBERATELY SEPARATED

**Did the raw run complete?** Arithmetic, and the code answers it:

.. code-block:: text

    expected_outcomes = 6000
    stored_outcomes   = 6000
    missing           = 0

Every attempt appears, including the ones that failed. A run with algorithmic
failures in it is still a complete raw run.

**Should MCC become the preferred fifth method?** Section 26 froze the *reason*
before the run, so that nobody could look at the scores afterwards and pick the
prettier distribution:

.. code-block:: text

    MCC              official SDK, unmodified upstream matcher
    OpenAFIS 19B     project-defined capacity extension, modified upstream source

Both share MINDTCT, so OpenAFIS has no independence advantage to weigh against
that. The preference is therefore ``OFFICIAL_UNMODIFIED_MATCHER_ROUTE`` and
``selection_based_on_sd300_accuracy`` is ``false`` — settled here, in source,
before a single canonical image was opened.

**But the preference is conditional, and section 33 says on what.** If all 6,000
comparisons are score-bearing and no systemic defect appears, the code may reach
it. If some structured failures remain, the raw run still closes and the fifth
slot waits for one human review: :data:`FAILURE_REVIEW` is a constant a person
edits after reading the classification, exactly as Stage 19A's sufficiency
constant is. An automatic 90%/95% rule would be the one place in this stage where
the answer chose itself.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "STAGE",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "DISPLAY_NAME",
    "EXPERIMENT_ID",
    "RUN_ID",
    "EXPECTED_OUTCOMES",
    "NBIS_VERSION",
    "NBIS_BUILD_ID",
    "MCC_SDK_VERSION",
    "REFERENCE_PREPARATION_SET_ID",
    "REFERENCE_PAIR_MANIFEST_HASH",
    "PROTOCOL_STAGES",
    "GATE_B_SUBSET_RULE",
    "GATE_B_SUBSET",
    "PREFERENCE_REASON",
    "FAILURE_REVIEW",
    "FAILURE_REVIEW_STATES",
    "OUTCOME_COMPLETE",
    "OUTCOME_GATE_A_FAIL",
    "OUTCOME_GATE_B_FAIL",
    "EVIDENCE_DIRECTORY",
    "STAGE_20B_FINALIZATION_NAME",
    "EVIDENCE_DOCUMENTS",
    "SUPERVISOR_DISCLOSURE",
]

STAGE = "20B"
ALGORITHM_ID = "nbis_mindtct_mcc_sdk_v2"
ADAPTER_ID = "nbis_mindtct_mcc_sdk_v2_subprocess"
DISPLAY_NAME = "NBIS MINDTCT + MCC SDK v2.0"
EXPERIMENT_ID = "stage20b_mindtct_mcc_canonical500_raw"
RUN_ID = "run_stage20b_canonical500"

EXPECTED_OUTCOMES = 6000

NBIS_VERSION = "5.0.0"
#: The certified build Algorithm 2 runs. Stage 20B runs *this* one, not a
#: MINDTCT compiled for convenience on the host that has the SDK.
NBIS_BUILD_ID = "658f9f54a8f2"
MCC_SDK_VERSION = "2.0.0.0"

REFERENCE_PREPARATION_SET_ID = "prepset_be560e047991"
REFERENCE_PAIR_MANIFEST_HASH = (
    "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
)

#: The four cells of the manifest, 1,500 comparisons each.
PROTOCOL_STAGES: tuple[str, ...] = (
    "plain_self",
    "roll_self",
    "plain_roll_mated",
    "plain_roll_non_mated",
)

#: How the Gate B subset was chosen, stated so that it can be re-derived rather
#: than believed. Purely positional: nothing about a score, a quality, a minutiae
#: count or a previous run enters it.
GATE_B_SUBSET_RULE = (
    "for each release, in the preparation set's published order, the first two "
    "plain and the first two roll images, taking at most one image per subject"
)

#: The subset itself, frozen in source before any extraction was run.
#: ``tests/test_stage20b_contract.py`` re-derives it from
#: :data:`GATE_B_SUBSET_RULE` and fails if the two disagree.
GATE_B_SUBSET: tuple[str, ...] = (
    "sd300a_00001012_plain_f01",
    "sd300a_00001020_plain_f01",
    "sd300a_00001012_roll_f01",
    "sd300a_00001020_roll_f01",
    "sd300b_00001012_plain_f01",
    "sd300b_00001020_plain_f01",
    "sd300b_00001012_roll_f01",
    "sd300b_00001020_roll_f01",
    "sd300c_00001012_plain_f01",
    "sd300c_00001020_plain_f01",
    "sd300c_00001012_roll_f01",
    "sd300c_00001020_roll_f01",
)

#: Section 26, frozen before the run. The preference is about how the two routes
#: were built, not about what they scored.
PREFERENCE_REASON = "OFFICIAL_UNMODIFIED_MATCHER_ROUTE"

#: Section 33's human decision. ``None`` until somebody has read the failure
#: classification and judged it; the marker publishes ``preferred_final_fifth``
#: as ``null`` until then rather than guessing in either direction.
#:
#: Only consulted when the run has structured failures in it. A run in which all
#: 6,000 comparisons are score-bearing and no systemic defect appears meets
#: section 33's first branch outright, and no human review is required.
FAILURE_REVIEW: str | None = None

FAILURE_REVIEW_STATES: tuple[str, ...] = (
    "FAILURES_UNDERSTOOD_MCC_PREFERRED",
    "FAILURES_UNDERSTOOD_MCC_NOT_PREFERRED",
)

OUTCOME_COMPLETE = "MINDTCT_MCC_SDK_V2_CANONICAL_RAW_COMPLETE"
OUTCOME_GATE_A_FAIL = "MCC_PRODUCTION_BRIDGE_REPRODUCTION_FAIL"
OUTCOME_GATE_B_FAIL = "MINDTCT_ROUTE_PARITY_FAIL"

EVIDENCE_DIRECTORY = Path("evidence") / "stage20b-mindtct-mcc-canonical500-raw"
STAGE_20B_FINALIZATION_NAME = "stage-20b-finalization.json"
EVIDENCE_DOCUMENTS: tuple[str, ...] = (
    "README.md",
    "algorithm-identity.json",
    "runtime-binding.json",
    "gate-a-bridge-reproduction.json",
    "gate-b-mindtct-parity.json",
    "canonical-run-binding.json",
    "result-integrity.json",
    "diagnostic-report.json",
)

#: The sentence that has to travel with the number into the supervisor's table.
SUPERVISOR_DISCLOSURE = (
    "NBIS MINDTCT + MCC SDK v2.0 — a composition defined by this project. It shares the "
    "MINDTCT extractor with the NBIS/BOZORTH3 method and differs in the matcher: minutiae "
    "are passed to the official Minutia Cylinder-Code SDK v2.0 published by the University "
    "of Bologna, unmodified and at its own optimal parameters. The SDK contains no image "
    "extractor, which is why the extractor is named in the method. Scores are the SDK's raw "
    "similarity in [0,1]; no threshold, calibration or decision was applied."
)
