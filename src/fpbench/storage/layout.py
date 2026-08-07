"""Where a run's artefacts live on disk.

One definition, shared by every store that writes under a run, so that the
result store and the plan store cannot drift into disagreeing about where a run
directory is::

    <workspace>/results/<run_id>/
    ├── run.json
    ├── runtime.json        which runtime bundle produced these results
    ├── plan/
    │   ├── plan.json
    │   └── jobs.parquet
    ├── raw/jobs/<job_id>.parquet
    ├── result-set/
    │   ├── manifest.json
    │   └── results.parquet
    ├── derived/            regenerable: progress, audit snapshots, summaries
    ├── completion.json
    └── research-receipt.json

Runtime bundles are not run-scoped. One bundle can back many runs, and its
identity is its contents rather than the run that first materialised it::

    <workspace>/runtime/bundles/<bundle_id>/
    ├── bundle.json
    └── assets/<filename>

What an experiment pinned is filed by experiment, run and definition id, so that
two policies over the same decisions can coexist::

    <workspace>/derivations/<experiment_id>/<run_id>/
    ├── definitions/<definition_id>/definition.json
    └── current-<kind>.json      a pointer to the active one
"""

from __future__ import annotations

from pathlib import Path

from fpbench.core.identifiers import validate_id

__all__ = [
    "results_root",
    "run_directory",
    "derived_directory",
    "result_set_directory",
    "runtime_root",
    "runtime_bundles_root",
    "runtime_bundle_directory",
    "runtime_bundle_assets_directory",
    "decisions_root",
    "decision_set_directory",
    "eligibility_directory",
    "evaluation_views_directory",
    "evaluation_view_directory",
    "evaluations_root",
    "metric_set_directory",
    "derivations_root",
    "derivation_experiment_directory",
    "definitions_directory",
    "definition_directory",
    "prepared_images_root",
    "prepared_image_blobs_root",
    "prepared_image_blob_path",
    "prepared_image_pending_directory",
    "prepared_image_set_directory",
    "paired_evaluations_root",
    "paired_evaluation_directory",
    "calibration_root",
    "calibration_protocols_directory",
    "calibration_source_bindings_directory",
    "calibration_operating_points_directory",
    "calibration_receipts_directory",
    "calibration_finalizations_directory",
    "VIEW_DIRECTORY_NAMES",
]

#: Where each view lives inside a decision set. Fixed names rather than the
#: view id, because the id changes whenever its contents do and a reader looking
#: for "the conditional view" should not have to know this run's digest.
VIEW_DIRECTORY_NAMES = {
    "plain_roll_mated_unconditional_v1": "plain-roll-mated-unconditional",
    "plain_roll_mated_both_self_match_v1": "plain-roll-mated-both-self-match",
    "plain_roll_non_mated_same_subject_cyclic_v1": "plain-roll-non-mated-sanity",
}


def results_root(root: Path) -> Path:
    return Path(root) / "results"


def run_directory(root: Path, run_id: str) -> Path:
    return results_root(root) / validate_id(run_id)


def derived_directory(root: Path, run_id: str) -> Path:
    """Regenerable artefacts. Everything here may be deleted or overwritten."""
    return run_directory(root, run_id) / "derived"


def result_set_directory(root: Path, run_id: str) -> Path:
    """The immutable identity of this run's raw results (docs/adr/0019)."""
    return run_directory(root, run_id) / "result-set"


def runtime_root(root: Path) -> Path:
    return Path(root) / "runtime"


def runtime_bundles_root(root: Path) -> Path:
    return runtime_root(root) / "bundles"


def runtime_bundle_directory(root: Path, bundle_id: str) -> Path:
    return runtime_bundles_root(root) / validate_id(bundle_id)


def runtime_bundle_assets_directory(root: Path, bundle_id: str) -> Path:
    from fpbench.core.runtime_models import ASSETS_DIRECTORY

    return runtime_bundle_directory(root, bundle_id) / ASSETS_DIRECTORY


def decisions_root(root: Path, run_id: str) -> Path:
    """Every derivation over one run's results lives under here."""
    return run_directory(root, run_id) / "decisions"


