"""One pinned SourceAFIS score, so that a silent change cannot happen.

The value below is not meaningful as biometrics — it is two procedural textures
compared with each other. It is meaningful as a **canary**: if it moves, something in
the chain moved with it, and every SourceAFIS result already on disk was produced by a
different pipeline than the one running now.

When this test fails, work through the list before touching the number:

1. the SourceAFIS dependency version in `integrations/sourceafis-java/pom.xml`;
2. the bridge's own code — extraction order, matcher construction, score handling;
3. the JDK (the reference environment is Java 17);
4. the fixture bytes (their digests are pinned in
   `tests/fixtures/sourceafis/README.md`);
5. the DPI passed for each side;
6. the left/right order — left is the probe, right the candidate.

Only once one of those explains the change should the expected value be updated, and
the change should be described in the commit that does it.
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import ExecutionStatus
from sourceafis_support import comparison_context, prepared_image, require_bridge
from synthetic_ridges import whorl_png, write_fixture

pytestmark = pytest.mark.sourceafis

#: Reference environment: SourceAFIS 3.18.1, bridge 1, Java 17, fixture seed 1 at
#: 500 ppi compared with itself.
SELF_500_SEED1 = 23.165117663467225

#: Two different procedural textures share no minutiae, so SourceAFIS finds nothing
#: in common. Exactly zero is itself a stable, pinnable answer.
CROSS_500_SEED1_SEED6 = 0.0

TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def adapter():
    instance, _ = require_bridge()
    return instance


def test_the_self_comparison_score_is_pinned(adapter, tmp_path):
    image = write_fixture(tmp_path, "a.png", whorl_png(500, 1))
    left = prepared_image(image, 500, "img_a")
    right = prepared_image(image, 500, "img_a")

    result = adapter.compare(left, right, comparison_context(tmp_path))

    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == pytest.approx(SELF_500_SEED1, abs=TOLERANCE)


def test_the_cross_comparison_score_is_pinned(adapter, tmp_path):
    left = write_fixture(tmp_path, "a.png", whorl_png(500, 1))
    right = write_fixture(tmp_path, "b.png", whorl_png(500, 6))

    result = adapter.compare(
        prepared_image(left, 500, "img_a"),
        prepared_image(right, 500, "img_b"),
        comparison_context(tmp_path),
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == pytest.approx(CROSS_500_SEED1_SEED6, abs=TOLERANCE)


def test_the_reference_environment_is_the_one_being_measured(adapter):
    """The pin above only means anything on the environment it was taken from."""
    report = adapter.validate_environment()
    assert report.dependencies["sourceafis"] == "3.18.1"
    assert report.dependencies["bridge.version"] == "1"
    major = int(report.runtime["java.version"].split(".")[0])
    assert major >= 17, "the pinned score was taken on Java 17"


def test_the_fixture_bytes_are_the_pinned_ones():
    """A regression score is only comparable against identical input."""
    import hashlib

    assert hashlib.sha256(whorl_png(500, 1)).hexdigest() == (
        "5930ceb5b634259001f1b18cb968340694c6f1e9698734057acbd5dbd5709ab5"
    )
    assert hashlib.sha256(whorl_png(500, 6)).hexdigest() == (
        "1300ca628f22ca37e716c7270e4cc68ce5a8f0d92b884d3dce55bfb9892d8fdc"
    )
