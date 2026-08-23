"""Every committed Stage 19/20 marker is what its builder makes of the evidence.

A marker concludes: it says the run is complete, the algorithm established, the
publication eligible. What makes that checkable is not the fingerprint over its
own bytes — a document can be internally consistent and still not follow from
anything — but the property that a reader can take the documents beside it, run
the current builder, and get the same file back.

That property had quietly broken. The markers were re-fingerprinted as the
validator gained checks, so each carried a ``source_fingerprint`` naming a tree
whose builder computed a *different* condition map from the one in the body. The
fingerprint matched and the marker did not follow — the worst of the two ends,
because it looks verified.

So the property is a test. For each stage: read the published inputs, feed the
marker's own ``created_utc`` back in as the clock, build, and compare byte for
byte. ``scripts/reissue_stage19_20_markers.py`` is what makes it pass, and this
is what stops it drifting again.

**The clock is the only injected thing.** Everything else — the gate documents,
the run binding, the integrity document, the diagnostics, the evidence digests,
the source fingerprint, the predecessor markers — is read from the repository
exactly as a reader would read it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from reissue_stage19_20_markers import STAGES, render  # noqa: E402


@pytest.mark.parametrize(
    "stage", STAGES, ids=[label for label, _relative, _name, _rebuild in STAGES]
)
def test_the_committed_marker_is_the_builders_own_output(stage) -> None:
    label, relative, name, rebuild = stage
    directory = REPOSITORY_ROOT / relative
    path = directory / name
    committed = path.read_bytes()
    stored = json.loads(committed.decode("utf-8"))

    rebuilt = render(rebuild(directory, stored["created_utc"]))

    if rebuilt != committed:
        difference = sorted(
            key
            for key in set(stored) | set(json.loads(rebuilt.decode("utf-8")))
            if stored.get(key) != json.loads(rebuilt.decode("utf-8")).get(key)
        )
        pytest.fail(
            f"Stage {label}'s marker is not what the current builder makes of "
            f"the evidence beside it. Fields that differ: {difference}. Run "
            "python scripts/reissue_stage19_20_markers.py"
        )


@pytest.mark.parametrize(
    "stage", STAGES, ids=[label for label, _relative, _name, _rebuild in STAGES]
)
def test_the_clock_is_the_only_thing_that_moves(stage) -> None:
    """Twice with the same instant is the same document; a different one differs.

    Without the second half, a builder that ignored ``created_utc`` altogether
    would pass the test above and be no more reproducible than before.
    """
    label, relative, name, rebuild = stage
    directory = REPOSITORY_ROOT / relative
    stored = json.loads((directory / name).read_text(encoding="utf-8"))

    once = render(rebuild(directory, stored["created_utc"]))
    twice = render(rebuild(directory, stored["created_utc"]))
    assert once == twice, f"Stage {label} is not deterministic at a fixed instant"

    other = render(rebuild(directory, "2000-01-01T00:00:00Z"))
    assert other != once, f"Stage {label} ignores the clock it is given"


@pytest.mark.parametrize(
    "stage", STAGES, ids=[label for label, _relative, _name, _rebuild in STAGES]
)
def test_the_marker_carries_the_conditions_the_builder_checks(stage) -> None:
    """The conditions live in the marker, not only in a test beside it.

    ``at_least_one_score`` and ``no_unclassified_failure`` were checks the
    builder made and the published document did not mention, so a reader had to
    take the repository's word that they had been applied to this run.
    """
    label, relative, name, _rebuild = stage
    marker = json.loads((REPOSITORY_ROOT / relative / name).read_text(encoding="utf-8"))
    conditions = marker.get("algorithm_5_conditions") or marker["completion_conditions"]
    for required in ("at_least_one_score", "no_unclassified_failure"):
        assert required in conditions, (
            f"Stage {label} does not publish {required} among its conditions"
        )
        assert conditions[required] is True, (
            f"Stage {label} published {required}={conditions[required]!r} and "
            "still concluded"
        )


@pytest.mark.parametrize(
    "stage", STAGES, ids=[label for label, _relative, _name, _rebuild in STAGES]
)
def test_a_conclusion_follows_from_every_condition(stage) -> None:
    """Nothing may be established over a condition the marker itself denies."""
    label, relative, name, _rebuild = stage
    marker = json.loads((REPOSITORY_ROOT / relative / name).read_text(encoding="utf-8"))
    conditions = marker.get("algorithm_5_conditions") or marker["completion_conditions"]
    unmet = sorted(key for key, value in conditions.items() if value is False)
    if not unmet:
        return
    for claim in (
        "algorithm_5_established",
        "publication_eligible",
        "opens_common_calibration",
        "preferred_final_fifth",
    ):
        assert marker.get(claim) in (False, None), (
            f"Stage {label} publishes {claim}={marker.get(claim)!r} with "
            f"{unmet} unmet"
        )


def test_the_chain_binds_the_markers_that_are_committed() -> None:
    """19B binds 19A and 20B binds 19B, at the fingerprints now on disk.

    Re-issuing one marker moves its fingerprint, so a rebuild that stopped short
    of the chain would leave a downstream marker pointing at a version of its
    predecessor that no longer exists.
    """
    published = {}
    for label, relative, name, _rebuild in STAGES:
        marker = json.loads(
            (REPOSITORY_ROOT / relative / name).read_text(encoding="utf-8")
        )
        key = next(k for k in marker if k.endswith("_finalization_fingerprint"))
        published[label] = (marker, marker[key])

    for label, (marker, _fingerprint) in published.items():
        for bound in marker.get("bound_markers", []):
            stage = str(bound.get("stage"))
            if stage not in published:
                continue
            assert bound.get("finalization_fingerprint") == published[stage][1], (
                f"Stage {label} binds Stage {stage} at "
                f"{bound.get('finalization_fingerprint')!r}, and the committed "
                f"Stage {stage} marker publishes {published[stage][1]!r}"
            )
