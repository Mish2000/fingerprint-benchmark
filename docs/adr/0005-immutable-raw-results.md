# 0005 — Manifests and raw results are immutable

## Status

Accepted. Implemented for manifests in `fpbench.storage.manifest_store`. The
result store follows when the runner exists.

## Context

The artefacts this project produces fall into two kinds that are easy to
confuse:

* things that are expensive to produce and impossible to reconstruct — which
  images exist, which subjects were selected, which pairs were compared, what
  score each comparison returned;
* things that are cheap to produce and are a pure function of the first kind —
  match counts, rates, tables, plots, reports.

Treating the second kind as precious clutters the workspace. Treating the first
kind as disposable destroys the study.

## Decision

```
manifests/   source of truth   never overwritten silently
results/     source of truth   append-only
reports/     derived           delete and regenerate freely
```

Enforcement in code:

* `ManifestStore` refuses to overwrite an existing manifest unless
  `overwrite=True` is passed explicitly, raising `ManifestExistsError`.
* Writes are atomic: a temporary sibling file is written and then renamed, so
  an interrupted run cannot leave a partial file that later looks valid.
* Each manifest carries its creation time, the `fpbench` version and its row
  count in the parquet schema metadata — inside the file, where it cannot drift
  away from the data it describes.
* Derived views are written to a separate `derived/` directory and *do* default
  to overwriting, because they legitimately change as more of the experiment
  runs. `self_eligible_pairs.parquet` is such a view; it never modifies
  `pairs.parquet`.

Changing a threshold produces new decision records against unchanged raw
scores. It never re-runs a matcher and never edits a stored score.

## Alternatives

**A relational database.** Rejected for now: it adds a service to install,
configure and back up, in exchange for query features that a few parquet files
and a dataframe already provide at this scale (6,000 comparisons per algorithm
per release). The storage layer is deliberately narrow so this can be
revisited without touching anything above it.

**Overwrite manifests freely and rely on git.** Rejected: the manifests are in
`workspace/`, which is not tracked, and the data they describe cannot be
committed at all.

## Consequences

* Regenerating a manifest under changed rules is a deliberate act that has to
  be typed out, which is the intent.
* Disk usage grows monotonically. At this scale that is not a problem;
  `reports/` can always be deleted.
* Any result record must reference the manifest it was produced against, or the
  immutability guarantee buys nothing.
