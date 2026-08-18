"""Acquire, qualify, publish, and verify Stage 20A MCC SDK v2.0 evidence.

Vendor bytes live only in fpbench's local third-party store. The repository gets
the small original C# probe, a mechanical translation contract, and derived JSON
evidence. Nothing in this module reads SD300 or any prior algorithm result.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.experiments import stage20a_mcc_contract as route
from fpbench.third_party import resolve_third_party_root

__all__ = [
    "OFFICIAL_PAGE_URL",
    "DOWNLOAD_URL",
    "ARCHIVE_NAME",
    "ARCHIVE_SIZE",
    "ARCHIVE_SHA256",
    "DLL_SHA256",
    "EVIDENCE_DIRECTORY",
    "EVIDENCE_DOCUMENTS",
    "FINALIZATION_NAME",
    "acquire_official_artifact",
    "extract_official_artifact",
    "run_qualification_probe",
    "publish_evidence",
    "verify_evidence",
    "stage20a_source_fingerprint",
]


OFFICIAL_PAGE_URL = "https://biolab.csr.unibo.it/mccsdk.html"
DOWNLOAD_URL = (
    "https://biolab.csr.unibo.it/researchPages/download/MCCSdk%20v2.0.zip"
)
ARTIFACT_STORE_PREFIX = "unibo-mcc-sdk-v2"
ARCHIVE_NAME = "MCCSdk v2.0.zip"
ARCHIVE_SIZE = 10_404_479
ARCHIVE_SHA256 = "79851f32900be641a02462a6e9ce6dad7f59963344b0394f4a1c6d26d5c021cc"
PACKAGE_DIRECTORY = "MccSdk v2.0"
DLL_RELATIVE = Path("Sdk/MccSdk.dll")
DLL_SIZE = 171_008
DLL_SHA256 = "7267ea9f2ea4c32bdeef30a49e648a516381941b531c59960517a87e5cd2eb01"

EVIDENCE_DIRECTORY = Path("evidence/stage20a-mcc-sdk-preflight")
FINALIZATION_NAME = "stage-20a-finalization.json"
EVIDENCE_DOCUMENTS = (
    "README.md",
    "artifact-identity.json",
    "license-use-record.json",
    "runtime-identity.json",
    "api-inventory.json",
    "input-route-contract.json",
    "score-contract.json",
    "runtime-smoke.json",
    FINALIZATION_NAME,
)

SOURCE_FILES = (
    "integrations/mcc-sdk-v2-probe/Program.cs",
    "integrations/mcc-sdk-v2-probe/README.md",
    "scripts/stage20a_mcc_sdk_preflight.py",
    "src/fpbench/experiments/stage20a_mcc_contract.py",
    "src/fpbench/experiments/stage20a_mcc_sdk.py",
    "tests/test_stage20a_contract.py",
    "tests/test_stage20a_evidence.py",
)

PROBE_SOURCE = Path("integrations/mcc-sdk-v2-probe/Program.cs")
PROBE_OUTPUT_NAME = "probe-output.json"
ACQUISITION_RECEIPT_NAME = "acquisition-receipt.json"


class Stage20AError(RuntimeError):
    """The official artifact or qualification record violates Stage 20A."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _store(repository_root: Path) -> Path:
    root = resolve_third_party_root(repository_root=repository_root)
    return Path(root) / ARTIFACT_STORE_PREFIX


def _archive(repository_root: Path) -> Path:
    return _store(repository_root) / ARCHIVE_NAME


def _package(repository_root: Path) -> Path:
    return _store(repository_root) / "extracted" / PACKAGE_DIRECTORY


def _probe_output(repository_root: Path) -> Path:
    return _store(repository_root) / "audit" / PROBE_OUTPUT_NAME


def _receipt(repository_root: Path) -> Path:
    return _store(repository_root) / ACQUISITION_RECEIPT_NAME


def _require_artifact(path: Path, *, size: int, sha256: str) -> None:
    if not path.is_file():
        raise Stage20AError(f"required local artifact is absent: {path.name}")
    observed_size = path.stat().st_size
    observed_hash = _sha256(path)
    if observed_size != size or observed_hash != sha256:
        raise Stage20AError(
            f"{path.name} identity mismatch: size={observed_size}, sha256={observed_hash}"
        )


