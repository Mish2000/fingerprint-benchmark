"""Break a finished paired comparison on purpose and check that it stops verifying.

Every other paired test asks whether the engine computes the right answer. These
ask the opposite question: when something downstream of the computation is wrong
— a stored row edited, a hash rewritten, a marker written for a different
comparison, the report re-rendered from moved sources — does the chain *notice*?

The failure mode this guards against is the quiet one. A tampered artefact that
still loads, still parses, still prints a plausible table, and is cited by
committed evidence is worse than one that crashes, because nothing draws
attention to it. So each test here writes a lie into a real store and requires a
refusal, rather than trusting that verification is called somewhere.

Spec sections 73 (tampering), 74 (failure injection) and 75 (re-render).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.core.enums import PairedEvaluationStatus
from fpbench.core.errors import PairedEvaluationError, StorageError
from fpbench.core.paired_models import (
    paired_receipt_content_hash,
    paired_receipt_fingerprint,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.paired import (
    align_pairs,
    build_common_eligible_view,
    build_control_audit,
    build_eligibility_transitions,
    build_paired_finalization_marker,
    build_paired_observations,
    build_paired_receipt,
    build_paired_records,
    build_paired_summary,
    build_transition_counts,
    inspect_paired_evaluation,
    release_order,
    render_paired_report,
    require_sanitised_paired_receipt,
)
from fpbench.storage.paired_evaluation_store import (
    PairedEvaluationStore,
    paired_summary_content_hash,
    report_content_hash,
)

from pairedworld import build_paired_world

pytestmark = [pytest.mark.paired_evaluation]

_IDS = {
    "run_id": "run_000000000001",
    "result_set_id": "resultset_000000000001",
    "decision_set_id": "decisionset_00000001",
    "eligibility_set_id": "eligibilityset_0001",
    "metric_set_id": "metricset_000000001",
}


class _Derived:
    """One fully stored, finalised comparison, plus everything it was built from.

    Kept as an object rather than a tuple because the tampering tests each reach
    for a different two or three of these, and positional unpacking of nine
    values is how a test starts asserting about the wrong artefact.
    """

    def __init__(self, **parts):
        self.__dict__.update(parts)


def _derive(tmp_path: Path, *, finalize: bool = True) -> _Derived:
    """Build both chains, store them, and (by default) finalise.

    Deliberately duplicates the experiment module's orchestration instead of
    calling it: that module resolves two real runs out of a real workspace and
    demands a clean git tree, neither of which a unit test has.
    """
    world = build_paired_world()
    native, canonical = world.native, world.canonical

    pair_ids = align_pairs(native=native, canonical=canonical)
    records = build_paired_records(
        native=native, canonical=canonical, pair_ids=pair_ids
    )
    transitions = build_eligibility_transitions(native=native, canonical=canonical)
    common = build_common_eligible_view(
        native=native, canonical=canonical, transitions=transitions, records=records
    )
    control = build_control_audit(records)
    releases = release_order(native)
    counts = build_transition_counts(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=releases,
        source_fingerprints={
            "native_decision_set": native.decision_manifest.decision_set_fingerprint,
            "canonical_decision_set": (
                canonical.decision_manifest.decision_set_fingerprint
            ),
            "native_eligibility_set": (
                native.eligibility_manifest.eligibility_set_fingerprint
            ),
            "canonical_eligibility_set": (
                canonical.eligibility_manifest.eligibility_set_fingerprint
            ),
        },
    )
    observations = build_paired_observations(
        records=records,
        transitions=transitions,
        common_eligible=common,
        releases=releases,
        policy_fingerprint="e" * 64,
    )

    definition, manifest = _definition_and_manifest(
        records=records,
        transitions=transitions,
        common=common,
        counts=counts,
        observations=observations,
        control=control,
    )
    paired_id = manifest.paired_evaluation_id

    store = PairedEvaluationStore(tmp_path)
    store.ensure_definition(paired_id, definition)
    store.ensure_policy(paired_id, {"policy_id": "synthetic_v1"})
    store.ensure_records(paired_id, records)
    store.ensure_eligibility_transitions(paired_id, transitions)
    store.ensure_common_eligible_view(paired_id, common)
    store.ensure_counts(paired_id, counts)
    store.ensure_observations(paired_id, observations)
    store.ensure_control_audit(paired_id, control)
    store.ensure_manifest(manifest)

    derived = _Derived(
        world=world,
        store=store,
        paired_id=paired_id,
        definition=definition,
        manifest=manifest,
        records=records,
        transitions=transitions,
        common=common,
        counts=counts,
        observations=observations,
        control=control,
        releases=releases,
    )
    if not finalize:
        return derived

    summary = build_paired_summary(
        manifest=manifest,
        native_ids=_IDS,
        canonical_ids=_IDS,
        control=control,
        counts=counts,
        observations=observations,
        records=records,
        generated_utc="2026-01-01T00:00:00+00:00",
    )
    store.ensure_summary(paired_id, summary)

    markdown = _render(derived)
    store.ensure_report(paired_id, markdown)

    receipt = build_paired_receipt(
        manifest=manifest,
        policy_id="synthetic_v1",
        policy_fingerprint="e" * 64,
        native_ids=_IDS,
        canonical_ids=_IDS,
        canonical_preparation_set_id="preparedset_000000000001",
        pair_manifest_hash=native.pair_manifest_hash,
        control=control,
        counts=counts,
        observations=observations,
        source_commit="f" * 40,
        source_tree_clean=True,
        created_utc="2026-01-01T00:00:00+00:00",
    )
    store.ensure_receipt(paired_id, receipt)

    marker = build_paired_finalization_marker(
        manifest=manifest,
        control=control,
        summary_content_hash=paired_summary_content_hash(summary),
        report_content_hash=report_content_hash(markdown),
        receipt=receipt,
        source_commit="f" * 40,
        source_tree_clean=True,
    )
    store.ensure_finalization(paired_id, marker)

    derived.summary = summary
    derived.markdown = markdown
    derived.receipt = receipt
    derived.marker = marker
    return derived


def _render(derived: _Derived) -> str:
    return render_paired_report(
        manifest=derived.manifest,
        policy_id="synthetic_v1",
        native_ids=_IDS,
        canonical_ids=_IDS,
        native_source_commit="1" * 40,
        canonical_source_commit="2" * 40,
        derivation_commit="f" * 40,
        control=derived.control,
        counts=derived.counts,
        observations=derived.observations,
        records=derived.records,
        common_eligible=derived.common,
        transitions=derived.transitions,
        releases=derived.releases,
    )


def _definition_and_manifest(**parts):
    from fpbench.experiments.sourceafis_native_vs_canonical500 import _build_manifest

    definition = _synthetic_definition()
    return definition, _build_manifest(definition=definition, **parts)


def _synthetic_definition():
    """Built by the real builder, from the synthetic world's own fingerprints.

    Hand-rolling the definition would let it drift from what the experiment
    actually stores, and the tampering tests below are only meaningful against
    the real shape.
    """
    from types import SimpleNamespace

    from fpbench.experiments.sourceafis_native_vs_canonical500 import _build_definition
    from fpbench.provenance.software import SoftwareProvenance

    world = build_paired_world()
    return _build_definition(
        native=world.native,
        canonical=world.canonical,
        policy=SimpleNamespace(policy_fingerprint="e" * 64),
        software=SoftwareProvenance(
            provenance_kind="git",
            source_revision="f" * 40,
            source_tree_clean=True,
            package_version="0.1.0",
            python_version="3.11.0",
            python_implementation="CPython",
            dependency_versions={},
        ),
    )


def _refuses():
    """A tampered row must be refused — by the hash *or* by the model.

    Which of the two catches it depends on what was edited: an unreadable enum
    or a cell total that no longer sums is rejected while the row is being
    reconstructed, before the hash is ever compared. Both are refusals, and a
    test that insisted on one exception type would be asserting about the order
    the checks happen to run in rather than about the guarantee.
    """
    return pytest.raises((StorageError, ValueError))


def _first(derived: _Derived, column: str):
    import pyarrow.parquet as pq

    path = derived.store.comparisons_path(derived.paired_id)
    return pq.read_table(path).column(column).to_pylist()[0]


def _retype_column(path: Path, name: str, mutate) -> None:
    """Rewrite one parquet column in place, leaving every row hash stale."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    index = table.schema.get_field_index(name)
    if index < 0:  # pragma: no cover - schema changed under the test
        raise AssertionError(f"no {name!r} column in {table.column_names}")
    field = table.schema.field(index)
    values = mutate(table.column(name).to_pylist())
    table = table.set_column(index, field, pa.array(values, type=field.type))
    pq.write_table(table, path)


