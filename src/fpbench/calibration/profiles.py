"""Turning a selected operating point into a decision profile.

The join between this package and the layer that actually applies thresholds. It
produces a ``DecisionProfile`` whose origin is ``CALIBRATED_DEVELOPMENT`` — the
first artifact in this project entitled to that origin, and entitled to it only
because it carries the three links that make the claim checkable: which boundary
was selected, under which policy, and from which development scores
(docs/adr/0079, spec section 21).

**Why this is not in the YAML loader.** ``fpbench.decisions.profiles`` refuses
``CALIBRATED_DEVELOPMENT`` outright, and Stage 8D does not change that. A config
file cannot evidence a calibration; it can only assert one. An operating point
*is* the evidence — it re-derives from the scores it cites — so a calibrated
profile is constructed from one rather than declared in a document. The two paths
therefore have different rules on purpose, and the loader stays exactly as strict
as it was.

**Why the profile is built here rather than by ``build_decision_profile``.**
``fpbench.calibration`` may not import ``fpbench.decisions``; a calibration
engine that could reach the derivation layer could reach the decisions it is
supposed to be upstream of. ``DecisionProfile`` itself lives in ``core``, which is
shared, so the container is available and the derivation rule is not.
"""

from __future__ import annotations

from typing import Any, Iterable

from fpbench.core.calibration_errors import CalibrationBridgeError
from fpbench.core.calibration_models import CalibrationOperatingPoint
from fpbench.core.decision_models import (
    DecisionProfile,
    ThresholdOrigin,
    canonical_threshold,
    decision_profile_fingerprint,
)

__all__ = [
    "CALIBRATED_PROFILE_SCHEMA_VERSION",
    "CALIBRATED_SOURCE_KIND",
    "calibrated_profile_id",
    "derive_calibrated_decision_profile",
]

#: A calibrated profile is a schema-3 profile and can be nothing else: schemas 1
#: and 2 have no place to put the links, and a profile that claimed calibration
#: without them would be asserting something its identity does not cover.
CALIBRATED_PROFILE_SCHEMA_VERSION = "3"

#: What the profile says it came from. Not a paper, not a vendor's documentation
#: — an artifact in this repository that a reader can re-derive.
CALIBRATED_SOURCE_KIND = "fpbench_calibration_operating_point"


def calibrated_profile_id(operating_point: CalibrationOperatingPoint) -> str:
    """``calibrated_<operating point id>``.

    Derived rather than passed in, so that two profiles built from one operating
    point cannot be given different names and then cited as if they were
    different thresholds.
    """
    return f"calibrated_{operating_point.operating_point_id}"


def derive_calibrated_decision_profile(
    operating_point: CalibrationOperatingPoint,
    *,
    implementation_version: str,
    allowed_execution_profiles: Iterable[str],
    profile_version: str = "1",
) -> DecisionProfile:
    """Build the decision profile one operating point authorises.

    Two arguments beyond the operating point, and both are things it genuinely
    cannot know. ``implementation_version`` is a property of the build that
    produced the scores rather than of the boundary chosen from them, and
    ``allowed_execution_profiles`` says which image preparation the threshold
    transfers to — a threshold chosen on images prepared one way does not carry
    to images prepared another way (docs/adr/0022).

    Everything else is taken from the operating point, so the profile cannot
    disagree with it about the threshold, the comparator, the direction or the
    algorithm.
    """
    profiles = tuple(str(item).strip() for item in allowed_execution_profiles)
    if not profiles:
        raise CalibrationBridgeError(
            "a calibrated profile must name the execution profiles it applies to; "
            "a threshold that spans every way of preparing an image is a threshold "
            "nobody can attribute (docs/adr/0022)"
        )
    version = str(implementation_version).strip()
    if not version:
        raise CalibrationBridgeError(
            "a calibrated profile must name the implementation version whose "
            "scores it was selected from"
        )

    fields: dict[str, Any] = {
        "schema_version": CALIBRATED_PROFILE_SCHEMA_VERSION,
        "profile_id": calibrated_profile_id(operating_point),
        "display_name": calibrated_profile_id(operating_point),
        "profile_version": str(profile_version).strip(),
        "algorithm_id": operating_point.algorithm_id,
        "implementation_version": version,
        "algorithm_fingerprint": operating_point.algorithm_fingerprint,
        "score_direction": operating_point.score_direction,
        "comparator": operating_point.comparator,
        "threshold": canonical_threshold(operating_point.threshold),
        "origin": ThresholdOrigin.CALIBRATED_DEVELOPMENT,
        "source_kind": CALIBRATED_SOURCE_KIND,
        "source_reference": operating_point.operating_point_id,
        "source_version": operating_point.schema_version,
        "allowed_execution_profiles": profiles,
        "calibration_performed": True,
        # The manifest a calibrated profile has had to name since docs/adr/0021
        # *is* the operating point. There was no such artifact when the rule was
        # written; there is now, and pointing the field at anything else would
        # leave a reader to guess which of two documents the threshold came from.
        "calibration_manifest_fingerprint": (
            operating_point.operating_point_fingerprint
        ),
        "calibration_operating_point_fingerprint": (
            operating_point.operating_point_fingerprint
        ),
        "calibration_protocol_fingerprint": (
            operating_point.calibration_protocol_fingerprint
        ),
        "calibration_source_binding_fingerprint": (
            operating_point.source_binding_fingerprint
        ),
        "metadata": {
            "calibration.target_rate": (
                f"{operating_point.target_rate_numerator}/"
                f"{operating_point.target_rate_denominator}"
            ),
            "calibration.selection_rule": operating_point.selection_rule.value,
            "calibration.tie_policy": operating_point.tie_policy.value,
            "calibration.score_normalization": "none",
        },
    }
    # The profile validates its own fingerprint, so it is computed from a
    # stand-in carrying exactly the attributes the mapping reads — the same
    # reason ``fpbench.decisions.profiles`` keeps a probe class.
    fingerprint = decision_profile_fingerprint(_FingerprintProbe(fields))
    return DecisionProfile(profile_fingerprint=fingerprint, **fields)


class _FingerprintProbe:
    """A stand-in with exactly the attributes the schema-3 mapping reads.

    Building the real object first is impossible — it checks its own fingerprint
    — and giving ``DecisionProfile`` a mutable escape hatch would remove the check
    that makes a stored profile fingerprint worth reading.
    """

    __slots__ = (
        "schema_version",
        "profile_id",
        "profile_version",
        "algorithm_id",
        "implementation_version",
        "algorithm_fingerprint",
        "score_direction",
        "comparator",
        "threshold",
        "origin",
        "source_kind",
        "source_reference",
        "source_version",
        "allowed_execution_profiles",
        "calibration_performed",
        "calibration_manifest_fingerprint",
        "calibration_operating_point_fingerprint",
        "calibration_protocol_fingerprint",
        "calibration_source_binding_fingerprint",
        "metadata",
    )

    def __init__(self, fields: dict[str, Any]) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
