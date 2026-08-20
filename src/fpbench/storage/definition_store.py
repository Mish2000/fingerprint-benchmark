"""Where an experiment records what it pinned, filed by definition id.

Stage 5A wrote one file per experiment and run::

    derivations/<experiment_id>/<run_id>/definition.json

which was correct while an experiment could only ever pin one thing. It cannot.
A second metric policy over the same decisions is a second, equally permanent
definition, and a flat filename forces one to overwrite the other — which is the
one thing every store in this project refuses to do. So definitions are now
namespaced::

    derivations/<experiment_id>/<run_id>/definitions/<definition_id>/definition.json

with a separate pointer naming the active one.

**The old path still reads.** Stage 5A's derivation is finalised, its receipt is
committed, and its decision set is cited by identity in three places. Migrating
that file would change nothing about the decisions and would invalidate a
verified chain for no reason, so :meth:`DefinitionStore.read` falls back to the
legacy location when the namespaced one is absent, and :meth:`DefinitionStore.write`
recognises a legacy file that already pins the same definition as a no-op
(spec section 35).

The store is deliberately ignorant of what a definition *is*. It is handed a
loader — ``DerivationDefinition`` for stage 5A, ``MetricDerivationDefinition``
for 5B — because the two share a filing convention and nothing else.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Callable, Protocol

from fpbench.core.errors import StorageError
from fpbench.core.serialization import read_json
from fpbench.core.json_io import write_json
from fpbench.storage import layout

__all__ = ["DefinitionStore", "DefinitionLike"]

_DEFINITION = "definition.json"
_LEGACY_DEFINITION = "definition.json"


class DefinitionLike(Protocol):
    """The two fields a filing system needs from any definition."""

    definition_id: str
    definition_fingerprint: str


class DefinitionStore:
    """Immutable, namespaced storage for what an experiment pinned."""

    def __init__(
        self,
        root: Path,
        *,
        experiment_id: str,
        loader: Callable[[dict[str, Any]], Any],
        pointer_name: str,
    ) -> None:
        """
        Args:
            loader: Turns a JSON payload into the definition type this
                experiment uses. Given a payload it does not recognise it should
                raise ``TypeError`` or ``ValueError``; the store converts those
                into :class:`StorageError` with the offending path attached.
            pointer_name: File that names the active definition, e.g.
                ``current-metric-set.json``. One per experiment, so two
                experiments over the same run do not fight over a pointer.
        """
        self.root = Path(root)
        self.experiment_id = experiment_id
        self._loader = loader
        self._pointer_name = pointer_name

    # ------------------------------------------------------------------ paths

    def experiment_dir(self, run_id: str) -> Path:
        return layout.derivation_experiment_directory(
            self.root, self.experiment_id, run_id
        )

    def definitions_dir(self, run_id: str) -> Path:
        return layout.definitions_directory(self.root, self.experiment_id, run_id)

    def definition_path(self, run_id: str, definition_id: str) -> Path:
        return (
            layout.definition_directory(
                self.root, self.experiment_id, run_id, definition_id
            )
            / _DEFINITION
        )

    def legacy_definition_path(self, run_id: str) -> Path:
        """Stage 5A's flat filename. Read, never written to."""
        return self.experiment_dir(run_id) / _LEGACY_DEFINITION

    def pointer_path(self, run_id: str) -> Path:
        return self.experiment_dir(run_id) / self._pointer_name

    def definition_ids(self, run_id: str) -> tuple[str, ...]:
        directory = self.definitions_dir(run_id)
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in directory.iterdir()
                if (path / _DEFINITION).is_file()
            )
        )

    # ------------------------------------------------------------- read/write

    def read(self, run_id: str, definition_id: str) -> Any:
        """Read one definition, from either layout.

        The namespaced path wins when both exist. A legacy file is only ever a
        fallback, so a workspace that has been through both versions cannot end
        up reading the older of two files.
        """
        path = self.definition_path(run_id, definition_id)
        if not path.is_file():
            legacy = self.legacy_definition_path(run_id)
            if not legacy.is_file():
                raise StorageError(f"definition not found: {path}")
            definition = self._load(legacy)
            if definition.definition_id != definition_id:
                raise StorageError(
                    f"{legacy} pins {definition.definition_id}, not {definition_id}"
                )
            return definition
        return self._load(path)

    def read_active(self, run_id: str) -> Any | None:
        """The definition the pointer names, or the legacy one, or nothing."""
        definition_id = self.read_pointer(run_id)
        if definition_id:
            return self.read(run_id, definition_id)
        legacy = self.legacy_definition_path(run_id)
        if legacy.is_file():
            return self._load(legacy)
        return None

    def write(self, run_id: str, definition: DefinitionLike) -> Path:
        """Store a definition, or confirm the stored one is already it.

        Raises:
            StorageError: a *different* definition is already filed under this
                id, which can only mean the file was edited — the id is derived
                from the fingerprint.
        """
        legacy = self.legacy_definition_path(run_id)
        if legacy.is_file():
            stored = self._load(legacy)
            if stored.definition_fingerprint == definition.definition_fingerprint:
                # Stage 5A already pinned exactly this. Rewriting it in the new
                # layout would gain nothing and would leave two files claiming
                # the same identity.
                return legacy

        path = self.definition_path(run_id, definition.definition_id)
        if path.is_file():
            stored = self._load(path)
            if stored.definition_fingerprint != definition.definition_fingerprint:
                raise StorageError(
                    f"{path} already pins a different definition "
                    f"({stored.definition_fingerprint[:12]}...); refusing to "
                    f"replace it with {definition.definition_fingerprint[:12]}..."
                )
            return path
        return write_json(path, definition)

    # ---------------------------------------------------------------- pointer

    def read_pointer(self, run_id: str) -> str | None:
        path = self.pointer_path(run_id)
        if not path.is_file():
            return None
        payload = read_json(path)
        return str(payload.get("definition_id") or "") or None

    def read_pointer_value(self, run_id: str, key: str) -> str | None:
        """Read another field the pointer carries, e.g. the metric-set id."""
        path = self.pointer_path(run_id)
        if not path.is_file():
            return None
        payload = read_json(path)
        return str(payload.get(key) or "") or None

    def write_pointer(self, run_id: str, **fields: Any) -> Path:
        """Name the active definition. The pointer is derived, not authoritative.

        It may be rewritten freely: it says which definition this workspace is
        currently working with, and every artefact it points at carries its own
        identity anyway.
        """
        return write_json(
            self.pointer_path(run_id),
            {
                "experiment_id": self.experiment_id,
                "run_id": run_id,
                **{key: value for key, value in fields.items()},
                "written_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            },
        )

    # --------------------------------------------------------------- internal

    def _load(self, path: Path) -> Any:
        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable definition ({exc})") from exc
        try:
            return self._loader(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable definition ({exc})") from exc
