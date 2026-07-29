"""The shipped configs must load and mean what the protocol document says."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.enums import CohortRole
from fpbench.core.errors import ConfigurationError
from fpbench.datasets.registry import create_provider, load_dataset_spec
from fpbench.protocols.sd300_protocol import SD300Protocol, load_protocol_config

REPO = Path(__file__).resolve().parents[2]
DATASET_CONFIG = REPO / "configs" / "datasets" / "sd300.yaml"
PROTOCOL_CONFIG = REPO / "configs" / "protocols" / "sd300_50_subjects.yaml"


def test_dataset_config_requires_the_root_environment_variable(monkeypatch):
    monkeypatch.delenv("FPBENCH_SD300_ROOT", raising=False)
    with pytest.raises(ConfigurationError, match="FPBENCH_SD300_ROOT"):
        load_dataset_spec(DATASET_CONFIG)


def test_dataset_config_resolves_all_three_releases(monkeypatch, tmp_path):
    monkeypatch.setenv("FPBENCH_SD300_ROOT", str(tmp_path))
    provider = create_provider(load_dataset_spec(DATASET_CONFIG))
    assert provider.releases == ("SD300A", "SD300B", "SD300C")
    assert provider.layout("SD300C").effective_ppi == 2000


def test_root_override_bypasses_the_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("FPBENCH_SD300_ROOT", raising=False)
    spec = load_dataset_spec(DATASET_CONFIG, root_override=tmp_path)
    assert spec.root == tmp_path


def test_protocol_config_matches_the_agreed_protocol():
    config = load_protocol_config(PROTOCOL_CONFIG)
    assert config.protocol_id == "sd300_50_subjects"
    assert config.criteria.size == 50
    assert config.criteria.role is CohortRole.TEST
    assert config.criteria.releases == ("SD300A", "SD300B", "SD300C")
    assert config.criteria.require_all_ten_plain
    assert config.criteria.require_all_ten_roll
    assert config.criteria.require_common_across_releases
    assert config.plan.plain_self
    assert config.plan.roll_self
    assert config.plan.plain_roll_mated
    assert config.plan.plain_roll_non_mated
    assert config.plan.non_mated_finger_shift == 1


def test_protocol_config_points_at_an_existing_dataset_config():
    config = load_protocol_config(PROTOCOL_CONFIG)
    assert config.dataset_config == DATASET_CONFIG.resolve()


def test_protocol_object_exposes_its_releases():
    protocol = SD300Protocol.from_config_file(PROTOCOL_CONFIG)
    assert protocol.releases == ("SD300A", "SD300B", "SD300C")
    assert protocol.dataset_id == "sd300"


def test_sd300_protocol_rejects_non_common_cross_release_cohorts(tmp_path):
    path = tmp_path / "configs" / "protocols" / "invalid.yaml"
    path.parent.mkdir(parents=True)
    document = PROTOCOL_CONFIG.read_text(encoding="utf-8").replace(
        "common_across_releases: true", "common_across_releases: false"
    )
    path.write_text(document, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="common_across_releases=true"):
        load_protocol_config(path)
