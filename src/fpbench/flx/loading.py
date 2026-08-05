"""Read the published Stage 8B evidence back, strictly.

Strictly means: duplicate JSON keys are an error rather than a last-one-wins,
non-finite numbers are refused, unknown and missing fields are refused, and
every record's own fingerprint is recomputed from its claims on the way in.
A document that reconstructs is a document that still says what it said.

It also means refusing to *read* something that should never have been
published: an embedding, a raw fixture score, a machine-local absolute path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping, get_args, get_origin

from fpbench.core.flx_errors import Stage8BFinalizationError
from fpbench.core.flx_models import (
    FlxAdapterProfile,
    FlxArtifactBinding,
    FlxDependencyPin,
    FlxDeterminismReport,
    FlxGateResult,
    FlxOfflineReport,
    FlxOperationalReport,
    FlxPreprocessingProfile,
    FlxPreprocessingStep,
    FlxQualificationReport,
    FlxRepresentationBranchSpec,
    FlxRepresentationProfile,
    FlxRuntimeManifest,
    FlxRuntimeProbe,
    FlxScoreProfile,
    FlxScoreSerializationProfile,
    FlxSelfIndependenceReport,
    Stage8BFinalization,
)
from fpbench.flx.policy import load_runtime_policy
from fpbench.storage.flx_store import Stage8BEvidenceStore

__all__ = ["PublishedEvidence", "ensure_publishable", "load_document", "load_published_evidence"]

_ABSOLUTE_PATH = re.compile(
    r"(?:\b[A-Za-z]:[\\/]|\\\\|(?<!:)//[^\s/]|"
    r"(?<![A-Za-z0-9+.-])file://|"
    r"(?<![:/A-Za-z0-9._-])/(?!/)(?=$|[^\s/]))",
    re.IGNORECASE,
)
_FORBIDDEN_FIELDS = frozenset(
    {
        "checkpoint_bytes",
        "embedding_values",
        "embeddings",
        "image_bytes",
        "raw_scores",
        "representation_values",
        "scores",
        "source_code_body",
        "texture",
        "minutia",
        "values",
        "weights_bytes",
    }
)
_NESTED = {
    "dependencies": FlxDependencyPin,
    "steps": FlxPreprocessingStep,
    "branches": FlxRepresentationBranchSpec,
    "serialization": FlxScoreSerializationProfile,
    "self_independence": FlxSelfIndependenceReport,
    "determinism": FlxDeterminismReport,
    "offline": FlxOfflineReport,
    "operational": FlxOperationalReport,
    "gates": FlxGateResult,
}


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def ensure_publishable(value: Any, *, location: str = "document") -> None:
    """Refuse private payloads and machine-local paths in committed evidence."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_FIELDS:
                raise Stage8BFinalizationError(
                    f"{location}.{key} is forbidden in public Stage 8B evidence"
                )
            ensure_publishable(item, location=f"{location}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_publishable(item, location=f"{location}[{index}]")
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise Stage8BFinalizationError(f"{location} contains binary payload bytes")
    if isinstance(value, str):
        if _ABSOLUTE_PATH.search(value.strip()):
            raise Stage8BFinalizationError(
                f"{location} contains a machine-local absolute path"
            )
        return
    if value is not None and not isinstance(value, (bool, int, float)):
        raise Stage8BFinalizationError(
            f"{location} contains unsupported public value {type(value).__name__}"
        )


def _read_unique_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, ValueError) as exc:
        raise Stage8BFinalizationError(
            f"{path}: unreadable Stage 8B evidence ({exc})"
        ) from exc
    if not isinstance(value, Mapping):
        raise Stage8BFinalizationError(f"{path}: Stage 8B evidence must be a JSON object")
    return dict(value)


def _rebuild(record_type: type, payload: Mapping[str, Any], where: str) -> Any:
    if not is_dataclass(record_type):
        raise Stage8BFinalizationError(f"{where}: {record_type!r} is not a record type")
    expected = {field.name for field in fields(record_type)}
    unknown = sorted(set(payload) - expected)
    missing = sorted(expected - set(payload))
    if unknown or missing:
        raise Stage8BFinalizationError(
            f"{where}: field mismatch; unknown={unknown}, missing={missing}"
        )
    claims: dict[str, Any] = {}
    for name, value in payload.items():
        nested = _NESTED.get(name)
        if nested is not None and isinstance(value, list):
            claims[name] = tuple(
                _rebuild(nested, item, f"{where}.{name}[{index}]")
                for index, item in enumerate(value)
            )
        elif nested is not None and isinstance(value, Mapping):
            claims[name] = _rebuild(nested, value, f"{where}.{name}")
        elif isinstance(value, list):
            claims[name] = tuple(value)
        else:
            claims[name] = value
    try:
        # Constructing with the stored fingerprint re-checks it against the
        # claims, so a document whose contents were edited cannot load.
        return record_type(**claims)
    except (TypeError, ValueError) as exc:
        raise Stage8BFinalizationError(f"{where}: {exc}") from exc


