"""Every multi-file store, against the same adversarial matrix.

The rule these enforce is one sentence, and it is stronger than the one the
stores used to satisfy:

    A public publish returns successfully only if, at a linearization point
    before it returns, the set on disk is the set the caller asked to publish.

"I did not create corruption" was the weaker one, and the difference between
them is where three separate defects lived — each found by review rather than by
a test, each fixed as the instance that was demonstrated, each followed by
another instance of the same class one layer down. So this is written against the
class: eight stores, one table of situations, no store exempt.

**The oracle is independent of the code under test.** ``assert_disk_equals_expected``
re-reads every body and compares it to a snapshot taken when the set was first
published — it never calls ``store.verify_*``. That matters: a stored set that
disagreed with its own inputs *passed* the store's verifier, because the verifier
checks a set against its manifest and both had been written by the same wrong
publication. An oracle sharing a blind spot with the code confirms the blind
spot.

**Canonical, not byte-for-byte.** A Parquet body carries a wall clock in its
metadata and some JSON bodies carry ``created_utc``; the fingerprints that give
a set its identity deliberately exclude both. Equality here means
:func:`~fpbench.storage.set_publication.canonical_table` and
:func:`~fpbench.storage.set_publication.canonical_document`, which is what the
stores compare on — and is why a legitimate retry is not a conflict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fpbench.core.errors import FpbenchError
from fpbench.storage.set_publication import canonical_document, canonical_table

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]

_CONFLICT = (FpbenchError, ValueError)


# ------------------------------------------------------------------ the oracle


def _snapshot(path: Path):
    """What is at ``path``, canonically, read without asking the store."""
    if not path.is_file():
        return None
    if path.suffix == ".parquet":
        with pq.ParquetFile(path) as reader:
            return canonical_table(reader.read())
    return canonical_document(json.loads(path.read_text(encoding="utf-8")))


def _agrees(left, right) -> bool:
    if isinstance(left, pa.Table) or isinstance(right, pa.Table):
        return (
            isinstance(left, pa.Table)
            and isinstance(right, pa.Table)
            and left.equals(right)
        )
    return left == right


def file_state(paths: Sequence[Path]) -> dict[Path, str | None]:
    """Exact bytes, so "nothing was rewritten" is not a canonical judgement."""
    import hashlib

    return {
        path: (
            None
            if not Path(path).is_file()
            else hashlib.sha256(Path(path).read_bytes()).hexdigest()
        )
        for path in paths
    }


@dataclass
class SetHarness:
    """One store's set, and the four things this file needs to do to it."""

    name: str
    manifest_path: Path
    body_paths: tuple[Path, ...]
    publish_expected: Callable[[], object]
    expected: dict[Path, object]

    def assert_disk_equals_expected(self) -> None:
        for path in self.body_paths:
            stored = _snapshot(path)
            assert stored is not None, f"{self.name}: {path.name} is missing"
            assert _agrees(stored, self.expected[path]), (
                f"{self.name}: {path.name} on disk is not what was published"
            )

    def capture(self) -> None:
        self.expected = {path: _snapshot(path) for path in self.body_paths}

    def replace_with_valid_other(self, path: Path) -> None:
        """A different body that is still perfectly readable.

        The interesting corruption is the one that parses. A truncated file is
        caught by any reader; a valid table with one row missing is caught only
        by comparing against what was published.
        """
        if path.suffix == ".parquet":
            with pq.ParquetFile(path) as reader:
                table = reader.read()
            assert table.num_rows > 1, f"{self.name}: {path.name} has too few rows"
            pq.write_table(table.slice(0, table.num_rows - 1), path)
            return
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            document = {**document, "fpbench_harness_marker": "elsewhere"}
        path.write_text(json.dumps(document), encoding="utf-8")

    def corrupt(self, path: Path) -> None:
        path.write_bytes(b"this is not a document of any kind")


# ---------------------------------------------------------------- the factories


