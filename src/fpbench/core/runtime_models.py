"""The executable a run was actually carried out by, identified by its bytes.

An environment fingerprint that names a *path* to a jar proves nothing: the
path can be rebuilt under the run's feet and every subsequent comparison would
be produced by different code while claiming the old identity. So the bytes are
copied once into an immutable, content-addressed bundle, and everything
downstream refers to the copy (docs/adr/0018).

Three records, in decreasing generality:

``RuntimeAssetDefinition``
    One file: its digest, its size, its media type and where it sits inside the
    bundle. Never where it came from — a build directory on one machine is not
    part of the experiment.

``RuntimeBundleDefinition``
    An adapter's complete set of assets under one materialisation policy, with
    a fingerprint over their contents. Two builds that produce byte-identical
    jars produce the same bundle id, from any source path, at any time.

``RunRuntimeReference``
    The binding between one run and one bundle, written beside the run. It is
    what makes "this run used that executable" checkable years later without
    trusting the directory the files happen to sit in.

None of these knows what a jar is for. The roles (``sourceafis_bridge_jar``)
belong to the adapter that declares them; ``core`` only knows that a role names
a file and that two files cannot share one.

The dataclasses live in ``core`` because the storage layer persists them and
``storage`` may only import ``core``. Materialisation — copying, hashing,
fsyncing, refusing symlinks — is :mod:`fpbench.storage.runtime_bundle_store`'s
business. Data here, policy there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Iterable, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import freeze_str_mapping, stable_hash

__all__ = [
    "RuntimeAssetDefinition",
    "RuntimeBundleDefinition",
    "RuntimeBundleVerification",
    "RunRuntimeReference",
    "runtime_asset_id",
    "runtime_bundle_fingerprint",
    "runtime_bundle_id",
    "run_runtime_reference_fingerprint",
    "runtime_reference_id",
    "asset_relative_path",
    "RUNTIME_BUNDLE_SCHEMA_VERSION",
    "RUNTIME_REFERENCE_SCHEMA_VERSION",
    "CONTENT_ADDRESSED_COPY_V1",
    "BUNDLE_ID_LENGTH",
    "ASSET_ID_LENGTH",
    "ASSETS_DIRECTORY",
]

#: Bumped when the meaning of a bundle changes. Inside the fingerprint, so a
#: bump separates new bundles from old rather than silently reusing their ids.
RUNTIME_BUNDLE_SCHEMA_VERSION = "1"

RUNTIME_REFERENCE_SCHEMA_VERSION = "1"

#: The only materialisation policy this stage implements: every asset is copied
#: byte for byte into the bundle and identified by the digest of the copy. Named
#: rather than assumed, because a future policy — an extracted container image,
#: a verified download — would produce a different bundle for the same jar and
#: must not collide with this one.
CONTENT_ADDRESSED_COPY_V1 = "content_addressed_copy_v1"

#: Twelve hex characters, matching ``run_id`` and ``plan_id``.
BUNDLE_ID_LENGTH = 12
ASSET_ID_LENGTH = 12

#: Where assets sit inside a bundle directory.
ASSETS_DIRECTORY = "assets"

_HEX = frozenset("0123456789abcdef")


# ---------------------------------------------------------------- validation


def _require_sha256(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_empty(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _require_safe_relative_path(value: str, field_name: str) -> str:
    text = _require_non_empty(value, field_name)
    if PurePosixPath(text).is_absolute() or PureWindowsPath(text).is_absolute():
        raise ValueError(f"{field_name} must be bundle-relative, got {text!r}")
    parts = PurePosixPath(text.replace("\\", "/")).parts
    if ".." in parts:
        raise ValueError(f"{field_name} must not escape the bundle, got {text!r}")
    return text


def _require_bare_filename(value: str, field_name: str) -> str:
    text = _require_non_empty(value, field_name)
    if "/" in text or "\\" in text or text in (".", ".."):
        raise ValueError(
            f"{field_name} must be a bare file name with no path separators, "
            f"got {text!r}"
        )
    return text


def asset_relative_path(filename: str) -> str:
    """Where an asset lives inside its bundle. POSIX, always."""
    return f"{ASSETS_DIRECTORY}/{_require_bare_filename(filename, 'filename')}"


def runtime_asset_id(sha256: str) -> str:
    """``asset_<12 chars of the content digest>``."""
    return f"asset_{_require_sha256(sha256, 'sha256')[:ASSET_ID_LENGTH]}"


# ------------------------------------------------------------------- assets


@dataclass(frozen=True, slots=True)
class RuntimeAssetDefinition:
    """One immutable file inside a runtime bundle."""

    asset_id: str
    role: str
    filename: str

    sha256: str
    size_bytes: int
    media_type: str

    relative_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        validate_id(self.role)
        object.__setattr__(
            self, "filename", _require_bare_filename(self.filename, "filename")
        )
        object.__setattr__(
            self,
            "media_type",
            _require_non_empty(self.media_type, "media_type"),
        )
        object.__setattr__(
            self,
            "relative_path",
            _require_safe_relative_path(self.relative_path, "relative_path"),
        )

        if int(self.size_bytes) <= 0:
            raise ValueError("size_bytes must be positive; an empty asset is not one")
        object.__setattr__(self, "size_bytes", int(self.size_bytes))

        expected = runtime_asset_id(self.sha256)
        if self.asset_id != expected:
            raise ValueError(
                f"asset_id must be derived from the content digest: expected "
                f"{expected}, got {self.asset_id!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        role: str,
        filename: str,
        sha256: str,
        size_bytes: int,
        media_type: str,
    ) -> "RuntimeAssetDefinition":
        """Derive the id and the in-bundle path from the content."""
        return cls(
            asset_id=runtime_asset_id(sha256),
            role=role,
            filename=filename,
            sha256=sha256,
            size_bytes=size_bytes,
            media_type=media_type,
            relative_path=asset_relative_path(filename),
        )


# ------------------------------------------------------------------ bundles


def runtime_bundle_fingerprint(
    *,
    adapter_id: str,
    materialization_policy: str,
    assets: Iterable[RuntimeAssetDefinition],
) -> str:
    """A 64-character digest of what a bundle contains.

    Covers the roles, names, digests, sizes and media types, in role order.
    Excludes the source path it was copied from, the workspace it landed in,
    the creation time and the file permissions: the same jar materialised on two
    machines a month apart is the same runtime, and must be recognisable as one.
    """
    ordered = sorted(assets, key=lambda asset: asset.role)
    return stable_hash(
        {
            "schema": "runtime_bundle_fingerprint_v1",
            "runtime_bundle_schema_version": RUNTIME_BUNDLE_SCHEMA_VERSION,
            "adapter_id": adapter_id,
            "materialization_policy": materialization_policy,
            "assets": [
                {
                    "role": asset.role,
                    "filename": asset.filename,
                    "sha256": asset.sha256,
                    "size_bytes": asset.size_bytes,
                    "media_type": asset.media_type,
                }
                for asset in ordered
            ],
        },
        length=64,
    )


def runtime_bundle_id(fingerprint: str) -> str:
    """``runtime_<12 chars of the bundle fingerprint>``."""
    return f"runtime_{_require_sha256(fingerprint, 'bundle_fingerprint')[:BUNDLE_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class RuntimeBundleDefinition:
    """An adapter's complete, content-addressed set of runtime assets."""

    bundle_id: str
    bundle_fingerprint: str

    adapter_id: str
    materialization_policy: str
    assets: tuple[RuntimeAssetDefinition, ...]

    created_utc: str

    def __post_init__(self) -> None:
        validate_id(self.bundle_id)
        validate_id(self.adapter_id)
        validate_id(self.materialization_policy)
        object.__setattr__(
            self,
            "bundle_fingerprint",
            _require_sha256(self.bundle_fingerprint, "bundle_fingerprint"),
        )
        object.__setattr__(
            self, "created_utc", _require_non_empty(self.created_utc, "created_utc")
        )

        # Canonical order is role order, so that a bundle rebuilt from JSON in
        # whatever order a reader produced still fingerprints identically.
        assets = tuple(sorted(self.assets, key=lambda asset: asset.role))
        object.__setattr__(self, "assets", assets)
        if not assets:
            raise ValueError("a runtime bundle with no assets is not a runtime")

        roles = [asset.role for asset in assets]
        if len(set(roles)) != len(roles):
            raise ValueError("each role appears at most once in a bundle")
        paths = [asset.relative_path for asset in assets]
        if len(set(paths)) != len(paths):
            raise ValueError("two assets cannot occupy one path in a bundle")

        expected_fingerprint = runtime_bundle_fingerprint(
            adapter_id=self.adapter_id,
            materialization_policy=self.materialization_policy,
            assets=assets,
        )
        if self.bundle_fingerprint != expected_fingerprint:
            raise ValueError(
                "bundle_fingerprint does not match the assets it claims to cover"
            )
        expected_id = runtime_bundle_id(expected_fingerprint)
        if self.bundle_id != expected_id:
            raise ValueError(
                f"bundle_id must be derived from the fingerprint: expected "
                f"{expected_id}, got {self.bundle_id!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        adapter_id: str,
        materialization_policy: str,
        assets: Iterable[RuntimeAssetDefinition],
        created_utc: str,
    ) -> "RuntimeBundleDefinition":
        ordered = tuple(sorted(assets, key=lambda asset: asset.role))
        fingerprint = runtime_bundle_fingerprint(
            adapter_id=adapter_id,
            materialization_policy=materialization_policy,
            assets=ordered,
        )
        return cls(
            bundle_id=runtime_bundle_id(fingerprint),
            bundle_fingerprint=fingerprint,
            adapter_id=adapter_id,
            materialization_policy=materialization_policy,
            assets=ordered,
            created_utc=created_utc,
        )

    def asset(self, role: str) -> RuntimeAssetDefinition:
        for asset in self.assets:
            if asset.role == role:
                return asset
        raise KeyError(f"bundle {self.bundle_id} has no asset for role {role!r}")

    def asset_sha256s(self) -> Mapping[str, str]:
        return freeze_str_mapping({asset.role: asset.sha256 for asset in self.assets})


