"""Strict YAML readers, where the experiment layer expects to find them.

The implementation is :mod:`fpbench.core.config_values`. It lives in ``core``
because the adapters need it too — ``SourceAfisJavaConfig`` reads a mapping that
came out of a YAML file, and it has the same right to refuse ``research_mode:
"false"`` as an experiment does. ``adapters`` may import ``core`` and may not
import ``experiments`` (docs/adr/0001), so the shared code goes to the layer both
sides are allowed to see, and this module is the name the experiment layer uses.

There is one implementation. Everything below is the same object as its
counterpart in ``core``.
"""

from __future__ import annotations

from fpbench.core.config_values import (
    MISSING,
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_mapping,
    require_yaml_non_empty_str,
    require_yaml_positive_number,
    require_yaml_string_mapping,
)

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