def _plan_and_results(tmp_path: Path):
    from runworld import build_world

    world = build_world(tmp_path / "w", subjects=1, fingers=2)
    return world


def plan_set(tmp_path: Path) -> SetHarness:
    world = _plan_and_results(tmp_path)
    store, plan = world.plan_store, world.plan
    run_id = world.run.run_id
    store.ensure_plan(plan)
    harness = SetHarness(
        name="plan",
        manifest_path=store.plan_manifest_path(run_id),
        body_paths=(store.jobs_path(run_id),),
        publish_expected=lambda: store.ensure_plan(plan),
        expected={},
    )
    harness.capture()
    return harness


def prepared_image_set(tmp_path: Path) -> SetHarness:
    from canonicalworld import build_canonical_world

    world = build_canonical_world(tmp_path / "w", subjects=1, fingers=(1,))
    store = world.store
    set_id = world.preparation_set_id
    container = store.set_dir(set_id)

    def publish():
        return store.ensure_manifest(
            manifest=world.manifest,
            entries=world.entries,
            profile=world.profile,
            runtime=world.runtime,
            definition=world.definition,
        )

    harness = SetHarness(
        name="prepared-image",
        manifest_path=store.manifest_path(set_id),
        body_paths=(
            store.profile_path(container),
            store.runtime_path(container),
            store.definition_path(container),
            store.entries_table_path(set_id),
        ),
        publish_expected=publish,
        expected={},
    )
    harness.capture()
    return harness


def paired_set(tmp_path: Path) -> SetHarness:
    # The paired chain is eight bodies of five different shapes and building one
    # by hand here would be a second, drifting definition of what a paired set
    # is. The unit suite already has the real derivation.
    import sys

    unit = str(Path(__file__).resolve().parents[1] / "unit")
    if unit not in sys.path:
        sys.path.insert(0, unit)
    import test_paired_failure_injection as paired

    derived = paired._derive(tmp_path / "w", finalize=False)
    store, paired_id = derived.store, derived.paired_id

    def publish():
        return store.publish_paired_set(
            paired.PairedSetInputs(
                definition=derived.definition,
                policy=paired._POLICY,
                records=derived.records,
                transitions=derived.transitions,
                common=derived.common,
                counts=derived.counts,
                observations=derived.observations,
                control_audit=derived.control,
                manifest=derived.manifest,
            )
        )

    harness = SetHarness(
        name="paired-evaluation",
        manifest_path=store.manifest_path(paired_id),
        body_paths=(
            store.definition_path(paired_id),
            store.policy_path(paired_id),
            store.comparisons_path(paired_id),
            store.eligibility_path(paired_id),
            store.common_eligible_path(paired_id),
            store.counts_path(paired_id),
            store.observations_path(paired_id),
            store.control_audit_path(paired_id),
        ),
        publish_expected=publish,
        expected={},
    )
    harness.capture()
    return harness


def result_set(tmp_path: Path) -> SetHarness:
    from runworld import build_world
    from fpbench.execution.result_set import build_result_set

    world = build_world(tmp_path / "w", research=True)
    world.executor().execute(finalize=False)
    manifest, entries = build_result_set(
        run=world.run,
        plan=world.plan,
        result_store=world.result_store,
        runtime_reference=world.runtime_reference,
    )
    store = world.result_set_store
    store.ensure_result_set(manifest, entries)
    harness = SetHarness(
        name="result-set",
        manifest_path=store.manifest_path(manifest.run_id),
        body_paths=(store.entries_path(manifest.run_id),),
        publish_expected=lambda: store.ensure_result_set(manifest, entries),
        expected={},
    )
    harness.capture()
    return harness


def _chain(tmp_path: Path):
    from decisionworld import build_decision_world, derive_full_chain

    world = build_decision_world(tmp_path / "w")
    return world, derive_full_chain(world)


