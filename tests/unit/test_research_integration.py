"""The one seam, and what it refuses.

Everything algorithm-specific about a research run now arrives through a
``ResearchAdapterIntegration``. That makes the record's own checks load-bearing:
a mis-declared role, a primary asset that is not in the list, a development build
that is a different algorithm from the pinned one — each of them would otherwise
surface as a run whose manifest and results disagree (spec sections 11 to 15).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.core.errors import ConfigurationError, ResearchPreflightError
from fpbench.core.identifiers import InvalidIdentifierError
from fpbench.core.runtime_models import RuntimeBundleDefinition
from fpbench.experiments.research_integration import (
    AlgorithmValidationReport,
    DevelopmentAdapterRuntime,
    ResearchAdapterIntegration,
)
from fakes import CountingAdapter, fake_descriptor
from runworld import research_provenance

pytestmark = pytest.mark.adapter_contract


@pytest.fixture
def asset(tmp_path: Path) -> Path:
    path = tmp_path / "tool.bin"
    path.write_bytes(b"tool bytes")
    return path


def integration(**overrides) -> ResearchAdapterIntegration:
    settings: dict[str, object] = {
        "integration_id": "example_research_v1",
        "adapter_id": "counting_adapter",
        "runtime_asset_roles": ("tool_extractor",),
        "primary_runtime_asset_role": "tool_extractor",
        "create_development_runtime": lambda *_: None,
        "create_research_delegate": lambda *_: None,
        "validate_result_set": lambda _: None,
    }
    settings.update(overrides)
    return ResearchAdapterIntegration(**settings)  # type: ignore[arg-type]


# ---------------------------------------------------- the integration record


def test_a_well_formed_integration_is_accepted():
    record = integration()
    assert record.roles == {"tool_extractor"}


def test_an_integration_must_declare_at_least_one_runtime_asset():
    with pytest.raises(ConfigurationError, match="declares no runtime assets"):
        integration(runtime_asset_roles=(), primary_runtime_asset_role="x")


def test_a_duplicate_role_is_refused():
    with pytest.raises(ConfigurationError, match="duplicate runtime"):
        integration(runtime_asset_roles=("tool_a", "tool_a"),
                    primary_runtime_asset_role="tool_a")


def test_the_primary_role_must_be_one_of_the_declared_roles():
    with pytest.raises(ConfigurationError, match="primary runtime asset"):
        integration(
            runtime_asset_roles=("tool_a", "tool_b"),
            primary_runtime_asset_role="tool_c",
        )


def test_identifiers_must_be_well_formed():
    with pytest.raises(InvalidIdentifierError):
        integration(integration_id="Not An Id")
    with pytest.raises(InvalidIdentifierError):
        integration(runtime_asset_roles=("Not A Role",),
                    primary_runtime_asset_role="Not A Role")


def test_the_three_hooks_must_be_callable():
    with pytest.raises(ConfigurationError, match="callable"):
        integration(validate_result_set="not a function")


def test_the_record_is_immutable():
    record = integration()
    with pytest.raises(Exception):
        record.adapter_id = "something_else"  # type: ignore[misc]


# ------------------------------------------------------ the development build


def test_a_development_runtime_resolves_and_freezes_its_assets(asset):
    runtime = DevelopmentAdapterRuntime(
        adapter=CountingAdapter(), assets={"tool_extractor": asset}
    )
    assert runtime.roles == {"tool_extractor"}
    with pytest.raises(TypeError):
        runtime.assets["tool_extractor"] = asset  # type: ignore[index]


def test_a_development_runtime_with_no_assets_is_refused():
    with pytest.raises(ConfigurationError, match="at least one file"):
        DevelopmentAdapterRuntime(adapter=CountingAdapter(), assets={})


def test_a_relative_asset_path_is_refused():
    with pytest.raises(ConfigurationError, match="absolute path"):
        DevelopmentAdapterRuntime(
            adapter=CountingAdapter(), assets={"tool_extractor": Path("tool.bin")}
        )


def test_a_missing_asset_is_refused(tmp_path):
    with pytest.raises(ConfigurationError, match="not a regular file"):
        DevelopmentAdapterRuntime(
            adapter=CountingAdapter(),
            assets={"tool_extractor": tmp_path / "absent.bin"},
        )


def test_a_symlinked_asset_is_refused(tmp_path, asset):
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(asset)
    except (OSError, NotImplementedError):  # pragma: no cover - needs privilege
        pytest.skip("this platform will not create symlinks without privileges")
    with pytest.raises(ConfigurationError, match="symlink"):
        DevelopmentAdapterRuntime(
            adapter=CountingAdapter(), assets={"tool_extractor": link}
        )


def test_two_roles_cannot_name_the_same_file(asset):
    with pytest.raises(ConfigurationError, match="same file"):
        DevelopmentAdapterRuntime(
            adapter=CountingAdapter(),
            assets={"tool_extractor": asset, "tool_matcher": asset},
        )


def test_the_declared_roles_must_match_what_the_build_produced(asset):
    runtime = DevelopmentAdapterRuntime(
        adapter=CountingAdapter(), assets={"tool_extractor": asset}
    )
    with pytest.raises(ResearchPreflightError, match="missing=\\['tool_matcher'\\]"):
        integration(
            runtime_asset_roles=("tool_extractor", "tool_matcher"),
            primary_runtime_asset_role="tool_extractor",
        ).require_development_runtime(runtime)


def test_the_build_must_be_the_algorithm_the_integration_claims(asset):
    runtime = DevelopmentAdapterRuntime(
        adapter=CountingAdapter(), assets={"tool_extractor": asset}
    )
    with pytest.raises(ResearchPreflightError, match="development runtime built"):
        integration(adapter_id="other_adapter").require_development_runtime(runtime)


# -------------------------------------------------------------- the bundle


def bundle_with(*roles: str) -> RuntimeBundleDefinition:
    from fpbench.core.runtime_models import RuntimeAssetDefinition

    import hashlib

    assets = [
        RuntimeAssetDefinition.create(
            role=role,
            filename=f"{role}.bin",
            sha256=hashlib.sha256(role.encode()).hexdigest(),
            size_bytes=10,
            media_type="application/octet-stream",
        )
        for role in roles
    ]
    return RuntimeBundleDefinition.create(
        adapter_id="counting_adapter",
        materialization_policy="content_addressed_copy_v1",
        assets=assets,
        created_utc="2026-07-30T00:00:00+00:00",
    )


def test_a_bundle_with_the_declared_roles_is_accepted():
    integration().require_bundle_matches(bundle_with("tool_extractor"))


def test_a_bundle_missing_a_role_is_refused():
    with pytest.raises(ResearchPreflightError, match="missing="):
        integration(
            runtime_asset_roles=("tool_extractor", "tool_matcher"),
            primary_runtime_asset_role="tool_extractor",
        ).require_bundle_matches(bundle_with("tool_extractor"))


def test_a_bundle_with_an_extra_role_is_refused():
    with pytest.raises(ResearchPreflightError, match="extra="):
        integration().require_bundle_matches(
            bundle_with("tool_extractor", "tool_matcher")
        )


def test_a_bundle_belonging_to_another_adapter_is_refused():
    with pytest.raises(ResearchPreflightError, match="belongs to adapter"):
        integration(adapter_id="dummy_sha256").require_bundle_matches(
            bundle_with("tool_extractor")
        )


# -------------------------------------------- development against research


class _Descriptive(CountingAdapter):
    def __init__(self, descriptor) -> None:
        super().__init__()
        self._fixed = descriptor

    @property
    def descriptor(self):
        return self._fixed


def test_two_adapters_describing_the_same_algorithm_are_accepted():
    descriptor = fake_descriptor("counting_adapter")
    integration().require_same_algorithm(
        development=_Descriptive(descriptor), research=_Descriptive(descriptor)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("implementation_version", "test-2"),
        ("adapter_version", "2"),
        ("algorithm_id", "another_algorithm"),
    ],
)
def test_pinning_may_not_change_what_the_algorithm_is(field, value):
    """Materialising a bundle moves bytes, not identity (spec section 15)."""
    descriptor = fake_descriptor("counting_adapter")
    drifted = replace(descriptor, **{field: value})
    with pytest.raises(ResearchPreflightError):
        integration().require_same_algorithm(
            development=_Descriptive(descriptor), research=_Descriptive(drifted)
        )


def test_a_metadata_only_difference_is_still_a_different_algorithm():
    """It changes the fingerprint, so it changes what results mean."""
    descriptor = fake_descriptor("counting_adapter")
    drifted = replace(descriptor, metadata={"template_cache": "enabled"})
    with pytest.raises(ResearchPreflightError, match="fingerprint differently"):
        integration().require_same_algorithm(
            development=_Descriptive(descriptor), research=_Descriptive(drifted)
        )


# ----------------------------------------------------- the validator contract


def test_the_sourceafis_report_satisfies_the_generic_contract():
    """``SourceAfisValidationReport`` must fit without changing identity."""
    from fpbench.experiments.sourceafis_validation import SourceAfisValidationReport

    report = SourceAfisValidationReport(
        run_id="run_0123456789ab",
        plan_id="plan_0123456789ab",
        total_results=3,
        successful_results=3,
        algorithmic_failures=0,
        blocking_failures=0,
        failure_counts={},
        issues=(),
        validation_fingerprint="a" * 64,
        inspected_utc="2026-07-30T00:00:00+00:00",
    )
    assert isinstance(report, AlgorithmValidationReport)
    assert report.is_clean
    assert report.errors == ()


def test_something_missing_a_member_does_not_satisfy_it():
    from types import SimpleNamespace

    assert not isinstance(SimpleNamespace(run_id="x"), AlgorithmValidationReport)


def test_a_validation_context_carries_no_threshold():
    from fpbench.experiments.research_integration import ResearchValidationContext

    forbidden = {"threshold", "decision_profile", "ground_truth"}
    assert forbidden.isdisjoint(ResearchValidationContext.__dataclass_fields__)


def test_provenance_helper_is_importable_for_integration_authors():
    """A smoke check that the test's own provenance helper still lines up."""
    assert research_provenance().source_tree_clean
