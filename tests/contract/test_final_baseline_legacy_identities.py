"""The real frozen roster must dispatch without opening any score source."""

import json
from collections import Counter
from pathlib import Path

import pytest

from fpbench.final_baseline.sources import legacy_source_format

pytestmark = pytest.mark.final_baseline_contract


def test_all_six_stage21a_identity_shapes_are_supported(monkeypatch):
    roster_path = (
        Path(__file__).resolve().parents[2]
        / "evidence/stage21a-final-baseline-evaluation-protocol/baseline-roster.json"
    )
    original_open = Path.open
    opened = []

    def metadata_only(path, *args, **kwargs):
        assert path == roster_path, "identity dispatch must not open a score store"
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", metadata_only)
    methods = json.loads(roster_path.read_bytes())["methods"]
    formats = {
        row["algorithm_id"]: legacy_source_format(
            row["algorithm_id"], row["raw_result_identity"]
        )
        for row in methods
    }
    assert formats == {
        "sourceafis_java": "result_set_store",
        "nbis_mindtct_bozorth3": "result_set_store",
        "flx_deepprint_texminu_512_without_localization": "result_set_store",
        "verifinger_1to1": "result_set_store",
        "nbis_mindtct_mcc_sdk_v2": "stage20b_pair_outcomes_jsonl",
        "nbis_mindtct_openafis_capacity_extended": "stage19b_pair_outcomes_jsonl",
    }
    assert list(formats) == [row["algorithm_id"] for row in methods]
    assert Counter(formats.values()) == {
        "result_set_store": 4,
        "stage20b_pair_outcomes_jsonl": 1,
        "stage19b_pair_outcomes_jsonl": 1,
    }
    assert opened == [roster_path]