def _rewrite(path: Path, mutate) -> None:
    payload = read_json(path)
    mutate(payload)
    write_json(path, payload)


# ------------------------------------------------------------------ tampering


def test_the_untouched_comparison_verifies(tmp_path):
    """The control for every test below: unbroken, it passes.

    Without this, a tampering test that passed because the fixture was broken in
    some other way would look like a success.
    """
    derived = _derive(tmp_path)
    derived.store.verify_paired_evaluation(derived.paired_id)
    state = inspect_paired_evaluation(
        store=derived.store, paired_evaluation_id=derived.paired_id
    )
    assert state.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY
    assert state.issues == ()


def test_manifest_fingerprint_is_recomputed_from_all_manifest_fields(tmp_path):
    derived = _derive(tmp_path, finalize=False)
    with pytest.raises(ValueError, match="does not cover the manifest fields"):
        replace(
            derived.manifest,
            total_paired_comparisons=(
                derived.manifest.total_paired_comparisons + 1
            ),
        )


def test_derivation_software_fingerprint_covers_the_software_object(tmp_path):
    derived = _derive(tmp_path, finalize=False)
    forged_software = replace(
        derived.definition.derivation_software, package_version="forged"
    )
    with pytest.raises(ValueError, match="does not cover derivation_software"):
        replace(derived.definition, derivation_software=forged_software)


