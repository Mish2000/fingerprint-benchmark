"""The identified transport retains the original sealed-archive checks."""

from __future__ import annotations

import hashlib
import io
import runpy
import urllib.error
import urllib.request
import urllib.response
import zipfile
from pathlib import Path

import pytest

from fpbench.adapters.nbis.build_manifest import NbisArchiveLock, NbisSourceLock

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.nbis_contract


@pytest.fixture
def transport(monkeypatch):
    build = runpy.run_path(str(ROOT / "integrations/nbis/build.py"))
    launcher = runpy.run_path(str(ROOT / "scripts/fetch_nbis_archives.py"))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("fixture.txt", "synthetic transport fixture")
    payload = output.getvalue()
    entries = {
        name: NbisArchiveLock(
            version="5.0.0",
            source="official_nist_nigos",
            url=f"https://nigos.nist.gov/nist/nbis/{filename}",
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
        for name, filename in (
            ("release", "nbis_v5_0_0.zip"), ("tests", "test_v5_0_0.zip")
        )
    }
    lock = NbisSourceLock(schema_version="1", **entries)
    monkeypatch.setitem(build["main"].__globals__, "require_sealed_lock", lambda: lock)
    monkeypatch.setattr(runpy, "run_path", lambda path: build)
    state = {"payload": payload, "requests": [], "fail": False}

    class NistFixture(urllib.request.HTTPSHandler):
        def https_open(self, request):
            state["requests"].append(request)
            if state["fail"] or request.get_header("User-agent") != launcher["USER_AGENT"]:
                raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
            response = urllib.response.addinfourl(
                io.BytesIO(state["payload"]), {}, request.full_url, 200
            )
            response.msg = "OK"
            return response

    real_build_opener = urllib.request.build_opener
    monkeypatch.setattr(
        urllib.request, "build_opener", lambda: real_build_opener(NistFixture())
    )
    # Restore urllib's process-wide opener when the test finishes.
    monkeypatch.setattr(urllib.request, "_opener", None)
    return build, launcher, state


def test_default_client_is_refused_but_identified_fetch_verifies_both_archives(
    transport, tmp_path
):
    build, launcher, state = transport
    cache = tmp_path / "cache"
    assert build["main"](["--cache", str(cache), "fetch"]) == 2
    assert launcher["main"](["--cache", str(cache)]) == 0
    for path in build["cache_paths"](cache).values():
        assert path.read_bytes() == state["payload"]
    count = len(state["requests"])
    assert launcher["main"](["--cache", str(cache)]) == 0
    assert len(state["requests"]) == count


def test_wrong_bytes_are_rejected_and_quarantine_is_removed(transport, tmp_path):
    _, launcher, state = transport
    state["payload"] = b"not the locked archive"
    cache = tmp_path / "cache"
    assert launcher["main"](["--cache", str(cache)]) == 2
    assert not list(cache.rglob("*.zip"))
    assert not list(cache.rglob("*.partial"))


def test_http_failure_remains_a_failure_without_a_fallback(transport, tmp_path):
    _, launcher, state = transport
    state["fail"] = True
    cache = tmp_path / "cache"
    assert launcher["main"](["--cache", str(cache)]) == 2
    assert len(state["requests"]) == 1
    assert not list(cache.rglob("*.partial"))


def test_invalid_existing_cache_is_preserved_and_refused(transport, tmp_path):
    build, launcher, state = transport
    cache = tmp_path / "cache"
    target = build["cache_paths"](cache)["release"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"invalid previous cache")
    assert launcher["main"](["--cache", str(cache)]) == 2
    assert target.read_bytes() == b"invalid previous cache"
    assert not state["requests"]