@dataclass(frozen=True, slots=True)
class RuntimeBundleVerification:
    """What a re-check of a stored bundle found.

    ``issues`` are short sentences meant to be shown. They never contain an
    absolute path: a bundle report is read by people and may be quoted into a
    log that outlives the machine.
    """

    bundle_id: str
    bundle_fingerprint: str

    verified_assets: int
    issues: tuple[str, ...]
    inspected_utc: str

    def __post_init__(self) -> None:
        validate_id(self.bundle_id)
        object.__setattr__(
            self,
            "bundle_fingerprint",
            _require_sha256(self.bundle_fingerprint, "bundle_fingerprint"),
        )
        if int(self.verified_assets) < 0:
            raise ValueError("verified_assets must not be negative")
        object.__setattr__(self, "verified_assets", int(self.verified_assets))
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))

    @property
    def is_valid(self) -> bool:
        return not self.issues


# --------------------------------------------------------------- references


def run_runtime_reference_fingerprint(
    *,
    run_fingerprint: str,
    environment_fingerprint: str,
    bundle_id: str,
    bundle_fingerprint: str,
    asset_sha256s: Mapping[str, str],
) -> str:
    """A digest binding one run to one bundle, with no timestamp in it."""
    return stable_hash(
        {
            "schema": "run_runtime_reference_fingerprint_v1",
            "runtime_reference_schema_version": RUNTIME_REFERENCE_SCHEMA_VERSION,
            "run_fingerprint": run_fingerprint,
            "environment_fingerprint": environment_fingerprint,
            "bundle_id": bundle_id,
            "bundle_fingerprint": bundle_fingerprint,
            "asset_sha256s": dict(sorted(dict(asset_sha256s).items())),
        },
        length=64,
    )