def _verify_against_synthetic_sources(derived, monkeypatch):
    import fpbench.experiments.sourceafis_native_vs_canonical500 as experiment

    policy = type(
        "Policy",
        (),
        {
            "policy_id": "synthetic_v1",
            "policy_fingerprint": "e" * 64,
            "document": {"policy": {"policy_id": "synthetic_v1"}},
        },
    )()
    config = experiment.PairedComparisonConfig(
        experiment_id="synthetic_paired_v1",
        native=dict(_IDS),
        canonical=dict(_IDS),
        policy_config=tmp_path_placeholder(),
        evidence_directory=Path("evidence") / "synthetic",
    )
    prepared = experiment.PreparedPairedComparison(
        config=config,
        policy=policy,
        software=derived.definition.derivation_software,
        workspace=derived.store.root,
        native=derived.world.native,
        canonical=derived.world.canonical,
        definition=derived.definition,
    )
    monkeypatch.setattr(experiment, "prepare_paired_evaluation", lambda **_: prepared)
    monkeypatch.setattr(experiment, "load_paired_policy", lambda _path: policy)
    monkeypatch.setattr(
        experiment,
        "_canonical_preparation_set_id",
        lambda _root: "preparedset_000000000001",
    )
    monkeypatch.setattr(
        experiment,
        "_run_commit",
        lambda side: "1" * 40 if side.label == "native" else "2" * 40,
    )
    state = inspect_paired_evaluation(
        store=derived.store, paired_evaluation_id=derived.paired_id
    )
    return experiment.verify_paired_evaluation_against_sources(
        workspace=derived.store.root,
        config=config,
        repository_root=Path.cwd(),
        paired_evaluation_id=derived.paired_id,
        storage_state=state,
    )


def tmp_path_placeholder() -> Path:
    """A config path the monkeypatched synthetic verifier never opens."""
    return Path("synthetic-policy.yaml")


def test_the_full_verifier_rebuilds_an_untouched_comparison(tmp_path, monkeypatch):
    derived = _derive(tmp_path)
    state = _verify_against_synthetic_sources(derived, monkeypatch)
    assert state.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY


