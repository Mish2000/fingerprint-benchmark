"""Fetch the sealed NIST archives with an identified HTTP client.

The original build script is part of historical build fingerprints. This
launcher changes only the request's User-Agent; the original fetch command
still owns the URLs, cache, quarantine, size, SHA-256 and archive checks.
"""

from __future__ import annotations

import argparse
import runpy
import urllib.request
from pathlib import Path

BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "integrations/nbis/build.py"
USER_AGENT = (
    "fpbench/0.1.0 "
    "(research reproducibility; https://github.com/Mish2000/fingerprint-benchmark)"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, help="archive cache outside the repository")
    arguments = parser.parse_args(argv)

    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", USER_AGENT)]
    urllib.request.install_opener(opener)

    command = [] if arguments.cache is None else ["--cache", str(arguments.cache)]
    command.append("fetch")
    return runpy.run_path(str(BUILD_SCRIPT))["main"](command)


if __name__ == "__main__":
    raise SystemExit(main())
