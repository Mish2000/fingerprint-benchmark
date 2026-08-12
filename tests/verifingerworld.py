"""A VeriFinger route with no VeriFinger in it.

Everything Stage 11B's contract suite needs in order to exercise the real
adapter, the real bridge protocol, the real failure mapping and the real runtime
closure — on a machine with no SDK, no licence, no JVM and no network, which is
every CI runner by design (spec section 37).

Two fakes, and both are deliberately thin.

``fake_installation``
    Seventeen tiny files at the exact relative paths the closure declares, plus
    a manifest derived from them. Real digests over real bytes, so
    ``verify_installation``, the drift guard and the manifest reader are the
    genuine ones; only the contents are stand-ins.

``FakeBridgeClient``
    Answers ``version`` and ``compare`` with documents in the real wire format.
    The responses go through ``parse_version_response`` and
    ``parse_compare_response`` exactly as the real bridge's would, so a change to
    the protocol breaks these tests rather than sliding past them.

What is *not* faked is as important: the adapter, the descriptor, the metadata,
the failure mapping, the closure verification and the score contract are all the
production code.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.adapters.verifinger_java.bridge_client import BridgeClient, JavaRuntime
from fpbench.adapters.verifinger_java.config import VeriFingerJavaConfig
from fpbench.core.enums import ChecksumStatus
from fpbench.core.execution_models import ComparisonContext, PreparedImage
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure

__all__ = [
    "fake_installation",
    "fake_bridge_jar",
    "FakeBridgeClient",
    "fake_adapter",
    "version_document",
    "success_document",
    "failure_document",
    "prepared_image",
    "gray8_png",
    "job_directories",
    "comparison_context",
]


# ------------------------------------------------------------- the installation


def fake_installation(root: Path) -> tuple[Path, runtime_closure.RuntimeManifest]:
    """Seventeen stand-in files at the closure's own relative paths.

    The bytes are nonsense and the paths are exact, which is the right way round:
    what is under test is that the closure is complete and that every component
    is checked, not what a DLL contains.
    """
    installation = Path(root) / "installation"
    for index, relative in enumerate(runtime_closure.CLOSURE_PATHS):
        target = installation / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"stand-in for {relative} #{index}\n".encode("utf-8"))
    manifest = runtime_closure.build_runtime_manifest(
        installation,
        sdk_archive_sha256="0" * 64,
        platform=f"{identity.PLATFORM_OPERATING_SYSTEM}/{identity.PLATFORM_ARCHITECTURE}",
    )
    manifest_path = Path(root) / "verifinger_runtime_manifest_v1.json"
    manifest_path.write_text(
        json.dumps(manifest.as_document(), indent=2) + "\n", encoding="utf-8"
    )
    return installation, manifest


def fake_bridge_jar(root: Path) -> Path:
    """A file where the bridge jar goes. Its digest is what pins it."""
    jar = Path(root) / "fpbench-verifinger-bridge.jar"
    jar.write_bytes(b"PK\x03\x04stand-in bridge jar\n")
    return jar


# ------------------------------------------------------------------ the bridge


def version_document(**overrides: Any) -> dict[str, Any]:
    """A well-formed ``version`` response, in the real wire format."""
    document: dict[str, Any] = {
        "schema_version": "1",
        "bridge_protocol": identity.BRIDGE_PROTOCOL,
        "bridge_version": identity.BRIDGE_VERSION,
        "licences_requested": "FingerMatcher,FingerExtractor",
        "licences_obtained": True,
        "licence_detail": "",
        "runtime_started": True,
        "loaded_modules": [
            {
                "name": name.removesuffix(".dll"),
                "product": "Neurotechnology",
                "company": "Neurotechnology",
                "version": f"{identity.IMPLEMENTATION_VERSION}.0.0",
                "file_name": name,
            }
            for name in runtime_closure.NATIVE_LIBRARY_NAMES
        ],
        "delivered_runtime_defaults": dict(identity.EXPECTED_RUNTIME_DEFAULTS),
        "configured_settings": dict(identity.CONFIGURED_SETTINGS),
        "java_version": "17.0.18",
        "java_vendor": "Azul Systems, Inc.",
        "java_vm_name": "OpenJDK 64-Bit Server VM",
        "os_name": "Windows 11",
        "os_arch": "amd64",
        "required_ppi": identity.REQUIRED_EFFECTIVE_PPI,
    }
    document.update(overrides)
    return document


def success_document(
    request_id: str, score: int = 137, engine_status: str = "OK", **overrides: Any
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1",
        "bridge_protocol": identity.BRIDGE_PROTOCOL,
        "bridge_version": identity.BRIDGE_VERSION,
        "request_id": request_id,
        "status": "success",
        "score": score,
        "score_direction": "HIGHER_IS_BETTER",
        "native_score_type": "java_int",
        "engine_status": engine_status,
        "extraction_count": 2,
        "left_image_ppi": "500x500",
        "right_image_ppi": "500x500",
        "timings_ms": {"bridge_total": 1500.0, "verify": 1200.0},
    }
    document.update(overrides)
    return document


def failure_document(
    request_id: str, code: str = "extraction_failed", **overrides: Any
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1",
        "bridge_protocol": identity.BRIDGE_PROTOCOL,
        "bridge_version": identity.BRIDGE_VERSION,
        "request_id": request_id,
        "status": "failure",
        "code": code,
        "stage": "verify",
        "message": f"the engine reported {code}",
        "engine_status": "BAD_OBJECT",
        "timings_ms": {"bridge_total": 1400.0},
    }
    document.update(overrides)
    return document


@dataclass
class FakeBridgeClient(BridgeClient):
    """A bridge that answers in the real wire format and starts no process."""

    def __init__(
        self,
        config: VeriFingerJavaConfig,
        *,
        version_payload: Mapping[str, Any] | None = None,
        responder=None,
    ) -> None:
        super().__init__(config)
        self._version_payload = dict(version_payload or version_document())
        self._responder = responder or (lambda request_id, left, right: success_document(request_id))
        self.calls: list[dict[str, Any]] = []

    def resolve_java(self) -> JavaRuntime:  # type: ignore[override]
        return JavaRuntime(
            executable=Path("java"), major=identity.MINIMUM_JAVA_MAJOR, raw_version_output="17"
        )

    def version(self, java, jar, installation):  # type: ignore[override]
        from fpbench.adapters.verifinger_java.bridge_models import parse_version_response

        return parse_version_response(json.dumps(self._version_payload))

    def compare(self, **kwargs):  # type: ignore[override]
        from fpbench.adapters.verifinger_java.bridge_models import (
            build_compare_request,
            parse_compare_response,
        )

        # The real request builder, so a forbidden field or a wrong resolution
        # is refused here exactly as it would be against the real bridge.
        request = build_compare_request(
            request_id=kwargs["request_id"],
            left_path=kwargs["left_path"],
            left_effective_ppi=kwargs["left_effective_ppi"],
            right_path=kwargs["right_path"],
            right_effective_ppi=kwargs["right_effective_ppi"],
        )
        self.calls.append(json.loads(request))
        document = self._responder(
            kwargs["request_id"], kwargs["left_path"], kwargs["right_path"]
        )
        return parse_compare_response(
            json.dumps(document), expected_request_id=kwargs["request_id"]
        )


def fake_adapter(
    root: Path,
    *,
    version_payload: Mapping[str, Any] | None = None,
    responder=None,
    research_mode: bool = False,
    **config_overrides: Any,
):
    """The production adapter, with only the subprocess replaced."""
    from fpbench.adapters.verifinger_java.adapter import VeriFingerJavaAdapter

    installation, _ = fake_installation(root)
    jar = fake_bridge_jar(root)
    config = VeriFingerJavaConfig(
        bridge_jar=jar,
        runtime_manifest=Path(root) / "verifinger_runtime_manifest_v1.json",
        runtime_policy=Path("configs/verifinger/stage11b_verifinger_runtime_policy_v1.yaml"),
        installation=installation,
        research_mode=research_mode,
        **config_overrides,
    )
    adapter = VeriFingerJavaAdapter(config)
    adapter._client = FakeBridgeClient(
        config, version_payload=version_payload, responder=responder
    )
    return adapter


# ------------------------------------------------------------------- fixtures


def gray8_png(seed: int, width: int = 64, height: int = 64) -> bytes:
    """A real, decodable 500 ppi greyscale PNG. Not a fingerprint."""
    rows = []
    for y in range(height):
        row = bytes(((x * 7 + y * 13 + seed * 29) % 256) for x in range(width))
        rows.append(b"\x00" + row)
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    per_metre = int(round(identity.REQUIRED_EFFECTIVE_PPI * 39.3701))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"pHYs", struct.pack(">IIB", per_metre, per_metre, 1))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def prepared_image(
    path: Path, payload: bytes, *, image_id: str, effective_ppi: int | None = None
) -> PreparedImage:
    import hashlib

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return PreparedImage(
        image_id=image_id,
        local_path=target.resolve(),
        effective_ppi=effective_ppi or identity.REQUIRED_EFFECTIVE_PPI,
        media_type="image/png",
        expected_sha256=digest,
        checksum_status=ChecksumStatus.VERIFIED,
        preparation_profile_id="canonical_gray8_500ppi_lanczos3_v1",
        preparation_hash=hashlib.sha256(b"verifingerworld").hexdigest(),
    )


def job_directories(root: Path) -> tuple[Path, Path]:
    working = Path(root) / "work"
    artifacts = Path(root) / "artifacts"
    working.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    return working, artifacts


def comparison_context(
    working: Path, artifacts: Path, *, job_id: str = "5b0000000000b001"
) -> ComparisonContext:
    return ComparisonContext(
        run_id="run_verifingerfake",
        job_id=job_id,
        attempt=1,
        working_directory=Path(working).resolve(),
        artifact_directory=Path(artifacts).resolve(),
        timeout_seconds=180.0,
        deterministic_seed=0,
    )