def decision_set_directory(root: Path, run_id: str, decision_set_id: str) -> Path:
    return decisions_root(root, run_id) / validate_id(decision_set_id)


def eligibility_directory(root: Path, run_id: str, decision_set_id: str) -> Path:
    """SELF eligibility is scoped to the decision set, never to the run.

    The same finger can be eligible under one threshold and not under another,
    so an eligibility table that sat beside the run rather than beside the
    decisions would be answering a question it had not been asked
    (docs/adr/0023).
    """
    return decision_set_directory(root, run_id, decision_set_id) / "self-eligibility"


def evaluation_views_directory(
    root: Path, run_id: str, decision_set_id: str
) -> Path:
    return decision_set_directory(root, run_id, decision_set_id) / "evaluation-views"


def evaluation_view_directory(
    root: Path, run_id: str, decision_set_id: str, view_kind: str
) -> Path:
    try:
        name = VIEW_DIRECTORY_NAMES[view_kind]
    except KeyError:
        raise ValueError(f"unknown evaluation view kind {view_kind!r}") from None
    return evaluation_views_directory(root, run_id, decision_set_id) / name


def evaluations_root(root: Path, run_id: str) -> Path:
    """Every metric set over one run's decisions lives under here.

    A sibling of ``decisions/`` rather than a child of it. An evaluation names
    exactly one decision set in its manifest, but it also names a metric policy
    and a metric-engine commit, and filing it *inside* the decision set would
    suggest that the decisions are the only thing it depends on.
    """
    return run_directory(root, run_id) / "evaluations"


def metric_set_directory(root: Path, run_id: str, metric_set_id: str) -> Path:
    return evaluations_root(root, run_id) / validate_id(metric_set_id)


def derivations_root(root: Path) -> Path:
    """Where a workspace records what each experiment pinned, per run."""
    return Path(root) / "derivations"


def derivation_experiment_directory(
    root: Path, experiment_id: str, run_id: str
) -> Path:
    return derivations_root(root) / validate_id(experiment_id) / validate_id(run_id)


def definitions_directory(root: Path, experiment_id: str, run_id: str) -> Path:
    """Namespaced definitions: one directory per definition id.

    Stage 5A wrote a single ``definition.json`` per experiment and run, which was
    fine while an experiment could only pin one thing. It cannot: a second metric
    policy over the same decisions is a second definition, equally valid and
    equally permanent, and a flat filename would force one to overwrite the other
    (spec section 35).
    """
    return derivation_experiment_directory(root, experiment_id, run_id) / "definitions"


def definition_directory(
    root: Path, experiment_id: str, run_id: str, definition_id: str
) -> Path:
    return definitions_directory(root, experiment_id, run_id) / validate_id(
        definition_id
    )


# -------------------------------------------------------------- prepared images
#
# A prepared-image set is not run-scoped. That is the entire point: one set is
# materialised once and handed unchanged to SourceAFIS, to NBIS and to whatever
# comes after them (docs/adr/0033). So it lives beside ``runtime/`` rather than
# under ``results/<run_id>/``::
#
#     <workspace>/prepared-images/
#     ├── images/<first-two-sha-chars>/<encoded_sha256>.png
#     ├── pending/<preparation_definition_id>/
#     │   ├── transform-profile.json
#     │   ├── transform-runtime.json
#     │   ├── preparation-definition.json
#     │   └── entries/<image_id>.json
#     └── <preparation_set_id>/
#         ├── transform-profile.json
#         ├── transform-runtime.json
#         ├── preparation-definition.json
#         ├── manifest.json
#         ├── entries.parquet
#         ├── preparation-summary.json
#         ├── preparation-receipt.json
#         └── preparation-finalization.json
#
# Two deliberate departures from the shape the stage 6A specification sketches,
# both of which strengthen what it asks for rather than relax it.
#
# **The canonical PNGs sit at the workspace level, not inside the set.** A set's
# id is derived from its entry hashes and therefore cannot be known until the
# last image has been produced, so images cannot be written into their final
# set directory as they are made. Making them workspace-level and
# content-addressed solves that without a rename and without a copy — and it is
# what content addressing is *for*: two sets that share an image share the
# bytes, which is exactly the reuse section 40 permits. ``relative_path`` stays
# workspace-relative, so nothing downstream notices.
#
# **Work in progress lives under ``pending/``.** An unfinished materialisation
# has a definition id but no set id, and giving it a directory of its own keeps
# a half-built set from ever looking like a finished one.


