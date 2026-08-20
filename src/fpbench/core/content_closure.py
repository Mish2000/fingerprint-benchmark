"""One binding type, over everything that decides what a score was.

The provenance in this repository is thorough and it is assembled a stage at a
time, which means each stage closes over the things its author thought of. The
gaps that leaves are all the same shape — an identity is bound by *name* where
it should have been bound by *content*:

* a run records ``preparer_id`` but not the preparer's implementation version,
  so two preparers with one id and different behaviour produce results that
  claim to be the same kind of thing;
* a licence record is joined to an upstream identity of the right *kind*
  without anything requiring it to be the same *component*;
* a stage fingerprints its source over checkout bytes, so the answer depends on
  whether the machine writes ``\\n`` or ``\\r\\n``.

Each was fixed where it was found. This is the type that stops the next one:
a binding that will not construct unless every part of the closure is present.

**What "closure" means here.** Six parts, and the constructor refuses a binding
missing any of them:

``code``
    The source that ran, hashed content-normalised (see
    :func:`fpbench.experiments.source_fingerprints.canonical_source_sha256`).
``preparer``
    Which preparer produced the adapter's input, *and* at which implementation
    version — an id alone does not identify behaviour.
``interpreter``
    The language runtime. A pure-Python result still depends on it.
``native_dependencies``
    The executables and libraries the route actually loaded, by digest.
``runtime_assets``
    The pinned files whose bytes define the route, and whether they were
    re-checked *during* the run rather than only at preflight. Stage 19A and
    19B both ran with that re-check disabled, and nothing in their evidence
    said so.
``source_identity``
    Which commit, and whether the tree was clean.

**What it is not.** It is not a replacement for the stage markers already
published; those are frozen and their fingerprints are load-bearing. It is what
a stage after this one binds with, so the closure is a precondition of building
the binding rather than something a reviewer has to go looking for.

**Why the third-party gap is closed here and not at its own call site.**
:func:`fpbench.third_party.manifest.build_usage_record` accepts any
:class:`~fpbench.core.third_party_models.UpstreamIdentity` of a matching
component kind, with nothing tying it to the licence observation beside it.
Binding the two would mean either a field on ``LicenseObservation`` — whose
fingerprint is inside every usage record in ``evidence/`` — or a new required
argument, which changes the source fingerprint of Stage 9A and Stage 10A and so
forces two published markers to be re-issued for runs nobody redid. Neither is
worth it for a check that could not have *proved* the pairing anyway. A new
stage binds its upstream through :attr:`native_dependencies` here, where the
digest is the identity and there is nothing to pair wrongly.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from typing import Mapping

from fpbench.core.errors import FpbenchError
from fpbench.core.serialization import freeze_str_mapping, stable_hash

__all__ = [
    "ContentClosureError",
    "ContentClosureBinding",
    "NativeDependency",
    "PreparerIdentity",
    "RuntimeAssetBinding",
    "SourceIdentity",
    "current_interpreter_identity",
]

_HEX = frozenset("0123456789abcdef")


class ContentClosureError(FpbenchError):
    """A binding was offered that does not close over its own content."""


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ContentClosureError(
            f"{field_name} must be a 64-character SHA-256 hex digest, got {value!r}"
        )
    return digest


def _require_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ContentClosureError(f"{field_name} must not be empty")
    return text


@dataclass(frozen=True, slots=True)
class PreparerIdentity:
    """Which preparer, at which version, producing which schema of provenance.

    ``preparer_id`` alone is what the runner used to record. It names a *role* —
    "the canonical-500 preparer" — and two implementations can hold it in turn.
    The version is what distinguishes them, and the metadata schema is what says
    which fields the run's provenance is even expected to contain.
    """

    preparer_id: str
    preparer_version: str
    runner_metadata_schema: str

    def __post_init__(self) -> None:
        for name in ("preparer_id", "preparer_version", "runner_metadata_schema"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class NativeDependency:
    """One executable or library the route loaded, by digest rather than path.

    No path field, deliberately. Where a file sat is a fact about one machine;
    which bytes it held is the fact a score depends on (docs/adr/0083).
    """

    role: str
    sha256: str
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _require_text(self.role, "role"))
        object.__setattr__(self, "sha256", _require_digest(self.sha256, "sha256"))
        if self.version is not None:
            object.__setattr__(
                self, "version", _require_text(self.version, "version")
            )


@dataclass(frozen=True, slots=True)
class RuntimeAssetBinding:
    """The pinned assets, and whether drift was checked while the run ran.

    ``rechecked_per_comparison`` is the field this class exists for. Preflight
    verifying an executable proves what it was when the run *started*; a route
    that swaps it at comparison 3,000 produces 3,000 attributable results and
    3,000 that are not, and a binding that only recorded the preflight digest
    would look identical in both cases (docs/adr/0018).
    """

    assets: tuple[NativeDependency, ...]
    rechecked_per_comparison: bool

    def __post_init__(self) -> None:
        assets = tuple(self.assets)
        if not assets:
            raise ContentClosureError(
                "a runtime asset binding must name at least one asset; a route "
                "that pins nothing cannot say what produced its scores"
            )
        for asset in assets:
            if not isinstance(asset, NativeDependency):
                raise ContentClosureError(
                    "every runtime asset must be a NativeDependency"
                )
        roles = [asset.role for asset in assets]
        if len(set(roles)) != len(roles):
            raise ContentClosureError(f"a runtime asset role is named twice: {roles}")
        if type(self.rechecked_per_comparison) is not bool:
            raise ContentClosureError("rechecked_per_comparison must be a bool")
        object.__setattr__(
            self, "assets", tuple(sorted(assets, key=lambda a: a.role))
        )


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Which commit produced this, and whether anything was uncommitted."""

    commit: str
    tree_clean: bool

    def __post_init__(self) -> None:
        commit = str(self.commit).strip().lower()
        if len(commit) != 40 or not set(commit) <= _HEX:
            raise ContentClosureError(
                f"commit must be a 40-character Git object name, got {self.commit!r}"
            )
        object.__setattr__(self, "commit", commit)
        if type(self.tree_clean) is not bool:
            raise ContentClosureError("tree_clean must be a bool")