def runtime_reference_id(fingerprint: str) -> str:
    """``runtimeref_<12 chars of the reference fingerprint>``."""
    digest = _require_sha256(fingerprint, "runtime_reference_fingerprint")
    return f"runtimeref_{digest[:BUNDLE_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class RunRuntimeReference:
    """The immutable statement that one run used one runtime bundle.

    Written to ``results/<run_id>/runtime.json`` before the first comparison,
    and re-checked before every subsequent invocation. Its fingerprint excludes
    ``created_utc`` so that the same binding, recorded twice, is recognisably
    the same binding.
    """

    runtime_reference_id: str
    runtime_reference_fingerprint: str

    run_id: str
    run_fingerprint: str
    environment_fingerprint: str

    bundle_id: str
    bundle_fingerprint: str
    asset_sha256s: Mapping[str, str] = field(default_factory=dict)

    created_utc: str = ""

    def __post_init__(self) -> None:
        validate_id(self.run_id)
        validate_id(self.bundle_id)
        validate_id(self.runtime_reference_id)
        for name in (
            "runtime_reference_fingerprint",
            "run_fingerprint",
            "environment_fingerprint",
            "bundle_fingerprint",
        ):
            object.__setattr__(
                self, name, _require_sha256(getattr(self, name), name)
            )
        object.__setattr__(
            self, "asset_sha256s", freeze_str_mapping(self.asset_sha256s)
        )
        if not self.asset_sha256s:
            raise ValueError("a runtime reference must name at least one asset")
        for role, digest in self.asset_sha256s.items():
            validate_id(role)
            _require_sha256(digest, f"asset_sha256s[{role}]")
        object.__setattr__(
            self, "created_utc", _require_non_empty(self.created_utc, "created_utc")
        )

        expected = run_runtime_reference_fingerprint(
            run_fingerprint=self.run_fingerprint,
            environment_fingerprint=self.environment_fingerprint,
            bundle_id=self.bundle_id,
            bundle_fingerprint=self.bundle_fingerprint,
            asset_sha256s=self.asset_sha256s,
        )
        if self.runtime_reference_fingerprint != expected:
            raise ValueError(
                "runtime_reference_fingerprint does not match the binding it "
                "claims to cover"
            )
        expected_id = runtime_reference_id(expected)
        if self.runtime_reference_id != expected_id:
            raise ValueError(
                f"runtime_reference_id must be derived from the fingerprint: "
                f"expected {expected_id}, got {self.runtime_reference_id!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        run_fingerprint: str,
        environment_fingerprint: str,
        bundle: RuntimeBundleDefinition,
        created_utc: str,
    ) -> "RunRuntimeReference":
        asset_sha256s = bundle.asset_sha256s()
        fingerprint = run_runtime_reference_fingerprint(
            run_fingerprint=run_fingerprint,
            environment_fingerprint=environment_fingerprint,
            bundle_id=bundle.bundle_id,
            bundle_fingerprint=bundle.bundle_fingerprint,
            asset_sha256s=asset_sha256s,
        )
        return cls(
            runtime_reference_id=runtime_reference_id(fingerprint),
            runtime_reference_fingerprint=fingerprint,
            run_id=run_id,
            run_fingerprint=run_fingerprint,
            environment_fingerprint=environment_fingerprint,
            bundle_id=bundle.bundle_id,
            bundle_fingerprint=bundle.bundle_fingerprint,
            asset_sha256s=asset_sha256s,
            created_utc=created_utc,
        )
