"""What ties each published licence observation to the bytes beside it.

``ThirdPartyUsageRecord`` carries an ``UpstreamIdentity`` and a list of licence
evidence locators, and nothing in the schema says the two are about one thing.
:func:`fpbench.provenance.upstream_binding.derive_identity_link` reads the
pairing out of the two documents where it is there to read — a licence fetched
from the upstream's own URL proves its own pairing — and says
``ASSERTED_BY_THE_PUBLISHER`` where it is not.

The point of this file is that the answer is *published* rather than assumed.
Nine of the twelve records in ``evidence/`` rest on the author having checked,
and that was previously invisible: the record looked exactly like the three that
prove themselves. The list below makes it a fact a reader can see, and one that
can only shrink — a new component must derive its link or be added here
deliberately.

This checks the committed evidence, not the code paths;
``test_upstream_identity_is_bound.py`` is the code-path side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.provenance.upstream_binding import IdentityLinkBasis

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"

#: The published records whose licence evidence does not, on its own, say which
#: upstream it was read over. Every one is a component acquired outside a
#: version-controlled URL: a Drive checkpoint, a locally compiled build, a
#: dataset ordered on media, a jar assembled here.
#:
#: An entry may be removed — by re-recording the evidence at a locator inside
#: the upstream — and none may be added without this test failing first.
_RESTS_ON_THE_PUBLISHERS_ASSERTION = frozenset(
    {
        "NBIS 5.0.0, compiled locally",
        "NIST Biometric Image Software 5.0.0",
        "NIST Biometric Image Software Test 5.0.0",
        "NIST Special Database 300",
        "SourceAFIS for Java",
        "fixed-length extractor checkpoint",
        "flx CPU runtime bundle",
        "fpbench SourceAFIS bridge, shaded",
        "the SourceAFIS bridge dependency closure",
    }
)


def _records() -> list[tuple[Path, dict]]:
    """Every third-party usage record published anywhere under ``evidence/``."""
    found: list[tuple[Path, dict]] = []
    for path in sorted(EVIDENCE.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - evidence parses in CI
            continue

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if "upstream_identity" in node and "license_evidence_locators" in node:
                    found.append((path, node))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
    return found


def _basis(record: dict) -> IdentityLinkBasis:
    """The published record's basis, derived the same way the code derives it.

    Re-implemented over the raw JSON rather than reconstructing model objects:
    the published bytes are the subject, and rebuilding a ``LicenseObservation``
    from them would test the constructor instead.
    """
    identity = record["upstream_identity"]
    locators = [
        str(item).strip()
        for item in record.get("license_evidence_locators") or []
        if str(item).strip()
    ]
    upstream = str(identity.get("upstream_locator") or "").strip()
    if upstream:
        for locator in locators:
            # One direction only, matching the derivation. Evidence at a
            # *parent* of the upstream reads a repository-wide LICENSE as proof
            # of identity for every component beneath it, which is the mistaken
            # pairing the binding exists to detect. This re-implementation used
            # to accept it and was therefore weaker than the code it checks.
            if locator == upstream or locator.startswith(upstream.rstrip("/") + "/"):
                return IdentityLinkBasis.EVIDENCE_LOCATOR
    commit = str(identity.get("upstream_commit") or "").strip()
    if len(commit) >= 40 and any(commit in locator for locator in locators):
        return IdentityLinkBasis.UPSTREAM_COMMIT
    if identity.get("identity_established") is False:
        # Nothing links the two documents and nothing was acquired. That is a
        # fourth state, not an assertion: there is no act to attest to, and
        # counting it as one would put six components that nobody downloaded
        # on a list of things somebody vouched for.
        return IdentityLinkBasis.UNRESOLVED_DOCUMENTATION_ONLY
    return IdentityLinkBasis.PUBLISHER_ASSERTION


def test_there_are_published_records_to_check() -> None:
    """An empty scan finds no violation and is indistinguishable from clean."""
    assert _records(), "no third-party usage record was found under evidence/"


def test_no_new_record_rests_on_an_assertion_nobody_declared() -> None:
    """The list can only shrink.

    A component added with a locally recorded licence file is easy to publish
    and impossible to check afterwards. Naming it here is the deliberate act;
    the alternative — a silence that reads like a derived link — is what this
    test exists to prevent.
    """
    asserted = sorted(
        {
            str(record["upstream_identity"]["upstream_name"])
            for _, record in _records()
            if _basis(record) is IdentityLinkBasis.PUBLISHER_ASSERTION
        }
    )
    new = sorted(set(asserted) - _RESTS_ON_THE_PUBLISHERS_ASSERTION)
    assert not new, (
        f"{new} publish a licence observation whose evidence does not say which "
        "upstream it was read over. Record the evidence at a locator inside the "
        "upstream, or add the component to _RESTS_ON_THE_PUBLISHERS_ASSERTION "
        "with the reason it cannot be"
    )


def test_the_declared_list_still_describes_the_evidence() -> None:
    """An entry that became derivable must be deleted, not carried.

    The mirror of the test above: if somebody re-records a licence at the
    upstream's own URL, the exemption stops being true and has to go.
    """
    asserted = {
        str(record["upstream_identity"]["upstream_name"])
        for _, record in _records()
        if _basis(record) is IdentityLinkBasis.PUBLISHER_ASSERTION
    }
    names = {
        str(record["upstream_identity"]["upstream_name"]) for _, record in _records()
    }
    stale = sorted(
        name
        for name in _RESTS_ON_THE_PUBLISHERS_ASSERTION
        if name in names and name not in asserted
    )
    assert not stale, (
        f"{stale} now derive their link from the published evidence — remove "
        "them from _RESTS_ON_THE_PUBLISHERS_ASSERTION"
    )


def test_no_record_reads_its_licence_out_of_another_components_upstream() -> None:
    """The failure the binding exists for, checked against what was published.

    A record carrying upstream X's licence beside upstream Y's bytes is the
    thing ``bind_component`` refuses. Here it is checked from the other end: if
    a record's evidence locator sits inside *another* published component's
    upstream, the record names the wrong bytes.
    """
    records = _records()
    upstreams = {
        str(record["upstream_identity"]["upstream_name"]): str(
            record["upstream_identity"].get("upstream_locator") or ""
        ).strip()
        for _, record in records
    }
    offending: list[str] = []
    for path, record in records:
        name = str(record["upstream_identity"]["upstream_name"])
        mine = upstreams[name]
        for locator in record.get("license_evidence_locators") or []:
            locator = str(locator).strip()
            if not locator:
                continue
            for other, other_locator in upstreams.items():
                if other == name or not other_locator or other_locator == mine:
                    continue
                if locator.startswith(other_locator.rstrip("/") + "/"):
                    offending.append(
                        f"{path.name}: {name!r} reads {locator!r}, which is "
                        f"inside {other!r}"
                    )
    assert not offending, offending


#: Only the two states that are *derivations*. ``PUBLISHER_ASSERTION`` and
#: ``UNRESOLVED_DOCUMENTATION_ONLY`` are what the derivation returns when it
#: finds nothing, which is the opposite of a route being exercised.
_DERIVATION_ROUTES = (
    IdentityLinkBasis.EVIDENCE_LOCATOR,
    IdentityLinkBasis.UPSTREAM_COMMIT,
)


@pytest.mark.parametrize("basis", _DERIVATION_ROUTES)
def test_at_least_one_record_derives_its_link_each_way(basis: IdentityLinkBasis) -> None:
    """Both derivation routes are exercised by real published data.

    Without this, a derivation that silently stopped working would look like a
    repository in which nothing happens to be derivable.
    """
    found = [
        str(record["upstream_identity"]["upstream_name"])
        for _, record in _records()
        if _basis(record) is basis
    ]
    assert found, f"no published record derives its link by {basis.value}"


def test_the_published_basis_is_the_one_the_evidence_derives() -> None:
    """The strongest form: two derivations over the same bytes must agree.

    This file re-derives the basis from the published JSON; the record carries
    the basis its publisher derived from the live documents. Comparing them
    catches drift in either -- a re-implementation that quietly stops matching
    reads exactly like a repository in which nothing is wrong.
    """
    mismatches = []
    for path, record in _records():
        published = record.get("identity_link_basis")
        if published is None:
            continue
        rederived = _basis(record).value
        if published != rederived:
            mismatches.append(
                f"{path.name}: {record.get('record_id', '?')} publishes "
                f"{published} and its own evidence derives {rederived}"
            )
    assert not mismatches, mismatches