def test_consistently_forged_publication_files_fail_source_verification(
    tmp_path, monkeypatch
):
    """A fresh marker cannot make coordinated publication edits authoritative."""
    derived = _derive(tmp_path)
    paired_id = derived.paired_id
    store = derived.store

    summary = dict(store.read_summary(paired_id))
    summary["forged_claim"] = "canonical is superior"
    write_json(store.summary_path(paired_id), summary)

    report = store.read_report(paired_id) + "\n\nCanonical is superior.\n"
    store.report_path(paired_id).write_text(report, encoding="utf-8")

    receipt_payload = read_json(store.receipt_path(paired_id))
    receipt_payload["total_paired_comparisons"] = 1
    write_json(store.receipt_path(paired_id), receipt_payload)
    forged_receipt = store.read_receipt(paired_id)

    marker = build_paired_finalization_marker(
        manifest=derived.manifest,
        control=derived.control,
        summary_content_hash=paired_summary_content_hash(summary),
        report_content_hash=report_content_hash(report),
        receipt=forged_receipt,
        source_commit="f" * 40,
        source_tree_clean=True,
        created_utc=derived.marker.created_utc,
    )
    write_json(store.finalization_path(paired_id), marker)

    storage_only = inspect_paired_evaluation(
        store=store, paired_evaluation_id=paired_id
    )
    assert storage_only.status is PairedEvaluationStatus.PAIRED_EVALUATION_READY
    with pytest.raises(PairedEvaluationError, match="summary.json"):
        _verify_against_synthetic_sources(derived, monkeypatch)


def test_an_edited_paired_record_is_caught(tmp_path):
    """Flip one outcome — the single most useful lie to tell about this stage."""
    from fpbench.core.enums import DecisionOutcome

    derived = _derive(tmp_path)
    flipped = (
        DecisionOutcome.NON_MATCH.value
        if _first(derived, "canonical_outcome") == DecisionOutcome.MATCH.value
        else DecisionOutcome.MATCH.value
    )
    _retype_column(
        derived.store.comparisons_path(derived.paired_id),
        "canonical_outcome",
        lambda values: [flipped, *values[1:]],
    )
    with _refuses():
        derived.store.verify_paired_evaluation(derived.paired_id)


def test_an_edited_score_delta_is_caught(tmp_path):
    """The per-pair delta is the number a reader would most want moved."""
    derived = _derive(tmp_path)
    _retype_column(
        derived.store.comparisons_path(derived.paired_id),
        "score_delta_decimal",
        lambda values: ["999.0", *values[1:]],
    )
    with _refuses():
        derived.store.verify_paired_evaluation(derived.paired_id)


def test_a_swapped_job_id_is_caught_by_the_row_hash_alone(tmp_path):
    """The case no invariant can see.

    A different job id is still a well-formed job id: nothing about the row is
    self-contradictory afterwards. Only the stored ``record_hash`` knows the row
    changed, which is the whole reason each row carries one — so this test names
    the hash in the refusal, where the others accept whichever check fires first.
    """
    derived = _derive(tmp_path)
    _retype_column(
        derived.store.comparisons_path(derived.paired_id),
        "native_job_id",
        lambda values: [values[1], *values[1:]],
    )
    with pytest.raises(ValueError, match="record_hash does not cover"):
        derived.store.verify_paired_evaluation(derived.paired_id)


def test_an_edited_transition_count_is_caught(tmp_path):
    """Inflating a cell total is how an aggregate would be made to say more."""
    derived = _derive(tmp_path)
    _retype_column(
        derived.store.counts_path(derived.paired_id),
        "total",
        lambda values: [int(values[0]) + 1, *values[1:]],
    )
    with _refuses():
        derived.store.verify_paired_evaluation(derived.paired_id)


def test_a_rewritten_manifest_hash_is_caught(tmp_path):
    """Editing the manifest to agree with tampered rows does not rescue it.

    The manifest's own fingerprint covers the hashes it publishes, so a forger
    has to break one of the two.
    """
    derived = _derive(tmp_path)
    _rewrite(
        derived.store.manifest_path(derived.paired_id),
        lambda payload: payload.update({"ordered_paired_records_hash": "0" * 64}),
    )
    with pytest.raises(StorageError):
        derived.store.verify_paired_evaluation(derived.paired_id)


