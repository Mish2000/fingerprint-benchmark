"""A protocol config that would mean something else must not load.

Each case below loaded successfully before ADR 0140 and produced a run under a
protocol nobody wrote. The last test is the one that matters most: the real
config still loads, unchanged.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from fpbench.core.enums import CohortRole
from fpbench.core.errors import ConfigurationError, ProtocolError
from fpbench.protocols.cohorts import CohortCriteria
from fpbench.protocols.sd300_protocol import load_protocol_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG = REPOSITORY_ROOT / "configs" / "protocols" / "sd300_50_subjects.yaml"


def _write(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / "configs" / "protocols" / "candidate.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _base() -> dict[str, Any]:
    return yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))


CASES: dict[str, Callable[[dict[str, Any]], None]] = {
    # bool("false") is True: this used to *enable* the requirement it turns off.
    'all_ten_plain: "false"': lambda d: d["cohort"]["require"].__setitem__(
        "all_ten_plain", "false"
    ),
    'common_across_releases: "no"': lambda d: d["cohort"]["require"].__setitem__(
        "common_across_releases", "no"
    ),
    # int(True) is 1: a one-subject cohort.
    "size: true": lambda d: d["cohort"].__setitem__("size", True),
    "size: 0": lambda d: d["cohort"].__setitem__("size", 0),
    "size: -1": lambda d: d["cohort"].__setitem__("size", -1),
    "size: 50.0": lambda d: d["cohort"].__setitem__("size", 50.0),
    'seed: "20260728"': lambda d: d["cohort"].__setitem__("seed", "20260728"),
    "misspelled cohort key": lambda d: d["cohort"].__setitem__("sizee", 50),
    "misspelled require key": lambda d: d["cohort"]["require"].__setitem__(
        "all_ten_rolls", True
    ),
    "misspelled pairs key": lambda d: d["pairs"].__setitem__("plain_selfs", False),
    "unknown top-level section": lambda d: d.__setitem__("thresholds", {"score": 40}),
    "role: bogus": lambda d: d["cohort"].__setitem__("role", "bogus"),
    "releases as a bare string": lambda d: d["cohort"].__setitem__(
        "releases", "SD300A"
    ),
    "releases repeated": lambda d: d["cohort"].__setitem__(
        "releases", ["SD300A", "SD300A", "SD300B"]
    ),
    "releases empty": lambda d: d["cohort"].__setitem__("releases", []),
    "every stage disabled": lambda d: d["pairs"].update(
        {
            "plain_self": False,
            "roll_self": False,
            "plain_roll_mated": False,
            "plain_roll_non_mated": False,
        }
    ),
    'finger_shift: "1"': lambda d: d["pairs"].__setitem__(
        "plain_roll_non_mated", {"enabled": True, "finger_shift": "1"}
    ),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_config_that_would_mean_something_else_is_refused(
    name: str, tmp_path: Path
) -> None:
    document = _base()
    CASES[name](document)
    with pytest.raises((ConfigurationError, ProtocolError)):
        load_protocol_config(_write(tmp_path, document))


def test_the_message_names_the_file_and_the_key(tmp_path: Path) -> None:
    document = _base()
    document["cohort"]["require"]["all_ten_plain"] = "false"
    with pytest.raises(ConfigurationError) as raised:
        load_protocol_config(_write(tmp_path, document))
    message = str(raised.value)
    assert "candidate.yaml" in message
    assert "all_ten_plain" in message
    assert "YAML boolean" in message


def test_the_real_protocol_config_still_loads_to_the_same_protocol() -> None:
    """The change refuses what was wrong; it must accept what was right."""
    config = load_protocol_config(REAL_CONFIG)
    assert config.protocol_id == "sd300_50_subjects"
    assert config.dataset_id == "sd300"
    assert config.criteria.size == 50
    assert config.criteria.seed == 20260728
    assert config.criteria.role is CohortRole.TEST
    assert config.criteria.releases == ("SD300A", "SD300B", "SD300C")
    assert config.criteria.require_all_ten_plain is True
    assert config.criteria.require_all_ten_roll is True
    assert config.criteria.require_common_across_releases is True
    assert config.plan.plain_self is True
    assert config.plan.roll_self is True
    assert config.plan.plain_roll_mated is True
    assert config.plan.plain_roll_non_mated is True
    assert config.plan.non_mated_finger_shift == 1


@pytest.mark.parametrize("size", [-1, 0, True])
def test_a_cohort_that_draws_nobody_is_refused_at_construction(size: object) -> None:
    """``select_cohort``'s ``len(candidates) < size`` passes for every negative."""
    with pytest.raises(ProtocolError, match="positive integer"):
        CohortCriteria(size=size, seed=1, releases=("SD300A",))  # type: ignore[arg-type]


def test_a_cohort_naming_one_release_twice_is_refused() -> None:
    """Deduplicating would make ``common_across_releases`` look satisfied by one."""
    with pytest.raises(ProtocolError, match="twice"):
        CohortCriteria(size=50, seed=1, releases=("SD300A", "SD300A"))
