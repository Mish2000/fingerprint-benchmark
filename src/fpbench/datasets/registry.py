"""Loading a dataset configuration and turning it into a provider.

Deliberately a plain dict, not a plugin system discovered through entry points.
There are two datasets in sight and a dict is honest about that; the lookup can
become dynamic later without any provider changing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from fpbench.core.errors import ConfigurationError
from fpbench.datasets.base import DatasetProvider, DatasetSpec

__all__ = ["load_dataset_spec", "create_provider", "register_provider", "PROVIDERS"]

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

ProviderFactory = Callable[[DatasetSpec], DatasetProvider]

PROVIDERS: dict[str, ProviderFactory] = {}


def register_provider(name: str, factory: ProviderFactory) -> None:
    PROVIDERS[name] = factory


def _expand_env(value: Any, *, source: Path) -> Any:
    """Substitute ``${VAR}`` from the environment, recursively.

    Local dataset paths must not be committed, so configs reference them by
    environment variable. An unset variable is a configuration error, not an
    empty string — silently scanning the wrong directory is worse than failing.
    """
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            resolved = os.environ.get(name)
            if resolved is None:
                raise ConfigurationError(
                    f"{source}: environment variable {name!r} is referenced but not set"
                )
            return resolved

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, Mapping):
        return {k: _expand_env(v, source=source) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v, source=source) for v in value]
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML config verbatim.

    Environment references are *not* expanded here: expansion is applied by the
    caller, and only to the values it actually uses, so that an override can
    replace a value whose variable is unset.
    """
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError(f"configuration file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigurationError(f"{path}: expected a mapping at the top level")
    return raw


def load_dataset_spec(path: Path, *, root_override: Path | None = None) -> DatasetSpec:
    """Build a :class:`DatasetSpec` from ``configs/datasets/<name>.yaml``.

    ``root_override`` exists for tests and ad-hoc runs against a copy of the
    data; it bypasses the environment variable without editing the config.
    """
    document = load_yaml(path)
    section = document.get("dataset")
    if not isinstance(section, dict):
        raise ConfigurationError(f"{path}: missing 'dataset' section")

    for key in ("id", "provider"):
        if not section.get(key):
            raise ConfigurationError(f"{path}: dataset.{key} is required")

    if root_override is not None:
        root = Path(root_override)
    else:
        declared = section.get("root")
        if not declared:
            raise ConfigurationError(f"{path}: dataset.root is required")
        root = Path(_expand_env(declared, source=path))

    return DatasetSpec(
        dataset_id=str(section["id"]),
        provider=str(section["provider"]),
        root=root,
        options=_expand_env(section.get("options") or {}, source=path),
    )


def create_provider(spec: DatasetSpec) -> DatasetProvider:
    _ensure_builtin_providers()
    try:
        factory = PROVIDERS[spec.provider]
    except KeyError:
        raise ConfigurationError(
            f"unknown dataset provider {spec.provider!r}; "
            f"available: {sorted(PROVIDERS)}"
        ) from None
    return factory(spec)


def _ensure_builtin_providers() -> None:
    """Register providers on first use.

    Imported lazily so that adding a provider with heavy dependencies never
    makes ``import fpbench.datasets`` more expensive for everyone else.
    """
    if "sd300" not in PROVIDERS:
        from fpbench.datasets.sd300.catalog import SD300DatasetProvider

        register_provider("sd300", SD300DatasetProvider.from_spec)
