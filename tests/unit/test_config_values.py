"""A YAML scalar's type is part of the configuration.

Every case here is a value that some earlier idiom in this repository would have
accepted and quietly reinterpreted: ``bool("false")`` is ``True``, ``int("60")``
is ``60``, ``int(0.0)`` is ``0``. The point of the strict readers is that each of
those is now a refusal with the file named in it (spec section 47).
"""

from __future__ import annotations

import pytest

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_mapping,
    require_yaml_non_empty_str,
    require_yaml_positive_number,
    require_yaml_string_mapping,
)
from fpbench.core.errors import ConfigurationError

pytestmark = pytest.mark.adapter_contract


# ------------------------------------------------------------------- booleans


def test_a_yaml_boolean_is_accepted():
    assert require_yaml_bool({"research_mode": True}, "research_mode") is True
    assert require_yaml_bool({"research_mode": False}, "research_mode") is False


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], "yes"])
def test_anything_that_is_not_a_boolean_is_refused(value):
    """``research_mode: "false"`` is the failure this exists for."""
    with pytest.raises(ConfigurationError, match="YAML boolean"):
        require_yaml_bool({"research_mode": value}, "research_mode")


def test_a_missing_boolean_uses_its_default_and_only_then():
    assert require_yaml_bool({}, "research_mode", default=False) is False
    with pytest.raises(ConfigurationError, match="required"):
        require_yaml_bool({}, "research_mode")


# ------------------------------------------------------------------- integers


def test_an_exact_integer_is_accepted():
    assert require_yaml_exact_int({"replicate_index": 0}, "replicate_index") == 0


@pytest.mark.parametrize("value", [0.0, "0", True, False, None])
def test_a_number_that_is_not_an_integer_is_refused(value):
    with pytest.raises(ConfigurationError, match="exact integer"):
        require_yaml_exact_int({"replicate_index": value}, "replicate_index")


def test_integer_bounds_are_checked_when_asked_for():
    with pytest.raises(ConfigurationError, match="at least 1"):
        require_yaml_exact_int({"jobs": 0}, "jobs", minimum=1)
    with pytest.raises(ConfigurationError, match="at most 10"):
        require_yaml_exact_int({"jobs": 11}, "jobs", maximum=10)


# -------------------------------------------------------------------- strings


def test_a_non_empty_string_is_accepted_and_stripped():
    assert require_yaml_non_empty_str({"id": "  abc  "}, "id") == "abc"


@pytest.mark.parametrize("value", [1, 1.0, True, None, ["a"]])
def test_a_string_field_refuses_other_scalars(value):
    """``expected_bridge_version: 1`` must not become ``"1"``.

    The next version is ``1.0.1``, which YAML reads as a float and truncates.
    """
    with pytest.raises(ConfigurationError, match="YAML string"):
        require_yaml_non_empty_str({"version": value}, "version")


def test_an_empty_string_is_not_a_value():
    with pytest.raises(ConfigurationError, match="must not be empty"):
        require_yaml_non_empty_str({"id": "   "}, "id")


# -------------------------------------------------------------------- numbers


@pytest.mark.parametrize("value", [60, 60.0, 0.5])
def test_a_duration_may_be_an_integer_or_a_float(value):
    assert require_yaml_positive_number({"t": value}, "t") == float(value)


@pytest.mark.parametrize("value", ["60", True, None, float("inf"), 0, -1])
def test_a_duration_refuses_strings_booleans_and_non_positive_numbers(value):
    with pytest.raises(ConfigurationError):
        require_yaml_positive_number({"timeout_seconds": value}, "timeout_seconds")


# ------------------------------------------------------------------- mappings


def test_a_mapping_must_be_a_mapping_with_string_keys():
    assert require_yaml_mapping({"p": {"a": 1}}, "p") == {"a": 1}
    with pytest.raises(ConfigurationError, match="YAML mapping"):
        require_yaml_mapping({"p": ["a"]}, "p")
    with pytest.raises(ConfigurationError, match="keyed by strings"):
        require_yaml_mapping({"p": {1: "a"}}, "p")


def test_a_string_mapping_refuses_a_numeric_value():
    """``target_ppi: 500`` and ``"500"`` hash differently once rendered."""
    assert require_yaml_string_mapping({"p": {"a": "500"}}, "p") == {"a": "500"}
    with pytest.raises(ConfigurationError, match="YAML string"):
        require_yaml_string_mapping({"p": {"target_ppi": 500}}, "p")


# -------------------------------------------------------------- unknown keys


def test_an_unknown_key_is_a_setting_that_silently_did_nothing():
    with pytest.raises(ConfigurationError, match=r"\['threshold'\]"):
        reject_unknown_keys({"id": "x", "threshold": 40}, {"id"}, where="experiment")


def test_the_known_keys_pass_through():
    reject_unknown_keys({"id": "x"}, {"id", "kind"}, where="experiment")


def test_the_error_names_where_it_came_from():
    with pytest.raises(ConfigurationError, match="sourceafis_java"):
        reject_unknown_keys({"nope": 1}, set(), where="sourceafis_java")


# ------------------------------------------------- applied to the real configs
#
# The helpers are only worth having where the files are actually read. Each case
# below is one of the five spellings spec section 47 names, applied to the
# experiment config the stage 4B run is defined by.

from pathlib import Path  # noqa: E402 - kept beside the tests that use it

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
NATIVE_CONFIG = REPO / "configs" / "experiments" / "sourceafis_native_full_v1.yaml"


def write_variant(tmp_path: Path, section: str, key: str, value) -> Path:
    document = yaml.safe_load(NATIVE_CONFIG.read_text(encoding="utf-8"))
    document[section][key] = value
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def load(path: Path):
    from fpbench.experiments.sourceafis_native_full import load_experiment_config

    return load_experiment_config(path, repository_root=REPO)


def test_the_real_config_still_loads():
    """The point of the hardening is that valid files are unaffected."""
    config = load(NATIVE_CONFIG)
    assert config.experiment_id == "sourceafis_native_full_v1"
    assert config.research_mode is True
    assert config.replicate_index == 0
    assert config.execution_profile.timeout_seconds == 60.0
    assert config.execution_profile.parameters["resolution_mode"] == "native"


@pytest.mark.parametrize(
    "section,key,value,expected",
    [
        ("runtime", "research_mode", "false", "boolean"),
        ("experiment", "replicate_index", 0.0, "exact integer"),
        ("execution", "deterministic_seed", "0", "exact integer"),
        ("execution", "timeout_seconds", "60", "number"),
        ("dataset", "require_verified_checksums", "true", "boolean"),
    ],
)
def test_a_coerced_value_is_refused_by_the_real_loader(
    tmp_path, section, key, value, expected
):
    with pytest.raises(ConfigurationError, match=expected):
        load(write_variant(tmp_path, section, key, value))


def test_a_duration_may_still_be_written_either_way(tmp_path):
    """60 and 60.0 are the same duration; "60" is not a duration."""
    assert load(
        write_variant(tmp_path, "execution", "timeout_seconds", 60.0)
    ).execution_profile.timeout_seconds == 60.0
