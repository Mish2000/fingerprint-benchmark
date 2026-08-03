"""Stage 7C selects nothing, decides nothing, and orchestrates nothing.

Three claims, each checked here rather than asserted in a docstring:

**It reuses.** The wrapper never calls ``build_cohort`` or ``build_pairs``, never
rescans SD300 to choose participants, and never materialises an image. That is
checked over the syntax tree, because a module that merely *says* it reuses the
pair manifest is a module one edit away from generating a new one
(spec section 5).

**It decides nothing.** A configuration file carrying ``threshold``,
``decision_profile``, ``match_threshold``, ``acceptance_threshold`` or
``calibration`` — at any depth — is refused. BOZORTH3's scale has no threshold
anybody has earned yet, and SourceAFIS's documented 40 is a number about a
different scale (spec section 18, docs/adr/0052).

**It orchestrates nothing.** No subprocess, no raw result opened, no runtime
bundle built, no result set, no receipt, no marker, no digest computed over
results. All of that belongs to the engine stage 7A extracted, and the wrapper
forwards to it (spec section 22).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.execution_models import ExecutionProfile
from fpbench.experiments import nbis_canonical500_full as wrapper
from fpbench.experiments.canonical_run_alignment import (
    require_execution_controls_equal,
)

pytestmark = pytest.mark.nbis_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    REPOSITORY_ROOT / "configs" / "experiments" / "nbis_canonical500_full_v1.yaml"
)


@pytest.fixture(scope="module")
def config():
    return wrapper.load_nbis_canonical500_config(
        CONFIG_PATH, repository_root=REPOSITORY_ROOT
    )


def written(tmp_path: Path, document) -> Path:
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def document():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------ the committed file


def test_the_committed_config_names_the_reference_chain(config):
    """Spec section 3: one reference run, written down, never searched for."""
    assert config.reference.run_id == "run_4c59fa02a6ab"
    assert config.reference.plan_id == "plan_b4ae66e91923"
    assert config.reference.result_set_id == "resultset_087b084fb8a8"


def test_the_committed_config_names_the_canonical_input_set(config):
    assert config.preparation_set_id == "prepset_be560e047991"
    assert config.preparation_set_fingerprint == (
        "be560e047991a0d58af8f86a4576f8b78dc350e643af82f0e2405350d9e2fd3f"
    )
    assert config.transform_profile_id == "canonical_gray8_500ppi_lanczos3_v1"
    assert config.transform_profile_fingerprint == (
        "28abd453d86918132c03a57a2ace1a59024b5fb9c2e02eb5339e2a61e4597373"
    )
    assert config.target_ppi == 500


def test_the_committed_config_declares_the_whole_experiment(config):
    assert config.expected_jobs == 6000
    assert config.expected_per_release == 2000
    assert config.expected_per_stage == 1500
    assert config.expected_per_release_stage == 500
    assert config.expected_participating_images == 3000
    assert config.expected_subjects == 50
    assert config.expected_releases == ("SD300A", "SD300B", "SD300C")
    assert config.alignment_expectations == (
        wrapper.SD300_CANONICAL_EXPECTATIONS
    )


def test_the_committed_config_pins_one_build(config):
    """Spec section 12: no newest, no lexicographic first, no fallback."""
    assert config.nbis_build_id == "658f9f54a8f2"
    assert config.build_root == Path("build/nbis-5.0.0")
    assert "371409be18a6" not in CONFIG_PATH.read_text(encoding="utf-8").replace(
        "371409be18a6 that certified the route in stage 7B", ""
    )


def test_the_committed_config_reuses_the_reference_execution_profile(config):
    assert config.execution_profile.profile_id == "canonical_500_lanczos3_60s_v1"
    assert config.execution_profile.timeout_seconds == 60.0
    assert config.execution_profile.deterministic_seed == 0
    assert config.execution_profile.preparer_id == "canonical_500_png"
    assert config.replicate_index == 0
    assert config.materialization_policy == "content_addressed_copy_v1"
    assert config.research_mode is True


def test_the_spec_carries_the_canonical_input_set(config):
    spec = wrapper.build_nbis_canonical500_spec(config)
    assert spec.is_canonical
    assert spec.preparation_set_id == config.preparation_set_id
    assert spec.evidence_directory == Path("evidence/nbis-canonical500-raw")
    assert dict(spec.expected_source_ppi) == {
        "SD300A": 500,
        "SD300B": 1000,
        "SD300C": 2000,
    }


# ---------------------------------------------------------------- strict YAML


@pytest.mark.parametrize(
    "key", sorted(wrapper.FORBIDDEN_CONFIG_KEYS)
)
def test_a_decision_key_at_the_top_level_is_refused(tmp_path, document, key):
    document[key] = 40
    with pytest.raises(ConfigurationError, match="not a Stage 7C setting"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


@pytest.mark.parametrize("key", sorted(wrapper.FORBIDDEN_CONFIG_KEYS))
def test_a_decision_key_nested_anywhere_is_refused(tmp_path, document, key):
    """A threshold hidden three levels down is still a threshold."""
    document["reporting"] = {**document["reporting"], "extra": [{key: 40}]}
    with pytest.raises(ConfigurationError, match="not a Stage 7C setting"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_an_unknown_top_level_key_is_refused(tmp_path, document):
    document["cohort"] = "sd300_50_subjects_dev_000000000000"
    with pytest.raises(ConfigurationError, match="unknown"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


@pytest.mark.parametrize(
    "section,key",
    [
        ("reference", "cohort_id"),
        ("preparation", "resize"),
        ("expected", "successes"),
        ("execution", "workers"),
        ("runtime", "retry_policy"),
        ("build", "fallback"),
    ],
)
def test_an_unknown_nested_key_is_refused(tmp_path, document, section, key):
    document[section] = {**document[section], key: "no"}
    with pytest.raises(ConfigurationError, match="unknown"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_a_stringified_integer_is_refused(tmp_path, document):
    document["expected"] = {**document["expected"], "jobs": "6000"}
    with pytest.raises(ConfigurationError, match="exact integer"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_a_quoted_boolean_is_refused(tmp_path, document):
    document["runtime"] = {**document["runtime"], "research_mode": "true"}
    with pytest.raises(ConfigurationError, match="YAML boolean"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_a_concurrent_run_is_refused(tmp_path, document):
    document["execution"] = {**document["execution"], "sequential": False}
    with pytest.raises(ConfigurationError, match="sequential"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_a_retry_policy_is_refused(tmp_path, document):
    document["execution"] = {**document["execution"], "retries": 1}
    with pytest.raises(ConfigurationError, match="no retries"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


@pytest.mark.parametrize("key", ["biometric_metrics", "score_statistics"])
def test_a_biometric_claim_is_refused(tmp_path, document, key):
    document["reporting"] = {**document["reporting"], key: True}
    with pytest.raises(ConfigurationError, match="must be false"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_an_input_set_the_execution_profile_does_not_name_is_refused(
    tmp_path, document
):
    """Two files may not disagree about which pixels a run opened."""
    document["preparation"] = {
        **document["preparation"],
        "set_id": "prepset_000000000000",
    }
    with pytest.raises(ConfigurationError, match="straddle two input sets"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_an_execution_profile_id_that_does_not_match_the_file_is_refused(
    tmp_path, document
):
    document["execution"] = {
        **document["execution"],
        "profile_id": "canonical_500_lanczos3_30s_v1",
    }
    with pytest.raises(ConfigurationError, match="profile_id"):
        wrapper.load_nbis_canonical500_config(
            written(tmp_path, document), repository_root=REPOSITORY_ROOT
        )


def test_a_missing_config_is_an_error(tmp_path):
    with pytest.raises(ConfigurationError, match="not found"):
        wrapper.load_nbis_canonical500_config(tmp_path / "absent.yaml")


# --------------------------------------------------------------- build pinning


def test_no_build_directory_is_refused(config):
    """Spec section 12: the path is explicit or the run does not start."""
    with pytest.raises(ConfigurationError, match="pass it explicitly"):
        wrapper.require_pinned_build(
            None, config=config, repository_root=REPOSITORY_ROOT
        )


def test_a_different_build_id_is_refused(tmp_path, config):
    directory = tmp_path / "371409be18a6"
    (directory / "bin").mkdir(parents=True)
    (directory / "nbis-build-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="658f9f54a8f2"):
        wrapper.require_pinned_build(
            directory, config=config, repository_root=REPOSITORY_ROOT
        )


def test_a_build_without_a_manifest_is_refused(tmp_path, config):
    directory = tmp_path / "658f9f54a8f2"
    (directory / "bin").mkdir(parents=True)
    with pytest.raises(ConfigurationError, match="nbis-build-manifest.json"):
        wrapper.require_pinned_build(
            directory, config=config, repository_root=REPOSITORY_ROOT
        )


def test_an_uncertified_build_is_refused(tmp_path, config):
    directory = tmp_path / "658f9f54a8f2"
    (directory / "bin").mkdir(parents=True)
    (directory / "nbis-build-manifest.json").write_text(
        '{"schema_version": "1"}', encoding="utf-8"
    )
    with pytest.raises(ResearchPreflightError, match="not certified"):
        wrapper.require_pinned_build(
            directory, config=config, repository_root=REPOSITORY_ROOT
        )


def test_the_wrapper_never_resolves_a_build_from_the_environment():
    """``FPBENCH_NBIS_BUILD_DIR`` is stage 7B's convenience, not stage 7C's."""
    source = Path(wrapper.__file__).read_text(encoding="utf-8")
    assert "FPBENCH_NBIS_BUILD_DIR" not in source
    assert "resolve_build_directory" not in source


# ------------------------------------------------------- execution controls


def reference_run(**overrides):
    profile = ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id="canonical_500_png",
        timeout_seconds=60.0,
        deterministic_seed=0,
        parameters={"target_ppi": "500", "resolution_mode": "canonical_500"},
    )
    return SimpleNamespace(
        execution_profile=overrides.get("execution_profile", profile),
        replicate_index=overrides.get("replicate_index", 0),
        environment=SimpleNamespace(
            runtime={"fpbench.source.revision": "a" * 40},
            dependencies={},
        ),
    )


def candidate_spec(**overrides):
    profile = ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id="canonical_500_png",
        timeout_seconds=60.0,
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


def test_identical_execution_controls_pass():
    require_execution_controls_equal(
        reference_run(),
        candidate_spec(),
        reference_materialization_policy="content_addressed_copy_v1",
    )


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("replicate_index", 1, "replicate_index"),
        ("research_mode", False, "research_mode"),
        ("materialization_policy", "symlink_v1", "materialization_policy"),
    ],
)
def test_a_changed_execution_control_is_refused(field, value, message):
    with pytest.raises(ResearchPreflightError, match=message):
        require_execution_controls_equal(
            reference_run(),
            candidate_spec(**{field: value}),
            reference_materialization_policy="content_addressed_copy_v1",
        )


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"timeout_seconds": 30.0}, "timeout_seconds"),
        ({"deterministic_seed": 7}, "deterministic_seed"),
        ({"preparer_id": "identity_source_png"}, "preparer_id"),
        ({"profile_id": "canonical_500_lanczos3_30s_v1"}, "profile_id"),
        ({"parameters": {"target_ppi": "1000"}}, "parameters"),
    ],
)
def test_a_changed_execution_profile_is_refused(changes, message):
    base = dict(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id="canonical_500_png",
        timeout_seconds=60.0,
        deterministic_seed=0,
        parameters={"target_ppi": "500", "resolution_mode": "canonical_500"},
    )
    base.update(changes)
    with pytest.raises(ResearchPreflightError, match=message):
        require_execution_controls_equal(
            reference_run(),
            candidate_spec(execution_profile=ExecutionProfile(**base)),
            reference_materialization_policy="content_addressed_copy_v1",
        )


def test_a_reference_without_research_provenance_is_refused():
    reference = reference_run()
    reference.environment.runtime.clear()
    with pytest.raises(ResearchPreflightError, match="source revision"):
        require_execution_controls_equal(reference, candidate_spec())


def test_the_committed_config_reproduces_the_reference_profile(config):
    """The committed YAML against the profile file the reference run used.

    Not against the recorded run itself — that needs the real workspace and is
    asserted in ``tests/integration/test_stage_7c_workspace_preflight.py``. What
    is checked here is the half that lives in version control: Stage 7C reuses
    ``canonical_500_lanczos3_60s_v1`` rather than restating it (spec section 19).
    """
    profile = wrapper._load_execution_profile(
        REPOSITORY_ROOT / "configs" / "execution" / "canonical_500_lanczos3_60s_v1.yaml"
    )
    require_execution_controls_equal(
        reference_run(execution_profile=profile),
        wrapper.build_nbis_canonical500_spec(config),
        reference_materialization_policy="content_addressed_copy_v1",
    )
    assert dict(config.execution_profile.parameters) == dict(profile.parameters)


# ------------------------------------------------------------ the state model


def test_readiness_needs_all_three():
    ready_research = SimpleNamespace(is_research_ready=True, run_id="run_111111111111")
    world = _clean_report()
    assert wrapper.NbisCanonical500ExperimentState(
        research_state=ready_research, alignment_report=world, issues=()
    ).is_ready
    assert not wrapper.NbisCanonical500ExperimentState(
        research_state=SimpleNamespace(is_research_ready=False, run_id="run_1"),
        alignment_report=world,
        issues=(),
    ).is_ready
    assert not wrapper.NbisCanonical500ExperimentState(
        research_state=ready_research,
        alignment_report=_unclean_report(),
        issues=(),
    ).is_ready
    assert not wrapper.NbisCanonical500ExperimentState(
        research_state=ready_research,
        alignment_report=world,
        issues=(_an_issue(),),
    ).is_ready


def _an_issue():
    from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
    from fpbench.core.run_state_models import IntegrityIssue

    return IntegrityIssue(
        code=IntegrityIssueCode.PLAN_CONFLICT,
        severity=IntegritySeverity.ERROR,
        message="something is wrong",
    )


def _clean_report():
    from alignmentworld import REFERENCE, build_alignment_world
    from fpbench.experiments.canonical_run_alignment import (
        build_canonical_run_alignment_report,
    )

    world = build_alignment_world()
    return build_canonical_run_alignment_report(
        reference=world.side("reference"),
        candidate=world.side("candidate"),
        expected_reference=REFERENCE,
        expectations=world.expectations,
    )


def _unclean_report():
    from alignmentworld import REFERENCE, build_alignment_world
    from fpbench.experiments.canonical_run_alignment import (
        build_canonical_run_alignment_report,
    )

    world = build_alignment_world()
    return build_canonical_run_alignment_report(
        reference=world.side("reference", run_id="run_999999999999"),
        candidate=world.side("candidate"),
        expected_reference=REFERENCE,
        expectations=world.expectations,
    )


# ------------------------------------------------------- structural isolation


def tree() -> ast.Module:
    return ast.parse(Path(wrapper.__file__).read_text(encoding="utf-8"))


def called_names(module: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def imported_names(module: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize(
    "forbidden",
    [
        "build_cohort",
        "build_pairs",
        "build_execution_plan",
        "create_run_definition",
        "materialize",
        "canonicalise",
        "encode_canonical_png",
        "resize",
    ],
)
def test_the_wrapper_never_builds_the_inputs(forbidden):
    """Spec section 5: it loads the pair manifest; it does not produce one."""
    assert forbidden not in called_names(tree()), forbidden


@pytest.mark.parametrize(
    "forbidden",
    [
        "read_raw_result",
        "iter_raw_results",
        "build_result_set",
        "build_research_receipt",
        "build_research_finalization_marker",
        "SingleJobRunner",
        "SequentialRunExecutor",
        "run",
        "Popen",
        "check_output",
    ],
)
def test_the_wrapper_holds_no_orchestration(forbidden):
    """Spec section 22: it forwards to the engine and reads no result."""
    assert forbidden not in called_names(tree()), forbidden


@pytest.mark.parametrize(
    "forbidden", ["subprocess", "hashlib", "PIL", "fpbench.execution.runner"]
)
def test_the_wrapper_imports_nothing_that_would_run_or_hash_anything(forbidden):
    assert forbidden not in imported_names(tree()), forbidden


def test_the_wrapper_imports_no_decision_or_metric_layer():
    """Spec section 51: no DecisionSet, no EligibilitySet, no MetricSet."""
    offenders = [
        name
        for name in imported_names(tree())
        if name.startswith(
            (
                "fpbench.decisions",
                "fpbench.eligibility",
                "fpbench.metrics",
                "fpbench.paired",
                "fpbench.evaluation",
                "fpbench.derivations",
            )
        )
    ]
    assert offenders == [], offenders


def test_the_wrapper_reads_the_reference_run_through_one_function():
    """Spec section 41: identity and readiness, in one place, and no scores.

    The dependency on the first algorithm's wrapper is real and is meant to be
    one function wide. Checked over the syntax tree rather than over the text,
    because the module's own docstring explains what it does not read from the
    reference run, and a prose ban would be defeated by explaining it.
    """
    module = tree()
    mentions: set[int] = set()
    for node in ast.walk(module):
        written = ""
        if isinstance(node, ast.Import):
            written = " ".join(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            written = f"{node.module or ''} " + " ".join(
                alias.name for alias in node.names
            )
        elif isinstance(node, ast.Name):
            written = node.id
        elif isinstance(node, ast.Attribute):
            written = node.attr
        if "sourceafis" in written.lower():
            mentions.add(node.lineno)
    assert mentions, "the reference run has to be read from somewhere"

    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_reference_research_state"
    )
    outside = sorted(
        number
        for number in mentions
        if not (function.lineno <= number <= (function.end_lineno or function.lineno))
    )
    assert outside == [], f"the first algorithm is named outside one function: {outside}"

    for forbidden in ("raw_score", "read_result_set", "score", "decision"):
        assert forbidden not in called_names(tree()), forbidden


def test_the_wrapper_defines_no_command_line_entry_point():
    """Spec section 48: a convenient ``execute`` verb is how a run restarts."""
    module = tree()
    assert "argparse" not in imported_names(module)
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "main"
        for node in module.body
    )


def test_every_documented_export_exists():
    for name in (
        "build_nbis_canonical500_spec",
        "verify_nbis_canonical500_alignment",
        "prepare_nbis_canonical500_run",
        "execute_nbis_canonical500_run",
        "inspect_nbis_canonical500_experiment",
        "finalize_nbis_canonical500_run",
    ):
        assert name in wrapper.__all__
        assert callable(getattr(wrapper, name))