def load_document(path: Path, record_type: type, what: str) -> Any:
    payload = _read_unique_json(path)
    ensure_publishable(payload, location=what)
    return _rebuild(record_type, payload, what)


@dataclass(frozen=True, slots=True)
class PublishedEvidence:
    binding: FlxArtifactBinding
    manifest: FlxRuntimeManifest
    preprocessing: FlxPreprocessingProfile
    representation: FlxRepresentationProfile
    score: FlxScoreProfile
    adapter: FlxAdapterProfile
    probe: FlxRuntimeProbe
    report: FlxQualificationReport
    policy: Any
    finalization: Stage8BFinalization | None
    stage8a_finalization_fingerprint: str

    @property
    def profile_fingerprints(self) -> Mapping[str, str]:
        return {
            "preprocessing": self.preprocessing.fingerprint,
            "representation": self.representation.fingerprint,
            "score": self.score.fingerprint,
            "adapter": self.adapter.fingerprint,
        }


def _stage8a_finalization_fingerprint(repository_root: Path) -> str:
    path = (
        Path(repository_root)
        / "evidence"
        / "stage8a-modern-matcher-selection"
        / "stage-8a-finalization.json"
    )
    payload = _read_unique_json(path)
    fingerprint = str(payload.get("fingerprint", ""))
    if len(fingerprint) != 64:
        raise Stage8BFinalizationError(
            "Stage 8B binds to the published Stage 8A finalization, which is missing "
            "or has no fingerprint"
        )
    return fingerprint


def load_published_evidence(
    store: Stage8BEvidenceStore, *, policy_config: Path, require_finalization: bool = False
) -> PublishedEvidence:
    directory = store.evidence_dir
    if not directory.is_dir():
        raise Stage8BFinalizationError(f"Stage 8B evidence directory not found: {directory}")
    expected = set(store.ALL_NAMES) if require_finalization else set(store.PREREQUISITE_NAMES)
    actual = {path.name for path in directory.iterdir()}
    extra = sorted(actual - set(store.ALL_NAMES))
    missing = sorted(expected - actual)
    if extra or missing:
        raise Stage8BFinalizationError(
            "the Stage 8B evidence tree must contain exactly the frozen publication; "
            f"missing={missing}, extra={extra}"
        )
    linked = sorted(path.name for path in directory.iterdir() if path.is_symlink())
    if linked:
        raise Stage8BFinalizationError(f"Stage 8B evidence files may not be links: {linked}")

    readme = store.readme_path.read_text(encoding="utf-8")
    ensure_publishable(readme, location="stage8b_readme")

    finalization = None
    if store.finalization_path.is_file():
        finalization = load_document(
            store.finalization_path, Stage8BFinalization, "stage8b_finalization"
        )
    return PublishedEvidence(
        binding=load_document(
            store.path(store.ARTIFACT_BINDING_NAME), FlxArtifactBinding, "artifact_binding"
        ),
        manifest=load_document(
            store.path(store.RUNTIME_MANIFEST_NAME), FlxRuntimeManifest, "runtime_manifest"
        ),
        preprocessing=load_document(
            store.path(store.PREPROCESSING_PROFILE_NAME),
            FlxPreprocessingProfile,
            "preprocessing_profile",
        ),
        representation=load_document(
            store.path(store.REPRESENTATION_PROFILE_NAME),
            FlxRepresentationProfile,
            "representation_profile",
        ),
        score=load_document(store.path(store.SCORE_PROFILE_NAME), FlxScoreProfile, "score_profile"),
        adapter=load_document(
            store.path(store.ADAPTER_PROFILE_NAME), FlxAdapterProfile, "adapter_profile"
        ),
        probe=load_document(store.path(store.RUNTIME_PROBE_NAME), FlxRuntimeProbe, "runtime_probe"),
        report=load_document(
            store.path(store.QUALIFICATION_REPORT_NAME),
            FlxQualificationReport,
            "qualification_report",
        ),
        policy=load_runtime_policy(policy_config),
        finalization=finalization,
        stage8a_finalization_fingerprint=_stage8a_finalization_fingerprint(
            store.repository_root
        ),
    )