def current_interpreter_identity() -> Mapping[str, str]:
    """The running interpreter, described the same way every time."""
    return {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "abi": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": platform.system(),
        "machine": platform.machine(),
    }


@dataclass(frozen=True, slots=True)
class ContentClosureBinding:
    """Everything a score depends on, bound at once or not at all.

    Construction is the check. There is no partial binding to fill in later and
    no default for any of the six parts, because every gap this type exists to
    close was a field somebody meant to add.
    """

    #: What this binding is about: a run id, a stage, an operating point.
    subject: str

    #: ``relative path -> content-normalised digest`` for the source that ran.
    code: Mapping[str, str]

    preparer: PreparerIdentity
    interpreter: Mapping[str, str]
    native_dependencies: tuple[NativeDependency, ...]
    runtime_assets: RuntimeAssetBinding
    source_identity: SourceIdentity

    closure_fingerprint: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _require_text(self.subject, "subject"))

        code = dict(self.code)
        if not code:
            raise ContentClosureError(
                "a content closure must name the code that ran; an empty code "
                "map is the gap this type exists to refuse"
            )
        object.__setattr__(
            self,
            "code",
            freeze_str_mapping(
                {
                    _require_text(path, "code path"): _require_digest(
                        digest, f"code[{path}]"
                    )
                    for path, digest in sorted(code.items())
                }
            ),
        )

        if not isinstance(self.preparer, PreparerIdentity):
            raise ContentClosureError("preparer must be a PreparerIdentity")
        if not isinstance(self.runtime_assets, RuntimeAssetBinding):
            raise ContentClosureError("runtime_assets must be a RuntimeAssetBinding")
        if not isinstance(self.source_identity, SourceIdentity):
            raise ContentClosureError("source_identity must be a SourceIdentity")

        interpreter = dict(self.interpreter)
        missing = {"implementation", "version"} - set(interpreter)
        if missing:
            raise ContentClosureError(
                f"the interpreter identity is missing {sorted(missing)}"
            )
        object.__setattr__(self, "interpreter", freeze_str_mapping(interpreter))

        dependencies = tuple(self.native_dependencies)
        for dependency in dependencies:
            if not isinstance(dependency, NativeDependency):
                raise ContentClosureError(
                    "every native dependency must be a NativeDependency"
                )
        roles = [dependency.role for dependency in dependencies]
        if len(set(roles)) != len(roles):
            raise ContentClosureError(
                f"a native dependency role is named twice: {roles}"
            )
        object.__setattr__(
            self,
            "native_dependencies",
            tuple(sorted(dependencies, key=lambda d: d.role)),
        )
        object.__setattr__(self, "metadata", freeze_str_mapping(dict(self.metadata)))

        expected = content_closure_fingerprint(self)
        stored = str(self.closure_fingerprint).strip().lower()
        if stored and stored != expected:
            raise ContentClosureError(
                f"{self.subject}: closure_fingerprint does not cover what the "
                "binding says"
            )
        object.__setattr__(self, "closure_fingerprint", expected)


def content_closure_fingerprint(binding: ContentClosureBinding) -> str:
    """A digest over the whole closure, and nothing outside it.

    Wall-clock time is excluded on purpose: two runs of the same closure on
    different days are the same closure, and folding the clock in would make
    every binding unique and therefore useless for comparison.
    """
    return stable_hash(
        {
            "schema": "fpbench_content_closure_v1",
            "subject": binding.subject,
            "code": dict(binding.code),
            "preparer": {
                "preparer_id": binding.preparer.preparer_id,
                "preparer_version": binding.preparer.preparer_version,
                "runner_metadata_schema": binding.preparer.runner_metadata_schema,
            },
            "interpreter": dict(binding.interpreter),
            "native_dependencies": [
                {
                    "role": dependency.role,
                    "sha256": dependency.sha256,
                    "version": dependency.version,
                }
                for dependency in binding.native_dependencies
            ],
            "runtime_assets": {
                "assets": [
                    {
                        "role": asset.role,
                        "sha256": asset.sha256,
                        "version": asset.version,
                    }
                    for asset in binding.runtime_assets.assets
                ],
                "rechecked_per_comparison": (
                    binding.runtime_assets.rechecked_per_comparison
                ),
            },
            "source_identity": {
                "commit": binding.source_identity.commit,
                "tree_clean": binding.source_identity.tree_clean,
            },
            "metadata": dict(binding.metadata),
        },
        length=64,
    )
