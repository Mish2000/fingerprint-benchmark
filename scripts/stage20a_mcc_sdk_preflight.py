"""Operator entry point for Stage 20A MCC SDK v2.0 qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fpbench.experiments.stage20a_mcc_sdk import (
    acquire_official_artifact,
    extract_official_artifact,
    publish_evidence,
    run_qualification_probe,
    verify_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("acquire", "extract", "probe", "publish", "all", "verify")
    )
    parser.add_argument("--acquisition-utc")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    if args.command in {"acquire", "all"}:
        print(
            acquire_official_artifact(
                repository_root=root, acquisition_utc=args.acquisition_utc
            )
        )
    if args.command in {"extract", "all"}:
        print(extract_official_artifact(repository_root=root))
    if args.command in {"probe", "all"}:
        print(run_qualification_probe(repository_root=root))
    if args.command in {"publish", "all"}:
        print(publish_evidence(repository_root=root))
    if args.command == "verify":
        print(json.dumps(verify_evidence(repository_root=root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
