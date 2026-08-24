"""Reading the comparison policy, and refusing the claims it forbids.

A paired policy is a short YAML document, and almost all of it is a list of
things this comparison may not do. That is deliberate: the interesting failure
mode of a paired analysis is not a wrong number, it is a correct number
presented as an answer to a question nobody asked.

So the policy states, and the loader enforces, that this comparison performs no
significance test, computes no confidence interval, runs no bootstrap and no
McNemar, claims no resolution superiority, claims no causality, and claims no
general false-match rate. Every one of those needs machinery that does not
exist; a flag that switched one on would be requesting a claim nothing could
back (docs/adr/0030, docs/adr/0038).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.errors import ConfigurationError
from fpbench.core.serialization import stable_hash

__all__ = [
    "PairedComparisonPolicy",
    "load_paired_policy",
    "paired_policy_fingerprint",
    "FORBIDDEN_CLAIMS",
    "FORBIDDEN_STATISTICS",
]

#: Claims a paired comparison may never make. Checked, not merely recorded.
FORBIDDEN_CLAIMS: tuple[str, ...] = (
    "resolution_superiority",
    "capture_quality_causality",
    "general_fmr",
)

#: Statistical machinery this stage does not have. A confidence interval over a
#: closed cohort of 50 subjects would need a sampling model nobody has written
#: down, and a significance test would need a hypothesis nobody has stated.
FORBIDDEN_STATISTICS: tuple[str, ...] = (
    "confidence_intervals",
    "significance_tests",
    "bootstrap",
    "mcnemar",
)


@dataclass(frozen=True, slots=True)
class PairedComparisonPolicy:
    """What the comparison joins on, insists on, and refuses to say."""

    policy_id: str
    policy_version: str
    policy_fingerprint: str

    pairing_key: str
    require_same_pair_manifest: bool
    require_same_algorithm: bool
    require_same_runtime_bundle: bool
    require_same_threshold_rule: bool

    sd300a_exact_score_equality: bool
    sd300a_exact_decision_equality: bool

    transition_families: tuple[str, ...]

    retain_pair_delta: bool
    report_direction_counts: bool
    report_distribution: bool

    document: Mapping[str, Any]

    def fingerprint_of(self, document: Any) -> str:
        """Derive a document's fingerprint by the rule that produced this one.

        The storage layer holds the document and the fingerprint side by side and
        cannot check that one came from the other: the rule is here, and that
        layer imports only ``core``. So it asks the policy, before it publishes
        anything, whether the exact bytes it is about to write derive to the
        fingerprint the set claims.

        This is not a formality. ``document`` is an ordinary field of a frozen
        dataclass, so ``dataclasses.replace`` produces a perfectly real
        :class:`PairedComparisonPolicy` carrying somebody else's document under
        this one's fingerprint — and until storage asked, that published.
        """
        return policy_from_document(document, source="policy document").policy_fingerprint


def load_paired_policy(path: Path) -> PairedComparisonPolicy:
    """Read ``configs/comparisons/policies/<name>.yaml``."""
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"paired comparison policy not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return policy_from_document(document, source=path)


def policy_from_document(
    document: Any, *, source: object
) -> PairedComparisonPolicy:
    """The same policy, derived from a document rather than from a file.

    Split out so that a *stored* ``policy.json`` can be read back through the
    identical rules that produced the fingerprint in the first place. Storage
    cannot do this — the rules are here, and that layer imports only ``core``
    — so it asks a policy to re-derive itself from the exact document it is
    about to write, and this is what answers.

    ``source`` only names the document in error messages.
    """
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{source}: expected a mapping at the top level")
    path = source

    unknown_sections = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown_sections:
        raise ConfigurationError(
            f"{path}: the document carries {unknown_sections}, which this policy "
            f"does not define. Permitted sections are {sorted(_TOP_LEVEL_KEYS)}"
        )

    policy = _section(document, "policy", path)
    pairing = _section(document, "pairing", path)
    control = _section(document, "control", path)
    transitions = _section(document, "transitions", path)
    scores = _section(document, "scores", path)
    statistics = _section(document, "statistics", path)
    claims = _section(document, "claims", path)

    if str(pairing.get("key")) != "pair_id":
        raise ConfigurationError(
            f"{path}: pairing.key must be pair_id. A job id is a hash over its own "
            "run and differs between the two; an ordinal alone would join silently "
            "and wrongly (spec section 27)"
        )
    for name in (
        "require_same_pair_manifest",
        "require_same_algorithm",
        "require_same_runtime_bundle",
        "require_same_threshold_rule",
    ):
        if not _yaml_bool(pairing, name, path=path, section="pairing", default=False):
            raise ConfigurationError(
                f"{path}: pairing.{name} must be true. Relaxing it would let the "
                "comparison measure a sum of differences and attribute it to one"
            )

    for name in ("sd300a_exact_score_equality", "sd300a_exact_decision_equality"):
        if str(control.get(name)) != "required":
            raise ConfigurationError(
                f"{path}: control.{name} must be 'required'. SD300A is the control: "
                "identical pixels through an identical build must reproduce exactly, "
                "and without that check no other number here can be interpreted"
            )

    for name in FORBIDDEN_STATISTICS:
        if _yaml_bool(statistics, name, path=path, section="statistics", default=False):
            raise ConfigurationError(
                f"{path}: statistics.{name} may not be true. The machinery behind "
                "it does not exist, and switching a flag would not create it"
            )
    for name in FORBIDDEN_CLAIMS:
        if _yaml_bool(claims, name, path=path, section="claims", default=False):
            raise ConfigurationError(
                f"{path}: claims.{name} may not be true. This comparison observes "
                "what changed between two runs; it establishes no superiority, no "
                "cause and no population rate"
            )

    if not _yaml_bool(
        scores, "retain_pair_delta", path=path, section="scores", default=True
    ):
        raise ConfigurationError(
            f"{path}: scores.retain_pair_delta may not be false. The control "
            "audit compares SD300A's two runs score for score, and a paired "
            "record refuses a scored relation with no delta — so nothing here "
            "can produce the derivation that flag describes"
        )

    report_distribution = _yaml_bool(
        scores, "report_distribution", path=path, section="scores", default=False
    )
    if report_distribution:
        raise ConfigurationError(
            f"{path}: scores.report_distribution may not be true. Scores are used "
            "here for exact equality on the control, for direction counts, and for "
            "nothing else (spec section 31)"
        )

    families = tuple(
        name
        for name in sorted(transitions)
        if _yaml_bool(transitions, name, path=path, section="transitions")
    )
    if not families:
        raise ConfigurationError(f"{path}: transitions enables no family")

    fields = dict(
        policy_id=str(policy["policy_id"]),
        policy_version=str(policy.get("policy_version", "1")),
        pairing_key="pair_id",
        require_same_pair_manifest=True,
        require_same_algorithm=True,
        require_same_runtime_bundle=True,
        require_same_threshold_rule=True,
        sd300a_exact_score_equality=True,
        sd300a_exact_decision_equality=True,
        transition_families=families,
        retain_pair_delta=_yaml_bool(
            scores, "retain_pair_delta", path=path, section="scores", default=True
        ),
        report_direction_counts=_yaml_bool(
            scores,
            "report_direction_counts",
            path=path,
            section="scores",
            default=True,
        ),
        report_distribution=False,
        document=dict(document),
    )
    fingerprint = paired_policy_fingerprint(fields)
    return PairedComparisonPolicy(policy_fingerprint=fingerprint, **fields)


def paired_policy_fingerprint(fields: Mapping[str, Any]) -> str:
    """A digest of the policy's rules, excluding the file it was read from."""
    payload = {key: value for key, value in dict(fields).items() if key != "document"}
    return stable_hash(
        {"schema": "paired_policy_fingerprint_v1", "policy": payload}, length=64
    )


