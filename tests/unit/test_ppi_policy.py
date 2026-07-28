from __future__ import annotations

import pytest

from fpbench.core.errors import ConfigurationError
from fpbench.datasets.sd300 import ppi_policy


@pytest.mark.parametrize(
    "release,ppi", [("SD300A", 500), ("SD300B", 1000), ("SD300C", 2000)]
)
def test_effective_matches_nominal_for_every_release(release, ppi):
    assert ppi_policy.nominal_ppi(release) == ppi
    assert ppi_policy.effective_ppi(release) == ppi


def test_5080_is_a_documented_sd300c_defect():
    """See docs/adr/0004: 5080 is the scanner's optical resolution, not the image's."""
    assert ppi_policy.is_known_metadata_anomaly("SD300C", 5080)


def test_the_same_value_is_not_excused_in_other_releases():
    assert not ppi_policy.is_known_metadata_anomaly("SD300A", 5080)
    assert not ppi_policy.is_known_metadata_anomaly("SD300B", 5080)


def test_an_undocumented_value_is_never_excused():
    assert not ppi_policy.is_known_metadata_anomaly("SD300C", 1200)


def test_unknown_release_is_rejected():
    with pytest.raises(ConfigurationError):
        ppi_policy.effective_ppi("SD300D")
