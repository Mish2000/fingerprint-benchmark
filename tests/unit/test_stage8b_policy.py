"""The operational policy is frozen, loaded strictly, and inherits Stage 8A's budgets."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from fpbench.core.flx_errors import FlxPolicyError
from fpbench.core.serialization import to_plain
from fpbench.flx import identity
from fpbench.flx.policy import load_runtime_policy, runtime_policy_from_plain
from flxworld import make_policy

pytestmark = pytest.mark.stage8b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPOSITORY_ROOT / "configs" / "flx" / "stage8b_flx_runtime_policy_v1.yaml"
STAGE8A_POLICY_PATH = (
    REPOSITORY_ROOT / "configs" / "modern-matchers" / "stage8a_selection_policy_v1.yaml"
)


def _payload() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def test_the_committed_policy_loads_and_is_the_frozen_one() -> None:
    policy = load_runtime_policy(POLICY_PATH)

    assert policy.policy_id == identity.RUNTIME_POLICY_ID
    assert policy.fingerprint == _payload()["fingerprint"]


def test_the_full_run_budgets_are_stage8a_s_own() -> None:
    # Spec section 19 permits binding directly to stage8a_selection_policy_v1.
    # Inheriting by fingerprint means the two documents cannot drift into
    # different budgets for the same run.
    policy = load_runtime_policy(POLICY_PATH)
    stage8a = yaml.safe_load(STAGE8A_POLICY_PATH.read_text(encoding="utf-8"))

    assert policy.inherits_selection_policy_fingerprint == stage8a["fingerprint"]
    assert policy.max_projected_12000_extractions_seconds == (
        stage8a["max_projected_12000_extractions_seconds"]
    )
    assert policy.max_projected_6000_comparisons_seconds == (
        stage8a["max_projected_6000_comparisons_seconds"]
    )
    assert policy.max_peak_ram_bytes == stage8a["max_peak_ram_bytes"]
    assert policy.max_artifact_disk_bytes == stage8a["max_artifact_disk_bytes"]


def test_every_operation_has_a_deadline() -> None:
    policy = load_runtime_policy(POLICY_PATH)
    for name in (
        "max_worker_startup_seconds",
        "max_model_load_seconds",
        "preprocess_deadline_seconds",
        "extract_deadline_seconds",
        "compare_deadline_seconds",
    ):
        assert Decimal(getattr(policy, name)) > 0, name


def test_the_policy_targets_bitwise_equality() -> None:
    assert load_runtime_policy(POLICY_PATH).numeric_tolerance == "0"


def _write_valid(path: Path, **changes) -> Path:
    """Write a policy whose fingerprint is internally consistent.

    Editing the YAML by hand trips the fingerprint check first, which would
    hide whichever rule the test is actually about.  These edits are
    re-fingerprinted so the loader has to refuse them on their merits.
    """
    payload = to_plain(make_policy(**changes))
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_a_widened_tolerance_is_refused_even_when_internally_consistent(
    tmp_path: Path,
) -> None:
    # Spec section 18: a wider tolerance is a new runtime profile declared in
    # advance, never an edit to this policy after a measurement was seen.
    path = _write_valid(tmp_path / "widened.yaml", numeric_tolerance="0.000001")

    with pytest.raises(FlxPolicyError, match="bitwise equality"):
        load_runtime_policy(path)


def test_a_renamed_policy_is_a_different_identity(tmp_path: Path) -> None:
    path = _write_valid(
        tmp_path / "renamed.yaml", policy_id="stage8b_flx_runtime_policy_v2"
    )

    with pytest.raises(FlxPolicyError, match="different policy is a different identity"):
        load_runtime_policy(path)


def test_an_edited_limit_no_longer_matches_its_fingerprint(tmp_path: Path) -> None:
    payload = _payload()
    payload["max_peak_ram_bytes"] = payload["max_peak_ram_bytes"] * 2
    path = tmp_path / "edited.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(FlxPolicyError, match="fingerprint does not cover"):
        load_runtime_policy(path)


def test_an_unknown_or_missing_field_is_refused() -> None:
    payload = _payload()
    payload["max_peak_vram_bytes"] = 1
    with pytest.raises(FlxPolicyError, match="unknown=\\['max_peak_vram_bytes'\\]"):
        runtime_policy_from_plain(payload)

    payload = _payload()
    del payload["extract_deadline_seconds"]
    with pytest.raises(FlxPolicyError, match="missing=\\['extract_deadline_seconds'\\]"):
        runtime_policy_from_plain(payload)


def test_a_duplicate_key_is_refused_instead_of_silently_winning(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    text = POLICY_PATH.read_text(encoding="utf-8") + '\nnumeric_tolerance: "1"\n'
    path.write_text(text, encoding="utf-8")

    with pytest.raises(FlxPolicyError, match="duplicate policy key"):
        load_runtime_policy(path)


def test_a_missing_policy_names_the_path_it_looked_for(tmp_path: Path) -> None:
    with pytest.raises(FlxPolicyError, match="not found"):
        load_runtime_policy(tmp_path / "absent.yaml")


def test_there_is_no_vram_limit_because_there_is_no_device() -> None:
    # A limit that can only ever read zero is not a gate; a GPU would be a new
    # runtime profile with its own policy.
    assert "max_peak_vram_bytes" not in _payload()