def decision_set(tmp_path: Path) -> SetHarness:
    from fpbench.storage.decision_set_store import DecisionSetStore

    world, chain = _chain(tmp_path)
    store = DecisionSetStore(world.workspace)
    set_id = chain.decision_set_id
    run_id = chain.decision_set.manifest.run_id

    def publish():
        return store.ensure_decision_set(
            profile=chain.decision_set.profile,
            manifest=chain.decision_set.manifest,
            records=chain.decision_set.records,
        )

    harness = SetHarness(
        name="decision-set",
        manifest_path=store.manifest_path(run_id, set_id),
        body_paths=(
            store.records_path(run_id, set_id),
            store.profile_path(run_id, set_id),
        ),
        publish_expected=publish,
        expected={},
    )
    harness.capture()
    return harness


def eligibility_set(tmp_path: Path) -> SetHarness:
    from fpbench.storage.eligibility_set_store import EligibilitySetStore

    world, chain = _chain(tmp_path)
    store = EligibilitySetStore(world.workspace)
    set_id = chain.decision_set_id
    manifest = chain.eligibility.manifest

    def publish():
        return store.ensure_eligibility_set(
            decision_set_id=set_id,
            manifest=manifest,
            records=chain.eligibility.records,
        )

    harness = SetHarness(
        name="eligibility-set",
        manifest_path=store.manifest_path(manifest.run_id, set_id),
        body_paths=(store.entries_path(manifest.run_id, set_id),),
        publish_expected=publish,
        expected={},
    )
    harness.capture()
    return harness


def evaluation_view(tmp_path: Path) -> SetHarness:
    from fpbench.storage.evaluation_view_store import EvaluationViewStore

    world, chain = _chain(tmp_path)
    store = EvaluationViewStore(world.workspace)
    set_id = chain.decision_set_id
    view = next(iter(chain.views.values()))
    manifest = view.manifest
    run_id = chain.decision_set.manifest.run_id

    def publish():
        return store.ensure_view(
            run_id=run_id,
            decision_set_id=set_id,
            manifest=manifest,
            entries=view.entries,
        )

    harness = SetHarness(
        name="evaluation-view",
        manifest_path=store.manifest_path(run_id, set_id, manifest.view_kind),
        body_paths=(store.entries_path(run_id, set_id, manifest.view_kind),),
        publish_expected=publish,
        expected={},
    )
    harness.capture()
    return harness


def metric_set(tmp_path: Path) -> SetHarness:
    from metricworld import all_matching, build_metric_world
    from fpbench.storage.metric_set_store import MetricSetStore

    workspace = tmp_path / "w"
    world = build_metric_world({"sd300a": all_matching(4), "sd300b": all_matching(4)})
    definition, policy, profile, manifest, counts, observations = world.metric_set()
    store = MetricSetStore(workspace)

    def publish():
        return store.ensure_metric_set(
            definition=definition,
            policy=policy,
            report_profile=profile,
            manifest=manifest,
            counts=counts,
            observations=observations,
        )

    publish()
    run_id, set_id = manifest.run_id, manifest.metric_set_id
    harness = SetHarness(
        name="metric-set",
        manifest_path=store.manifest_path(run_id, set_id),
        body_paths=(
            store.definition_path(run_id, set_id),
            store.policy_path(run_id, set_id),
            store.report_profile_path(run_id, set_id),
            store.counts_path(run_id, set_id),
            store.observations_path(run_id, set_id),
        ),
        publish_expected=publish,
        expected={},
    )
    harness.capture()
    return harness


#: All eight. A store missing from this tuple is a store nothing here checks,
#: which is how three of them stayed broken through three rounds of review.
SET_FACTORIES = (
    plan_set,
    result_set,
    decision_set,
    eligibility_set,
    evaluation_view,
    metric_set,
    prepared_image_set,
    paired_set,
)


@pytest.fixture(params=SET_FACTORIES, ids=lambda factory: factory.__name__)
def factory(request):
    return request.param


# ------------------------------------------------------------------- the matrix


def test_a_fresh_publication_puts_the_expected_set_on_disk(tmp_path, factory):
    case = factory(tmp_path)
    case.assert_disk_equals_expected()
    assert case.manifest_path.is_file()


