"""How the bridge is invoked, and how strictly its answers are read.

Almost all of this runs without Java: the wire format is validated in Python, and the
subprocess call is inspected rather than performed. That keeps the strict-parsing
rules — the ones that stand between SourceAFIS and a stored research result — under
test on any machine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fpbench.adapters.sourceafis_java.bridge_client import (
    MINIMUM_JAVA_MAJOR,
    BridgeClient,
    BridgeProcessError,
    BridgeUnavailable,
    JavaRuntime,
)
from fpbench.adapters.sourceafis_java.bridge_models import (
    BridgeContractViolation,
    build_compare_request,
    parse_compare_response,
    parse_version_response,
)
from fpbench.adapters.sourceafis_java.config import SourceAfisJavaConfig

pytestmark = pytest.mark.sourceafis

REQUEST_ID = "job_0123456789abcdef"


def client(tmp_path: Path, **overrides) -> BridgeClient:
    settings = dict(bridge_jar=tmp_path / "bridge.jar", project_root=tmp_path)
    settings.update(overrides)
    return BridgeClient(SourceAfisJavaConfig(**settings))


def java_runtime(tmp_path: Path) -> JavaRuntime:
    return JavaRuntime(
        executable=tmp_path / "java", major=17, raw_version_output='version "17.0.1"'
    )


def success_response(**overrides) -> str:
    import json

    document = {
        "schema_version": "1",
        "request_id": REQUEST_ID,
        "status": "success",
        "score": 42.5,
        "sourceafis_version": "3.18.1",
        "bridge_version": "1",
        "extraction_count": 2,
        "timings_ms": {"bridge_total": 40.2, "matching": 0.3},
    }
    document.update(overrides)
    return json.dumps(document)


def failure_response(**overrides) -> str:
    import json

    document = {
        "schema_version": "1",
        "request_id": REQUEST_ID,
        "status": "failure",
        "code": "image_decode_failed",
        "stage": "left_extraction",
        "side": "left",
        "message": "Input image could not be decoded",
        "exception_type": "IllegalArgumentException",
        "sourceafis_version": "3.18.1",
        "bridge_version": "1",
        "timings_ms": {"bridge_total": 1.8},
    }
    document.update(overrides)
    return json.dumps(document)


def parse(payload: str):
    return parse_compare_response(
        payload,
        expected_request_id=REQUEST_ID,
        expected_sourceafis_version="3.18.1",
        expected_bridge_version="1",
    )


# ------------------------------------------------------------------- request


def test_the_request_carries_only_paths_and_resolutions(tmp_path):
    import json

    payload = json.loads(
        build_compare_request(
            request_id=REQUEST_ID,
            left_path=tmp_path / "a.png",
            left_dpi=500,
            right_path=tmp_path / "b.png",
            right_dpi=1000,
        )
    )
    assert set(payload) == {"schema_version", "request_id", "left", "right"}
    assert set(payload["left"]) == {"path", "dpi"}
    forbidden = {"pair_id", "subject", "finger", "protocol_stage", "ground_truth", "threshold"}
    assert forbidden.isdisjoint(payload)


def test_the_two_resolutions_are_forwarded_unchanged(tmp_path):
    import json

    payload = json.loads(
        build_compare_request(
            request_id=REQUEST_ID,
            left_path=tmp_path / "a.png",
            left_dpi=2000,
            right_path=tmp_path / "b.png",
            right_dpi=500,
        )
    )
    assert payload["left"]["dpi"] == 2000
    assert payload["right"]["dpi"] == 500


def test_left_and_right_keep_their_order(tmp_path):
    import json

    payload = json.loads(
        build_compare_request(
            request_id=REQUEST_ID,
            left_path=tmp_path / "probe.png",
            left_dpi=500,
            right_path=tmp_path / "candidate.png",
            right_dpi=500,
        )
    )
    assert payload["left"]["path"].endswith("probe.png")
    assert payload["right"]["path"].endswith("candidate.png")


def test_a_relative_path_is_refused(tmp_path):
    with pytest.raises(BridgeContractViolation, match="absolute"):
        build_compare_request(
            request_id=REQUEST_ID,
            left_path=Path("a.png"),
            left_dpi=500,
            right_path=tmp_path / "b.png",
            right_dpi=500,
        )


@pytest.mark.parametrize("dpi", [0, -500, 500.5])
def test_an_unusable_dpi_is_refused(tmp_path, dpi):
    with pytest.raises(BridgeContractViolation, match="dpi"):
        build_compare_request(
            request_id=REQUEST_ID,
            left_path=tmp_path / "a.png",
            left_dpi=dpi,
            right_path=tmp_path / "b.png",
            right_dpi=500,
        )


# ------------------------------------------------------------------ responses


def test_a_valid_success_response_parses():
    result = parse(success_response())
    assert result.succeeded
    assert result.score == 42.5
    assert result.extraction_count == 2
    assert result.timings_ms["bridge_total"] == 40.2


def test_a_valid_failure_response_parses():
    result = parse(failure_response())
    assert not result.succeeded
    assert result.code == "image_decode_failed"
    assert result.side == "left"
    assert result.score is None


@pytest.mark.parametrize(
    "payload,expected",
    [
        pytest.param("", "no output", id="empty"),
        pytest.param("   ", "no output", id="blank"),
        pytest.param("{not json", "single JSON document", id="malformed"),
        pytest.param('{"a":1}{"b":2}', "single JSON document", id="two documents"),
        pytest.param("[1,2,3]", "JSON object", id="not an object"),
    ],
)
def test_unusable_output_is_a_contract_violation(payload, expected):
    with pytest.raises(BridgeContractViolation, match=expected):
        parse(payload)


def test_an_unknown_schema_version_is_refused():
    with pytest.raises(BridgeContractViolation, match="schema_version"):
        parse(success_response(schema_version="99"))


def test_an_unknown_status_is_refused():
    with pytest.raises(BridgeContractViolation, match="unknown status"):
        parse(success_response(status="maybe"))


def test_a_mismatched_request_id_is_refused():
    """A response from another job would attach its score to the wrong result."""
    with pytest.raises(BridgeContractViolation, match="request_id"):
        parse(success_response(request_id="job_ffffffffffffffff"))


def test_a_wrong_sourceafis_version_is_refused():
    with pytest.raises(BridgeContractViolation, match="SourceAFIS reported"):
        parse(success_response(sourceafis_version="3.19.0"))


def test_a_wrong_bridge_version_is_refused():
    with pytest.raises(BridgeContractViolation, match="bridge reported version"):
        parse(success_response(bridge_version="2"))


def test_a_success_without_a_score_is_refused():
    document = success_response()
    with pytest.raises(BridgeContractViolation, match="score"):
        parse(document.replace('"score": 42.5', '"score": null'))


@pytest.mark.parametrize("score", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_score_is_refused(score):
    with pytest.raises(BridgeContractViolation, match="finite"):
        parse(success_response().replace("42.5", score))


def test_a_negative_score_is_refused():
    """SourceAFIS documents a non-negative similarity; anything else breaks the
    score-direction promise recorded with every result."""
    with pytest.raises(BridgeContractViolation, match="negative"):
        parse(success_response(score=-1.0))


@pytest.mark.parametrize(
    "count",
    [
        pytest.param(0, id="zero"),
        pytest.param(1, id="one"),
        pytest.param(3, id="three"),
        pytest.param(2.5, id="float"),
        pytest.param("2", id="string"),
        pytest.param(True, id="boolean"),
        pytest.param(None, id="null"),
    ],
)
def test_only_the_json_integer_two_is_a_valid_extraction_count(count):
    """Two independent extractions is an exact wire-level guarantee."""
    with pytest.raises(BridgeContractViolation, match="extraction_count"):
        parse(success_response(extraction_count=count))


def test_a_success_without_the_total_timing_is_refused():
    with pytest.raises(BridgeContractViolation, match="bridge_total"):
        parse(success_response(timings_ms={"matching": 1.0}))


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("code", "matching_failed", id="code"),
        pytest.param("stage", "matching", id="stage"),
        pytest.param("side", "left", id="side"),
        pytest.param("message", "failure", id="message"),
        pytest.param("exception_type", "RuntimeException", id="exception-type"),
    ],
)
def test_a_success_carrying_a_failure_field_is_refused(field, value):
    with pytest.raises(BridgeContractViolation, match=field):
        parse(success_response(**{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        pytest.param("score", 1.0, id="score"),
        pytest.param("score", None, id="null-score"),
        pytest.param("extraction_count", 2, id="extraction-count"),
        pytest.param("extraction_count", None, id="null-extraction-count"),
    ],
)
def test_a_failure_carrying_a_success_field_is_refused(field, value):
    with pytest.raises(BridgeContractViolation, match=field):
        parse(failure_response(**{field: value}))


def test_a_failure_without_a_code_is_refused():
    document = failure_response()
    with pytest.raises(BridgeContractViolation, match="code"):
        parse(document.replace('"code": "image_decode_failed"', '"code": null'))


@pytest.mark.parametrize("value", [-1.0, "NaN", "Infinity"])
def test_an_unusable_timing_is_refused(value):
    payload = success_response().replace("40.2", str(value))
    with pytest.raises(BridgeContractViolation):
        parse(payload)


def test_a_version_response_parses():
    import json

    info = parse_version_response(
        json.dumps(
            {
                "schema_version": "1",
                "bridge_version": "1",
                "bridge_protocol": "fpbench.sourceafis.bridge.v1",
                "sourceafis_version": "3.18.1",
                "java_version": "17.0.1",
                "java_vendor": "Acme",
            }
        )
    )
    assert info.sourceafis_version == "3.18.1"
    assert info.bridge_protocol == "fpbench.sourceafis.bridge.v1"


def test_a_version_response_missing_a_field_is_refused():
    import json

    with pytest.raises(BridgeContractViolation, match="bridge_protocol"):
        parse_version_response(
            json.dumps(
                {
                    "schema_version": "1",
                    "bridge_version": "1",
                    "sourceafis_version": "3.18.1",
                }
            )
        )


# ------------------------------------------------------------------ invocation


def test_the_command_line_is_a_list_with_the_pinned_jvm_args(tmp_path):
    bridge = client(tmp_path)
    argv = bridge.argv(java_runtime(tmp_path), tmp_path / "bridge.jar", "compare")
    assert isinstance(argv, list)
    assert argv[-2:] == [str(tmp_path / "bridge.jar"), "compare"]
    assert "-Djava.awt.headless=true" in argv
    assert "-Xmx2g" in argv


def test_no_invocation_ever_uses_a_shell():
    """A path containing a space or a quote must never become a command."""
    source = Path(
        __import__("fpbench.adapters.sourceafis_java.bridge_client", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    assert "shell=True" not in source


@pytest.mark.parametrize("variable", ["JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"])
def test_ambient_jvm_options_are_stripped(tmp_path, monkeypatch, variable):
    """A heap size arriving from the shell would make the run unreproducible."""
    monkeypatch.setenv(variable, "-Xmx1m")
    assert variable not in client(tmp_path).sanitised_env()


def test_a_missing_jar_reports_unavailable_with_a_hint(tmp_path):
    with pytest.raises(BridgeUnavailable, match="has not been built"):
        client(tmp_path).resolve_jar()


def test_a_directory_instead_of_a_jar_is_refused(tmp_path):
    (tmp_path / "bridge.jar").mkdir()
    with pytest.raises(BridgeUnavailable, match="not a file"):
        client(tmp_path).resolve_jar()


def test_a_missing_java_reports_unavailable(tmp_path):
    bridge = client(tmp_path, java_executable=tmp_path / "definitely-not-java")
    with pytest.raises(BridgeUnavailable, match="not found"):
        bridge.resolve_java()


def test_the_jar_digest_and_size_are_reported(tmp_path):
    import hashlib

    jar = tmp_path / "bridge.jar"
    jar.write_bytes(b"pretend jar contents")
    digest, size = client(tmp_path).jar_digest(jar)
    assert digest == hashlib.sha256(b"pretend jar contents").hexdigest()
    assert size == len(b"pretend jar contents")


def test_a_timeout_becomes_the_builtin_timeout_error(tmp_path, monkeypatch):
    """So the runner's existing taxonomy records FailureCode.TIMEOUT."""

    def explode(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["java"], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(subprocess, "run", explode)
    bridge = client(tmp_path)
    with pytest.raises(TimeoutError, match="budget"):
        bridge.compare(
            java=java_runtime(tmp_path),
            jar=tmp_path / "bridge.jar",
            request_id=REQUEST_ID,
            left_path=tmp_path / "a.png",
            left_dpi=500,
            right_path=tmp_path / "b.png",
            right_dpi=500,
            working_directory=tmp_path,
            timeout_seconds=0.01,
        )


def test_a_non_zero_exit_raises_a_process_error(tmp_path, monkeypatch):
    def crash(*args, **kwargs):
        return subprocess.CompletedProcess(args=["java"], returncode=70, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", crash)
    with pytest.raises(BridgeProcessError) as raised:
        client(tmp_path).compare(
            java=java_runtime(tmp_path),
            jar=tmp_path / "bridge.jar",
            request_id=REQUEST_ID,
            left_path=tmp_path / "a.png",
            left_dpi=500,
            right_path=tmp_path / "b.png",
            right_dpi=500,
            working_directory=tmp_path,
            timeout_seconds=60.0,
        )
    assert raised.value.exit_code == 70
    assert raised.value.stderr == "boom"


def test_the_job_directory_is_the_working_directory(tmp_path, monkeypatch):
    captured = {}

    def record(argv, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=success_response(), stderr="")

    monkeypatch.setattr(subprocess, "run", record)
    work = tmp_path / "work"
    work.mkdir()
    client(tmp_path).compare(
        java=java_runtime(tmp_path),
        jar=tmp_path / "bridge.jar",
        request_id=REQUEST_ID,
        left_path=tmp_path / "a.png",
        left_dpi=500,
        right_path=tmp_path / "b.png",
        right_dpi=500,
        working_directory=work,
        timeout_seconds=60.0,
    )
    assert captured["cwd"] == str(work)
    assert captured["shell"] is False
    assert captured["check"] is False


def test_the_minimum_java_version_is_the_project_reference():
    assert MINIMUM_JAVA_MAJOR == 17
