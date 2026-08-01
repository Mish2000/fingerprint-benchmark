"""Reading YAML without letting the reader decide what a value meant.

``bool(config.get("research_mode"))`` is true for the string ``"false"``.
``int(config["expected_bridge_jar_size"])`` accepts ``"27183104"`` and ``27183104.0``
alike. Neither is a hypothetical: both idioms are already in this repository, and
both turn a typo in a config file into a run that starts anyway under settings
nobody wrote down.

The rule here is that a YAML scalar carries a type and that type is part of the
configuration. ``research_mode: "false"`` is not a boolean that happens to be
spelled oddly — it is a string where a boolean was required, and the only honest
response is to refuse it. Every helper below therefore checks the Python type
YAML produced rather than coercing it, and every failure names the file it came
from.

Two deliberate exceptions, both narrow:

* ``timeout_seconds`` and friends may be written ``60`` or ``60.0``, because a
  duration is a quantity and both spellings mean the same quantity. They may not
  be written ``"60"`` or ``true``.
* An integer field accepts ``int`` only. ``0.0`` is rejected even though it
  compares equal to ``0``: a replicate index of ``0.0`` means somebody's editor
  reformatted the file, and that is worth knowing.

``bool`` is rejected everywhere a number is expected, because ``True`` is an
``int`` in Python and ``expected_jobs: true`` would otherwise quietly mean one.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from fpbench.core.errors import ConfigurationError

__all__ = [
    "require_yaml_bool",
    "require_yaml_exact_int",
    "require_yaml_non_empty_str",
    "require_yaml_positive_number",
    "require_yaml_mapping",
    "require_yaml_string_mapping",
    "reject_unknown_keys",
    "MISSING",
]


class _Missing:
    """Sentinel distinguishing "no default" from ``None``/``False``/``0``."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<no default>"


#: Passed as ``default`` when a key is required. A plain ``None`` cannot serve,
#: because ``None`` is a perfectly reasonable default for an optional key.
MISSING = _Missing()


def _where(where: object | None, key: str) -> str:
    return f"{where}: {key!r}" if where is not None else repr(key)


def _fetch(
    document: Mapping[str, Any], key: str, default: Any, where: object | None
) -> Any:
    if key in document:
        return document[key]
    if isinstance(default, _Missing):
        raise ConfigurationError(f"{_where(where, key)} is required")
    return default


def _type_name(value: Any) -> str:
    return type(value).__name__


def require_yaml_bool(
    document: Mapping[str, Any],
    key: str,
    *,
    where: object | None = None,
    default: Any = MISSING,
) -> bool:
    """A YAML boolean, never a string and never a number.

    ``research_mode: "false"`` is the failure this exists for. Under ``bool()``
    it is ``True``, which is the exact opposite of what was written.
    """
    value = _fetch(document, key, default, where)
    if isinstance(value, _Missing):  # pragma: no cover - _fetch raises first
        raise ConfigurationError(f"{_where(where, key)} is required")
    if type(value) is not bool:
        raise ConfigurationError(
            f"{_where(where, key)} must be a YAML boolean (true/false), got "
            f"{_type_name(value)} {value!r}"
        )
    return value


def require_yaml_exact_int(
    document: Mapping[str, Any],
    key: str,
    *,
    where: object | None = None,
    default: Any = MISSING,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """A YAML integer. ``0.0``, ``"0"`` and ``true`` are all refused."""
    value = _fetch(document, key, default, where)
    if type(value) is not int:  # bool is an int subclass; type() excludes it
        raise ConfigurationError(
            f"{_where(where, key)} must be a YAML integer, got "
            f"{_type_name(value)} {value!r}"
        )
    if minimum is not None and value < minimum:
        raise ConfigurationError(
            f"{_where(where, key)} must be at least {minimum}, got {value}"
        )
    if maximum is not None and value > maximum:
        raise ConfigurationError(
            f"{_where(where, key)} must be at most {maximum}, got {value}"
        )
    return value


def require_yaml_non_empty_str(
    document: Mapping[str, Any],
    key: str,
    *,
    where: object | None = None,
    default: Any = MISSING,
) -> str:
    """A YAML string with something in it. Numbers are not strings here.

    ``bridge_version: 1`` is refused rather than rendered as ``"1"``: a version
    is an opaque label and the next one may be ``1.0.1``, which YAML would read
    as a float and silently truncate.
    """
    value = _fetch(document, key, default, where)
    if not isinstance(value, str):
        raise ConfigurationError(
            f"{_where(where, key)} must be a YAML string, got "
            f"{_type_name(value)} {value!r}"
        )
    text = value.strip()
    if not text:
        raise ConfigurationError(f"{_where(where, key)} must not be empty")
    return text


def require_yaml_positive_number(
    document: Mapping[str, Any],
    key: str,
    *,
    where: object | None = None,
    default: Any = MISSING,
) -> float:
    """A finite positive number, written as an integer or a float.

    The one place both spellings are allowed, because ``60`` and ``60.0`` seconds
    are the same duration. ``"60"`` and ``true`` are still refused.
    """
    import math

    value = _fetch(document, key, default, where)
    if type(value) not in (int, float):
        raise ConfigurationError(
            f"{_where(where, key)} must be a YAML number, got "
            f"{_type_name(value)} {value!r}"
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ConfigurationError(
            f"{_where(where, key)} must be a finite positive number, got {value!r}"
        )
    return number


def require_yaml_mapping(
    document: Mapping[str, Any],
    key: str,
    *,
    where: object | None = None,
    default: Any = MISSING,
) -> Mapping[str, Any]:
    """A YAML mapping with string keys, values left alone."""
    value = _fetch(document, key, default, where)
    if not isinstance(value, Mapping):
        raise ConfigurationError(
            f"{_where(where, key)} must be a YAML mapping, got "
            f"{_type_name(value)} {value!r}"
        )
    for item in value:
        if not isinstance(item, str):
            raise ConfigurationError(
                f"{_where(where, key)} must be keyed by strings, got "
                f"{_type_name(item)} {item!r}"
            )
    return dict(value)


def require_yaml_string_mapping(
    document: Mapping[str, Any],
    key: str,
    *,
    where: object | None = None,
    default: Any = MISSING,
) -> Mapping[str, str]:
    """A YAML mapping whose values are strings too.

    Used where the mapping is stamped into a fingerprint. ``target_ppi: 500``
    and ``target_ppi: "500"`` would hash differently once rendered, so the file
    has to commit to one.
    """
    mapping = require_yaml_mapping(document, key, where=where, default=default)
    for name, item in mapping.items():
        if not isinstance(item, str):
            raise ConfigurationError(
                f"{_where(where, key)}[{name!r}] must be a YAML string, got "
                f"{_type_name(item)} {item!r}"
            )
    return dict(mapping)


def reject_unknown_keys(
    document: Mapping[str, Any],
    known: Iterable[str],
    *,
    where: object | None = None,
) -> None:
    """Refuse a key nobody reads.

    A typo that is ignored is a setting that silently did nothing, which is the
    worst of both worlds: the file says one thing and the run did another.
    """
    unknown = sorted(set(document) - set(known))
    if unknown:
        label = f"{where} " if where is not None else ""
        raise ConfigurationError(f"unknown {label}configuration keys: {unknown}")