def test_complete_retry_revalidates_every_body_and_rewrites_none(tmp_path, factory):
    """Publishing a finished set again reads it all and changes nothing."""
    case = factory(tmp_path)
    before = file_state((case.manifest_path, *case.body_paths))

    case.publish_expected()

    case.assert_disk_equals_expected()
    assert file_state((case.manifest_path, *case.body_paths)) == before, (
        "a retry over a complete set rewrote something"
    )


def test_a_replaced_body_is_never_accepted_or_repaired(tmp_path, factory):
    """The defect this whole matrix exists for.

    A body swapped for a different, valid one used to be invisible to a retry:
    the manifest fingerprint matched, no body was missing, so nothing was read.
    """
    for index in range(len(factory(tmp_path / "probe").body_paths)):
        case = factory(tmp_path / f"case{index}")
        body = case.body_paths[index]
        case.replace_with_valid_other(body)
        before = file_state((case.manifest_path, *case.body_paths))

        with pytest.raises(_CONFLICT):
            case.publish_expected()

        assert file_state((case.manifest_path, *case.body_paths)) == before, (
            f"{case.name}: a refused publication still wrote to disk"
        )


def test_an_unreadable_body_is_a_conflict_and_not_a_rewrite(tmp_path, factory):
    case = factory(tmp_path)
    body = case.body_paths[0]
    case.corrupt(body)
    before = file_state((case.manifest_path, *case.body_paths))

    with pytest.raises(_CONFLICT):
        case.publish_expected()

    assert file_state((case.manifest_path, *case.body_paths)) == before


def test_only_missing_bodies_are_completed(tmp_path, factory):
    """A partial set is finished, and finishing it is not repairing it."""
    for index in range(len(factory(tmp_path / "probe").body_paths)):
        case = factory(tmp_path / f"case{index}")
        missing = case.body_paths[index]
        missing.unlink()
        survivors = [path for path in case.body_paths if path != missing]
        before = file_state(survivors)

        case.publish_expected()

        case.assert_disk_equals_expected()
        assert file_state(survivors) == before, (
            f"{case.name}: completing one body rewrote another"
        )


def test_missing_plus_different_is_a_conflict_not_a_repair(tmp_path, factory):
    """The order matters: everything present is checked before anything is made."""
    case = factory(tmp_path)
    if len(case.body_paths) < 2:
        pytest.skip("requires a multi-body set")
    missing, different = case.body_paths[0], case.body_paths[1]
    missing.unlink()
    case.replace_with_valid_other(different)
    before = file_state((case.manifest_path, *case.body_paths))

    with pytest.raises(_CONFLICT):
        case.publish_expected()

    assert file_state((case.manifest_path, *case.body_paths)) == before
    assert not missing.is_file(), (
        "the missing body was created even though another one disagreed"
    )


def test_an_orphaned_body_without_a_manifest_is_decided_before_the_claim(
    tmp_path, factory
):
    """Bodies under a name nothing claims.

    Under manifest-first this cannot be our own crash, so it is either older data
    or somebody else's files. If they are what we would write, the name is ours
    to complete; if they are not, we must not claim a set we would then have to
    refuse for ever.
    """
    case = factory(tmp_path)
    case.manifest_path.unlink()
    case.publish_expected()
    case.assert_disk_equals_expected()

    other = factory(tmp_path / "other")
    other.manifest_path.unlink()
    other.replace_with_valid_other(other.body_paths[0])
    with pytest.raises(_CONFLICT):
        other.publish_expected()
    assert not other.manifest_path.is_file(), (
        "a set was claimed over bodies that disagree with it"
    )


def test_an_unreadable_manifest_is_refused_without_touching_a_body(tmp_path, factory):
    case = factory(tmp_path)
    case.manifest_path.write_bytes(b"{ not json")
    before = file_state(case.body_paths)

    with pytest.raises((*_CONFLICT, json.JSONDecodeError)):
        case.publish_expected()

    assert file_state(case.body_paths) == before
