"""The operator's end of Stage 15A: run it, then publish what it produced.

Five commands, in the order they are meant to be used:

.. code-block:: text

    preflight   check every input, write nothing
    prepare     write the run, the plan and the runtime binding
    execute     the 6,000 comparisons, resumable
    documents   derive the seven readable evidence files
    publish     write the marker over evidence that is already committed

``prepare`` refuses a dirty working tree and ``execute`` refuses to resume under
a different source commit, so the sequence has one rule that is easy to state and
easy to get wrong: **commit before ``prepare``, and do not commit again until
``execute`` has finished.** A commit in the middle produces a run whose results
came from two revisions, which is not one run.

``documents`` and ``publish`` are two writes on purpose, and the pause between
them is a commit. That is what makes the marker a statement about bytes that are
in Git rather than about whatever happened to be on disk.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fpbench.core.stage15a_errors import Stage15AFinalizationError
from fpbench.experiments import stage15a_finalization as finalization
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT, read_run_pointer
from fpbench.experiments.stage15a_canonical500_full import (
    DEFAULT_WORKSPACE,
    execute_stage15a_canonical500_run,
    inspect_stage15a_canonical500_experiment,
    load_stage15a_canonical500_config,
    prepare_stage15a_canonical500_run,
    preflight_stage15a_canonical500_run,
)

__all__ = ["resolve_run_id", "build_integrity", "main"]


def resolve_run_id(*, workspace: Path, run_id: str | None = None) -> str:
    if run_id:
        return run_id
    return read_run_pointer(Path(workspace), frozen.EXPERIMENT_ID)


def build_integrity(
    *, workspace: Path, repository_root: Path, run_id: str
) -> tuple[dict[str, Any], Any]:
    """Re-derive the validation pass from the stored results, and shape it."""
    from fpbench.experiments.sd300_inputs import load_sd300_inputs
    from fpbench.experiments.stage15a_validation import (
        SD300_CANONICAL500_INPUT_SET,
        validate_fingerprints_matching_result_set,
    )
    from fpbench.storage.plan_store import PlanStore
    from fpbench.storage.result_store import ResultStore

    workspace = Path(workspace)
    config = load_stage15a_canonical500_config(repository_root=Path(repository_root))
    result_store = ResultStore(workspace)
    inputs = load_sd300_inputs(
        workspace=workspace,
        dataset_root=None,
        dataset_config=config.dataset_config,
        protocol_config=config.protocol_config,
        require_verified_checksums=config.require_verified_checksums,
        allow_creation=False,
    )
    report = validate_fingerprints_matching_result_set(
        run=result_store.read_run(run_id),
        plan=PlanStore(workspace).read_plan(run_id),
        pairs=inputs.pairs,
        images=inputs.images,
        result_store=result_store,
        runtime_reference=result_store.read_runtime_reference(run_id),
        preparation=None,
        expected_input_set=SD300_CANONICAL500_INPUT_SET,
    )
    return finalization.build_result_integrity_document(report, run_id=run_id), report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "preflight"
    root = Path(".")
    workspace = DEFAULT_WORKSPACE

    if command == "preflight":
        print(
            json.dumps(
                preflight_stage15a_canonical500_run(repository_root=root),
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return 0

    if command == "prepare":
        prepared = prepare_stage15a_canonical500_run(
            workspace=workspace, repository_root=root
        )
        print(f"run    {prepared.run.run_id}")
        print(f"plan   {prepared.plan.plan_id}")
        print(f"jobs   {len(prepared.plan.jobs)}")
        return 0

    if command == "execute":
        limit = int(argv[1]) if len(argv) > 1 else None
        summary = execute_stage15a_canonical500_run(
            workspace=workspace, repository_root=root, max_new_jobs=limit
        )
        print(
            json.dumps(
                {
                    "run_id": getattr(summary, "run_id", None),
                    "executed": getattr(summary, "executed_jobs", None),
                    "skipped": getattr(summary, "skipped_jobs", None),
                    "failed": getattr(summary, "failed_jobs", None),
                },
                indent=2,
                default=str,
            )
        )
        return 0

    if command == "status":
        state = inspect_stage15a_canonical500_experiment(
            workspace=workspace, repository_root=root
        )
        print(state.status, state.run_id)
        return 0

    if command in {"integrity", "documents", "publish"}:
        run_id = resolve_run_id(
            workspace=workspace, run_id=argv[1] if len(argv) > 1 else None
        )
        from fpbench.core.errors import StorageError
        from fpbench.storage.plan_store import PlanStore
        from fpbench.storage.result_set_store import ResultSetStore

        plan = PlanStore(workspace).read_plan(run_id)
        # ``read_result_set`` returns (manifest, entries); the identity lives on
        # the manifest. Reading it off the tuple raised AttributeError, and the
        # bare ``except Exception`` below turned that into "no result set" — so a
        # run that had one published ``result_set_id: null``. Only a genuine
        # absence may reach the fallback, which is why the catch is narrow now.
        try:
            result_set_id = ResultSetStore(workspace).read_manifest(run_id).result_set_id
        except StorageError:  # absent before finalization
            result_set_id = None
        integrity, report = build_integrity(
            workspace=workspace, repository_root=root, run_id=run_id
        )

        if command == "integrity":
            print(json.dumps(integrity, indent=2, sort_keys=True, default=str))
            return 0 if report.is_clean else 1

        if command == "documents":
            written = finalization.publish_stage15a_evidence(
                repository_root=root,
                run_id=run_id,
                plan_id=plan.plan_id,
                result_set_id=result_set_id,
                integrity=integrity,
            )
            for name in sorted(written):
                print(f"wrote {frozen.EVIDENCE_DIRECTORY.as_posix()}/{name}")
            print(
                "\nCommit these, then run `publish` — the marker is a statement "
                "about committed bytes."
            )
            return 0

        path = finalization.publish_stage15a_finalization(
            repository_root=root,
            run_id=run_id,
            plan_id=plan.plan_id,
            result_set_id=result_set_id,
            integrity=integrity,
        )
        marker = json.loads(path.read_text(encoding="utf-8"))
        print(f"wrote {path.relative_to(root) if path.is_absolute() else path}")
        print(f"outcome              {marker['outcome']}")
        print(f"score-bearing        {marker['result_set_is_score_bearing']}")
        print(f"algorithm 5          {marker['algorithm_5_established']}")
        print(f"opens calibration    {marker['opens_common_calibration']}")
        return 0

    if command == "verify":
        print(
            json.dumps(
                finalization.verify_stage15a_evidence(repository_root=root),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(
        f"unknown command {command!r}; expected preflight, prepare, execute, "
        "status, integrity, documents, publish or verify",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
