"""What Stage 19A is, and the one verdict the code refuses to reach on its own.

Stage 19A builds Algorithm 5: ``MINDTCT → OpenAFIS``, over the same 6,000
comparisons the other four algorithms ran, with no threshold, no decision and no
calibration.

TWO QUESTIONS, DELIBERATELY SEPARATED

**Did the raw run complete?** Arithmetic, and the code answers it:

.. code-block:: text

    expected_outcomes = 6000
    stored_outcomes   = 6000
    missing           = 0

**Is Algorithm 5 established?** Section 20 gives four conditions. Three of them
are properties of the code and the run, and the code evaluates them:

1. the translation route was settled from upstream sources and not from tuning;
2. there is no systemic implementation defect;
3. the failures, if any, come from real limits of MINDTCT and OpenAFIS rather
   than from the bridge.

The fourth is not:

4. *"a substantial quantity of score-bearing comparisons between different
   impressions."*

**"Substantial" has no number in the requirement, and this module refuses to
invent one.** :data:`CROSS_IMPRESSION_SUFFICIENCY` is a frozen constant a human
edits after reading the run, exactly as Stage 14A's request status is. Until it is
set, ``algorithm_5_established`` is published as ``null`` — not ``false``, because
nobody has judged it, and not ``true``, because nobody has judged it. A threshold
picked by whoever wrote the code, to a number that happened to pass, would be the
one place in this stage where the answer chose itself.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "STAGE",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "EXPERIMENT_ID",
    "EXPECTED_OUTCOMES",
    "OPENAFIS_COMMIT",
    "NBIS_VERSION",
    "NBIS_BUILD_ID",
    "REFERENCE_PREPARATION_SET_ID",
    "REFERENCE_PAIR_MANIFEST_HASH",
    "CROSS_IMPRESSION_STAGES",
    "CROSS_IMPRESSION_SUFFICIENCY",
    "SUFFICIENCY_STATES",
    "OUTCOME_COMPLETE",
    "OUTCOME_ROUTE_BROKEN",
    "EVIDENCE_DIRECTORY",
    "STAGE_19A_FINALIZATION_NAME",
    "EVIDENCE_DOCUMENTS",
    "BOUND_MARKERS",
]

STAGE = "19A"
ALGORITHM_ID = "nbis_mindtct_openafis"
ADAPTER_ID = "nbis_mindtct_openafis_subprocess"
EXPERIMENT_ID = "nbis_mindtct_openafis_canonical500_full_v1"

EXPECTED_OUTCOMES = 6000

OPENAFIS_COMMIT = "3ae1c757c6dafea977a33ef51380e37f1715e626"
NBIS_VERSION = "5.0.0"

#: The same certified build Algorithm 2 runs. Not an equivalent build — the same
#: one, so that the pair is a controlled matcher comparison (docs/adr/0135).
NBIS_BUILD_ID = "658f9f54a8f2"

REFERENCE_PREPARATION_SET_ID = "prepset_be560e047991"
REFERENCE_PAIR_MANIFEST_HASH = "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"

#: The protocol stages that compare two *different* impressions. Section 20's
#: fourth condition is about these and not about SELF, where an image is matched
#: against itself and a score proves only that the route runs.
CROSS_IMPRESSION_STAGES: tuple[str, ...] = ("plain_roll_mated", "plain_roll_non_mated")

SUFFICIENCY_STATES: tuple[str, ...] = ("UNDETERMINED", "SUFFICIENT", "INSUFFICIENT")

#: Set by a human after reading the run, never derived. See the module docstring.
CROSS_IMPRESSION_SUFFICIENCY = "UNDETERMINED"

OUTCOME_COMPLETE = "MINDTCT_OPENAFIS_CANONICAL500_RAW_COMPLETE"
OUTCOME_ROUTE_BROKEN = "MINDTCT_OPENAFIS_ROUTE_BROKEN"

EVIDENCE_DIRECTORY = Path("evidence") / "stage19a-mindtct-openafis"
STAGE_19A_FINALIZATION_NAME = "stage-19a-finalization.json"
EVIDENCE_DOCUMENTS = (
    "README.md",
    "algorithm-identity.json",
    "translation-contract.json",
    "canonical-run-binding.json",
    "matcher-comparison.json",
)

BOUND_MARKERS = (
    {
        "stage": "18A",
        "why": "the private reference that produced the working OpenAFIS build, the raw 1:1 bridge and the proven score contract. Bound, and never read for its scores",
    },
    {
        "stage": "17A",
        "why": "the predecessor candidate, closed at its score-contract gate, which left Algorithm 5 open",
    },
    {
        "stage": "8E",
        "why": "the third-party research-use policy, reused and not reopened",
    },
)