def test_a_changed_control_verdict_is_caught(tmp_path):
    """The one artefact a forger has the strongest motive to edit."""
    derived = _derive(tmp_path)
    _rewrite(
        derived.store.control_audit_path(derived.paired_id),
        lambda payload: payload.update({"equal_scores": 999999}),
    )
    with pytest.raises(StorageError):
        derived.store.verify_paired_evaluation(derived.paired_id)


def test_an_edited_report_is_caught(tmp_path):
    derived = _derive(tmp_path)
    path = derived.store.report_path(derived.paired_id)
    path.write_text(derived.markdown + "\n\nand canonical is better.\n", "utf-8")

    state = inspect_paired_evaluation(
        store=derived.store, paired_evaluation_id=derived.paired_id
    )
    assert state.status is not PairedEvaluationStatus.PAIRED_EVALUATION_READY
    assert any("report" in issue for issue in state.issues), state.issues


def test_an_edited_receipt_is_caught(tmp_path):
    derived = _derive(tmp_path)
    _rewrite(
        derived.store.receipt_path(derived.paired_id),
        lambda payload: payload.update({"total_paired_comparisons": 1}),
    )
    state = inspect_paired_evaluation(
        store=derived.store, paired_evaluation_id=derived.paired_id
    )
    assert state.status is not PairedEvaluationStatus.PAIRED_EVALUATION_READY


def test_a_marker_for_a_different_comparison_is_caught(tmp_path):
    """A valid marker is not a marker for *this*."""
    derived = _derive(tmp_path)
    _rewrite(
        derived.store.finalization_path(derived.paired_id),
        lambda payload: payload.update(
            {"paired_evaluation_fingerprint": "0" * 64}
        ),
    )
    state = inspect_paired_evaluation(
        store=derived.store, paired_evaluation_id=derived.paired_id
    )
    assert state.status is not PairedEvaluationStatus.PAIRED_EVALUATION_READY


# ----------------------------------------------------------- failure injection


def test_a_comparison_without_a_marker_is_not_ready(tmp_path):
    derived = _derive(tmp_path, finalize=False)
    state = inspect_paired_evaluation(
        store=derived.store, paired_evaluation_id=derived.paired_id
    )
    assert state.status is not PairedEvaluationStatus.PAIRED_EVALUATION_READY
    assert state.manifest_valid is True
    assert state.finalization_valid is False


def test_a_dirty_tree_may_not_be_finalised(tmp_path):
    """docs/adr/0017, at the last possible moment."""
    derived = _derive(tmp_path, finalize=False)
    with pytest.raises(PairedEvaluationError, match="clean source"):
        build_paired_finalization_marker(
            manifest=derived.manifest,
            control=derived.control,
            summary_content_hash="0" * 64,
            report_content_hash="1" * 64,
            receipt=_derive(tmp_path / "other").receipt,
            source_commit="f" * 40,
            source_tree_clean=False,
        )


def test_a_failed_control_may_not_be_finalised(tmp_path):
    """No amount of downstream verification rescues a broken control.

    The broken audit is derived from a world where SD300A genuinely moved,
    rather than assembled by hand: the audit model refuses a fingerprint that
    does not cover its own counts, so a hand-built lie cannot even be
    constructed — which is itself the property the model was given.
    """
    from fpbench.core.enums import ProtocolStage

    derived = _derive(tmp_path)
    moved = build_paired_world(
        scores={("sd300a_s0001_f01_mated", ProtocolStage.PLAIN_ROLL_MATED): (60.0, 61.0)}
    )
    broken = build_control_audit(
        build_paired_records(
            native=moved.native,
            canonical=moved.canonical,
            pair_ids=align_pairs(native=moved.native, canonical=moved.canonical),
        )
    )
    assert not broken.is_clean
    with pytest.raises(PairedEvaluationError, match="control did not reproduce"):
        build_paired_finalization_marker(
            manifest=derived.manifest,
            control=broken,
            summary_content_hash="0" * 64,
            report_content_hash="1" * 64,
            receipt=derived.receipt,
            source_commit="f" * 40,
            source_tree_clean=True,
        )


def test_a_missing_artefact_fails_verification(tmp_path):
    derived = _derive(tmp_path)
    derived.store.observations_path(derived.paired_id).unlink()
    with pytest.raises(StorageError):
        derived.store.verify_paired_evaluation(derived.paired_id)


