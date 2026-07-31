"""Reading a threshold from a config file, and refusing to misuse it.

A decision profile is a small YAML document, and almost all of the code here is
about the ways one can be wrong in a manner that would not show up in the
results:

* a threshold that parses but is not canonical, so the same number fingerprints
  two ways;
* a comparator that disagrees with the algorithm's score direction, which
  inverts every decision while looking like a setting;
* a profile applied to a *different build* of the same algorithm, which produces
  decisions that cannot be attributed to either;
* a threshold described as calibrated when nobody calibrated anything, or
  calibrated on the test cohort — the one form of leakage that would quietly
  invalidate the whole study.

The last of these is why ``calibration`` is a section in the file at all. It
would be simpler to leave it out and let a documented threshold be the only kind
there is. But the next threshold *will* be calibrated, and a schema that has no
place to say "on what?" is a schema that will be filled in with a guess
(docs/adr/0021).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.decision_models import (
    DecisionProfile,
    ThresholdComparator,
    ThresholdOrigin,
    canonical_threshold,
    decision_profile_fingerprint,
)
from fpbench.core.enums import ScoreDirection
from fpbench.core.errors import (
    DecisionProfileApplicabilityError,
    DecisionProfileError,
)
from fpbench.core.execution_models import ExecutionProfile
from fpbench.core.result_models import RunDefinition

__all__ = [
    "DecisionProfile",
    "load_decision_profile",
    "build_decision_profile",
    "require_profile_applies_to_run",
    "ALLOWED_ORIGINS",
]

#: The only threshold origin stage 5A may execute. A calibrated profile needs a
#: calibration manifest tied to a *development* cohort, and neither the manifest
#: format nor the development cohort exists yet. Accepting one now would mean
#: accepting a claim with nothing behind it.
ALLOWED_ORIGINS: frozenset[ThresholdOrigin] = frozenset(
    {ThresholdOrigin.DOCUMENTED_NATIVE}
)


def load_decision_profile(
    path: Path,
    *,
    algorithm_fingerprint: str,
) -> DecisionProfile:
    """Read ``configs/decisions/<name>.yaml`` and bind it to one algorithm build.

    Args:
        algorithm_fingerprint: The exact algorithm identity this profile will be
            applied to, normally ``run.algorithm_fingerprint``. It enters the
            profile fingerprint: the same threshold against two builds of
            SourceAFIS is two profiles, because "score 40 means match" is a claim
            about a specific matcher and not about a number.

    Raises:
        DecisionProfileError: the file is missing, malformed, or describes a
            profile this stage may not execute.
    """
    path = Path(path)
    if not path.is_file():
        raise DecisionProfileError(f"decision profile not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise DecisionProfileError(f"{path}: expected a mapping at the top level")

    profile = _section(document, "profile", path)
    algorithm = _section(document, "algorithm", path)
    rule = _section(document, "rule", path)
    scope = _section(document, "scope", path)
    provenance = _section(document, "provenance", path)
    calibration = document.get("calibration") or {}
    if not isinstance(calibration, Mapping):
        raise DecisionProfileError(f"{path}: malformed 'calibration' section")

    declared = str(algorithm.get("fingerprint") or "").strip().lower()
    if declared and declared != str(algorithm_fingerprint).strip().lower():
        raise DecisionProfileError(
            f"{path}: the profile pins algorithm fingerprint {declared[:12]}... but "
            f"is being bound to {str(algorithm_fingerprint)[:12]}..."
        )

    if calibration.get("test_cohort_used"):
        raise DecisionProfileError(
            f"{path}: a threshold may never be calibrated on the TEST cohort. "
            "Choosing a threshold from the same 50 subjects it is later reported "
            "on is the one form of leakage that invalidates the whole study; draw "
            "a development cohort instead"
        )

    metadata = {
        "upstream_claim": str(provenance.get("upstream_claim", "")),
        "upstream_claim_is_not_benchmark_result": _flag(
            provenance.get("upstream_claim_is_not_benchmark_result", True)
        ),
        "calibration_test_cohort_used": _flag(
            calibration.get("test_cohort_used", False)
        ),
    }
    extra = document.get("metadata") or {}
    if isinstance(extra, Mapping):
        metadata.update({str(k): str(v) for k, v in extra.items()})

    try:
        return build_decision_profile(
            profile_id=str(profile["profile_id"]),
            display_name=str(profile.get("display_name", profile["profile_id"])),
            profile_version=str(profile.get("profile_version", "1")),
            origin=ThresholdOrigin(str(profile["origin"])),
            algorithm_id=str(algorithm["algorithm_id"]),
            implementation_version=str(algorithm["implementation_version"]),
            algorithm_fingerprint=str(algorithm_fingerprint),
            score_direction=ScoreDirection(str(algorithm["score_direction"])),
            comparator=ThresholdComparator(str(rule["comparator"])),
            threshold=str(rule["threshold"]),
            source_kind=str(provenance["source_kind"]),
            source_reference=str(provenance["source_reference"]),
            source_version=str(provenance["source_version"]),
            allowed_execution_profiles=tuple(
                str(item) for item in (scope.get("execution_profiles") or ())
            ),
            calibration_performed=bool(calibration.get("performed", False)),
            calibration_manifest_fingerprint=(
                str(calibration["manifest_fingerprint"])
                if calibration.get("manifest_fingerprint")
                else None
            ),
            metadata=metadata,
        )
    except KeyError as exc:
        raise DecisionProfileError(f"{path}: missing required key {exc}") from None
    except ValueError as exc:
        raise DecisionProfileError(f"{path}: {exc}") from None


def build_decision_profile(**fields: Any) -> DecisionProfile:
    """Derive a profile's fingerprint and construct it.

    Separate from the loader so that a test can build one without a file, and so
    that the fingerprint is computed in exactly one place.
    """
    origin = fields["origin"]
    if origin not in ALLOWED_ORIGINS:
        raise DecisionProfileError(
            f"threshold origin {origin.value!r} cannot be executed yet: a "
            "calibrated threshold needs a calibration manifest drawn from a "
            "development cohort, and neither exists (docs/adr/0021)"
        )

    fields = dict(fields)
    fields["threshold"] = canonical_threshold(fields["threshold"])

    # The fingerprint covers the profile, and the profile validates its own
    # fingerprint, so it has to be computed from the parts rather than from a
    # half-built object. A throwaway namespace keeps that honest.
    probe = _FingerprintProbe(**fields)
    fingerprint = decision_profile_fingerprint(probe)  # type: ignore[arg-type]
    return DecisionProfile(profile_fingerprint=fingerprint, **fields)


class _FingerprintProbe:
    """A stand-in with exactly the attributes the fingerprint reads.

    Building the real object first is impossible — it checks its own
    fingerprint — and giving ``DecisionProfile`` a mutable escape hatch would be
    worse than this eight-line class.
    """

    __slots__ = (
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
        "metadata",
        "display_name",
    )

    def __init__(self, **fields: Any) -> None:
        for name in self.__slots__:
            setattr(self, name, fields.get(name))
        self.allowed_execution_profiles = tuple(
            str(item).strip() for item in (self.allowed_execution_profiles or ())
        )
        self.calibration_performed = bool(self.calibration_performed)
        self.metadata = dict(self.metadata or {})
        self.threshold = canonical_threshold(self.threshold)


def require_profile_applies_to_run(
    *,
    profile: DecisionProfile,
    run: RunDefinition,
) -> None:
    """Refuse to apply a profile to a run it does not describe.

    Every check here is an equality, and every failure is fatal. There is no
    warn-and-continue: a threshold applied across algorithm builds produces
    decisions that belong to neither, and nothing downstream could tell
    (docs/adr/0022).
    """
    checks: tuple[tuple[str, Any, Any], ...] = (
        ("algorithm_id", profile.algorithm_id, run.algorithm.algorithm_id),
        (
            "algorithm_fingerprint",
            profile.algorithm_fingerprint,
            run.algorithm_fingerprint,
        ),
        (
            "implementation_version",
            profile.implementation_version,
            run.algorithm.implementation_version,
        ),
        (
            "score_direction",
            profile.score_direction,
            run.algorithm.score_direction,
        ),
    )
    for label, expected, actual in checks:
        if expected != actual:
            raise DecisionProfileApplicabilityError(
                f"decision profile {profile.profile_id} declares {label} "
                f"{_render(expected)!r} but run {run.run_id} was produced with "
                f"{_render(actual)!r}"
            )

    execution_profile: ExecutionProfile = run.execution_profile
    if not profile.applies_to_execution_profile(execution_profile.profile_id):
        raise DecisionProfileApplicabilityError(
            f"decision profile {profile.profile_id} covers execution profiles "
            f"{list(profile.allowed_execution_profiles)}, but run {run.run_id} was "
            f"executed under {execution_profile.profile_id!r}. A threshold chosen "
            "for images prepared one way does not transfer to images prepared "
            "another way"
        )


def _render(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise DecisionProfileError(f"{path}: missing or malformed '{key}' section")
    return value


def _flag(value: Any) -> str:
    return "true" if bool(value) else "false"
