"""The SD300 50-subject protocol.

Binds the cohort criteria and the pair plan declared in
``configs/protocols/*.yaml`` into a concrete :class:`Protocol`. All research
parameters — how many subjects, which seed, which releases, how impostor pairs
are formed — live in the config, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_non_empty_str,
)
from fpbench.core.enums import CohortRole
from fpbench.core.errors import ConfigurationError
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord, SubjectRecord
from fpbench.protocols.base import Protocol
from fpbench.protocols.cohorts import CohortCriteria, select_cohort
from fpbench.protocols.pair_generation import PairPlan, generate_pairs

__all__ = ["SD300ProtocolConfig", "SD300Protocol", "load_protocol_config"]


@dataclass(frozen=True, slots=True)
class SD300ProtocolConfig:
    protocol_id: str
    dataset_id: str
    dataset_config: Path
    criteria: CohortCriteria
    plan: PairPlan


#: Every key each section of a protocol config may carry. A key outside these is
#: refused rather than ignored: a misspelled ``plain_self`` that silently kept
#: its default would change which comparisons a run generates, and the run would
#: report success (docs/adr/0140).
_TOP_LEVEL_KEYS = frozenset({"protocol", "dataset", "cohort", "pairs"})
_PROTOCOL_KEYS = frozenset({"id"})
_DATASET_KEYS = frozenset({"id", "ref"})
_COHORT_KEYS = frozenset({"size", "seed", "role", "releases", "require"})
_REQUIRE_KEYS = frozenset(
    {"all_ten_plain", "all_ten_roll", "common_across_releases"}
)
_PAIRS_KEYS = frozenset(
    {"plain_self", "roll_self", "plain_roll_mated", "plain_roll_non_mated"}
)
_NON_MATED_KEYS = frozenset({"enabled", "finger_shift"})


def _require_mapping(document: Mapping[str, Any], key: str, source: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{source}: missing or malformed '{key}' section")
    return value


def _require_releases(cohort: Mapping[str, Any], where: str) -> tuple[str, ...]:
    """A list of distinct, non-empty release names, written as YAML strings.

    ``releases: SD300A`` is refused rather than read character by character, and
    a repeated release is refused rather than silently deduplicated — it would
    make ``require_common_across_releases`` look satisfied by one release.
    """
    value = cohort.get("releases")
    if not isinstance(value, (list, tuple)) or isinstance(value, str):
        raise ConfigurationError(
            f"{where}: 'releases' must be a YAML list of release names"
        )
    releases: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(
                f"{where}: releases[{index}] must be a non-empty YAML string, "
                f"got {type(item).__name__} {item!r}"
            )
        releases.append(item.strip())
    if not releases:
        raise ConfigurationError(
            f"{where}: 'releases' must list at least one release"
        )
    duplicates = sorted({r for r in releases if releases.count(r) > 1})
    if duplicates:
        raise ConfigurationError(f"{where}: releases repeats {duplicates}")
    return tuple(releases)


def _require_role(cohort: Mapping[str, Any], where: str) -> CohortRole:
    """One of the declared cohort roles, named exactly.

    ``role`` decides whether calibrating on this cohort is permitted, so an
    unrecognised value must stop the load rather than fall back to a default.
    """
    raw = cohort.get("role", CohortRole.TEST.value)
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigurationError(
            f"{where}: 'role' must be a YAML string naming a cohort role"
        )
    try:
        return CohortRole(raw.strip().lower())
    except ValueError:
        permitted = ", ".join(sorted(role.value for role in CohortRole))
        raise ConfigurationError(
            f"{where}: 'role' must be one of {permitted}, got {raw!r}"
        ) from None


def load_protocol_config(path: Path) -> SD300ProtocolConfig:
    """Read ``configs/protocols/<name>.yaml``.

    Paths inside the config are resolved relative to the repository root, taken
    as the config file's grandparent (``configs/protocols/x.yaml`` -> repo).

    Every scalar is read with the strict helpers in
    :mod:`fpbench.core.config_values` rather than with ``bool()`` and ``int()``.
    The difference is not stylistic: ``bool("false")`` is ``True``, so
    ``all_ten_plain: "false"`` used to *enable* the requirement it was written to
    turn off, and ``int(True)`` is ``1``, so ``size: true`` used to draw a
    one-subject cohort. Both would have produced a run that reported success
    under a protocol nobody wrote (docs/adr/0140).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"protocol config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    reject_unknown_keys(document, _TOP_LEVEL_KEYS, where=str(path))
    protocol = _require_mapping(document, "protocol", path)
    dataset = _require_mapping(document, "dataset", path)
    cohort = _require_mapping(document, "cohort", path)
    pairs = _require_mapping(document, "pairs", path)
    reject_unknown_keys(protocol, _PROTOCOL_KEYS, where=f"{path}: protocol")
    reject_unknown_keys(dataset, _DATASET_KEYS, where=f"{path}: dataset")
    reject_unknown_keys(cohort, _COHORT_KEYS, where=f"{path}: cohort")
    reject_unknown_keys(pairs, _PAIRS_KEYS, where=f"{path}: pairs")

    protocol_id = require_yaml_non_empty_str(
        protocol, "id", where=f"{path}: protocol"
    )
    dataset_ref = require_yaml_non_empty_str(dataset, "ref", where=f"{path}: dataset")
    repo_root = path.resolve().parent.parent.parent
    dataset_config = (repo_root / dataset_ref).resolve()

    cohort_where = f"{path}: cohort"
    releases = _require_releases(cohort, cohort_where)

    require = cohort.get("require", {})
    if not isinstance(require, Mapping):
        raise ConfigurationError(f"{cohort_where}: 'require' must be a mapping")
    require_where = f"{path}: cohort.require"
    reject_unknown_keys(require, _REQUIRE_KEYS, where=require_where)

    criteria = CohortCriteria(
        # A cohort of zero or fewer subjects is not a small cohort; it is a
        # protocol that draws nobody, and `sorted(...)[:0]` would have returned
        # one without complaint.
        size=require_yaml_exact_int(cohort, "size", where=cohort_where, minimum=1),
        seed=require_yaml_exact_int(cohort, "seed", where=cohort_where),
        releases=releases,
        role=_require_role(cohort, cohort_where),
        require_all_ten_plain=require_yaml_bool(
            require, "all_ten_plain", where=require_where, default=True
        ),
        require_all_ten_roll=require_yaml_bool(
            require, "all_ten_roll", where=require_where, default=True
        ),
        require_common_across_releases=require_yaml_bool(
            require, "common_across_releases", where=require_where, default=True
        ),
    )
    if not criteria.require_common_across_releases:
        raise ConfigurationError(
            f"{path}: SD300Protocol requires common_across_releases=true because "
            "pair generation requires every selected subject in every release"
        )

    pairs_where = f"{path}: pairs"
    non_mated = pairs.get("plain_roll_non_mated", {})
    if isinstance(non_mated, bool):  # the terse form: a bare true/false
        non_mated = {"enabled": non_mated}
    if not isinstance(non_mated, Mapping):
        raise ConfigurationError(
            f"{pairs_where}: 'plain_roll_non_mated' must be a YAML boolean or a "
            f"mapping, got {type(non_mated).__name__} {non_mated!r}"
        )
    non_mated_where = f"{path}: pairs.plain_roll_non_mated"
    reject_unknown_keys(non_mated, _NON_MATED_KEYS, where=non_mated_where)

    plan = PairPlan(
        plain_self=require_yaml_bool(
            pairs, "plain_self", where=pairs_where, default=True
        ),
        roll_self=require_yaml_bool(
            pairs, "roll_self", where=pairs_where, default=True
        ),
        plain_roll_mated=require_yaml_bool(
            pairs, "plain_roll_mated", where=pairs_where, default=True
        ),
        plain_roll_non_mated=require_yaml_bool(
            non_mated, "enabled", where=non_mated_where, default=True
        ),
        non_mated_finger_shift=require_yaml_exact_int(
            non_mated, "finger_shift", where=non_mated_where, default=1
        ),
    )
    if not (plan.plain_self or plan.roll_self or plan.plain_roll_mated or plan.plain_roll_non_mated):
        raise ConfigurationError(
            f"{pairs_where}: every comparison stage is disabled, so the protocol "
            "would generate no pairs at all"
        )

    return SD300ProtocolConfig(
        protocol_id=protocol_id,
        dataset_id=require_yaml_non_empty_str(
            dataset, "id", where=f"{path}: dataset", default="sd300"
        ),
        dataset_config=dataset_config,
        criteria=criteria,
        plan=plan,
    )


class SD300Protocol(Protocol):
    """50 complete subjects, four comparison stages, per release."""

    def __init__(self, config: SD300ProtocolConfig) -> None:
        if not config.criteria.require_common_across_releases:
            raise ConfigurationError(
                "SD300Protocol requires common_across_releases=true because pair "
                "generation requires every selected subject in every release"
            )
        self.config = config
        self.protocol_id = config.protocol_id
        self.dataset_id = config.dataset_id

    @classmethod
    def from_config_file(cls, path: Path) -> "SD300Protocol":
        return cls(load_protocol_config(path))

    @property
    def releases(self) -> tuple[str, ...]:
        return self.config.criteria.releases

    def build_cohort(
        self,
        subjects: Iterable[SubjectRecord],
        image_manifest_hashes: Mapping[str, str],
    ) -> Cohort:
        return select_cohort(
            protocol_id=self.protocol_id,
            dataset_id=self.dataset_id,
            subjects=subjects,
            criteria=self.config.criteria,
            image_manifest_hashes=image_manifest_hashes,
        )

    def build_pairs(
        self, cohort: Cohort, images: Sequence[ImageRecord]
    ) -> tuple[ComparisonPair, ...]:
        return generate_pairs(cohort, images, self.config.plan)
