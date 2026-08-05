"""Load the Stage 8B operational policy, frozen before any measurement.

The policy exists so that "fast enough" is a question with an answer that was
written down first.  It inherits Stage 8A's three full-run budgets by
fingerprint rather than restating them, and adds the per-operation deadlines
that only a subprocess route needs.

There is no VRAM limit here.  ``flx_cpu_linux_x86_64_v1`` has no device to
measure, and a limit that can only ever read zero is not a gate.  Adding a GPU
means a new runtime profile, and that profile brings its own policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from fpbench.core.flx_errors import FlxPolicyError
from fpbench.core.flx_models import STAGE8B_SCHEMA_VERSION, FlxRuntimePolicy
from fpbench.flx.identity import NUMERIC_TOLERANCE, RUNTIME_POLICY_ID

__all__ = ["load_runtime_policy", "runtime_policy_from_plain", "StrictYamlLoader"]

_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "inherits_selection_policy_fingerprint",
        "max_projected_12000_extractions_seconds",
        "max_projected_6000_comparisons_seconds",
        "max_peak_ram_bytes",
        "max_artifact_disk_bytes",
        "max_worker_startup_seconds",
        "max_model_load_seconds",
        "preprocess_deadline_seconds",
        "extract_deadline_seconds",
        "compare_deadline_seconds",
        "numeric_tolerance",
        "fingerprint",
    }
)


class StrictYamlLoader(yaml.SafeLoader):
    """A safe loader that refuses a duplicate key instead of silently winning."""


def _construct_mapping(
    loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False
) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise FlxPolicyError(
                f"duplicate policy key {key!r} at line {key_node.start_mark.line + 1}"
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def runtime_policy_from_plain(payload: Any) -> FlxRuntimePolicy:
    if not isinstance(payload, Mapping):
        raise FlxPolicyError("a Stage 8B runtime policy must be a mapping")
    unknown = sorted(set(payload) - _FIELDS)
    missing = sorted(_FIELDS - set(payload))
    if unknown or missing:
        raise FlxPolicyError(
            f"Stage 8B runtime policy fields do not match; unknown={unknown}, missing={missing}"
        )
    return FlxRuntimePolicy(**{str(key): payload[key] for key in payload})


def load_runtime_policy(path: Path) -> FlxRuntimePolicy:
    path = Path(path)
    if not path.is_file():
        raise FlxPolicyError(f"Stage 8B runtime policy not found: {path}")
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=StrictYamlLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise FlxPolicyError(f"{path}: unreadable Stage 8B runtime policy ({exc})") from exc
    try:
        policy = runtime_policy_from_plain(payload)
    except FlxPolicyError:
        raise
    except (TypeError, ValueError) as exc:
        raise FlxPolicyError(f"{path}: invalid Stage 8B runtime policy ({exc})") from exc
    if policy.schema_version != STAGE8B_SCHEMA_VERSION:
        raise FlxPolicyError(f"{path}: unsupported Stage 8B policy schema version")
    if policy.policy_id != RUNTIME_POLICY_ID:
        raise FlxPolicyError(
            f"{path}: the frozen Stage 8B policy is {RUNTIME_POLICY_ID!r}, "
            f"got {policy.policy_id!r}; a different policy is a different identity"
        )
    if policy.numeric_tolerance != NUMERIC_TOLERANCE:
        raise FlxPolicyError(
            f"{path}: Stage 8B targets bitwise equality (tolerance "
            f"{NUMERIC_TOLERANCE!r}); widening it requires a new runtime profile "
            "declared in advance, not an edited policy"
        )
    return policy
