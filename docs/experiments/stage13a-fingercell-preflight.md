# Stage 13A — FingerCell 3.3 active artifact/API preflight

## The question

> Does the official FingerCell 3.3 SDK trial that Neurotechnology publishes today
> give fpbench a complete, reproducible and upstream-authoritative route from
> `canonical_500` to a native raw 1:1 similarity score, without fpbench inventing
> preprocessing, parameter tuning, merging, thresholding or a score
> transformation?

Ten hard gates answer it, in a frozen order, and the run stops at the first
failure.

## What is different about this stage

Stage 12A could not start its real work: Innovatrics declined to supply a package,
so nine of its ten gates were questions about bytes nobody held. Stage 13A can do
all of its own work. Neurotechnology publishes a direct trial download, so there
is no vendor-pending state in this stage at all.

What replaces it is `ACTION_REQUIRED`, and the distinction is carried from day
one rather than discovered late:

```text
local action not yet performed
    -> ACTION_REQUIRED

action actually performed and exposed an incompatibility
    -> FAIL
```

Only a failure stops the run. A gate awaiting an action is recorded and the run
continues, so an incomplete stage publishes the whole remaining job rather than
one next step (docs/adr/0104, docs/adr/0112).

## The order of work

The order is deliberate and the gate machine enforces it:

1. freeze the predecessor binding and the identity;
2. build the infrastructure that does not depend on the SDK;
3. download the official trial into the local artifact store;
4. hash it, and compare its revision against the published release notes;
5. read the licence, the activation guide, the headers and the samples;
6. inventory the archive and pin the runtime closure;
7. select exactly one binding from what the archive ships;
8. write the qualification bridge and **compile it**;
9. only then activate the trial;
10. run at most twenty comparisons;
11. close determinism, failures, workload and provenance;
12. publish a real PASS or a real FAIL.

Steps 8 and 9 are in that order on purpose. The delivered guide requires an
explicit activation but does not establish when the 30-day clock begins. The
bridge was therefore made to compile before the entitlement request, avoiding
build work under a clock whose state is `UNKNOWN` (docs/adr/0115).

## Final state

`FINGERCELL_PREFLIGHT_FAIL`, failure class
`OPERATIONAL_TRIAL_ENTITLEMENT_NOT_ESTABLISHED`. G1 passed. G2 retains
`RUNTIME_CLOSURE_NOT_OBSERVED`. G3 failed after the delivered Linux entitlement
route was exhausted, and G4–G10 were not reached. A finalization marker is
published; Stage 13B stays closed and the Algorithm 5 search is reopened.

The client trial switch was accepted and read back as enabled. The licensing
subsystem reported `LICENSE_NOT_OBTAINED` before and after the component request,
and did not report `SERVER_OFFLINE`; no entitlement was returned. These are
status observations, not authority for an inference about transport semantics.
No template was extracted, no match ran and no score was produced.

## What the archive settled before anything was executed

The delivered header is the authority for the whole score contract:

```c
NResult FingerCellExtract(HFingerCell, HNImage hImage, HNBuffer* phTemplate);
NResult FingerCellMatch(HFingerCell, HNBuffer hReference, HNBuffer hCandidate,
                        NInt* pScore);
```

One image to one template; two templates to one native signed integer; and the
delivered C++ binding documents that a bigger score means more similar. The
shipped verification tutorial reads that integer with no threshold anywhere near
it, under a licence obtained for the component named `FingerCell` specifically.

## What this stage does not build

No adapter, no registry entry, no experiment configuration, no 6,000-comparison
run, no result set, no threshold, no calibration, no metric. All of that is Stage
13B, and the FAIL does not open it.

## Running it

```bash
make stage13a-status
```

```bash
make stage13a-contract
```

The contract and evidence suites need no archive, no licence and no network. The
checks that read the delivered archive carry the `fingercell_artifact` marker and
skip without it. Public CI downloads nothing, activates nothing, loads no vendor
module and produces no score.