#: Every key each section of a paired-comparison policy may carry.
#:
#: A key outside these is refused rather than ignored. ``retain_pair_dleta:
#: false`` used to be read as "this document sets nothing", which is
#: indistinguishable from a document that deliberately leaves the default —
#: except that the author believed they had turned something off.
_SECTION_KEYS: Mapping[str, frozenset[str]] = {
    "policy": frozenset({"policy_id", "policy_version"}),
    "pairing": frozenset(
        {
            "key",
            "require_same_pair_manifest",
            "require_same_algorithm",
            "require_same_runtime_bundle",
            "require_same_threshold_rule",
        }
    ),
    "control": frozenset(
        {"sd300a_exact_score_equality", "sd300a_exact_decision_equality"}
    ),
    "scores": frozenset(
        {"retain_pair_delta", "report_direction_counts", "report_distribution"}
    ),
    # The refusal sections. Their keys are exactly the things this stage does
    # not have and may not say, so an unrecognised one is not a new option — it
    # is a claim or a statistic nobody implemented, spelled as though somebody
    # had. ``statistics.bootstrp: true`` set nothing, raised nothing, and did
    # not move the policy fingerprint.
    "statistics": frozenset(FORBIDDEN_STATISTICS),
    "claims": frozenset(FORBIDDEN_CLAIMS),
    # Every transition family the derivation can build. One that is not here
    # cannot be counted, so enabling it would be a policy nothing can obey.
    "transitions": frozenset(
        {
            "plain_self",
            "roll_self",
            "mated_unconditional",
            "mated_common_eligible",
            "negative_sanity",
            "eligibility",
        }
    ),
}

#: The document's own sections. A new top-level key was accepted and ignored,
#: which reads to an author exactly like a section that took effect.
_TOP_LEVEL_KEYS = frozenset(_SECTION_KEYS)


def _reject_unknown(
    section: Mapping[str, Any], key: str, path: Path
) -> Mapping[str, Any]:
    permitted = _SECTION_KEYS.get(key)
    if permitted is None:
        return section
    unknown = sorted(set(section) - permitted)
    if unknown:
        raise ConfigurationError(
            f"{path}: {key} carries {unknown}, which this policy does not define. "
            f"Permitted keys are {sorted(permitted)}"
        )
    return section


def _section(document: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{path}: missing or malformed '{key}' section")
    return _reject_unknown(value, key, path)


_MISSING = object()


def _yaml_bool(
    section_value: Mapping[str, Any],
    name: str,
    *,
    path: Path,
    section: str,
    default: object = _MISSING,
) -> bool:
    """Read one YAML boolean without Python's truthiness coercions."""
    if name not in section_value:
        if default is _MISSING:
            raise ConfigurationError(f"{path}: {section}.{name} is required")
        value = default
    else:
        value = section_value[name]
    if type(value) is not bool:
        raise ConfigurationError(
            f"{path}: {section}.{name} must be a YAML boolean, got "
            f"{type(value).__name__}"
        )
    return value
