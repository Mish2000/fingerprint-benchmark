from __future__ import annotations

import copy
from fractions import Fraction
from pathlib import Path

import pytest
import yaml

from fpbench.baseline_evaluation.policy import load_baseline_evaluation_policy
from fpbench.core.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "comparisons" / "final_baseline_tar_far_frr_v1.yaml"
ROSTER = ROOT / "configs" / "comparisons" / "final_baseline_roster_v1.yaml"
pytestmark = pytest.mark.stage21a_contract


def _document() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "configs" / "comparisons" / CONFIG.name
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    roster = path.parent / "final_baseline_roster_v1.yaml"
    roster.write_text(ROSTER.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def test_the_real_policy_freezes_only_tar_far_frr_and_three_targets() -> None:
    policy = load_baseline_evaluation_policy(CONFIG)
    assert policy.allowed_metrics == ("TAR", "FAR", "FRR")
    assert policy.primary_far_target == Fraction(1, 1000)
    assert set(policy.far_targets) == {
        Fraction(1, 100),
        Fraction(1, 1000),
        Fraction(1, 10000),
    }
    assert policy.per_release and policy.pooled and policy.common_score_secondary
    assert len(policy.roster.methods) == 6
    assert policy.roster.common_score_primary is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["metrics"]["allowed"].append("OTHER"),
        lambda d: d["threshold_evaluation"].__setitem__("calibration", True),
        lambda d: d["threshold_evaluation"].__setitem__(
            "create_operational_threshold", True
        ),
        lambda d: d["threshold_evaluation"].__setitem__("interpolation", "allowed"),
        lambda d: d["populations"].__setitem__("eligibility_filtering", "self"),
        lambda d: d["far_targets"].__setitem__("primary", 0.002),
        lambda d: d.__setitem__("threshold_profile", {}),
    ],
)
def test_a_methodological_change_is_not_silently_accepted(tmp_path, mutation) -> None:
    document = copy.deepcopy(_document())
    mutation(document)
    with pytest.raises(ConfigurationError):
        load_baseline_evaluation_policy(_write(tmp_path, document))
