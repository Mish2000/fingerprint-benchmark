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
    DECISION_PROFILE_SCHEMA_VERSION,
    DecisionProfile,
    ThresholdComparator,
    ThresholdOrigin,
    canonical_threshold,
    decision_profile_fingerprint,
    require_comparator_schema_version,
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

    schema_version = require_comparator_schema_version(
        profile.get("schema_version", DECISION_PROFILE_SCHEMA_VERSION)
    )

    declared = str(algorithm.get("fingerprint") or "").strip().lower()
    if declared and declared != str(algorithm_fingerprint).strip().lower():
        raise DecisionProfileError(
            f"{path}: the profile pins algorithm fingerprint {declared[:12]}... but "
            f"is being bound to {str(algorithm_fingerprint)[:12]}..."
        )

    calibration_test_cohort_used = _yaml_bool(
        calibration,
        "test_cohort_used",
        path=path,
        section="calibration",
        default=False,
    )
    calibration_performed = _yaml_bool(
        calibration,
        "performed",
        path=path,
        section="calibration",
        default=False,
    )
    upstream_not_benchmark = _yaml_bool(
        provenance,
        "upstream_claim_is_not_benchmark_result",
        path=path,
        section="provenance",
        default=True,
    )

    if calibration_test_cohort_used:
        raise DecisionProfileError(
            f"{path}: a threshold may never be calibrated on the TEST cohort. "
            "Choosing a threshold from the same 50 subjects it is later reported "
            "on is the one form of leakage that invalidates the whole study; draw "
            "a development cohort instead"
        )
    if calibration_performed:
        raise DecisionProfileError(
            f"{path}: calibration.performed is true, but nothing in this project "
            "has calibrated a threshold. A calibrated threshold needs a "
            "development cohort and a calibration manifest, and neither exists "
            "(docs/adr/0021)"
        )

    metadata = {
        "upstream_claim": str(provenance.get("upstream_claim", "")),
        "upstream_claim_is_not_benchmark_result": _flag(upstream_not_benchmark),
        "calibration_test_cohort_used": _flag(calibration_test_cohort_used),
    }
    metadata.update(_transfer_metadata(document, path))
    metadata.update(_claims_metadata(document, path, schema_version=schema_version))
    metadata.update(
        _statement_kind_metadata(provenance, path, schema_version=schema_version)
    )
    extra = document.get("metadata") or {}
    if isinstance(extra, Mapping):
        metadata.update({str(k): str(v) for k, v in extra.items()})

    try:
        return build_decision_profile(
            schema_version=schema_version,
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
            calibration_performed=calibration_performed,
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
        "schema_version",
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
        self.schema_version = require_comparator_schema_version(
            self.schema_version
            if self.schema_version is not None
            else DECISION_PROFILE_SCHEMA_VERSION
        )


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


#: Every field of a ``transfer`` block, and all of them are required once the
#: block exists. A transfer that recorded only its source profile would leave
#: the two questions that matter — was the number changed, and was anything
#: calibrated — answered by whoever read it (spec section 10).
_TRANSFER_FIELDS: tuple[str, ...] = (
    "source_profile_id",
    "threshold_unchanged",
    "calibration_performed",
    "test_cohort_used",
    "interpretation",
)


def _transfer_metadata(
    document: Mapping[str, Any], path: Path
) -> Mapping[str, str]:
    """Read a ``transfer`` block, if the profile has one.

    A transferred profile is one whose threshold came from *another profile*
    rather than from upstream documentation directly or from a calibration. The
    canonical-500 profile is the first: 40 is SourceAFIS's documented number,
    carried across unchanged so that the only thing that differs between the two
    derivations is which images were compared.

    Every field lands in ``metadata``, which is inside
    :func:`decision_profile_fingerprint`. So a transfer that quietly started
    claiming ``calibration_performed: true``, or pointed at a different source
    profile, would be a different profile with a different fingerprint and could
    not be mistaken for this one.

    A profile without the block — the native one — gets nothing, so its
    fingerprint is exactly what it was before this loader learned the word.
    """
    block = document.get("transfer")
    if block is None:
        return {}
    if not isinstance(block, Mapping):
        raise DecisionProfileError(f"{path}: malformed 'transfer' section")

    missing = [name for name in _TRANSFER_FIELDS if name not in block]
    if missing:
        raise DecisionProfileError(
            f"{path}: transfer is missing {', '.join(missing)}. A transferred "
            "threshold has to say what it came from and what was left unchanged, "
            "or it is indistinguishable from a threshold somebody chose"
        )

    threshold_unchanged = _yaml_bool(
        block,
        "threshold_unchanged",
        path=path,
        section="transfer",
    )
    if not threshold_unchanged:
        raise DecisionProfileError(
            f"{path}: transfer.threshold_unchanged is false. A transfer that moved "
            "the number is not a transfer; it is a new threshold, and a new "
            "threshold needs an origin of its own"
        )
    for name in ("calibration_performed", "test_cohort_used"):
        if _yaml_bool(block, name, path=path, section="transfer"):
            raise DecisionProfileError(
                f"{path}: transfer.{name} may not be true. Nothing was calibrated "
                "here and the TEST cohort was not used to choose anything; a "
                "profile that claimed otherwise would be claiming work nobody did"
            )

    return {
        f"transfer.{name}": _render_transfer(block[name]) for name in _TRANSFER_FIELDS
    }


#: The three claims a schema-2 profile has to disclaim, in the order the stage
#: 7D specification lists them. All three are false in every profile this
#: project can execute, and all three are inside the fingerprint, so a profile
#: that started claiming one would be a different profile rather than the same
#: one read more generously (spec section 11).
_REQUIRED_FALSE_CLAIMS: tuple[str, ...] = (
    "calibrated_fmr",
    "equivalent_to_sourceafis_operating_point",
    "optimal_for_sd300",
)


def _claims_metadata(
    document: Mapping[str, Any], path: Path, *, schema_version: str
) -> Mapping[str, str]:
    """Read the ``claims`` block, which exists to be false.

    A threshold taken from somebody else's documentation carries no measurement
    of this study's data. It has no calibrated false-match rate, it is not
    equivalent to another algorithm's operating point, and it is not an optimum
    for SD300 — three sentences that are easy to write in a paper and impossible
    to substantiate here. The block turns each of them into a flag that is
    checked and fingerprinted rather than a caveat somebody may forget to repeat
    (docs/adr/0057, docs/adr/0058).
    """
    block = document.get("claims")
    if schema_version == "1":
        if block is not None:
            raise DecisionProfileError(
                f"{path}: a 'claims' block needs profile schema 2. Under schema 1 it "
                "would sit outside the fingerprint, which is worse than not having "
                "it: the file would assert something its identity did not cover"
            )
        return {}
    if not isinstance(block, Mapping):
        raise DecisionProfileError(
            f"{path}: schema 2 requires a 'claims' section. A profile that says "
            "nothing about what it does not claim is a profile whose reader has to "
            "guess"
        )
    unknown = sorted(set(map(str, block)) - set(_REQUIRED_FALSE_CLAIMS))
    if unknown:
        raise DecisionProfileError(
            f"{path}: unknown claims {unknown}; this project has a fixed catalogue "
            "of claims it refuses to make, and a new one needs a decision, not a key"
        )
    for name in _REQUIRED_FALSE_CLAIMS:
        if _yaml_bool(block, name, path=path, section="claims"):
            raise DecisionProfileError(
                f"{path}: claims.{name} may not be true. Nothing in this project "
                "has measured it, and a threshold profile is not where such a "
                "claim could be established"
            )
    return {f"claims.{name}": _flag(False) for name in _REQUIRED_FALSE_CLAIMS}


def _statement_kind_metadata(
    provenance: Mapping[str, Any], path: Path, *, schema_version: str
) -> Mapping[str, str]:
    """Record *what kind of sentence* the upstream source actually wrote.

    NIST's guide describes a score above 40 as a rule of thumb that usually
    indicates a true match. That is not the same kind of statement as a
    published operating point with a measured error rate, and the difference is
    the whole reason stage 7D refuses to equate two thresholds that happen to
    be spelled with the same digits (docs/adr/0058).
    """
    value = provenance.get("source_statement_kind")
    if schema_version == "1":
        if value is not None:
            raise DecisionProfileError(
                f"{path}: provenance.source_statement_kind needs profile schema 2; "
                "under schema 1 it would not reach the fingerprint"
            )
        return {}
    text = str(value or "").strip()
    if not text:
        raise DecisionProfileError(
            f"{path}: schema 2 requires provenance.source_statement_kind — what the "
            "upstream source actually claimed, not merely where it is written"
        )
    return {"provenance.source_statement_kind": text}


def _render_transfer(value: Any) -> str:
    if isinstance(value, bool):
        return _flag(value)
    return str(value)


def _render(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise DecisionProfileError(f"{path}: missing or malformed '{key}' section")
    return value


_MISSING = object()


def _yaml_bool(
    section_value: Mapping[str, Any],
    name: str,
    *,
    path: Path,
    section: str,
    default: object = _MISSING,
) -> bool:
    """Read one YAML boolean without accepting truthy strings or integers."""
    if name not in section_value:
        if default is _MISSING:
            raise DecisionProfileError(f"{path}: {section}.{name} is required")
        value = default
    else:
        value = section_value[name]
    if type(value) is not bool:
        raise DecisionProfileError(
            f"{path}: {section}.{name} must be a YAML boolean, got "
            f"{type(value).__name__}"
        )
    return value


def _flag(value: bool) -> str:
    if type(value) is not bool:
        raise TypeError("a rendered flag must be a bool")
    return "true" if value else "false"