def acquire_official_artifact(
    *, repository_root: Path, acquisition_utc: str | None = None
) -> Path:
    """Download the pinned archive directly from BioLab, or verify the local copy."""
    store = _store(repository_root)
    store.mkdir(parents=True, exist_ok=True)
    archive = _archive(repository_root)
    started = acquisition_utc or _utc_now()

    if not archive.exists():
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix="mcc-sdk-v2-", suffix=".zip", dir=str(store)
        )
        os.close(file_descriptor)
        temporary = Path(temporary_name)
        try:
            request = urllib.request.Request(
                DOWNLOAD_URL, headers={"User-Agent": "fpbench-stage20a/1"}
            )
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open(
                "wb"
            ) as output:
                shutil.copyfileobj(response, output)
            _require_artifact(temporary, size=ARCHIVE_SIZE, sha256=ARCHIVE_SHA256)
            temporary.replace(archive)
        finally:
            if temporary.exists():
                temporary.unlink()

    _require_artifact(archive, size=ARCHIVE_SIZE, sha256=ARCHIVE_SHA256)
    receipt_path = _receipt(repository_root)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        started = str(receipt["acquisition_utc"])
    _write_json(
        receipt_path,
        {
            "schema": "stage_20a_mcc_sdk_acquisition_receipt_v1",
            "product_name": "MCC Software Development Kit (SDK)",
            "version": "2.0",
            "download_url": DOWNLOAD_URL,
            "acquisition_utc": started,
            "archive_filename": ARCHIVE_NAME,
            "archive_size": ARCHIVE_SIZE,
            "archive_sha256": ARCHIVE_SHA256,
            "artifact_source": "OFFICIAL_AUTHOR_LAB",
        },
    )
    return archive


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise Stage20AError(f"unsafe archive member: {member.filename!r}")
        members.append(member)
    return members


def extract_official_artifact(*, repository_root: Path) -> Path:
    """Extract the official archive once, outside the repository."""
    archive_path = _archive(repository_root)
    _require_artifact(archive_path, size=ARCHIVE_SIZE, sha256=ARCHIVE_SHA256)
    destination = _store(repository_root) / "extracted"
    package = _package(repository_root)
    if package.exists():
        _require_artifact(
            package / DLL_RELATIVE, size=DLL_SIZE, sha256=DLL_SHA256
        )
        return package

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_zip_members(archive)
        archive.extractall(destination, members=members)
    _require_artifact(package / DLL_RELATIVE, size=DLL_SIZE, sha256=DLL_SHA256)
    return package


def _framework_compiler() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    candidates = (
        system_root / "Microsoft.NET/Framework64/v4.0.30319/csc.exe",
        system_root / "Microsoft.NET/Framework/v4.0.30319/csc.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise Stage20AError(".NET Framework 4.x C# compiler is not installed")


def run_qualification_probe(*, repository_root: Path) -> Path:
    """Compile and run the original Stage 20A probe in the external store."""
    package = extract_official_artifact(repository_root=repository_root)
    source = Path(repository_root) / PROBE_SOURCE
    if not source.is_file():
        raise Stage20AError(f"probe source is absent: {PROBE_SOURCE.as_posix()}")
    build = _store(repository_root) / "probe"
    build.mkdir(parents=True, exist_ok=True)
    dll = package / DLL_RELATIVE
    executable = build / "MccSdkV2Probe.exe"
    shutil.copy2(dll, build / dll.name)

    compile_run = subprocess.run(
        [
            str(_framework_compiler()),
            "/nologo",
            "/target:exe",
            "/platform:anycpu",
            "/optimize+",
            f"/reference:{dll}",
            "/reference:System.Core.dll",
            "/reference:System.Web.Extensions.dll",
            f"/out:{executable}",
            str(source),
        ],
        cwd=str(build),
        capture_output=True,
        text=True,
        check=False,
    )
    if compile_run.returncode != 0:
        raise Stage20AError(f"probe compilation failed: {compile_run.stderr.strip()}")

    smoke = subprocess.run(
        [str(executable), str(package)],
        cwd=str(build),
        capture_output=True,
        text=True,
        check=False,
    )
    if smoke.returncode != 0:
        raise Stage20AError(f"probe execution failed: {smoke.stderr.strip()}")
    try:
        record = json.loads(smoke.stdout)
    except json.JSONDecodeError as exc:
        raise Stage20AError("probe did not emit one JSON record") from exc

    _validate_probe(record)
    output = _probe_output(repository_root)
    _write_json(output, record)
    return output


def _validate_probe(record: Mapping[str, Any]) -> None:
    assembly = record.get("assembly", {})
    smoke = record.get("smoke", {})
    if assembly.get("full_name") != (
        "MccSdk, Version=2.0.0.0, Culture=neutral, "
        "PublicKeyToken=494f31afeacaf3f4"
    ):
        raise Stage20AError("probe loaded an unexpected assembly")
    if not smoke.get("all_finite") or not smoke.get("all_in_documented_range"):
        raise Stage20AError("probe did not return finite [0,1] scalar scores")
    if record.get("parameter_setters_called") is not False:
        raise Stage20AError("probe changed the SDK's native defaults")
    if record.get("sd300_used") is not False:
        raise Stage20AError("probe claims it used SD300")


def _read_probe(repository_root: Path) -> dict[str, Any]:
    path = _probe_output(repository_root)
    if not path.is_file():
        raise Stage20AError("qualification probe output is absent; run probe first")
    record = json.loads(path.read_text(encoding="utf-8"))
    _validate_probe(record)
    return record


def _receipt_record(repository_root: Path) -> dict[str, Any]:
    path = _receipt(repository_root)
    if not path.is_file():
        raise Stage20AError("acquisition receipt is absent; run acquire first")
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_files(root: Path, pattern: str) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob(pattern))


