"""Integrity-bearing Stage 5B integers are parsed, never coerced."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from fpbench.core.errors import ConfigurationError, MetricPolicyError, StorageError
from fpbench.experiments.sourceafis_native_evaluation import load_evaluation_config
from fpbench.metrics import load_metric_policy
from fpbench.storage.metric_set_store import MetricSetStore
from metricworld import (
    DEFAULT_POLICY_PATH,
    REPOSITORY_ROOT,
    SPEC_EXAMPLE_SCRIPT,
    build_metric_world,
)

pytestmark = pytest.mark.metrics

INVALID_INTEGERS = (2.5, "2", True, None)


@pytest.fixture
def stored(tmp_path: Path):
    world = build_metric_world({"SD300A": SPEC_EXAMPLE_SCRIPT})
    set_id = world.finalize(tmp_path)
    return world, set_id, MetricSetStore(tmp_path)


def _edit_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _mutate_summary(payload, family: str, value) -> None:
    if family == "count_ordinal":
        payload["count_records"][0]["ordinal"] = value
    elif family == "total_count":
        payload["count_records"][0]["total_count"] = value
    elif family == "component_count":
        key = next(iter(payload["count_records"][0]["counts"]))
        payload["count_records"][0]["counts"][key] = value
    elif family == "observation_ordinal":
        payload["observations"][0]["ordinal"] = value
    elif family == "numerator_count":
        payload["observations"][0]["numerator_count"] = value
    else:
        payload["observations"][0]["denominator_count"] = value


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize(
    "family",
    (
        "count_ordinal",
        "total_count",
        "component_count",
        "observation_ordinal",
        "numerator_count",
        "denominator_count",
    ),
)
def test_summary_count_families_reject_non_integer_json(
    stored, family, value
) -> None:
    world, set_id, store = stored
    path = store.summary_path(world.run_id, set_id)
    _edit_json(path, lambda payload: _mutate_summary(payload, family, value))

    with pytest.raises(StorageError, match="exact integer"):
        store.read_summary(world.run_id, set_id)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize("field", ("total_count_records", "total_observations"))
def test_manifest_row_totals_reject_non_integer_json(stored, field, value) -> None:
    world, set_id, store = stored
    path = store.manifest_path(world.run_id, set_id)
    _edit_json(path, lambda payload: payload.__setitem__(field, value))

    with pytest.raises(StorageError, match="exact integer"):
        store.read_manifest(world.run_id, set_id)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize(
    "family", ("structural", "metric_numerator", "metric_denominator")
)
def test_receipt_counts_reject_non_integer_json(stored, family, value) -> None:
    world, set_id, store = stored

    def mutate(payload):
        if family == "structural":
            payload["structural_counts"]["decisions"] = value
            return
        metric = next(iter(payload["metrics"]))
        scope = next(iter(payload["metrics"][metric]))
        field = "numerator" if family == "metric_numerator" else "denominator"
        payload["metrics"][metric][scope][field] = value

    _edit_json(store.receipt_path(world.run_id, set_id), mutate)
    with pytest.raises(StorageError, match="exact integer"):
        store.read_receipt(world.run_id, set_id)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize("artifact", ("policy", "report_profile"))
def test_stored_percentage_precision_rejects_non_integer_json(
    stored, artifact, value
) -> None:
    world, set_id, store = stored
    if artifact == "policy":
        path = store.policy_path(world.run_id, set_id)
        reader = store.read_policy
    else:
        path = store.report_profile_path(world.run_id, set_id)
        reader = store.read_report_profile
    _edit_json(
        path,
        lambda payload: payload.__setitem__("percentage_decimal_places", value),
    )

    with pytest.raises(StorageError, match="exact integer"):
        reader(world.run_id, set_id)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
@pytest.mark.parametrize(
    "field",
    (
        "decisions",
        "eligibility_units",
        "rows_per_view",
        "rows_per_release_per_view",
    ),
)
def test_expected_shape_rejects_non_integer_yaml(tmp_path: Path, field, value) -> None:
    source = (
        REPOSITORY_ROOT
        / "configs"
        / "evaluations"
        / "sourceafis_native_threshold40_v1.yaml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["expected_shape"][field] = value
    path = tmp_path / "evaluation.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="exact integer"):
        load_evaluation_config(path, repository_root=REPOSITORY_ROOT)


@pytest.mark.parametrize("value", INVALID_INTEGERS)
def test_policy_percentage_precision_rejects_non_integer_yaml(
    tmp_path: Path, value
) -> None:
    payload = yaml.safe_load(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    payload["display"]["percentage_decimal_places"] = value
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(MetricPolicyError, match="exact integer"):
        load_metric_policy(path)
