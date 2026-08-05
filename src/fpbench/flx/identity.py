"""Everything Stage 8B froze before the checkpoint was ever loaded.

These constants are the stage's contract with itself.  They are asserted by
the acceptance tests, embedded in every profile fingerprint, and republished
in the evidence, so that a later change to any of them is a different route
with a different identity rather than a quiet correction to this one.

The algorithm is deliberately *not* called "DeepPrint".  What is executed here
is one author-supplied implementation of one variant, and the identity says so
(docs/adr/0066, docs/adr/0069).
"""

from __future__ import annotations

from fpbench.core.identifiers import validate_id

__all__ = [
    "STAGE8B_SCHEMA_VERSION",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "RUNTIME_PROFILE_ID",
    "PREPROCESSING_PROFILE_ID",
    "REPRESENTATION_PROFILE_ID",
    "SCORE_PROFILE_ID",
    "SCORE_SERIALIZATION_PROFILE_ID",
    "QUALIFICATION_PROTOCOL_ID",
    "RUNTIME_POLICY_ID",
    "IMPLEMENTATION_ORIGIN",
    "UPSTREAM_STUDY",
    "UPSTREAM_RELATIONSHIP",
    "SOURCE_COMMIT",
    "SOURCE_ARCHIVE_SHA256",
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_SHA256",
    "CHECKPOINT_SIZE_BYTES",
    "CHECKPOINT_VARIANT",
    "TEXTURE_DIMENSIONS",
    "MINUTIA_DIMENSIONS",
    "CONCATENATED_DIMENSIONS",
    "NUM_TRAINING_CLASSES",
    "INFERENCE_BATCH_ROWS",
    "INFERENCE_BATCH_RULE",
    "REPRESENTED_ROW",
    "MODEL_INPUT_SIDE",
    "PAD_FILL_VALUE",
    "SCORE_MINIMUM",
    "SCORE_MAXIMUM",
    "SCORE_DIRECTION",
    "DECIMAL_SIGNIFICANT_DIGITS",
    "NUMERIC_TOLERANCE",
    "TRAINING_ONLY_CHECKPOINT_KEYS",
    "WEIGHTS_LICENSE_STATUS",
    "REDISTRIBUTION_ALLOWED",
    "PUBLICATION_PERMISSION",
    "EVIDENCE_DIRECTORY_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "all_frozen_identifiers",
]

STAGE8B_SCHEMA_VERSION = "1"

# ------------------------------------------------------------------ identity
ALGORITHM_ID = "flx_deepprint_texminu_512_without_localization"
ADAPTER_ID = "flx_pytorch_subprocess"
ADAPTER_VERSION = 1
RUNTIME_PROFILE_ID = "flx_cpu_linux_x86_64_v1"
PREPROCESSING_PROFILE_ID = "fpbench_canonical500_to_flx299_squarepad_v1"
REPRESENTATION_PROFILE_ID = "flx_texminu_256x2_v1"
SCORE_PROFILE_ID = "flx_texminu_equal_branch_dot_v1"
SCORE_SERIALIZATION_PROFILE_ID = "ieee_scalar_to_decimal17_v1"
QUALIFICATION_PROTOCOL_ID = "stage8b_flx_runtime_adapter_qualification_v1"
RUNTIME_POLICY_ID = "stage8b_flx_runtime_policy_v1"

IMPLEMENTATION_ORIGIN = "independent_reimplementation"
UPSTREAM_STUDY = "Rohwedder et al., BIOSIG 2023"
UPSTREAM_RELATIONSHIP = (
    "author-supplied implementation for the BIOSIG 2023 study, independently "
    "reimplementing the DeepPrint architecture family"
)

# ----------------------------------------------------------------- artifacts
# Re-stated from the Stage 8A acquisition manifest.  Stage 8B re-verifies all
# three before every runtime load; a mismatch is an immediate failure.
SOURCE_COMMIT = "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13"
SOURCE_ARCHIVE_SHA256 = (
    "60fa2c8894ea90efe2bb0553cd331d8ef84611b973b6126eaf6d162d1aa9b7e2"
)
CHECKPOINT_FILENAME = "best_model.pyt"
CHECKPOINT_SHA256 = (
    "2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28"
)
CHECKPOINT_SIZE_BYTES = 875770140
CHECKPOINT_VARIANT = "DeepPrint_TexMinu_512_without_localization"

# ------------------------------------------------------------ representation
TEXTURE_DIMENSIONS = 256
MINUTIA_DIMENSIONS = 256
CONCATENATED_DIMENSIONS = TEXTURE_DIMENSIONS + MINUTIA_DIMENSIONS
NUM_TRAINING_CLASSES = 8000

#: The pinned texture branch squeezes its batch dimension away and then
#: normalizes along ``dim=1``, so a batch of one raises IndexError before any
#: embedding exists.  There is no single-image route in this artifact.  The
#: frozen rule feeds the identical preprocessed tensor twice and represents
#: row 0; the adapter additionally asserts the two rows are bitwise equal, so
#: the workaround is a checked invariant and not an assumption (docs/adr/0070).
INFERENCE_BATCH_ROWS = 2
INFERENCE_BATCH_RULE = "duplicate_pair_take_first_row"
REPRESENTED_ROW = 0

# ------------------------------------------------------------- preprocessing
MODEL_INPUT_SIDE = 299
PAD_FILL_VALUE = 255

# --------------------------------------------------------------------- score
SCORE_MINIMUM = "-2"
SCORE_MAXIMUM = "2"
SCORE_DIRECTION = "higher_is_more_similar"
DECIMAL_SIGNIFICANT_DIGITS = 17

#: Bitwise equality is the target on this profile.  Nothing may widen it after
#: a measurement has been seen; a wider tolerance requires a new runtime
#: profile, declared in advance (spec section 18).
NUMERIC_TOLERANCE = "0"

#: Top-level checkpoint entries that belong to training and are deliberately
#: not loaded.  Frozen here, before the checkpoint was opened, so that the
#: allowlist cannot grow by trial and error against real data (spec section 7).
TRAINING_ONLY_CHECKPOINT_KEYS = ("loss_state_dict", "optimizer_state_dict")

# ------------------------------------------------------------------- licence
# Stage 8B executes the checkpoint locally under the project owner's explicit
# instruction.  That permission is not a licence finding, and the evidence
# keeps saying so (docs/adr/0068).
WEIGHTS_LICENSE_STATUS = "unresolved"
REDISTRIBUTION_ALLOWED = "not_established"
PUBLICATION_PERMISSION = "not_established"

# ------------------------------------------------------------------ evidence
EVIDENCE_DIRECTORY_NAME = "stage8b-flx-runtime-qualification"
REQUIRED_EVIDENCE_FILES = (
    "README.md",
    "artifact-binding.json",
    "runtime-manifest.json",
    "preprocessing-profile.json",
    "representation-profile.json",
    "score-profile.json",
    "adapter-profile.json",
    "runtime-probe.json",
    "qualification-report.json",
    "stage-8b-finalization.json",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 8B identifier, validated as a safe path and key component."""
    identifiers = (
        ALGORITHM_ID,
        ADAPTER_ID,
        RUNTIME_PROFILE_ID,
        PREPROCESSING_PROFILE_ID,
        REPRESENTATION_PROFILE_ID,
        SCORE_PROFILE_ID,
        SCORE_SERIALIZATION_PROFILE_ID,
        QUALIFICATION_PROTOCOL_ID,
        RUNTIME_POLICY_ID,
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers
