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


def _require_mapping(document: Mapping[str, Any], key: str, source: Path) -> Mapping[str, Any]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{source}: missing or malformed '{key}' section")
    return value


def load_protocol_config(path: Path) -> SD300ProtocolConfig:
    """Read ``configs/protocols/<name>.yaml``.

    Paths inside the config are resolved relative to the repository root, taken
    as the config file's grandparent (``configs/protocols/x.yaml`` -> repo).
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"protocol config not found: {path}")
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")

    protocol = _require_mapping(document, "protocol", path)
    dataset = _require_mapping(document, "dataset", path)
    cohort = _require_mapping(document, "cohort", path)
    pairs = _require_mapping(document, "pairs", path)

    protocol_id = protocol.get("id")
    if not protocol_id:
        raise ConfigurationError(f"{path}: protocol.id is required")

    dataset_ref = dataset.get("ref")
    if not dataset_ref:
        raise ConfigurationError(f"{path}: dataset.ref is required")
    repo_root = path.resolve().parent.parent.parent
    dataset_config = (repo_root / str(dataset_ref)).resolve()

    releases = tuple(cohort.get("releases") or ())
    if not releases:
        raise ConfigurationError(f"{path}: cohort.releases must list at least one release")

    require = cohort.get("require") or {}
    criteria = CohortCriteria(
        size=int(cohort["size"]),
        seed=int(cohort["seed"]),
        releases=releases,
        role=CohortRole(str(cohort.get("role", CohortRole.TEST.value))),
        require_all_ten_plain=bool(require.get("all_ten_plain", True)),
        require_all_ten_roll=bool(require.get("all_ten_roll", True)),
        require_common_across_releases=bool(
            require.get("common_across_releases", True)
        ),
    )

    non_mated = pairs.get("plain_roll_non_mated") or {}
    if isinstance(non_mated, bool):  # allow the terse form
        non_mated = {"enabled": non_mated}
    plan = PairPlan(
        plain_self=bool(pairs.get("plain_self", True)),
        roll_self=bool(pairs.get("roll_self", True)),
        plain_roll_mated=bool(pairs.get("plain_roll_mated", True)),
        plain_roll_non_mated=bool(non_mated.get("enabled", True)),
        non_mated_finger_shift=int(non_mated.get("finger_shift", 1)),
    )

    return SD300ProtocolConfig(
        protocol_id=str(protocol_id),
        dataset_id=str(dataset.get("id", "sd300")),
        dataset_config=dataset_config,
        criteria=criteria,
        plan=plan,
    )


class SD300Protocol(Protocol):
    """50 complete subjects, four comparison stages, per release."""

    def __init__(self, config: SD300ProtocolConfig) -> None:
        self.config = config
        self.protocol_id = config.protocol_id
        self.dataset_id = config.dataset_id

    @classmethod
    def from_config_file(cls, path: Path) -> "SD300Protocol":
        return cls(load_protocol_config(path))

    @property
    def releases(self) -> tuple[str, ...]:
        return self.config.criteria.releases

    def build_cohort(self, subjects: Iterable[SubjectRecord]) -> Cohort:
        return select_cohort(
            protocol_id=self.protocol_id,
            dataset_id=self.dataset_id,
            subjects=subjects,
            criteria=self.config.criteria,
        )

    def build_pairs(
        self, cohort: Cohort, images: Sequence[ImageRecord]
    ) -> tuple[ComparisonPair, ...]:
        return generate_pairs(cohort, images, self.config.plan)
