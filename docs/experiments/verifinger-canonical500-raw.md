# Stage 11B — running the canonical 6,000 under VeriFinger 2025.2

The 6,000-comparison run has no `make` target and no command-line entry point,
for the same reason Stage 8C's has none: it takes hours, it may not be started
under a different commit than it was prepared under, and a convenient `execute`
verb is exactly how that happens by accident. This file is the documented
invocation.

## What has to be true before you start

* the pinned VeriFinger 2025.2 archive is in the local third-party store, and
  `make stage11a-verify` says `obtained True`;
* the trial licence is activated on this machine and the Neurotechnology
  licensing service is running — nothing in this repository activates, bypasses
  or resets a licence;
* a Java 17 toolchain is on `PATH` (this project pins `openjdk=17`);
* the SD300 dataset root is set: `FPBENCH_SD300_ROOT`;
* the workspace holds the finished SourceAFIS canonical run `run_4c59fa02a6ab`
  and the prepared image set `prepset_be560e047991`;
* the working tree is clean and committed.

## The order

```
1. make verifinger-build             # the production bridge jar
2. make verifinger-runtime-verify    # all seventeen runtime components
3. make stage11b-contract            # the protocol, with no SDK involved
4. make stage11b-artifacts           # the same route against the real SDK
5. make stage11b-preflight           # every input, written nothing
6. prepare                           # below
7. execute                           # below, hours
8. finalize                          # below
9. make stage11b-documents           # seven evidence documents
   commit
10. make stage11b-publish            # the marker
   commit
```

The production smoke runs inside step 5 and again inside step 6, and the run is
refused if it does not establish every one of its claims. If it passes, there is
no further review stage: step 7 starts.

## Prepare

```python
from pathlib import Path
from fpbench.experiments.verifinger_canonical500_full import (
    prepare_verifinger_canonical500_run,
)

prepared = prepare_verifinger_canonical500_run(repository_root=Path("."))
print(prepared.run.run_id, prepared.plan.total_jobs)
```

This writes the run, the plan, the runtime binding and the alignment report, and
it stops on the first thing that is wrong — a lapsed licence, a moved DLL, a
drifted runtime default, a pair manifest that is not the reference run's. It
never reaches the executor, so no raw result can exist after it.

## Execute

```python
from pathlib import Path
from fpbench.experiments.verifinger_canonical500_full import (
    execute_verifinger_canonical500_run,
)

summary = execute_verifinger_canonical500_run(repository_root=Path("."))
print(summary)
```

One JVM per comparison, one comparison at a time, no retries. At the two to four
seconds per comparison the smoke measures, 6,000 comparisons is roughly four to
seven hours.

**It may be stopped and resumed.** A result that is already stored is verified
and skipped, never re-executed and never overwritten, so a power failure after
3,174 jobs costs 3,174 jobs of wall clock and no results. Resuming is not
retrying: a comparison that produced a recorded failure keeps that failure.

**Do not commit anything while it runs.** The engine refuses to resume a run
under a different source revision, and a commit between two `execute` calls is
the one way to make the rest of the run impossible.

## Finalize

```python
from pathlib import Path
from fpbench.experiments.verifinger_canonical500_full import (
    finalize_verifinger_canonical500_run,
)

receipt = finalize_verifinger_canonical500_run(repository_root=Path("."))
print(receipt.run_id)
```

Finalization re-audits every stored result, re-hashes all seventeen runtime
components one last time, re-derives the alignment, builds the immutable result
set, and writes the receipt and the engine's own marker. It raises rather than
publishing anything if the run did not reach `RESEARCH_READY`, if any
infrastructure failure was recorded, or if the alignment moved.

## What comes out, and what does not

Stage 11B publishes 6,000 stored raw outcomes and the operational facts beside
them: attempt count, score-success count, failure count, failure codes and
stages, engine statuses, release and stage counts, and timings.

It publishes no mean, no median, no histogram, no ROC, no EER, no FMR, no FNMR,
no accuracy and no statement about which algorithm won. It produces no threshold
and performs no calibration. Those are later layers over these stored scores, and
the VeriFinger vendor scale does not make 48 a common operating point against
SourceAFIS, NBIS or flx.
