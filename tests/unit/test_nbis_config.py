"""What the NBIS adapter will and will not accept as a description of itself.

The rule this file exists for is that there is **no PATH lookup and no default
name**. ``mindtct`` on its own means whatever a machine happens to have installed
first — a distribution package, a stale build in ``/usr/local/bin``, somebody's
experiment — and none of those is the certified build a result would be
attributed to (docs/adr/0048, spec section 17).

The second rule is the division of labour with ``validate_environment``. A
configuration is wrong in *shape* wherever it is read, so shape is refused at
construction. A file that is merely absent is one fault of the run, reported as
UNAVAILABLE and never raised — the adapter contract requires that, and the
conformance suite checks it (spec section 48).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    KNOWN_KEYS,
    MINDTCT_ROLE,
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    NbisConfig,
)
from fpbench.core.errors import ConfigurationError

pytestmark = pytest.mark.nbis_contract


def settings(root: Path) -> dict[str, str]:
    return {
        "mindtct_executable": str(root / "bin" / "mindtct"),
        "bozorth3_executable": str(root / "bin" / "bozorth3"),
        "build_manifest": str(root / "nbis-build-manifest.json"),
    }


# ------------------------------------------------------------------- shape


def test_a_complete_configuration_is_accepted(tmp_path):
    config = NbisConfig.from_mapping(settings(tmp_path))
    assert config.mindtct_executable.is_absolute()
    assert config.research_mode is False


@pytest.mark.parametrize(
    "key", ["mindtct_executable", "bozorth3_executable", "build_manifest"]
)
def test_every_path_is_required(tmp_path, key):
    payload = settings(tmp_path)
    del payload[key]
    with pytest.raises(ConfigurationError, match="required"):
        NbisConfig.from_mapping(payload)


@pytest.mark.parametrize(
    "key", ["mindtct_executable", "bozorth3_executable", "build_manifest"]
)
def test_a_bare_command_name_is_refused(tmp_path, key):
    """The whole point: ``mindtct`` is not a path, it is a wish about PATH."""
    payload = settings(tmp_path)
    payload[key] = "mindtct"
    with pytest.raises(ConfigurationError, match="absolute"):
        NbisConfig.from_mapping(payload)


def test_a_relative_path_is_refused(tmp_path):
    payload = settings(tmp_path)
    payload["mindtct_executable"] = "build/nbis-5.0.0/abc/bin/mindtct"
    with pytest.raises(ConfigurationError, match="absolute"):
        NbisConfig.from_mapping(payload)


def test_two_roles_may_not_be_the_same_file(tmp_path):
    payload = settings(tmp_path)
    payload["bozorth3_executable"] = payload["mindtct_executable"]
    with pytest.raises(ConfigurationError, match="same file"):
        NbisConfig.from_mapping(payload)


def test_a_directory_is_not_a_tool(tmp_path):
    directory = tmp_path / "bin"
    directory.mkdir()
    payload = settings(tmp_path)
    payload["mindtct_executable"] = str(directory)
    with pytest.raises(ConfigurationError, match="regular file"):
        NbisConfig.from_mapping(payload)


def test_a_symlinked_tool_is_refused(tmp_path):
    real = tmp_path / "real-mindtct"
    real.write_text("#!/bin/sh\n", encoding="ascii")
    link = tmp_path / "linked-mindtct"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):  # pragma: no cover - platform policy
        pytest.skip("this platform will not create symlinks")
    payload = settings(tmp_path)
    payload["mindtct_executable"] = str(link)
    with pytest.raises(ConfigurationError, match="symlink"):
        NbisConfig.from_mapping(payload)


def test_a_missing_file_is_not_a_construction_error(tmp_path):
    """It is an unavailable environment, which is a different thing entirely."""
    config = NbisConfig.from_mapping(settings(tmp_path))
    assert set(config.missing_runtime_assets()) == set(RUNTIME_ASSET_ROLES)


# ------------------------------------------------------------------- types


def test_an_unknown_key_is_refused(tmp_path):
    payload = settings(tmp_path)
    payload["threshold"] = "40"
    with pytest.raises(ConfigurationError, match="unknown"):
        NbisConfig.from_mapping(payload)


@pytest.mark.parametrize(
    "key",
    [
        "boost",
        "m1",
        "threshold",
        "max_minutiae",
        "min_minutiae",
        "reverse_match",
        "average_directions",
        "cache_templates",
        "persist_templates",
    ],
)
def test_no_algorithmic_option_can_be_configured(tmp_path, key):
    """Section 15: these are not knobs of this identity, so they do not exist."""
    assert key not in KNOWN_KEYS
    payload = settings(tmp_path)
    payload[key] = "anything"
    with pytest.raises(ConfigurationError, match="unknown"):
        NbisConfig.from_mapping(payload)


def test_a_quoted_boolean_is_refused(tmp_path):
    """``research_mode: "false"`` is true under ``bool()`` and must not pass."""
    payload = settings(tmp_path)
    payload["research_mode"] = "false"
    with pytest.raises(ConfigurationError, match="boolean"):
        NbisConfig.from_mapping(payload)


def test_research_mode_must_be_a_real_bool(tmp_path):
    with pytest.raises(ConfigurationError, match="boolean"):
        NbisConfig(
            mindtct_executable=Path(settings(tmp_path)["mindtct_executable"]),
            bozorth3_executable=Path(settings(tmp_path)["bozorth3_executable"]),
            build_manifest=Path(settings(tmp_path)["build_manifest"]),
            research_mode=1,  # type: ignore[arg-type]
        )


# ------------------------------------------------------------------- roles


def test_the_three_roles_are_declared_in_order():
    assert RUNTIME_ASSET_ROLES == (
        "nbis_mindtct_executable",
        "nbis_bozorth3_executable",
        "nbis_build_manifest",
    )
    assert PRIMARY_RUNTIME_ASSET_ROLE == "nbis_mindtct_executable"


def test_the_runtime_assets_cover_all_three_roles(tmp_path):
    assets = NbisConfig.from_mapping(settings(tmp_path)).runtime_assets()
    assert set(assets) == {MINDTCT_ROLE, BOZORTH3_ROLE, BUILD_MANIFEST_ROLE}


def test_an_executable_bit_is_required_of_the_tools_but_not_the_manifest(tmp_path):
    """The manifest is read, not run. On Windows there is no bit to check."""
    if sys.platform == "win32":
        pytest.skip("Windows has no executable bit to withhold")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("mindtct", "bozorth3"):
        (binaries / name).write_text("#!/bin/sh\n", encoding="ascii")
    (tmp_path / "nbis-build-manifest.json").write_text("{}", encoding="utf-8")
    config = NbisConfig.from_mapping(settings(tmp_path))
    assert set(config.missing_runtime_assets()) == {MINDTCT_ROLE, BOZORTH3_ROLE}

    (binaries / "mindtct").chmod(0o755)
    (binaries / "bozorth3").chmod(0o755)
    assert config.missing_runtime_assets() == ()