def prepared_images_root(root: Path) -> Path:
    return Path(root) / "prepared-images"


def prepared_image_blobs_root(root: Path) -> Path:
    """Where canonical PNGs live, addressed by the digest of their own bytes."""
    return prepared_images_root(root) / "images"


def prepared_image_blob_path(root: Path, encoded_sha256: str) -> Path:
    """``images/<first two hex chars>/<full digest>.png``.

    Fanned out by the first byte so that 3,000 files — or 300,000 — never land
    in one directory. The filename is the digest and nothing else: an image id
    or a subject id in a path would put a dataset inventory into a directory
    listing (spec section 37).
    """
    digest = str(encoded_sha256).strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(
            f"a content-addressed image is named by a 64-character digest, got "
            f"{encoded_sha256!r}"
        )
    return prepared_image_blobs_root(root) / digest[:2] / f"{digest}.png"


def prepared_image_pending_directory(root: Path, definition_id: str) -> Path:
    """Where an unfinished materialisation keeps its per-image entries."""
    return prepared_images_root(root) / "pending" / validate_id(definition_id)


def prepared_image_set_directory(root: Path, preparation_set_id: str) -> Path:
    """The immutable, finished set."""
    return prepared_images_root(root) / validate_id(preparation_set_id)


# ----------------------------------------------------------- paired analysis
#
# A paired comparison belongs to *two* runs, so it cannot live under either::
#
#     <workspace>/paired-evaluations/<paired_evaluation_id>/
#     ├── definition.json
#     ├── policy.json
#     ├── manifest.json
#     ├── paired-comparisons.parquet
#     ├── eligibility-transitions.parquet
#     ├── common-eligible-mated.parquet
#     ├── transition-counts.parquet
#     ├── observations.parquet
#     ├── control-audit.json
#     ├── summary.json
#     ├── report.md
#     ├── receipt.json
#     └── finalization.json
#
# Filing it under the canonical run would suggest the canonical run is the
# subject and the native one merely a reference. Neither is: the comparison is
# symmetric in its inputs and asymmetric only in which direction its deltas are
# written.


def paired_evaluations_root(root: Path) -> Path:
    return Path(root) / "paired-evaluations"


def paired_evaluation_directory(root: Path, paired_evaluation_id: str) -> Path:
    return paired_evaluations_root(root) / validate_id(paired_evaluation_id)


# --------------------------------------------------------------- calibration
#
# A calibration belongs to no run. It is chosen on a *development* cohort and
# then applied to evaluation runs it was deliberately not drawn from, so filing
# it under a run would put it inside the thing it must stay outside of
# (docs/adr/0079)::
#
#     <workspace>/calibration/
#     ├── protocols/<protocol_id>.json
#     ├── source-bindings/<binding_id>.json
#     ├── operating-points/<operating_point_id>.json
#     ├── receipts/<operating_point_id>.json
#     └── finalizations/<name>.json
#
# Flat directories rather than a hierarchy, because none of the four nests inside
# another: one protocol is meant to be run over many source bindings, and one
# source binding can be calibrated under several protocols. Each file is named by
# an id that is derived from a digest of its own contents, so a collision is a
# genuine conflict rather than a naming accident.


def calibration_root(root: Path) -> Path:
    return Path(root) / "calibration"


def calibration_protocols_directory(root: Path) -> Path:
    return calibration_root(root) / "protocols"


def calibration_source_bindings_directory(root: Path) -> Path:
    return calibration_root(root) / "source-bindings"


def calibration_operating_points_directory(root: Path) -> Path:
    return calibration_root(root) / "operating-points"


def calibration_receipts_directory(root: Path) -> Path:
    return calibration_root(root) / "receipts"


def calibration_finalizations_directory(root: Path) -> Path:
    return calibration_root(root) / "finalizations"
