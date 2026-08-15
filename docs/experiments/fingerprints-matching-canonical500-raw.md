# Stage 15A — running the canonical 6,000 under fingerprints-matching 0.1.0

The 6,000-comparison run has no `make` target, for the same reason Stage 8C's
and Stage 11B's have none: it may not be started under a different commit than it
was prepared under, and a convenient `execute` verb is exactly how that happens
by accident. This file is the documented invocation.

Unlike its three predecessors, this stage has no acquisition preflight in front
of it. There is nothing to acquire that anyone has to agree to: the artifact is a
4,492-byte MIT wheel on PyPI (docs/adr/0126).

## What has to be true before you start

* the two published artifacts are in the local third-party store and both
  SHA-256 match — `make stage15a-runtime-verify` says `gate_state PASS`;
* the frozen runtime environment is built: the pinned interpreter, numpy 1.26.4
  and opencv-python 4.7.0.72, installed offline from the local wheelhouse;
* the SD300 dataset root is set: `FPBENCH_SD300_ROOT`;
* the workspace holds the finished SourceAFIS canonical run `run_4c59fa02a6ab`
  and the prepared image set `prepset_be560e047991`;
* the working tree is clean and committed.

No licence, no activation, no clock, no JVM and no network. The environment is
built with `--no-index` against the wheelhouse and does not reach the network
again.

## The order

```
1. make stage15a-acquire          # the two published artifacts, both digests
2. make stage15a-runtime          # the frozen environment, offline
3. make stage15a-runtime-verify   # G1: the closure, re-hashed
4. make stage15a-route            # G2: the route, parsed from the installed module
5. make stage15a-qualify          # G3: determinism and the failure contract
6. make stage15a-contract         # the protocol, with no package involved
7. make stage15a-preflight        # every input, written nothing
   commit
8. prepare                        # below
9. execute                        # below
10. make stage15a-integrity       # G6: the pass over the stored outcomes
11. make stage15a-documents       # seven evidence documents
    commit
12. make stage15a-publish         # the marker
    commit
```

**Steps 8 and 9 must not be separated by a commit.** `prepare` refuses a dirty
tree and `execute` refuses to resume under a different source commit, so a commit
in the middle produces a run whose results came from two revisions — which is not
one run.

There is deliberately no SD300 pilot between steps 7 and 8. The qualification in
step 5 ran on non-SD300 fixtures, and these 6,000 comparisons are the canonical
production execution rather than a rehearsal for one.

## Prepare

```bash
python -m fpbench.experiments.stage15a_publish prepare
```

Writes the run, the plan and the runtime binding, and no raw result: this path
never reaches the executor. It stops on a dirty tree, on an artifact digest that
does not match, on a runtime that is not the frozen one, on a prepared set that
does not verify, and on a plan that is not exactly 6,000 jobs.

## Execute

```bash
python -m fpbench.experiments.stage15a_publish execute
```

Resumable. A result that is already stored is verified and skipped, never
re-executed and never overwritten, so a stop halfway costs wall clock rather than
results. An optional job limit is the first argument.

Each comparison hands two prepared file paths to
`FingerprintsMatching.fingerprints_matching` and records exactly one of two
outcomes: a raw score, or an algorithmic failure carrying no number. An
infrastructure failure is not recorded at all — it raises, and the run stops.

## Integrity and publication

```bash
python -m fpbench.experiments.stage15a_publish integrity
python -m fpbench.experiments.stage15a_publish documents
# commit
python -m fpbench.experiments.stage15a_publish publish
# commit
```

`publish` refuses a marker the evidence does not support: a missing or duplicated
outcome, an infrastructure failure that reached the stored set, a gate that did
not pass, or a partition that does not add up.

It also refuses `FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE` over a result
set that contains no score at all. Six thousand complete, deterministic refusals
satisfy every integrity check and are still not a fifth raw matcher; that run is
published in full under `FINGERPRINTS_MATCHING_QUALIFICATION_FAIL`, with its
counts and its failure breakdown, and Algorithm 5 passes to the reserve candidate
(docs/adr/0128).

## Reproducing it elsewhere

Needs the wheelhouse, not just the package. `pip install fingerprints-matching`
resolves `opencv-python` unbounded, and the current OpenCV cannot run this route
at all — `convexityDefects` changed shape and every image raises. The pinned
closure is in `evidence/stage15a-fingerprints-matching/artifact-runtime-identity.json`
and the reasoning is docs/adr/0125.

SD300 itself is redistribution-restricted and is not in this repository.
