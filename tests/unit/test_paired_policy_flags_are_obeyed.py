"""A paired-policy flag has to reach the code it governs.

Three of them did not. ``retain_pair_delta``, ``report_direction_counts`` and
``transition_families`` were parsed, validated and folded into the policy
fingerprint, and then handed to nobody: neither ``build_paired_records`` nor
``build_transition_counts`` took a policy at all. Two runs whose policies
differed produced identical derivations under different fingerprints.

And the typo, which is the same failure seen from the author's side:
``retain_pair_dleta: false`` set nothing, raised nothing, and left a document
that looked like it had turned something off.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from fpbench.core.errors import ConfigurationError, PairedAlignmentError
from fpbench.paired.policy import load_paired_policy

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REAL_POLICY = (
    REPOSITORY_ROOT
    / "configs"
    / "comparisons"
    / "policies"
    / "sourceafis_native_vs_canonical500_paired_v1.yaml"
)


def _written(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _base() -> dict:
    return yaml.safe_load(REAL_POLICY.read_text(encoding="utf-8"))


def test_the_real_policy_still_loads() -> None:
    """The rule must accept the configuration the repository ships."""
    policy = load_paired_policy(REAL_POLICY)
    assert policy.retain_pair_delta is True
    assert policy.report_direction_counts is True
    assert policy.transition_families


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("scores", "retain_pair_dleta"),
        ("scores", "report_direction_count"),
        ("pairing", "require_same_algorithms"),
        ("control", "sd300a_exact_score_equalty"),
        ("policy", "polcy_version"),
    ],
)
def test_a_misspelled_key_is_refused(tmp_path: Path, section: str, key: str) -> None:
    document = _base()
    document[section][key] = False
    with pytest.raises(ConfigurationError, match=key):
        load_paired_policy(_written(tmp_path, document))


def test_the_message_names_the_permitted_keys(tmp_path: Path) -> None:
    document = _base()
    document["scores"]["retain_pair_dleta"] = False
    with pytest.raises(ConfigurationError) as raised:
        load_paired_policy(_written(tmp_path, document))
    message = str(raised.value)
    assert "retain_pair_delta" in message, "the message should show the real spelling"


def test_a_policy_that_declines_the_delta_is_refused_at_load(tmp_path: Path) -> None:
    """The one flag that is not a choice, and now says so.

    ``retain_pair_delta: false`` cannot be honoured by anything here: the
    control audit compares SD300A's two runs score for score, and
    ``PairedComparisonRecord`` refuses a scored relation carrying no delta. It
    was accepted and ignored, which is the worst of the three outcomes —
    the document said one thing and the derivation did another.
    """
    document = _base()
    document["scores"]["retain_pair_delta"] = False
    with pytest.raises(ConfigurationError, match="retain_pair_delta"):
        load_paired_policy(_written(tmp_path, document))


def test_the_summary_omits_direction_counts_when_the_policy_declines_them() -> None:
    """The flag that *is* a choice, and now reaches the renderer.

    Rendered twice from one set of records, so the flag is the only difference
    between the two summaries.
    """
    import dataclasses
    from types import SimpleNamespace

    from pairedworld import build_paired_world, paired_policy
    from fpbench.paired import align_pairs, build_paired_records
    from fpbench.paired.report import build_paired_summary

    world = build_paired_world()
    policy = paired_policy()
    records = build_paired_records(
        native=world.native,
        canonical=world.canonical,
        pair_ids=align_pairs(native=world.native, canonical=world.canonical),
        policy=policy,
    )

    #: Only the fields the summary reads. A real manifest would drag a whole
    #: publication in for a question about one boolean.
    manifest = SimpleNamespace(
        paired_evaluation_id="pairedeval_probe",
        paired_evaluation_fingerprint="f" * 64,
        total_paired_comparisons=len(records),
        total_eligibility_units=0,
        total_common_eligible_rows=0,
    )
    control = SimpleNamespace(
        planned_sd300a_pairs=0,
        compared_scores=0,
        equal_scores=0,
        equal_result_statuses=0,
        equal_decisions=0,
        is_clean=True,
    )

    def summarise(active):
        return build_paired_summary(
            manifest=manifest,
            native_ids={},
            canonical_ids={},
            control=control,
            counts=(),
            observations=(),
            records=records,
            generated_utc="fixed",
            policy=active,
        )

    assert summarise(policy)["score_direction_counts"], "the shipped policy reports them"
    declined = summarise(dataclasses.replace(policy, report_direction_counts=False))
    assert declined["score_direction_counts"] is None


def test_a_policy_enabling_no_family_counts_nothing(tmp_path: Path) -> None:
    import dataclasses

    from pairedworld import build_paired_world, paired_policy
    from fpbench.paired import (
        align_pairs,
        build_common_eligible_view,
        build_eligibility_transitions,
        build_paired_records,
        build_transition_counts,
        release_order,
    )

    world = build_paired_world()
    policy = paired_policy()
    pair_ids = align_pairs(native=world.native, canonical=world.canonical)
    records = build_paired_records(
        native=world.native,
        canonical=world.canonical,
        pair_ids=pair_ids,
        policy=policy,
    )
    transitions = build_eligibility_transitions(
        native=world.native, canonical=world.canonical
    )
    common = build_common_eligible_view(
        native=world.native,
        canonical=world.canonical,
        transitions=transitions,
        records=records,
    )
    with pytest.raises(PairedAlignmentError, match="no transition family"):
        build_transition_counts(
            records=records,
            transitions=transitions,
            common_eligible=common,
            releases=release_order(world.native),
            source_fingerprints={},
            policy=dataclasses.replace(policy, transition_families=()),
        )