def _artifact_identity(repository_root: Path) -> dict[str, Any]:
    receipt = _receipt_record(repository_root)
    archive_path = _archive(repository_root)
    package = _package(repository_root)
    _require_artifact(archive_path, size=ARCHIVE_SIZE, sha256=ARCHIVE_SHA256)

    dlls = []
    for path in sorted(package.rglob("*.dll")):
        dlls.append(
            {
                "filename": path.relative_to(package).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    with zipfile.ZipFile(archive_path) as archive:
        members = _safe_zip_members(archive)
        files = [member for member in members if not member.is_dir()]

    documentation = []
    for name in ("MccSdk Documentation v2.0.pdf", "MccSdk License v2.0.pdf"):
        path = package / name
        documentation.append(
            {"filename": name, "size": path.stat().st_size, "sha256": _sha256(path)}
        )
    for name in ("Sdk/MccSdk.XML", "Executables/MccSdk.XML"):
        path = package / name
        documentation.append(
            {"filename": name, "size": path.stat().st_size, "sha256": _sha256(path)}
        )

    gui = package / "MccSdkSimpleApplication/MccSdkSimpleApplication.exe"
    return {
        "schema": "stage_20a_artifact_identity_v1",
        "product_name": receipt["product_name"],
        "version": receipt["version"],
        "copyright_holder": "Cappelli R., Ferrara M., Maltoni D. and Maio D.",
        "official_page_url": OFFICIAL_PAGE_URL,
        "download_url": receipt["download_url"],
        "acquisition_utc": receipt["acquisition_utc"],
        "artifact_source": "OFFICIAL_AUTHOR_LAB",
        "research_use": "ALLOWED_BY_PUBLISHED_TERMS",
        "redistribution": "NOT_ASSUMED_ALLOWED",
        "self_service_download": True,
        "additional_acquisition_gate": False,
        "archive_filename": ARCHIVE_NAME,
        "archive_size": ARCHIVE_SIZE,
        "archive_sha256": ARCHIVE_SHA256,
        "archive": {
            "filename": ARCHIVE_NAME,
            "size": ARCHIVE_SIZE,
            "sha256": ARCHIVE_SHA256,
            "entry_count": len(members),
            "file_count": len(files),
            "uncompressed_file_bytes": sum(member.file_size for member in files),
        },
        "dlls": dlls,
        "documentation": documentation,
        "included_examples": {
            "csharp_programs": _relative_files(package / "SourceCode/C#", "Program.cs"),
            "csharp_projects": _relative_files(package / "SourceCode/C#", "*.csproj"),
            "matlab_sources": _relative_files(package / "SourceCode/MATLAB", "*.m"),
            "sample_minutiae_files": len(list((package / "SampleMinutiae").glob("*.txt"))),
        },
        "included_gui": {
            "present": gui.is_file(),
            "filename": gui.relative_to(package).as_posix(),
            "size": gui.stat().st_size,
            "sha256": _sha256(gui),
            "source_included": False,
            "configuration_included": True,
            "configuration_files": _relative_files(
                package / "MccSdkSimpleApplication/Data", "*"
            ),
        },
        "included_matlab_examples": True,
        "official_artifact": True,
        "upstream_modified": False,
        "stored_outside_repository": True,
        "third_party_bytes_added_to_git": False,
    }


def _license_use_record(repository_root: Path) -> dict[str, Any]:
    package = _package(repository_root)
    license_path = package / "MccSdk License v2.0.pdf"
    return {
        "schema": "stage_20a_license_use_record_v1",
        "artifact_source": "OFFICIAL_AUTHOR_LAB",
        "research_use": "ALLOWED_BY_PUBLISHED_TERMS",
        "redistribution": "NOT_ASSUMED_ALLOWED",
        "redistributed_by_fpbench": False,
        "copyright_holder": (
            "Cappelli R., Ferrara M., Maltoni D. and Maio D."
        ),
        "copyright_year": 2015,
        "license_source": {
            "filename": license_path.name,
            "sha256": _sha256(license_path),
            "pages": 1,
        },
        "published_terms": {
            "research_purposes_only": True,
            "paper_citation_required": True,
            "citations_required": ["[1]", "[2]", "[3]", "[4]"],
            "conditional_redistribution_clause_present": True,
            "redistribution_conditions_include_notice_terms_and_disclaimer": True,
            "endorsement_by_university_or_contributors_forbidden_without_permission": True,
            "as_is_disclaimer": True,
        },
        "sample_source_header_observation": (
            "the bundled C# and MATLAB sample headers state that sample source "
            "cannot be distributed; fpbench therefore publishes no vendor source"
        ),
        "fpbench_use": "local non-commercial research qualification",
        "vendor_archive_committed": False,
        "vendor_dll_committed": False,
        "vendor_documentation_bytes_committed": False,
        "vendor_sample_bytes_committed": False,
    }


def _runtime_identity(repository_root: Path, probe: Mapping[str, Any]) -> dict[str, Any]:
    framework_release: int | None = None
    framework_version: str | None = None
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
            ) as key:
                framework_release = int(winreg.QueryValueEx(key, "Release")[0])
                framework_version = str(winreg.QueryValueEx(key, "Version")[0])
        except OSError:
            pass

    assembly = probe["assembly"]
    runtime = probe["runtime"]
    return {
        "schema": "stage_20a_runtime_identity_v1",
        "documented_requirement": ".NET Framework 4.0",
        "assembly": assembly,
        "assembly_file": {
            "filename": "Sdk/MccSdk.dll",
            "size": DLL_SIZE,
            "sha256": DLL_SHA256,
        },
        "target": {
            "clr_metadata": assembly["image_runtime_version"],
            "managed_il_only": assembly["portable_executable_kinds"] == "ILOnly",
            "required_32_bit": False,
            "any_cpu": True,
            "any_cpu_evidence": [
                "assembly PE kind is ILOnly without Required32Bit",
                "all ten bundled C# projects declare PlatformTarget AnyCPU",
            ],
        },
        "managed_dependencies": assembly["referenced_assemblies"],
        "additional_managed_dlls_in_package": [],
        "native_dll_dependencies_in_package": [],
        "qualified_environment": {
            "os": "Windows 11 x64",
            "os_build": platform.version(),
            "process_64bit": runtime["process_64bit"],
            "machine_64bit": runtime["machine_64bit"],
            "clr_version": runtime["clr_version"],
            "installed_dotnet_framework_version": framework_version,
            "installed_dotnet_framework_release": framework_release,
        },
        "windows_x64_qualified": True,
        "modern_dotnet_qualified": False,
        "linux_qualified": False,
        "linux_qualification_required": False,
        "runtime_loads": True,
    }


def _api_inventory(repository_root: Path, probe: Mapping[str, Any]) -> dict[str, Any]:
    package = _package(repository_root)
    public_api = probe["public_api"]
    mcc_type = next(
        item for item in public_api if item["full_name"] == "BioLab.Biometrics.Mcc.Sdk.MccSdk"
    )
    minutia_type = next(
        item for item in public_api if item["full_name"] == "BioLab.Biometrics.Mcc.Sdk.Minutia"
    )
    return {
        "schema": "stage_20a_api_inventory_v1",
        "audit_sources": [
            "MccSdk Documentation v2.0.pdf (all 40 pages)",
            "Sdk/MccSdk.XML",
            "reflection over Sdk/MccSdk.dll",
            "all ten bundled C# Program.cs samples",
            "all eleven bundled MATLAB samples",
            "MccSdkSimpleApplication/Data configuration",
        ],
        "exported_type_count": len(public_api),
        "exported_types": public_api,
        "mccsdk_public_method_count": len(mcc_type["methods"]),
        "minutia_struct": {
            "full_name": minutia_type["full_name"],
            "properties": minutia_type["properties"],
            "consumed_fields": ["X", "Y", "Direction"],
        },
        "raster_image_api": {
            "present": False,
            "image_to_mcc_template": False,
            "image_decoder": False,
            "minutiae_extractor": False,
            "finding": (
                "no exported template-construction method accepts Image, Bitmap, "
                "byte[], BMP, PNG, WSQ, or raster bytes; imageWidth and imageHeight "
                "are scalar metadata beside Minutia[]"
            ),
        },
        "official_minutiae_inputs": [
            {
                "kind": "IN_MEMORY",
                "api": route.TEMPLATE_API,
                "selected_for_stage20b": True,
            },
            {
                "kind": "ISO_IEC_19794_2_2011_FILE",
                "api": "CreateMccTemplateFromIsoTemplate(string filePath)",
                "selected_for_stage20b": False,
            },
            {
                "kind": "SDK_TEXT_MINUTIAE_FILE",
                "api": "CreateMccTemplateFromTextTemplate(string filePath)",
                "selected_for_stage20b": False,
            },
        ],
        "raw_match_api": route.MATCH_API,
        "variants_present": ["MCC", "P-MCC", "2P-MCC"],
        "selected_variant": "MCC",
        "native_defaults": probe["native_defaults"],
        "sample_source": {
            "csharp_programs": _relative_files(package / "SourceCode/C#", "Program.cs"),
            "matlab_sources": _relative_files(package / "SourceCode/MATLAB", "*.m"),
            "verification_example_without_parameter_setters": (
                "SourceCode/C#/MccIsoMatcher/Program.cs"
            ),
        },
        "gui": {
            "binary_present": True,
            "source_present": False,
            "configuration_present": True,
            "uses_minutiae_templates_not_raster_extraction": True,
            "optional_same-basename_images_are_display_only": True,
        },
    }


def _input_route_contract(probe: Mapping[str, Any]) -> dict[str, Any]:
    defaults = probe["native_defaults"]
    return {
        "schema": "stage_20a_input_route_contract_v1",
        "candidate": route.CANDIDATE_ID,
        "candidate_identity": route.CANDIDATE_ID,
        "shares_extractor_with_nbis": True,
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "input_route": "MINDTCT_MINUTIAE_TO_MCC",
        "route": [
            "canonical gray8 500 ppi image",
            "NBIS MINDTCT 5.0.0 with no flags",
            "mechanical XYT to MccSdk.Minutia[] representation",
            "official baseline MCC SDK v2.0 template construction",
            "official baseline MCC SDK v2.0 matching",
            "raw System.Double similarity",
        ],
        "image_extractor_in_mcc_sdk": False,
        "exact_mcc_input": {
            "api": route.TEMPLATE_API,
            "image_width": "canonical raster width (DIRECT)",
            "image_height": "canonical raster height (DIRECT)",
            "image_resolution": 500,
            "minutia_fields": ["X:System.Int32", "Y:System.Int32", "Direction:System.Double"],
        },
        "translation": {
            "x": "x_mcc = x_xyt",
            "y": "y_mcc = image_height - y_xyt",
            "direction": "direction_mcc = theta_xyt_degrees * pi / 180",
            "quality": "ignored because MccSdk.Minutia has no quality field",
            "order": "MINDTCT order preserved",
            "minutiae_count": "all MINDTCT minutiae passed; no caller limit",
        },
        "field_contract": dict(route.FIELD_CONTRACT),
        "project_choice_fields": [],
        "mindtct": {
            "version": "5.0.0",
            "contrast_boost_flag": False,
            "m1_flag": False,
            "quality_cutoff": None,
            "top_n": None,
            "image_enhancement": None,
            "crop": None,
            "resize": None,
            "rotation": None,
        },
        "stage20b_self_contract": {
            "mindtct_extractions": 2,
            "mindtct_extractions_independent": True,
            "mcc_template_constructions": 2,
            "ordinary_match_invocation": True,
            "same_path_shortcut": False,
        },
        "forbidden_route_operations": list(route.FORBIDDEN_ROUTE_OPERATIONS),
        "sdk_internal_selection": {
            "allowed_as_algorithm_behavior": True,
            "default_enroll_MinM": defaults["enroll"]["MinM"],
            "default_match_MinNP": defaults["match"]["MinNP"],
            "default_match_MaxNP": defaults["match"]["MaxNP"],
            "default_match_MaxNR": defaults["match"]["MaxNR"],
        },
        "configuration": {
            "variant": "baseline MCC",
            "selection": "SDK_OPTIMAL_DEFAULTS",
            "parameter_setters_called": False,
            "enroll": defaults["enroll"],
            "match": defaults["match"],
            "authority": (
                "manual states omitted setters use SDK optimal parameters; "
                "MccIsoMatcher verification sample omits both setters"
            ),
        },
        "sdk_image_dimension_restrictions": "NOT_DOCUMENTED",
        "sdk_fixed_dpi_requirement": "NOT_DOCUMENTED",
        "sdk_grayscale_requirement": "NOT_APPLICABLE_NO_RASTER_INPUT",
        "fpbench_preprocessing_added": False,
        "route_requires_score_affecting_fpbench_choice": False,
        "route_closed": True,
        "sd300_used_for_route_selection": False,
        "sd300_used_for_parameter_selection": False,
        "sd300_used_for_performance_selection": False,
    }


def _score_contract(probe: Mapping[str, Any]) -> dict[str, Any]:
    smoke = probe["smoke"]
    return {
        "schema": "stage_20a_score_contract_v1",
        "candidate": route.CANDIDATE_ID,
        "exact_api": route.MATCH_API,
        "native_type": "System.Double",
        "native_scalar_score": True,
        "range": {"minimum": 0.0, "maximum": 1.0, "inclusive": True},
        "direction": "HIGHER_MORE_SIMILAR",
        "direction_authority": (
            "SDK documentation and executable documentation define 0 as no "
            "similarity and 1 as maximum similarity"
        ),
        "runtime_direction_check_is_confirmation_not_selection": True,
        "calibration": "NONE",
        "fpbench_threshold": None,
        "native_decision_rule": None,
        "score_transform": "NONE",
        "hidden_threshold_required": False,
        "pair_order": {
            "checked": True,
            "symmetric": bool(
                smoke["related_exactly_symmetric"]
                and smoke["unrelated_exactly_symmetric"]
            ),
            "aggregation_of_both_orders": None,
        },
        "self": {
            "ordinary_invocation": True,
            "templates_constructed_independently": smoke[
                "self_templates_constructed_independently"
            ],
            "same_path_shortcut": False,
        },
        "zero_score": {
            "valid_similarity": True,
            "failure_sentinel": False,
            "authority": "documented inclusive [0,1] score range",
            "observed_in_smoke": smoke["zero_score_observed_as_success"],
        },
        "failure_semantics": {
            "MCC_TEMPLATE_REFUSAL": (
                "SDK throws while constructing a template from bridge-validated minutiae"
            ),
            "MCC_MATCH_REFUSAL": (
                "SDK throws while matching two successfully constructed templates"
            ),
            "MCC_RUNTIME_FAILURE": "assembly load, CLR, or process-level failure",
            "BRIDGE_FAILURE": (
                "invalid bridge payload, translation refusal, missing input, or "
                "malformed probe output"
            ),
            "score_zero": "successful scalar result, never a failure",
        },
        "observed_error_behavior": probe["failure_behavior"],
    }


def _runtime_smoke(repository_root: Path, probe: Mapping[str, Any]) -> dict[str, Any]:
    executable = _store(repository_root) / "probe/MccSdkV2Probe.exe"
    smoke = probe["smoke"]
    return {
        "schema": "stage_20a_runtime_smoke_v1",
        "status": "PASS",
        "probe_kind": "SMALL_CSHARP_QUALIFICATION_PROBE",
        "production_adapter": False,
        "probe_source": PROBE_SOURCE.as_posix(),
        "probe_source_sha256": _sha256(repository_root / PROBE_SOURCE),
        "compiled_probe_size": executable.stat().st_size,
        "compiled_probe_sha256": _sha256(executable),
        "compiled_probe_committed": False,
        "vendor_dll_committed": False,
        "sample_authority": smoke["sample_authority"],
        "sample_files": smoke["sample_files"],
        "sample_bytes_committed": False,
        "sample_template_api": smoke["sample_template_api"],
        "production_route_template_api": smoke["production_route_template_api"],
        "match_api": smoke["match_api"],
        "parameter_setters_called": False,
        "native_defaults_used": True,
        "scores": {
            "self": smoke["self"],
            "related_forward": smoke["related_forward"],
            "related_reverse": smoke["related_reverse"],
            "unrelated_forward": smoke["unrelated_forward"],
            "unrelated_reverse": smoke["unrelated_reverse"],
        },
        "all_scores_finite": smoke["all_finite"],
        "all_scores_in_documented_range": smoke["all_in_documented_range"],
        "pair_order_exactly_symmetric_on_smoke": bool(
            smoke["related_exactly_symmetric"]
            and smoke["unrelated_exactly_symmetric"]
        ),
        "self_templates_constructed_independently": smoke[
            "self_templates_constructed_independently"
        ],
        "api_executes": True,
        "scalar_exists": True,
        "hidden_threshold_required": False,
        "sd300_images_used": 0,
        "sd300_used_for_route_selection": False,
        "sd300_used_for_parameter_selection": False,
        "sd300_used_for_performance_selection": False,
        "score_values_used_to_change_route_or_configuration": False,
        "failure_behavior_observations": probe["failure_behavior"],
    }


def stage20a_source_fingerprint(repository_root: Path) -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_FILES:
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage20AError(f"Stage 20A source is absent: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_value(repository_root: Path, *args: str) -> str:
    run = subprocess.run(
        ["git", *args], cwd=str(repository_root), capture_output=True, text=True, check=False
    )
    return run.stdout.strip() if run.returncode == 0 else "unknown"


def _readme() -> str:
    return """# Stage 20A - MCC SDK v2.0 artifact, route, and score qualification

Stage 20A passes through the minutiae-only route. The official University of
Bologna MCC SDK v2.0 does **not** include a raster fingerprint extractor. Its
narrowest official baseline-MCC input is the in-memory
`CreateMccTemplate(width, height, resolution, Minutia[])` API, where a `Minutia`
contains only integer `X`, integer `Y`, and double-precision `Direction`.

The canonical route is therefore:

```text
canonical gray8 500 ppi
  -> NBIS MINDTCT 5.0.0 (no flags)
  -> mechanical XYT representation change
  -> official MCC SDK v2.0 baseline MCC, native SDK-optimal defaults
  -> raw System.Double similarity in [0,1]
```

The representation change preserves every minutia in MINDTCT order: x is direct,
y changes from bottom-left to upper-left by `image_height - y`, direction changes
units from degrees to radians, and quality is ignored because the SDK struct has
no quality field. There is no cutoff, top-N rule, sort, deduplication, crop,
resize, enhancement, rotation search, threshold, calibration, or score transform.

The runtime smoke used only three official sample-minutiae files. A fresh template
was built for every side, including SELF; both pair orders were checked; every
result was a finite native scalar. No SD300 image or prior algorithm result was
opened, and score magnitudes selected nothing.

## Four answers

1. Does MCC SDK include an image extractor? **NO**.
2. Exact input: `imageWidth`, `imageHeight`, `imageResolution`, and
   `MccSdk.Minutia[]` with `X`, `Y`, `Direction`; official ISO 19794-2:2011 and SDK
   text-file routes also exist.
3. Is there a raw native scalar similarity? **YES** - `System.Double`, `[0,1]`,
   higher means more similar.
4. Can canonical image -> MCC score be closed without choosing from SD300?
   **YES**.

Outcome: `MINDTCT_MCC_SDK_V2_ROUTE_PASS`. Stage 20B is open; no production
adapter and no 6,000-comparison run belong to this stage.
"""


def publish_evidence(*, repository_root: Path) -> Path:
    """Publish the eight derived records and final marker, never vendor bytes."""
    root = Path(repository_root)
    probe = _read_probe(root)
    evidence = root / EVIDENCE_DIRECTORY
    evidence.mkdir(parents=True, exist_ok=True)

    documents: dict[str, Any] = {
        "README.md": _readme(),
        "artifact-identity.json": _artifact_identity(root),
        "license-use-record.json": _license_use_record(root),
        "runtime-identity.json": _runtime_identity(root, probe),
        "api-inventory.json": _api_inventory(root, probe),
        "input-route-contract.json": _input_route_contract(probe),
        "score-contract.json": _score_contract(probe),
        "runtime-smoke.json": _runtime_smoke(root, probe),
    }
    for name, value in documents.items():
        path = evidence / name
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            _write_json(path, value)

    existing_marker = evidence / FINALIZATION_NAME
    created_utc = _utc_now()
    if existing_marker.is_file():
        previous = json.loads(existing_marker.read_text(encoding="utf-8"))
        created_utc = str(previous.get("created_utc", created_utc))

    evidence_hashes = {
        name: _sha256(evidence / name)
        for name in EVIDENCE_DOCUMENTS
        if name != FINALIZATION_NAME
    }
    marker: dict[str, Any] = {
        "schema": "stage_20a_finalization_v1",
        "kind": "stage_20a_finalization",
        "created_utc": created_utc,
        "outcome": route.OUTCOME,
        "blocker": None,
        "candidate": route.CANDIDATE_ID,
        "official_mcc_artifact": True,
        "upstream_modified": False,
        "extractor": "NBIS_MINDTCT_5_0_0",
        "matcher": "OFFICIAL_MCC_SDK_V2",
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "input_route": "MINDTCT_MINUTIAE_TO_MCC",
        "native_scalar_score": True,
        "score_type": "System.Double",
        "score_range": [0.0, 1.0],
        "score_direction": "HIGHER_MORE_SIMILAR",
        "route_closed": True,
        "runtime_loads": True,
        "runtime_smoke_passed": True,
        "research_use": "ALLOWED_BY_PUBLISHED_TERMS",
        "redistribution": "NOT_ASSUMED_ALLOWED",
        "calibration_performed": False,
        "threshold_selected_by_fpbench": False,
        "fpbench_threshold": None,
        "sd300_images_opened": 0,
        "sd300_parameter_selection": False,
        "sd300_route_selection": False,
        "sd300_performance_selection": False,
        "prior_algorithm_scores_consulted": False,
        "algorithm_comparison_performed": False,
        "algorithm_ranking_performed": False,
        "canonical_comparisons_executed": 0,
        "production_adapter_built": False,
        "opens_stage20b": True,
        "official_artifact_cannot_be_redistributed_by_this_repository": True,
        "third_party_bytes_added_to_git": False,
        "pass_conditions": {
            "official_mcc_sdk_v2_acquired": True,
            "research_use_terms_recorded": True,
            "runtime_loads": True,
            "deterministic_input_route_exists": True,
            "route_has_no_score_affecting_fpbench_choice": True,
            "native_raw_scalar_exists": True,
            "score_direction_established": True,
            "small_runtime_smoke_succeeds": True,
        },
        "final_answers": {
            "mcc_sdk_includes_image_extractor": "NO",
            "exact_minutiae_input": (
                "CreateMccTemplate(int imageWidth, int imageHeight, int "
                "imageResolution, Minutia[] minutiae), where Minutia is X:int, "
                "Y:int, Direction:double radians"
            ),
            "raw_native_scalar_similarity": "YES",
            "canonical_image_to_mcc_score_without_sd300_choice": "YES",
        },
        "source_commit": _git_value(root, "rev-parse", "HEAD"),
        "stage20a_source_fingerprint": stage20a_source_fingerprint(root),
        "evidence_content_hashes": evidence_hashes,
    }
    marker["stage_20a_finalization_fingerprint"] = _stable_hash(marker)
    _write_json(existing_marker, marker)
    _require_no_absolute_paths_or_vendor_bytes(evidence)
    return existing_marker


def _require_no_absolute_paths_or_vendor_bytes(evidence: Path) -> None:
    forbidden_extensions = {".dll", ".exe", ".pdf", ".zip", ".mcc", ".ist"}
    for path in evidence.iterdir():
        if path.suffix.lower() in forbidden_extensions:
            raise Stage20AError(f"vendor or binary artifact entered evidence: {path.name}")
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            if "c:\\users\\" in lowered or "/home/" in lowered:
                raise Stage20AError(f"absolute local path entered evidence: {path.name}")


def verify_evidence(*, repository_root: Path) -> dict[str, Any]:
    root = Path(repository_root)
    evidence = root / EVIDENCE_DIRECTORY
    present = sorted(path.name for path in evidence.iterdir() if path.is_file())
    missing = sorted(set(EVIDENCE_DOCUMENTS) - set(present))
    unexpected = sorted(set(present) - set(EVIDENCE_DOCUMENTS))
    if missing or unexpected:
        raise Stage20AError(f"evidence shape mismatch: missing={missing}, unexpected={unexpected}")
    _require_no_absolute_paths_or_vendor_bytes(evidence)
    marker = json.loads((evidence / FINALIZATION_NAME).read_text(encoding="utf-8"))
    for name, expected in marker["evidence_content_hashes"].items():
        if _sha256(evidence / name) != expected:
            raise Stage20AError(f"published evidence digest mismatch: {name}")
    fingerprint = marker.pop("stage_20a_finalization_fingerprint")
    if _stable_hash(marker) != fingerprint:
        raise Stage20AError("finalization fingerprint mismatch")
    if marker["stage20a_source_fingerprint"] != stage20a_source_fingerprint(root):
        raise Stage20AError("Stage 20A source fingerprint mismatch")
    return {
        "outcome": marker["outcome"],
        "candidate": marker["candidate"],
        "opens_stage20b": marker["opens_stage20b"],
        "missing_documents": missing,
        "unexpected_documents": unexpected,
    }
