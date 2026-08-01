"""Decision-profile scope, paired storage, and what tampering does to both.

Three groups.

*Scope.* Each decision profile covers exactly one execution profile and refuses
the other's. That refusal is why stage 6B needs a second profile at all — and
the transfer block that records where its threshold came from is inside the
profile fingerprint, so a transfer that started claiming a calibration would be
a different profile.

*Storage.* The paired comparison follows the same contract as every other store:
round-trips exactly, no-ops on identical content, conflicts on different content,
and refuses a retyped column.

*Tampering.* Change one thing in a finished comparison and it stops verifying.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from fpbench.core.enums import ComparabilityStatus, DecisionOutcome, ProtocolStage
from fpbench.core.errors import (
    DecisionProfileApplicabilityError,
    DecisionProfileError,
    PairedEvaluationConflictError,
    StorageError,
)
from fpbench.core.serialization import write_json
from fpbench.decisions import load_decision_profile, require_profile_applies_to_run
from fpbench.storage.paired_evaluation_store import PairedEvaluationStore
from fpbench.storage.paired_schemas import (
    PAIRED_COMPARISON_SCHEMA,
    paired_comparisons_to_table,
    table_to_paired_comparisons,
)

pytestmark = [pytest.mark.paired_evaluation, pytest.mark.decisions]

REPO = Path(__file__).resolve().parents[2]
NATIVE_PROFILE = (
    REPO / "configs" / "decisions" / "sourceafis_java_3_18_1_documented_40_v1.yaml"
)
CANONICAL_PROFILE = (
    REPO
    / "configs"
    / "decisions"
    / "sourceafis_java_3_18_1_documented_40_canonical500_v1.yaml"
)

_FINGERPRINT = "b" * 64


def _run(execution_profile_id: str):
    from types import SimpleNamespace

    from fpbench.core.enums import ScoreDirection

    return SimpleNamespace(
        run_id="run_000000000001",
        algorithm_fingerprint=_FINGERPRINT,
        algorithm=SimpleNamespace(
            algorithm_id="sourceafis_java",
            implementation_version="3.18.1",
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
        ),
        execution_profile=SimpleNamespace(profile_id=execution_profile_id),
    )


# --------------------------------------------------------------- profile scope


def test_the_canonical_profile_carries_the_documented_forty():
    profile = load_decision_profile(
        CANONICAL_PROFILE, algorithm_fingerprint=_FINGERPRINT
    )
    assert profile.threshold == "40"
    assert profile.comparator.value == "greater_than_or_equal"
    assert profile.origin.value == "documented_native"
    assert profile.calibration_performed is False


def test_the_two_profiles_agree_on_the_rule_and_differ_on_scope():
    native = load_decision_profile(NATIVE_PROFILE, algorithm_fingerprint=_FINGERPRINT)
    canonical = load_decision_profile(
        CANONICAL_PROFILE, algorithm_fingerprint=_FINGERPRINT
    )
    assert native.threshold == canonical.threshold
    assert native.comparator is canonical.comparator
    assert native.origin is canonical.origin
    assert native.profile_id != canonical.profile_id
    assert native.profile_fingerprint != canonical.profile_fingerprint
    assert native.allowed_execution_profiles == ("native_identity_60s_v1",)
    assert canonical.allowed_execution_profiles == ("canonical_500_lanczos3_60s_v1",)


def test_the_native_profile_refuses_the_canonical_execution_profile():
    profile = load_decision_profile(NATIVE_PROFILE, algorithm_fingerprint=_FINGERPRINT)
    with pytest.raises(DecisionProfileApplicabilityError, match="covers execution"):
        require_profile_applies_to_run(
            profile=profile, run=_run("canonical_500_lanczos3_60s_v1")
        )


def test_the_canonical_profile_refuses_the_native_execution_profile():
    profile = load_decision_profile(
        CANONICAL_PROFILE, algorithm_fingerprint=_FINGERPRINT
    )
    with pytest.raises(DecisionProfileApplicabilityError, match="covers execution"):
        require_profile_applies_to_run(
            profile=profile, run=_run("native_identity_60s_v1")
        )


def test_each_profile_accepts_its_own_execution_profile():
    for path, execution in (
        (NATIVE_PROFILE, "native_identity_60s_v1"),
        (CANONICAL_PROFILE, "canonical_500_lanczos3_60s_v1"),
    ):
        profile = load_decision_profile(path, algorithm_fingerprint=_FINGERPRINT)
        require_profile_applies_to_run(profile=profile, run=_run(execution))


# ------------------------------------------------------------ transfer block


@pytest.fixture()
def canonical_document():
    return yaml.safe_load(CANONICAL_PROFILE.read_text("utf-8"))


def _parse(document, tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return load_decision_profile(path, algorithm_fingerprint=_FINGERPRINT)


def test_the_transfer_block_is_load_bearing(canonical_document, tmp_path):
    baseline = _parse(canonical_document, tmp_path)
    for field, value in (
        ("source_profile_id", "some_other_profile_v1"),
        ("interpretation", "something_else_entirely"),
    ):
        changed = copy.deepcopy(canonical_document)
        changed["transfer"][field] = value
        assert (
            _parse(changed, tmp_path / field).profile_fingerprint
            != baseline.profile_fingerprint
        ), field


def test_a_transfer_missing_a_field_is_refused(canonical_document, tmp_path):
    for field in (
        "source_profile_id",
        "threshold_unchanged",
        "calibration_performed",
        "test_cohort_used",
        "interpretation",
    ):
        broken = copy.deepcopy(canonical_document)
        broken["transfer"].pop(field)
        with pytest.raises(DecisionProfileError, match=field):
            _parse(broken, tmp_path / f"missing-{field}")


def test_a_changed_threshold_is_not_a_transfer(canonical_document, tmp_path):
    broken = copy.deepcopy(canonical_document)
    broken["transfer"]["threshold_unchanged"] = False
    with pytest.raises(DecisionProfileError, match="not a transfer"):
        _parse(broken, tmp_path / "changed")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("threshold_unchanged", "false"),
        ("calibration_performed", "false"),
        ("test_cohort_used", 0),
    ),
)
def test_transfer_flags_require_yaml_booleans(
    canonical_document, tmp_path, field, value
):
    broken = copy.deepcopy(canonical_document)
    broken["transfer"][field] = value
    with pytest.raises(DecisionProfileError, match="YAML boolean"):
        _parse(broken, tmp_path / f"typed-{field}")


def test_a_transfer_claiming_calibration_is_refused(canonical_document, tmp_path):
    for field in ("calibration_performed", "test_cohort_used"):
        broken = copy.deepcopy(canonical_document)
        broken["transfer"][field] = True
        with pytest.raises(DecisionProfileError, match="may not be true"):
            _parse(broken, tmp_path / f"claims-{field}")


def test_test_cohort_calibration_is_refused_outright(canonical_document, tmp_path):
    broken = copy.deepcopy(canonical_document)
    broken["calibration"]["test_cohort_used"] = True
    with pytest.raises(DecisionProfileError, match="TEST cohort"):
        _parse(broken, tmp_path / "leak")


def test_the_native_profile_fingerprint_did_not_move():
    """Adding transfer support must not have changed a profile that has none.

    The native decision set is cited by committed evidence. A loader change that
    quietly moved its profile fingerprint would invalidate a verified chain.
    """
    profile = load_decision_profile(NATIVE_PROFILE, algorithm_fingerprint=_FINGERPRINT)
    assert not any(key.startswith("transfer.") for key in profile.metadata)


# -------------------------------------------------------------------- storage


def _records(world):
    from fpbench.paired import align_pairs, build_paired_records

    pair_ids = align_pairs(native=world.native, canonical=world.canonical)
    return build_paired_records(
        native=world.native, canonical=world.canonical, pair_ids=pair_ids
    )


def test_paired_records_round_trip_exactly(tmp_path):
    from pairedworld import build_paired_world

    records = _records(build_paired_world())
    table = paired_comparisons_to_table(records)
    assert table.schema == PAIRED_COMPARISON_SCHEMA

    rebuilt = table_to_paired_comparisons(table)
    assert [item.record_hash for item in rebuilt] == [
        item.record_hash for item in records
    ]
    for original, restored in zip(records, rebuilt):
        assert type(restored.ordinal) is int
        assert restored.score_delta_decimal == original.score_delta_decimal
        assert restored.native_outcome is original.native_outcome


def test_a_retyped_column_is_refused(tmp_path):
    import pyarrow as pa

    from pairedworld import build_paired_world

    table = paired_comparisons_to_table(_records(build_paired_world()))
    retyped = table.set_column(
        table.schema.get_field_index("ordinal"),
        pa.field("ordinal", pa.int32(), nullable=False),
        table.column("ordinal").cast(pa.int32()),
    )
    with pytest.raises(ValueError, match="declared schema"):
        table_to_paired_comparisons(retyped)


def test_a_null_delta_survives_the_round_trip(tmp_path):
    from pairedworld import build_paired_world

    world = build_paired_world(
        scores={
            ("sd300b_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (60.0, None)
        }
    )
    rebuilt = table_to_paired_comparisons(paired_comparisons_to_table(_records(world)))
    record = next(r for r in rebuilt if str(r.pair_id) == "sd300b_s0001_f01_mated")
    assert record.score_delta_decimal is None
    assert record.canonical_outcome is DecisionOutcome.UNDECIDABLE


def test_the_same_policy_twice_is_a_no_op_and_a_different_one_conflicts(tmp_path):
    store = PairedEvaluationStore(tmp_path)
    paired_id = "pairedeval_000000000001"
    store.ensure_policy(paired_id, {"policy": {"policy_id": "p"}})
    store.ensure_policy(paired_id, {"policy": {"policy_id": "p"}})
    with pytest.raises(PairedEvaluationConflictError):
        store.ensure_policy(paired_id, {"policy": {"policy_id": "q"}})


def test_reading_a_manifest_from_a_foreign_directory_is_refused(tmp_path):
    store = PairedEvaluationStore(tmp_path)
    other = store.paired_dir("pairedeval_000000000002")
    other.mkdir(parents=True, exist_ok=True)
    write_json(
        other / "manifest.json",
        {
            "paired_evaluation_id": "pairedeval_000000000003",
            "paired_evaluation_fingerprint": "c" * 64,
            "definition_fingerprint": "d" * 64,
            "total_paired_comparisons": 1,
            "total_eligibility_units": 1,
            "total_common_eligible_rows": 1,
            "ordered_paired_records_hash": "e" * 64,
            "ordered_eligibility_transitions_hash": "f" * 64,
            "common_eligible_view_hash": "0" * 64,
            "ordered_count_records_hash": "1" * 64,
            "ordered_observations_hash": "2" * 64,
            "control_audit_fingerprint": "3" * 64,
            "created_utc": "2026-01-01T00:00:00+00:00",
        },
    )
    with pytest.raises(StorageError):
        store.read_manifest("pairedeval_000000000002")


def test_an_observation_with_a_forged_difference_is_rejected():
    from fpbench.core.paired_models import (
        MetricScopeRef,
        PairedRateObservation,
        paired_rate_observation_hash,
    )

    fields = dict(
        ordinal=0,
        observation_id="plain_self_attempt_match_fraction",
        scope=MetricScopeRef(scope_kind="pooled"),
        native_numerator=10,
        native_denominator=20,
        canonical_numerator=11,
        canonical_denominator=20,
        difference_numerator=99,
        difference_denominator=100,
        comparability=ComparabilityStatus.DIRECTLY_COMPARABLE,
        policy_fingerprint="a" * 64,
    )

    class _Draft:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    with pytest.raises(ValueError, match="exact reduced difference"):
        PairedRateObservation(
            observation_hash=paired_rate_observation_hash(_Draft(**fields)), **fields
        )


def test_a_difference_on_an_incomparable_observation_is_rejected():
    from fpbench.core.paired_models import (
        MetricScopeRef,
        PairedRateObservation,
        paired_rate_observation_hash,
    )

    fields = dict(
        ordinal=0,
        observation_id="per_run_conditional_mated_decision_fnmr",
        scope=MetricScopeRef(scope_kind="pooled"),
        native_numerator=1,
        native_denominator=10,
        canonical_numerator=2,
        canonical_denominator=20,
        difference_numerator=0,
        difference_denominator=1,
        comparability=ComparabilityStatus.DIFFERENT_SELECTION,
        policy_fingerprint="a" * 64,
    )

    class _Draft:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    with pytest.raises(ValueError, match="do not subtract"):
        PairedRateObservation(
            observation_hash=paired_rate_observation_hash(_Draft(**fields)), **fields
        )


def test_the_paired_policy_refuses_every_forbidden_claim(tmp_path):
    from fpbench.core.errors import ConfigurationError
    from fpbench.paired import load_paired_policy

    source = REPO / "configs" / "comparisons" / "policies"
    document = yaml.safe_load(
        (source / "sourceafis_native_vs_canonical500_paired_v1.yaml").read_text("utf-8")
    )
    for section, name in (
        ("statistics", "confidence_intervals"),
        ("statistics", "significance_tests"),
        ("statistics", "bootstrap"),
        ("statistics", "mcnemar"),
        ("claims", "resolution_superiority"),
        ("claims", "capture_quality_causality"),
        ("claims", "general_fmr"),
        ("scores", "report_distribution"),
    ):
        broken = copy.deepcopy(document)
        broken[section][name] = True
        path = tmp_path / f"{section}-{name}.yaml"
        path.write_text(yaml.safe_dump(broken), encoding="utf-8")
        with pytest.raises(ConfigurationError, match=name):
            load_paired_policy(path)


def test_the_paired_policy_refuses_a_relaxed_pairing_rule(tmp_path):
    from fpbench.core.errors import ConfigurationError
    from fpbench.paired import load_paired_policy

    source = (
        REPO
        / "configs"
        / "comparisons"
        / "policies"
        / "sourceafis_native_vs_canonical500_paired_v1.yaml"
    )
    document = yaml.safe_load(source.read_text("utf-8"))
    for name in (
        "require_same_pair_manifest",
        "require_same_algorithm",
        "require_same_runtime_bundle",
        "require_same_threshold_rule",
    ):
        broken = copy.deepcopy(document)
        broken["pairing"][name] = False
        path = tmp_path / f"pairing-{name}.yaml"
        path.write_text(yaml.safe_dump(broken), encoding="utf-8")
        with pytest.raises(ConfigurationError, match=name):
            load_paired_policy(path)


@pytest.mark.parametrize(
    ("section", "name", "value"),
    (
        ("pairing", "require_same_algorithm", "false"),
        ("statistics", "bootstrap", "false"),
        ("claims", "general_fmr", 0),
        ("scores", "retain_pair_delta", "true"),
        ("transitions", "plain_self", 1),
    ),
)
def test_paired_policy_flags_require_yaml_booleans(
    tmp_path, section, name, value
):
    from fpbench.core.errors import ConfigurationError
    from fpbench.paired import load_paired_policy

    source = (
        REPO
        / "configs"
        / "comparisons"
        / "policies"
        / "sourceafis_native_vs_canonical500_paired_v1.yaml"
    )
    broken = yaml.safe_load(source.read_text("utf-8"))
    broken[section][name] = value
    path = tmp_path / f"typed-{section}-{name}.yaml"
    path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="YAML boolean"):
        load_paired_policy(path)


def test_the_paired_policy_refuses_a_non_pair_id_join(tmp_path):
    from fpbench.core.errors import ConfigurationError
    from fpbench.paired import load_paired_policy

    source = (
        REPO
        / "configs"
        / "comparisons"
        / "policies"
        / "sourceafis_native_vs_canonical500_paired_v1.yaml"
    )
    document = yaml.safe_load(source.read_text("utf-8"))
    document["pairing"]["key"] = "job_id"
    path = tmp_path / "join.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="pair_id"):
        load_paired_policy(path)


def test_the_receipt_sanitiser_refuses_per_pair_detail():
    from fpbench.core.errors import PairedEvaluationError
    from fpbench.paired import require_sanitised_paired_receipt

    class _Receipt:
        pass

    receipt = _Receipt()
    payload = {"transition_counts": {"plain_self.pooled": {"match_to_match": 1}}}

    import fpbench.paired.receipt as module

    original = module.to_plain
    module.to_plain = lambda _value: {
        **payload,
        "rate_observations": {"x": {"pair_id": "sd300a_00001012_plain_f01"}},
    }
    try:
        with pytest.raises(PairedEvaluationError, match="per-pair detail"):
            require_sanitised_paired_receipt(receipt)
    finally:
        module.to_plain = original


def test_json_round_trip_of_a_manifest(tmp_path):
    """A stored manifest re-reads to the same identity."""
    from fpbench.core.paired_models import (
        PairedEvaluationManifest,
        paired_evaluation_fingerprint,
        paired_evaluation_id,
    )

    fingerprint = paired_evaluation_fingerprint(
        definition_fingerprint="a" * 64,
        ordered_records_hash="b" * 64,
        ordered_eligibility_hash="c" * 64,
        common_eligible_hash="d" * 64,
        ordered_counts_hash="e" * 64,
        ordered_observations_hash="f" * 64,
        control_fingerprint="0" * 64,
        total_paired_comparisons=6000,
        total_eligibility_units=1500,
        total_common_eligible_rows=1400,
    )
    manifest = PairedEvaluationManifest(
        paired_evaluation_id=paired_evaluation_id(fingerprint),
        paired_evaluation_fingerprint=fingerprint,
        definition_fingerprint="a" * 64,
        total_paired_comparisons=6000,
        total_eligibility_units=1500,
        total_common_eligible_rows=1400,
        ordered_paired_records_hash="b" * 64,
        ordered_eligibility_transitions_hash="c" * 64,
        common_eligible_view_hash="d" * 64,
        ordered_count_records_hash="e" * 64,
        ordered_observations_hash="f" * 64,
        control_audit_fingerprint="0" * 64,
        created_utc="2026-01-01T00:00:00+00:00",
    )
    store = PairedEvaluationStore(tmp_path)
    store.ensure_manifest(manifest)
    assert (
        store.read_manifest(manifest.paired_evaluation_id).paired_evaluation_fingerprint
        == fingerprint
    )

    # A hand-edited count does not change the stored id, so the manifest still
    # loads — but it no longer describes the rows it names, which is what
    # verification catches (see the tampering tests).
    payload = json.loads(
        store.manifest_path(manifest.paired_evaluation_id).read_text("utf-8")
    )
    payload["paired_evaluation_id"] = "pairedeval_000000000009"
    write_json(store.manifest_path(manifest.paired_evaluation_id), payload)
    with pytest.raises(StorageError, match="must be derived from the fingerprint"):
        store.read_manifest(manifest.paired_evaluation_id)


def test_the_sanitiser_does_not_fire_on_the_projects_own_field_names():
    """``planned_sd300a_pairs`` is a count, not an inventory row.

    The control audit legitimately names the release it audits. An id matcher
    that fired on that would make every honest receipt unpublishable, which is
    the failure mode a too-eager check actually has.
    """
    from fpbench.paired import require_sanitised_paired_receipt
    import fpbench.paired.receipt as module

    class _Receipt:
        pass

    original = module.to_plain
    module.to_plain = lambda _value: {
        "control_audit": {
            "planned_sd300a_pairs": 2000,
            "equal_scores": 2000,
        },
        "transition_counts": {"plain_self.sd300a": {"match_to_match": 500}},
    }
    try:
        require_sanitised_paired_receipt(_Receipt())
    finally:
        module.to_plain = original
