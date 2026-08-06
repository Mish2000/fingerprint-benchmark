"""The Stage 8C experiment wrapper: what it binds to, and what stops it.

Three subjects, none of which needs SD300, torch or a checkpoint:

* the Stage 8B binding, read from the committed publication and compared with
  this repository's own source;
* the shape of ``prepare``, which must reach the engine and never the executor;
* the downstream check, which must have teeth against the comparison Stage 7D
  actually published.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import ResearchPreflightError
from fpbench.experiments import stage8c_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.flx_canonical500_full import (
    check_no_cross_algorithm_comparison,
    load_flx_canonical500_config,
)
from fpbench.experiments.stage8b_binding import (
    read_stage8b_publication,
    require_stage8b_binding,
)

pytestmark = pytest.mark.stage8c_contract


@pytest.fixture(scope="module")
def config():
    return load_flx_canonical500_config()


# ------------------------------------------------------- the Stage 8B binding


def test_the_committed_stage_8b_publication_is_readable_without_a_runtime() -> None:
    published = read_stage8b_publication()
    assert published.outcome == frozen.STAGE8B_OUTCOME
    assert published.finalization_fingerprint == frozen.STAGE8B_FINALIZATION_FINGERPRINT
    assert published.opens_stage_8c is True


def test_the_publication_carries_the_artifacts_stage_8c_is_defined_against() -> None:
    published = read_stage8b_publication()
    assert published.checkpoint_sha256 == frozen.CHECKPOINT_SHA256
    assert published.source_archive_sha256 == frozen.SOURCE_ARCHIVE_SHA256


def test_the_binding_holds_between_the_config_the_publication_and_this_source(
    config,
) -> None:
    published = require_stage8b_binding(config.stage8b, config.artifact)
    assert published.outcome == frozen.STAGE8B_OUTCOME
    # The four profiles were rebuilt from fpbench.flx and matched; if any had
    # drifted, require_stage8b_binding would have raised.
    assert published.score_profile_fingerprint == frozen.SCORE_PROFILE_FINGERPRINT
    assert published.adapter_profile_fingerprint == frozen.ADAPTER_PROFILE_FINGERPRINT


def _rebuilt(binding, **changes):
    from dataclasses import replace

    return replace(binding, **changes)


@pytest.mark.parametrize(
    "field, wrong",
    [
        ("finalization_fingerprint", "0" * 64),
        ("outcome", "FLX_CONTRACT_FAILED"),
        ("runtime_manifest_fingerprint", "1" * 64),
        ("preprocessing_profile_fingerprint", "2" * 64),
        ("representation_profile_fingerprint", "3" * 64),
        ("score_profile_fingerprint", "4" * 64),
        ("adapter_profile_fingerprint", "5" * 64),
    ],
)
def test_a_binding_the_publication_does_not_carry_is_refused(
    config, field: str, wrong: str
) -> None:
    with pytest.raises(ResearchPreflightError, match="not bound"):
        require_stage8b_binding(
            _rebuilt(config.stage8b, **{field: wrong}), config.artifact
        )


@pytest.mark.parametrize(
    "field, wrong",
    [
        ("checkpoint_sha256", "6" * 64),
        ("source_archive_sha256", "7" * 64),
    ],
)
def test_an_artifact_the_publication_does_not_carry_is_refused(
    config, field: str, wrong: str
) -> None:
    with pytest.raises(ResearchPreflightError, match="not bound"):
        require_stage8b_binding(
            config.stage8b, _rebuilt(config.artifact, **{field: wrong})
        )


def test_a_publication_with_no_stage_8b_evidence_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ResearchPreflightError, match="cannot be read"):
        read_stage8b_publication(repository_root=tmp_path)


def test_a_profile_that_drifted_since_the_qualification_is_refused(
    config, monkeypatch
) -> None:
    """The check with the real teeth: this source must still produce them.

    A restated fingerprint proves somebody typed the right number. This proves
    the transform, the representation and the comparator have not changed since
    the qualification, which a restated number cannot (docs/adr/0077).
    """

    class Drifted:
        fingerprint = "8" * 64

    monkeypatch.setattr(
        "fpbench.flx.score.build_score_profile", lambda: Drifted()
    )
    with pytest.raises(ResearchPreflightError, match="not the ones Stage 8B qualified"):
        require_stage8b_binding(config.stage8b, config.artifact)


def test_an_outcome_that_does_not_permit_execution_is_refused(
    config, monkeypatch
) -> None:
    from fpbench.experiments import stage8b_binding

    published = read_stage8b_publication()
    blocked = _rebuilt(published, outcome="FLX_CONTRACT_FAILED")
    monkeypatch.setattr(
        stage8b_binding, "read_stage8b_publication", lambda **_: blocked
    )
    # The declared binding is edited to match, so the only thing left to refuse
    # is the outcome itself.
    with pytest.raises(ResearchPreflightError, match="permits a benchmark-scale run"):
        require_stage8b_binding(
            _rebuilt(config.stage8b, outcome="FLX_CONTRACT_FAILED"), config.artifact
        )


def test_a_qualification_that_does_not_open_stage_8c_is_refused(
    config, monkeypatch
) -> None:
    from fpbench.experiments import stage8b_binding

    published = _rebuilt(read_stage8b_publication(), opens_stage_8c=False)
    monkeypatch.setattr(
        stage8b_binding, "read_stage8b_publication", lambda **_: published
    )
    with pytest.raises(ResearchPreflightError, match="does not open Stage 8C"):
        require_stage8b_binding(config.stage8b, config.artifact)


# ----------------------------------------------------------- no downstream


def test_the_downstream_check_finds_the_comparison_stage_7d_published() -> None:
    """Proof the check works, using the one comparison that really exists.

    A test that only ever asserted "no findings" would pass just as well if the
    function returned an empty list unconditionally.
    """
    findings = check_no_cross_algorithm_comparison(REPOSITORY_ROOT, "run_f0468f28ffba")
    assert findings
    assert "cites run run_f0468f28ffba" in findings[0].message


def test_a_run_nothing_compares_has_no_cross_algorithm_finding() -> None:
    assert check_no_cross_algorithm_comparison(REPOSITORY_ROOT, "run_000000000001") == []


def test_an_unreadable_comparison_bundle_is_a_finding(tmp_path: Path) -> None:
    directory = tmp_path / "evidence" / "some-comparison"
    directory.mkdir(parents=True)
    (directory / "algcompare_deadbeef.json").write_text(
        json.dumps({"definition": {"definition_id": "nonsense"}}), encoding="utf-8"
    )
    findings = check_no_cross_algorithm_comparison(tmp_path, "run_000000000001")
    assert findings
    assert "unreadable cross-algorithm definition" in findings[0].message


def test_nothing_is_entitled_to_derive_from_this_run_yet() -> None:
    assert frozen.PERMITTED_DOWNSTREAM_EXPERIMENTS == frozenset()


# ------------------------------------------- pre-current paired definitions


def test_a_paired_definition_the_current_schema_refuses_is_still_readable(
    tmp_path: Path,
) -> None:
    """The fallback that keeps Stage 6B's comparisons from becoming findings.

    Three paired definitions in the real workspace predate the current
    fingerprint schema, so ``read_definition`` refuses them. They are Stage 6B's
    and have nothing to do with this run, and treating "I cannot parse this" as
    "this derives from my run" would block finalization over someone else's
    artefact — which is exactly what happened before this existed.
    """
    from fpbench.experiments.flx_canonical500_full import (
        _legacy_paired_definition_cites_run,
    )

    path = tmp_path / "definition.json"
    path.write_text(
        json.dumps(
            {
                "native_run_fingerprint": "a" * 64,
                "canonical_run_fingerprint": "b" * 64,
                "some_field_the_current_schema_added": "unparseable",
            }
        ),
        encoding="utf-8",
    )
    assert _legacy_paired_definition_cites_run(path, "a" * 64) is True
    assert _legacy_paired_definition_cites_run(path, "b" * 64) is True
    assert _legacy_paired_definition_cites_run(path, "c" * 64) is False


def test_the_fallback_reads_two_named_fields_and_never_greps(tmp_path: Path) -> None:
    """A digest mentioned anywhere else in the document must not count."""
    from fpbench.experiments.flx_canonical500_full import (
        _legacy_paired_definition_cites_run,
    )

    path = tmp_path / "definition.json"
    path.write_text(
        json.dumps(
            {
                "native_run_fingerprint": "a" * 64,
                "canonical_run_fingerprint": "b" * 64,
                "notes": "this text mentions " + "c" * 64,
                "unrelated": {"nested_fingerprint": "c" * 64},
            }
        ),
        encoding="utf-8",
    )
    assert _legacy_paired_definition_cites_run(path, "c" * 64) is False


@pytest.mark.parametrize(
    "payload",
    [
        {"canonical_run_fingerprint": "b" * 64},
        {"native_run_fingerprint": "a" * 64},
        {"native_run_fingerprint": "short", "canonical_run_fingerprint": "b" * 64},
        {"native_run_fingerprint": "z" * 64, "canonical_run_fingerprint": "b" * 64},
    ],
)
def test_a_definition_without_two_valid_digests_is_refused(
    tmp_path: Path, payload: dict
) -> None:
    from fpbench.experiments.flx_canonical500_full import (
        _legacy_paired_definition_cites_run,
    )

    path = tmp_path / "definition.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises((KeyError, ValueError)):
        _legacy_paired_definition_cites_run(path, "a" * 64)


# -------------------------------------------------------- the pair manifest


def test_the_alignment_context_loads_the_pair_manifest_it_never_creates() -> None:
    """``allow_creation=False``, read out of the source rather than assumed.

    A workspace missing the manifest must be an error, not an invitation to
    build a new one that would happen to have the same shape and different
    contents (spec section 21, step 9).
    """
    import ast

    path = REPOSITORY_ROOT / "src/fpbench/experiments/flx_canonical500_full.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_sd300_inputs"
    ]
    assert calls, "the experiment must load the pair manifest"
    for call in calls:
        keywords = {
            keyword.arg: keyword.value
            for keyword in call.keywords
            if keyword.arg is not None
        }
        assert "allow_creation" in keywords, "allow_creation must be explicit"
        value = keywords["allow_creation"]
        assert isinstance(value, ast.Constant) and value.value is False


# ------------------------------------------------- the input controls check


def _reference_run():
    """A minimal stand-in for the canonical SourceAFIS run."""
    from datetime import datetime, timezone

    from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION
    from fpbench.core.enums import EnvironmentStatus, ScoreDirection
    from fpbench.core.execution_models import (
        AlgorithmDescriptor,
        EnvironmentReport,
        ExecutionProfile,
    )
    from fpbench.core.identifiers import CohortId
    from fpbench.core.result_models import RunDefinition

    return RunDefinition(
        run_id="run_4c59fa02a6ab",
        run_fingerprint="a" * 64,
        protocol_id="sd300_50_subjects",
        cohort_id=CohortId(frozen.REFERENCE_COHORT_ID),
        pair_manifest_hash=frozen.REFERENCE_PAIR_MANIFEST_HASH,
        algorithm=AlgorithmDescriptor(
            algorithm_id="sourceafis_java",
            display_name="SourceAFIS",
            adapter_id="sourceafis_java_subprocess",
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version="3.18.1",
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
        ),
        algorithm_fingerprint="b" * 64,
        environment=EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version="3.18.1",
            runtime={"fpbench.source.revision": "c" * 40},
            dependencies={},
        ),
        environment_fingerprint="d" * 64,
        execution_profile=ExecutionProfile(
            profile_id="canonical_500_lanczos3_60s_v1",
            preparer_id="canonical_500_png",
            timeout_seconds=60.0,
            deterministic_seed=0,
            parameters={"target_ppi": "500", "resolution_mode": "canonical_500"},
        ),
        execution_profile_hash="e" * 64,
        replicate_index=0,
        created_utc=datetime.now(timezone.utc).isoformat(),
    )


def _candidate_spec(**overrides):
    from types import SimpleNamespace

    from fpbench.core.execution_models import ExecutionProfile

    profile = ExecutionProfile(
        profile_id=frozen.EXECUTION_PROFILE_ID,
        preparer_id="canonical_500_png",
        # The one control that differs, and the whole reason this function
        # exists beside the strict one (docs/adr/0074).
        timeout_seconds=float(frozen.JOB_DEADLINE_SECONDS),
        deterministic_seed=0,
        parameters={"target_ppi": "500", "resolution_mode": "canonical_500"},
    )
    return SimpleNamespace(
        execution_profile=overrides.get("execution_profile", profile),
        replicate_index=overrides.get("replicate_index", 0),
        research_mode=overrides.get("research_mode", True),
        materialization_policy=overrides.get(
            "materialization_policy", "content_addressed_copy_v1"
        ),
    )


def test_a_different_job_deadline_and_profile_id_are_permitted() -> None:
    from fpbench.experiments.canonical_run_alignment import (
        require_canonical_input_controls_equal,
    )

    require_canonical_input_controls_equal(
        _reference_run(),
        _candidate_spec(),
        reference_materialization_policy="content_addressed_copy_v1",
    )


def test_the_strict_sibling_still_refuses_the_same_pair() -> None:
    """Stage 7C's guarantee is unchanged by Stage 8C existing."""
    from fpbench.experiments.canonical_run_alignment import (
        require_execution_controls_equal,
    )

    with pytest.raises(ResearchPreflightError, match="timeout_seconds"):
        require_execution_controls_equal(
            _reference_run(),
            _candidate_spec(),
            reference_materialization_policy="content_addressed_copy_v1",
        )


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("replicate_index", 1, "replicate_index"),
        ("research_mode", False, "research_mode"),
        ("materialization_policy", "symlink_v1", "materialization_policy"),
    ],
)
def test_a_changed_input_control_is_refused(field, value, message) -> None:
    from fpbench.experiments.canonical_run_alignment import (
        require_canonical_input_controls_equal,
    )

    with pytest.raises(ResearchPreflightError, match=message):
        require_canonical_input_controls_equal(
            _reference_run(),
            _candidate_spec(**{field: value}),
            reference_materialization_policy="content_addressed_copy_v1",
        )


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"deterministic_seed": 7}, "deterministic_seed"),
        ({"preparer_id": "identity_source_png"}, "preparer_id"),
        ({"parameters": {"target_ppi": "1000"}}, "parameters"),
        ({"parameters": {"target_ppi": "500"}}, "parameters"),
    ],
)
def test_a_changed_input_parameter_is_refused(changes, message) -> None:
    from fpbench.core.execution_models import ExecutionProfile
    from fpbench.experiments.canonical_run_alignment import (
        require_canonical_input_controls_equal,
    )

    base = dict(
        profile_id=frozen.EXECUTION_PROFILE_ID,
        preparer_id="canonical_500_png",
        timeout_seconds=float(frozen.JOB_DEADLINE_SECONDS),
        deterministic_seed=0,
        parameters={"target_ppi": "500", "resolution_mode": "canonical_500"},
    )
    base.update(changes)
    with pytest.raises(ResearchPreflightError, match=message):
        require_canonical_input_controls_equal(
            _reference_run(),
            _candidate_spec(execution_profile=ExecutionProfile(**base)),
            reference_materialization_policy="content_addressed_copy_v1",
        )


def test_a_reference_that_is_not_a_research_run_is_refused() -> None:
    from dataclasses import replace

    from fpbench.core.enums import EnvironmentStatus
    from fpbench.core.execution_models import EnvironmentReport
    from fpbench.experiments.canonical_run_alignment import (
        require_canonical_input_controls_equal,
    )

    reference = replace(
        _reference_run(),
        environment=EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version="3.18.1",
            runtime={},
            dependencies={},
        ),
    )
    with pytest.raises(ResearchPreflightError, match="not a research run"):
        require_canonical_input_controls_equal(
            reference,
            _candidate_spec(),
            reference_materialization_policy="content_addressed_copy_v1",
        )


def test_prepare_never_reaches_the_executor() -> None:
    """``prepare`` writes a run, a plan and a binding, and no raw result."""
    import ast

    path = REPOSITORY_ROOT / "src/fpbench/experiments/flx_canonical500_full.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prepare = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "prepare_flx_canonical500_run"
    )
    called = {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(prepare)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }
    assert "execute_flx_research_run" not in called
    assert "execute" not in called
    assert "write_raw_result" not in called
