"""The adapter's identity, its environment report, and what it refuses to do.

The identity tests matter more than they look. ``descriptor_fingerprint`` reaches
``run_id``, so every field asserted here is a field that, if it changed silently,
would let results from two different pipelines land in the same directory.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from fpbench.adapters.registry import create_adapter, registered_adapters
from fpbench.adapters.sourceafis_java.adapter import (
    ADAPTER_ID,
    PIPELINE_METADATA,
    SourceAfisJavaAdapter,
)
from fpbench.adapters.sourceafis_java.config import (
    DEFAULT_JVM_ARGS,
    EXPECTED_BRIDGE_PROTOCOL,
    EXPECTED_SOURCEAFIS_VERSION,
    SourceAfisJavaConfig,
)
from fpbench.core.enums import EnvironmentStatus, ScoreDirection
from fpbench.core.errors import ConfigurationError
from fpbench.core.execution_models import descriptor_fingerprint

pytestmark = pytest.mark.sourceafis

ADAPTER_SOURCE_FILES = tuple(
    (Path(__file__).resolve().parents[2] / "src" / "fpbench" / "adapters" / "sourceafis_java").glob("*.py")
)


# ----------------------------------------------------------------- descriptor


def test_the_descriptor_names_the_pipeline_not_just_the_matcher():
    """docs/adr/0014: an identity describes the whole image-to-score pipeline."""
    descriptor = SourceAfisJavaAdapter().descriptor
    assert descriptor.algorithm_id == "sourceafis_java"
    assert descriptor.adapter_id == "sourceafis_java_subprocess"
    assert descriptor.display_name == "SourceAFIS for Java"
    assert descriptor.adapter_version == "1"
    assert descriptor.adapter_contract_version == "1"
    assert descriptor.implementation_version == "3.18.1"
    assert descriptor.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert descriptor.deterministic
    assert descriptor.capabilities == ()


@pytest.mark.parametrize(
    "key,value",
    [
        ("family_id", "sourceafis"),
        ("pipeline_kind", "end_to_end_image_matcher"),
        ("extractor_id", "sourceafis_java"),
        ("extractor_version", "3.18.1"),
        ("matcher_id", "sourceafis_java"),
        ("matcher_version", "3.18.1"),
        ("upstream_artifact", "com.machinezoo.sourceafis:sourceafis:3.18.1"),
        ("implementation_language", "java"),
        ("integration_mode", "subprocess_per_comparison"),
        ("bridge_protocol", "fpbench.sourceafis.bridge.v1"),
        ("input_mode", "encoded_image"),
        ("dpi_policy", "explicit_effective_ppi"),
        ("probe_side", "left"),
        ("template_cache", "disabled"),
        ("template_persistence", "disabled"),
        ("seed_usage", "ignored_algorithm_has_no_seed"),
    ],
)
def test_every_load_bearing_metadata_field_is_present(key, value):
    assert SourceAfisJavaAdapter().descriptor.metadata[key] == value


def test_both_halves_of_the_pipeline_are_named():
    """Even though they are the same implementation here, the next one will not be."""
    metadata = SourceAfisJavaAdapter().descriptor.metadata
    assert metadata["extractor_id"] and metadata["matcher_id"]
    assert metadata["extractor_version"] and metadata["matcher_version"]


def test_the_descriptor_fingerprint_is_pinned():
    """Changing it invalidates every run id already produced against SourceAFIS."""
    assert descriptor_fingerprint(SourceAfisJavaAdapter().descriptor) == (
        "5a1784faae1e82c12c374e050fcd6cfd41aa25b7a9ade3905d099df2e06a9531"
    )


@pytest.mark.parametrize(
    "key",
    [
        "integration_mode",
        "bridge_protocol",
        "dpi_policy",
        "template_cache",
        "extractor_version",
        "matcher_version",
    ],
)
def test_changing_load_bearing_metadata_changes_the_fingerprint(key):
    from dataclasses import replace

    base = SourceAfisJavaAdapter().descriptor
    changed = replace(base, metadata={**dict(base.metadata), key: "something-else"})
    assert descriptor_fingerprint(changed) != descriptor_fingerprint(base)


def test_renaming_the_display_name_does_not_change_the_fingerprint():
    from dataclasses import replace

    base = SourceAfisJavaAdapter().descriptor
    renamed = replace(base, display_name="SourceAFIS (Java port)")
    assert descriptor_fingerprint(renamed) == descriptor_fingerprint(base)


def test_no_absolute_path_reaches_the_descriptor(tmp_path):
    """Where a jar lives says nothing about the experiment."""
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig(bridge_jar=tmp_path / "elsewhere" / "bridge.jar")
    )
    rendered = repr(adapter.descriptor)
    assert str(tmp_path) not in rendered
    assert "bridge_jar" not in rendered


# ------------------------------------------------------------------- registry


def test_the_adapter_is_registered():
    assert ADAPTER_ID in registered_adapters()


def test_the_registry_creates_it():
    assert isinstance(create_adapter(ADAPTER_ID), SourceAfisJavaAdapter)


def test_registering_it_does_not_require_java():
    """Listing the registry must work on a machine with no JDK at all."""
    assert "sourceafis_java_subprocess" in registered_adapters()


def test_an_unknown_adapter_still_fails_normally():
    with pytest.raises(ConfigurationError, match="unknown adapter"):
        create_adapter("sourceafis_dotnet")


def test_unknown_configuration_keys_are_refused():
    with pytest.raises(ConfigurationError, match="unknown sourceafis_java"):
        create_adapter(ADAPTER_ID, {"threshold": 40})


def test_configuration_can_override_the_jar_and_java(tmp_path):
    adapter = create_adapter(
        ADAPTER_ID,
        {"bridge_jar": str(tmp_path / "custom.jar"), "java_executable": "java17"},
    )
    assert adapter.config.bridge_jar == tmp_path / "custom.jar"
    assert str(adapter.config.java_executable) == "java17"


def test_a_relative_jar_is_anchored_to_the_repository():
    adapter = SourceAfisJavaAdapter()
    assert adapter.config.bridge_jar.is_absolute()
    assert adapter.config.bridge_jar.name == "fpbench-sourceafis-bridge.jar"


# --------------------------------------------------------------- environment


def _stub_version_document(**overrides) -> str:
    document = {
        "schema_version": "1",
        "bridge_version": "1",
        "bridge_protocol": EXPECTED_BRIDGE_PROTOCOL,
        "sourceafis_version": EXPECTED_SOURCEAFIS_VERSION,
        "java_version": "17.0.1",
        "java_vendor": "Acme",
        "java_vm_name": "Acme VM",
        "os_name": "Linux",
        "os_arch": "amd64",
    }
    document.update(overrides)
    return json.dumps(document)


def _adapter_with_stubbed_bridge(tmp_path, monkeypatch, version_document: str):
    """An adapter whose Java calls are replaced, so version checks can be exercised."""
    jar = tmp_path / "bridge.jar"
    jar.write_bytes(b"pretend jar")
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig(bridge_jar=jar, project_root=tmp_path)
    )

    from fpbench.adapters.sourceafis_java.bridge_client import BridgeClient, JavaRuntime

    monkeypatch.setattr(
        BridgeClient,
        "resolve_java",
        lambda self: JavaRuntime(
            executable=tmp_path / "java", major=17, raw_version_output='version "17.0.1"'
        ),
    )

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=version_document, stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    return adapter


def test_a_valid_version_response_is_ready(tmp_path, monkeypatch):
    adapter = _adapter_with_stubbed_bridge(tmp_path, monkeypatch, _stub_version_document())
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.READY
    assert report.implementation_version == "3.18.1"


def test_the_jar_digest_and_size_appear_in_the_report(tmp_path, monkeypatch):
    import hashlib

    adapter = _adapter_with_stubbed_bridge(tmp_path, monkeypatch, _stub_version_document())
    report = adapter.validate_environment()
    assert report.dependencies["bridge.jar.sha256"] == hashlib.sha256(b"pretend jar").hexdigest()
    assert report.dependencies["bridge.jar.size"] == str(len(b"pretend jar"))


def test_the_jvm_args_appear_in_the_report(tmp_path, monkeypatch):
    adapter = _adapter_with_stubbed_bridge(tmp_path, monkeypatch, _stub_version_document())
    report = adapter.validate_environment()
    for arg in DEFAULT_JVM_ARGS:
        assert arg in report.dependencies["jvm.args"]


def test_the_java_runtime_appears_in_the_report(tmp_path, monkeypatch):
    adapter = _adapter_with_stubbed_bridge(tmp_path, monkeypatch, _stub_version_document())
    report = adapter.validate_environment()
    assert report.runtime["java.version"] == "17.0.1"
    assert report.runtime["java.vendor"] == "Acme"


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"bridge_protocol": "fpbench.sourceafis.bridge.v2"}, "bridge protocol"),
        ({"bridge_version": "2"}, "bridge version"),
        ({"sourceafis_version": "3.19.0"}, "SourceAFIS on the classpath"),
    ],
)
def test_a_version_mismatch_is_unavailable(tmp_path, monkeypatch, overrides, expected):
    adapter = _adapter_with_stubbed_bridge(
        tmp_path, monkeypatch, _stub_version_document(**overrides)
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert expected in report.message


def test_a_malformed_version_response_is_unavailable(tmp_path, monkeypatch):
    adapter = _adapter_with_stubbed_bridge(tmp_path, monkeypatch, "not json at all")
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "unusable version response" in report.message


def test_a_missing_jar_is_unavailable(tmp_path):
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig(bridge_jar=tmp_path / "absent.jar", project_root=tmp_path)
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE


def test_a_missing_java_is_unavailable(tmp_path):
    jar = tmp_path / "bridge.jar"
    jar.write_bytes(b"pretend jar")
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig(
            bridge_jar=jar,
            java_executable=tmp_path / "definitely-not-java",
            project_root=tmp_path,
        )
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "java" in report.message


def test_validate_environment_never_raises_for_a_missing_dependency(tmp_path):
    """A missing JVM is one run-level fault, not six thousand per-pair failures."""
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig(
            bridge_jar=tmp_path / "absent.jar",
            java_executable=tmp_path / "absent-java",
            project_root=tmp_path,
        )
    )
    assert adapter.validate_environment().status is EnvironmentStatus.UNAVAILABLE


def test_an_unavailable_message_carries_no_absolute_path(tmp_path):
    adapter = SourceAfisJavaAdapter(
        SourceAfisJavaConfig(bridge_jar=tmp_path / "absent.jar", project_root=tmp_path)
    )
    assert str(tmp_path) not in (adapter.validate_environment().message or "")


# ---------------------------------------------------------- what is forbidden


@pytest.mark.parametrize(
    "forbidden",
    [
        "is_match",
        "decide(",
        "DecisionPolicy",
        "DecisionResult",
        "apply_threshold",
        "threshold=",
        "THRESHOLD",
    ],
)
def test_no_decision_machinery_lives_in_the_adapter(forbidden):
    """SourceAFIS documents a recommended threshold of 40. It stays documentation
    until a decision policy asks for it, and it is not in this package."""
    for path in ADAPTER_SOURCE_FILES:
        source = path.read_text(encoding="utf-8")
        assert forbidden not in source, f"{path.name} contains {forbidden!r}"


def test_the_adapter_imports_no_protocol_or_evaluation_code():
    for path in ADAPTER_SOURCE_FILES:
        source = path.read_text(encoding="utf-8")
        assert "fpbench.protocols" not in source, path.name
        assert "fpbench.evaluation" not in source, path.name
        assert "fpbench.execution" not in source, path.name


def test_no_module_outside_adapters_names_this_adapter():
    """docs/adr/0007, checked mechanically.

    A prose mention is fine — ``execution/jobs.py`` uses a SourceAFIS-shaped string
    as an example of a job id that would leak too much. What must not exist is an
    import or a reference to the adapter's identifiers.
    """
    root = Path(__file__).resolve().parents[2] / "src" / "fpbench"
    offenders = []
    for path in root.rglob("*.py"):
        if path.relative_to(root).parts[:1] == ("adapters",):
            continue
        text = path.read_text(encoding="utf-8")
        if "sourceafis_java" in text or "sourceafis import" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"SourceAFIS leaked outside adapters/: {offenders}"


def test_the_result_metadata_names_no_decision():
    forbidden = {"threshold", "decision", "is_match", "ground_truth", "protocol_stage"}
    assert forbidden.isdisjoint(PIPELINE_METADATA)
