from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from fpbench.baseline_evaluation.roster import load_baseline_roster_config
from fpbench.core.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "comparisons" / "final_baseline_roster_v1.yaml"
pytestmark = pytest.mark.stage21a_contract


def _document() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / CONFIG.name
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_real_roster_keeps_five_primary_and_the_completed_sixth_method() -> None:
    roster = load_baseline_roster_config(CONFIG)
    assert roster.method_ids == (
        "sourceafis_java",
        "nbis_mindtct_bozorth3",
        "flx_deepprint_texminu_512_without_localization",
        "verifinger_1to1",
        "nbis_mindtct_mcc_sdk_v2",
        "nbis_mindtct_openafis_capacity_extended",
    )
    assert sum(method.role == "primary_baseline" for method in roster.methods) == 5
    assert roster.methods[-1].role == "additional_experimentally_evaluated_method"
    assert roster.common_score_membership == "all_roster_methods"
    assert roster.common_score_primary is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.__setitem__("selection_uses_score_values", True),
        lambda d: (d["methods"].pop(), d["methods"].pop()),
        lambda d: d["methods"][0].__setitem__("role", "unknown"),
        lambda d: d["methods"].append(copy.deepcopy(d["methods"][0])),
        lambda d: d["common_score_population"].__setitem__(
            "primary_result", True
        ),
        lambda d: d["common_score_population"].__setitem__(
            "membership", "algorithm_specific"
        ),
        lambda d: d["excluded_completed_routes"][0].__setitem__(
            "decision_uses_score_values", True
        ),
        lambda d: d.__setitem__("threshold", 40),
    ],
)
def test_roster_methodology_changes_are_rejected(tmp_path: Path, mutation) -> None:
    document = copy.deepcopy(_document())
    mutation(document)
    with pytest.raises(ConfigurationError):
        load_baseline_roster_config(_write(tmp_path, document))
