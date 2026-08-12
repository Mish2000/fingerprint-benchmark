"""Who this algorithm is, frozen, before a single SD300 pixel is opened.

Stage 11A qualified a *candidate* under a provisional id. Stage 11B turns that
candidate into the benchmark's fourth algorithm, and an algorithm that is going
to be cited needs an identity that cannot drift: an id, a display name, a version
that came out of the binaries rather than off a web page, and a pipeline
description naming every choice that could move a score (docs/adr/0014).

Three things this module deliberately does *not* contain.

**No threshold.** Not 48, not any other number, in any field. VeriFinger's own
1:1 sample sets ``MatchingThreshold = 48`` and the bridge keeps that so the
official route is preserved byte for byte — but a threshold that lives inside the
matcher's control flow is not a decision profile, and fpbench's decision layer is
a different stage entirely (docs/adr/0003, spec section 10).

**No path.** Where 4.7 GB of vendor SDK lives is a fact about a machine. It
reaches no fingerprint, no result and no evidence document (spec section 39).

**No credential.** No serial, no activation identifier, no machine code
(spec section 38).

Everything here is a constant, so this module imports nothing that needs a
licence, a DLL or a JVM. That is what lets CI check the identity of an algorithm
it is not allowed to download.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from fpbench.adapters.pipeline_metadata import AlgorithmPipelineMetadata
from fpbench.core.enums import ScoreDirection
from fpbench.core.serialization import stable_hash

__all__ = [
    "ALGORITHM_ID",
    "DISPLAY_NAME",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "IMPLEMENTATION_VERSION",
    "VENDOR",
    "ALGORITHM_SLOT",
    "STAGE_11A_FINALIZATION_FINGERPRINT",
    "STAGE_11A_OUTCOME",
    "STAGE_11A_SELECTED_CANDIDATE",
    "PIPELINE",
    "PIPELINE_METADATA",
    "SCORE_DIRECTION",
    "NATIVE_SCORE_TYPE",
    "SCORE_SCALE",
    "SCORE_TRANSFORMATION_BY_FPBENCH",
    "SCORE_SERIALIZATION",
    "SCORE_BEARING_STATUSES",
    "REQUIRED_EFFECTIVE_PPI",
    "REQUIRED_EXTRACTION_COUNT",
    "EXPECTED_RUNTIME_DEFAULTS",
    "CONFIGURED_SETTINGS",
    "MATCHING_SPEED",
    "OFFICIAL_SAMPLE_MATCHING_THRESHOLD",
    "PLATFORM_OPERATING_SYSTEM",
    "PLATFORM_ARCHITECTURE",
    "PLATFORM_NATIVE_DIRECTORY",
    "MINIMUM_JAVA_MAJOR",
    "BRIDGE_PROTOCOL",
    "BRIDGE_VERSION",
    "FORBIDDEN_INPUTS",
    "METADATA_PREFIX",
    "algorithm_profile",
    "algorithm_profile_fingerprint",
]


# ------------------------------------------------------------------- identity

#: The production id. Not the Stage 11A candidate id: that one said "this is the
#: thing being examined", and this one says "this is algorithm 4".
ALGORITHM_ID = "verifinger_1to1"

DISPLAY_NAME = "VeriFinger 2025.2 1:1 Verification"

ADAPTER_ID = "verifinger_java_subprocess"

#: This repository's wrapper version, separate from the SDK's own. A change to
#: how fpbench drives VeriFinger moves this; a change to VeriFinger moves
#: ``IMPLEMENTATION_VERSION`` (docs/adr/0014).
ADAPTER_VERSION = "1"

#: What the running libraries report about themselves. Every one of the seven
#: native modules the engine loads carries ProductVersion "2025, 2, 0, 0", and
#: Stage 11A read that out of the binaries rather than off a download page.
IMPLEMENTATION_VERSION = "2025.2"

VENDOR = "Neurotechnology"

ALGORITHM_SLOT = "algorithm_4"


# ------------------------------------------------------- the Stage 11A binding

#: The qualification this stage rests on. If it moves, Stage 11B refuses to run
#: until somebody looks at why (spec section 1).
STAGE_11A_FINALIZATION_FINGERPRINT = (
    "f8228072e0dc6d016e191ab5356d1d65748ba62caa4768dfb21650f78a0b3a7b"
)
STAGE_11A_OUTCOME = "VERIFINGER_PREFLIGHT_PASS"
STAGE_11A_SELECTED_CANDIDATE = "neurotechnology_verifinger_2025_2_1to1"


# ------------------------------------------------------------------- pipeline

#: One JVM per comparison, and it is a choice rather than an oversight.
#:
#: A persistent worker would be faster and would buy a state machine nobody
#: needs yet: one job is one process, so there is no cross-comparison cache to
#: reason about, no representation that could survive into the next pair, and
#: restart determinism is simply what every job already does. At the 2.29 s per
#: verify Stage 11A measured, the cost is hours against a thirty-day licence
#: window (spec section 3).
INTEGRATION_MODE = "subprocess_per_comparison"

#: ``verify(reference, candidate)`` is one call that loads two images, extracts
#: two templates and matches them. Declaring an ``extract_then_match`` pipeline
#: would be describing an API this route does not use (docs/adr/0002).
PIPELINE_KIND = "end_to_end_image_matcher"

PIPELINE = AlgorithmPipelineMetadata(
    family_id="verifinger",
    pipeline_kind=PIPELINE_KIND,
    extractor_id="verifinger_finger_extractor",
    extractor_version=IMPLEMENTATION_VERSION,
    matcher_id="verifinger_finger_matcher",
    matcher_version=IMPLEMENTATION_VERSION,
    implementation_language="native_via_official_java_binding",
    integration_mode=INTEGRATION_MODE,
    input_mode="canonical_gray8_500ppi",
    dpi_policy="require_declared_500_ppi_both_sides",
    # The contract's word for "left is the reference subject". The two say the
    # same thing; the generic conformance pass checks this spelling, and
    # ``probe_role`` below carries the route's own (spec section 15).
    probe_side="left",
    template_cache="disabled",
    template_persistence="disabled",
    seed_usage="ignored_route_is_deterministic",
    extra={
        "vendor": VENDOR,
        "probe_role": "left_as_reference",
        "score_cache": "disabled",
        "bridge_protocol": "fpbench.verifinger.bridge.v1",
        "bridge_version": "1",
        "platform": "windows/x86_64",
        "stage11a_fingerprint": STAGE_11A_FINALIZATION_FINGERPRINT,
    },
)

PIPELINE_METADATA: Mapping[str, str] = PIPELINE.as_descriptor_metadata()

#: The prefix every key this route writes into a stored result carries. One
#: namespace, so the validator can say what belongs to VeriFinger and what does
#: not (spec section 31).
METADATA_PREFIX = "verifinger."


# ---------------------------------------------------------------- the score

SCORE_DIRECTION = ScoreDirection.HIGHER_IS_BETTER

#: What VeriFinger hands back: a Java ``int``. Recorded because the stored score
#: is an IEEE double, and the two are the same number only because every
#: 32-bit integer is exactly representable in float64 — which makes the
#: conversion a serialisation rather than a transformation (spec section 11).
NATIVE_SCORE_TYPE = "java_int"

#: The vendor documents the scale as related to a false-acceptance rate. fpbench
#: neither computes a FAR from it nor claims one; the name records the claim and
#: attributes it (spec section 11).
SCORE_SCALE = "vendor_native_claimed_far_scale"

SCORE_TRANSFORMATION_BY_FPBENCH = "none"

SCORE_SERIALIZATION = "exact_int_to_float64"

#: The two engine statuses that carry a score. ``MATCH_NOT_FOUND`` is one of
#: them: upstream's own sample reads the score in that case too, which is why
#: Stage 11A concluded the threshold is separate from the number
#: (spec section 10).
SCORE_BEARING_STATUSES: tuple[str, ...] = ("OK", "MATCH_NOT_FOUND")


# ---------------------------------------------------------------- the inputs

#: The canonical set is 500 ppi and this route refuses anything else. Declaring
#: the resolution to the SDK is metadata; resizing a pixel is not permitted
#: anywhere on this route (spec sections 6 and 7).
REQUIRED_EFFECTIVE_PPI = 500

#: Two subjects, two fingers, two extractions — for every comparison including
#: SELF, where both sides name the same file (spec section 14).
REQUIRED_EXTRACTION_COUNT = 2


# ------------------------------------------------------- the frozen defaults

#: What the delivered engine holds before anybody configures it, exactly as
#: Stage 11A read it out of a running NBiometricClient. These are *not* our
#: choices — that is the entire point of checking them. A runtime whose defaults
#: differ is a different runtime, and the environment is reported UNAVAILABLE
#: rather than quietly corrected (spec section 8).
EXPECTED_RUNTIME_DEFAULTS: Mapping[str, str] = MappingProxyType(
    {
        "Fingers.TemplateSize": "LARGE",
        "Fingers.ExtractionScenario": "0",
        "Fingers.FastExtraction": "false",
        "Fingers.QualityThreshold": "40",
        "Fingers.MinimalMinutiaCount": "10",
        "Fingers.DetectTips": "false",
        "Fingers.DetectLiveness": "false",
        "Fingers.LivenessConfidenceThreshold": "0",
        "Fingers.MaximalRotation": "180.0",
        "Matching.Scenario": "0",
    }
)

#: The one value this route sets, and why. ``verify-finger`` — upstream's own
#: complete 1:1 sample, inside the pinned archive — sets it explicitly, so the
#: production route sets it too. Not because LOW is more accurate: nobody here
#: has measured that and Stage 11B is forbidden from finding out
#: (spec section 9).
MATCHING_SPEED = "LOW"

#: The same sample also sets a matching threshold of 48. The bridge sets it so
#: that the official route is reproduced exactly, and fpbench then ignores the
#: MATCH/NO-MATCH answer entirely and reads the integer beside it. Recorded here
#: as provenance, never used as a decision (spec section 10).
OFFICIAL_SAMPLE_MATCHING_THRESHOLD = 48

CONFIGURED_SETTINGS: Mapping[str, str] = MappingProxyType(
    {
        "Fingers.MatchingSpeed": MATCHING_SPEED,
        "Matching.Threshold": str(OFFICIAL_SAMPLE_MATCHING_THRESHOLD),
    }
)


# ------------------------------------------------------------------ platform

#: The trial is single-platform and Stage 11A locked it here. Alternating two
#: platforms under one algorithm fingerprint is refused whichever is chosen.
PLATFORM_OPERATING_SYSTEM = "windows"
PLATFORM_ARCHITECTURE = "x86_64"
PLATFORM_NATIVE_DIRECTORY = "Bin/Win64_x64"

#: This project's reference JVM, as ``environment.yml`` pins it.
MINIMUM_JAVA_MAJOR = 17

BRIDGE_PROTOCOL = "fpbench.verifinger.bridge.v1"
BRIDGE_VERSION = "1"


# ------------------------------------------------------------ what may not go

#: Fields the bridge may never receive and the adapter may never see. Named so
#: the exclusion is auditable rather than merely true today — the request
#: builder asserts against this list, and a test asserts the algorithm config
#: restates it (spec section 5).
FORBIDDEN_INPUTS: tuple[str, ...] = (
    "expected_decision",
    "finger_position",
    "flx_score",
    "ground_truth",
    "mated",
    "nbis_score",
    "pair_id",
    "pair_kind",
    "protocol_stage",
    "release",
    "sourceafis_score",
    "stage",
    "subject_id",
    "threshold",
)


# ------------------------------------------------------------------- profile


def algorithm_profile() -> Mapping[str, object]:
    """Everything above, as one document a stage can publish and check.

    The published ``algorithm-profile.json`` is this mapping. It is built here
    rather than written by hand so that the evidence and the code cannot say
    different things about which algorithm ran.
    """
    return {
        "schema": "verifinger_algorithm_profile_v1",
        "algorithm_id": ALGORITHM_ID,
        "display_name": DISPLAY_NAME,
        "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
        "implementation_version": IMPLEMENTATION_VERSION,
        "vendor": VENDOR,
        "algorithm_slot": ALGORITHM_SLOT,
        "stage11a": {
            "finalization_fingerprint": STAGE_11A_FINALIZATION_FINGERPRINT,
            "outcome": STAGE_11A_OUTCOME,
            "selected_candidate": STAGE_11A_SELECTED_CANDIDATE,
        },
        "pipeline": dict(PIPELINE_METADATA),
        "score": {
            "direction": SCORE_DIRECTION.value,
            "native_score_type": NATIVE_SCORE_TYPE,
            "score_scale": SCORE_SCALE,
            "score_transformation_by_fpbench": SCORE_TRANSFORMATION_BY_FPBENCH,
            "serialization": SCORE_SERIALIZATION,
            "score_bearing_statuses": list(SCORE_BEARING_STATUSES),
            "far_computed_by_fpbench": False,
            "normalized": False,
            "clamped": False,
            "calibrated": False,
        },
        "inputs": {
            "required_effective_ppi": REQUIRED_EFFECTIVE_PPI,
            "required_extraction_count": REQUIRED_EXTRACTION_COUNT,
            "preprocessing_by_fpbench": "none",
            "forbidden_inputs": list(FORBIDDEN_INPUTS),
        },
        "runtime": {
            "expected_defaults": dict(EXPECTED_RUNTIME_DEFAULTS),
            "configured_settings": dict(CONFIGURED_SETTINGS),
            "official_sample_matching_threshold": OFFICIAL_SAMPLE_MATCHING_THRESHOLD,
            "decision_threshold_produced_by_fpbench": False,
            "operating_system": PLATFORM_OPERATING_SYSTEM,
            "architecture": PLATFORM_ARCHITECTURE,
            "native_library_directory": PLATFORM_NATIVE_DIRECTORY,
            "minimum_java_major": MINIMUM_JAVA_MAJOR,
            "bridge_protocol": BRIDGE_PROTOCOL,
            "bridge_version": BRIDGE_VERSION,
        },
    }


def algorithm_profile_fingerprint() -> str:
    """One digest over the whole frozen identity.

    A published run names it, so a later reader can prove the identity has not
    been edited since — including the parts, like the runtime defaults, that no
    descriptor field carries.
    """
    return stable_hash(algorithm_profile(), length=64)