# --------------------------------------------------------------- the re-render


def test_the_report_re_renders_byte_for_byte(tmp_path):
    """Spec section 75: the stored report must be reproducible, not merely stored.

    A report that could not be regenerated would make the committed evidence the
    only copy of a claim, which is the thing this project exists not to do.
    """
    derived = _derive(tmp_path)
    again = _render(derived)
    assert again == derived.markdown
    assert report_content_hash(again) == derived.marker.report_content_hash


def test_the_receipt_re_derives_to_the_same_fingerprint(tmp_path):
    derived = _derive(tmp_path)
    again = build_paired_receipt(
        manifest=derived.manifest,
        policy_id="synthetic_v1",
        policy_fingerprint="e" * 64,
        native_ids=_IDS,
        canonical_ids=_IDS,
        canonical_preparation_set_id="preparedset_000000000001",
        pair_manifest_hash=derived.world.native.pair_manifest_hash,
        control=derived.control,
        counts=derived.counts,
        observations=derived.observations,
        source_commit="f" * 40,
        source_tree_clean=True,
        created_utc="2026-01-01T00:00:00+00:00",
    )
    assert paired_receipt_fingerprint(again) == paired_receipt_fingerprint(
        derived.receipt
    )
    assert paired_receipt_content_hash(again) == derived.marker.receipt_content_hash


def test_the_real_receipt_of_this_comparison_is_sanitised(tmp_path):
    """The sanitiser runs against a receipt built from a full world, not a stub."""
    derived = _derive(tmp_path)
    require_sanitised_paired_receipt(derived.receipt)
    rendered = json.dumps(
        json.loads(derived.store.receipt_path(derived.paired_id).read_text("utf-8"))
    )
    assert "job_" not in rendered
    assert "_plainself" not in rendered


# ------------------------------------------------------------------- the pointer


def test_a_re_prepare_keeps_the_derived_id_it_is_about_to_overwrite():
    """Regression: ``finalize`` used to erase its own result.

    Both ``derive`` and ``finalize`` re-prepare first, and prepare rewrites the
    pointer. Before this, a finalisation that succeeded end to end left ``status``
    reporting ``not_prepared`` — the comparison was on disk, finalised and
    verified, and nothing could find it.
    """
    from fpbench.experiments.sourceafis_native_vs_canonical500 import (
        carry_forward_pointer,
    )

    existing = {
        "experiment_id": "x",
        "definition_id": "paireddef_0000",
        "paired_evaluation_id": "pairedeval_0000",
        "finalized_utc": "2026-01-01T00:00:00+00:00",
    }
    fresh = {
        "experiment_id": "x",
        "definition_id": "paireddef_0000",
        "prepared_utc": "2026-01-02T00:00:00+00:00",
    }
    merged = carry_forward_pointer(existing, fresh)
    assert merged["paired_evaluation_id"] == "pairedeval_0000"
    assert merged["finalized_utc"] == "2026-01-01T00:00:00+00:00"
    assert merged["prepared_utc"] == "2026-01-02T00:00:00+00:00"


def test_a_moved_definition_drops_the_derived_id():
    """The other half of the rule, and the reason it is not a plain merge.

    A different definition means the sources beneath the comparison changed. The
    old derived id still exists on disk, but it answers a question this pointer
    is no longer asking, so carrying it would make ``status`` describe the wrong
    comparison — a subtler failure than describing none.
    """
    from fpbench.experiments.sourceafis_native_vs_canonical500 import (
        carry_forward_pointer,
    )

    merged = carry_forward_pointer(
        {"definition_id": "paireddef_0000", "paired_evaluation_id": "pairedeval_0000"},
        {"definition_id": "paireddef_1111"},
    )
    assert "paired_evaluation_id" not in merged


def test_the_first_prepare_has_nothing_to_carry():
    from fpbench.experiments.sourceafis_native_vs_canonical500 import (
        carry_forward_pointer,
    )

    fresh = {"definition_id": "paireddef_0000", "prepared_utc": "now"}
    assert carry_forward_pointer({}, fresh) == fresh
