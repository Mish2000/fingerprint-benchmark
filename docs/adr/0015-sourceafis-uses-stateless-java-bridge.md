# 0015 — SourceAFIS is integrated through one stateless Java subprocess per comparison

## Status

Accepted. Implemented in `integrations/sourceafis-java` and
`fpbench.adapters.sourceafis_java`.

## Context

SourceAFIS is a Java library; the harness is Python. Three ways to bridge that gap:

1. **A JVM inside the Python process** (JPype, py4j). Fastest, and the algorithm ends
   up sharing an address space with the harness.
2. **A long-lived Java worker**: start one JVM, feed it thousands of comparisons, shut
   it down. Amortises startup cost.
3. **One JVM per comparison.** Slowest by far — a JVM start costs more than the
   comparison it performs.

The obvious choice on throughput is the wrong choice on evidence. This is the first
real algorithm in the project, and the questions that matter first are not "how fast?"
but "is it doing what we think?" and "when it breaks, how much do we lose?"

## Decision

**One stateless JVM per comparison**, invoked as
`java <pinned args> -jar fpbench-sourceafis-bridge.jar compare`, with a JSON request on
stdin and one JSON document on stdout.

What that buys, and why each item is worth the cost:

* **No state can carry between comparisons.** Not a cached template, not a warm data
  structure, not an accumulated anything. Template reuse across a SELF comparison —
  the specific hazard [ADR 0016](0016-sourceafis-receives-explicit-effective-dpi.md)
  and the extraction-count check exist to rule out — is impossible rather than merely
  unintended.
* **A crash costs one result.** Not a run. The JVM dies, the adapter records
  `PROCESS_CRASHED` for that comparison, and the executor continues
  ([ADR 0013](0013-comparison-failure-does-not-invalidate-run.md)).
* **A memory leak cannot exist.** 6,000 comparisons in one JVM would make peak memory a
  thing to measure and manage; here the process exits after each one.
* **The environment is exactly pinned.** The JVM's arguments, locale and timezone are
  fixed, and `JAVA_TOOL_OPTIONS`, `_JAVA_OPTIONS` and `JDK_JAVA_OPTIONS` are stripped
  from the child environment. A heap size arriving from an ambient variable would make
  a run unreproducible without leaving a trace.
* **The jar is identified, not trusted.** Its SHA-256 and size go into the environment
  fingerprint, and the bridge reports the SourceAFIS version *SourceAFIS itself*
  reports at runtime. A jar built from a different release is refused during preflight
  rather than producing thousands of misattributed results.
* **The interface is narrow enough to audit.** Two paths and two integers cross the
  boundary. There is no way for the protocol to leak through it.

The cost is stated rather than hidden: `adapter_ms` includes JVM startup, JSON
serialisation and process overhead, and **must not** be presented as SourceAFIS's own
speed. The bridge reports its internal `bridge_total` separately so the difference is
visible.

Java 17 is the reference environment. Newer is allowed to run, but the exact version
reaches the environment fingerprint, so a run on a different JVM is a different run,
and the pinned regression score is only asserted on 17.

## Alternatives

**In-process JVM.** Rejected for now: it puts the algorithm in the harness's address
space, makes a segfault fatal to the whole run, and makes "no state between
comparisons" a claim rather than a fact.

**Persistent worker.** The likely destination, and deliberately not yet. It needs a
lifecycle in the adapter contract — `close()`, or a context manager — and adding one
before there is a single measurement of what it would save is designing against a
guess. The stage-4A pilot exists to produce those measurements: JVM startup cost,
extraction time at 500/1000/2000 ppi, peak memory, failure rate, timeout headroom.

**Container per comparison.** Even slower, and solves an isolation problem this project
does not have.

## Consequences

* A full 6,000-comparison SourceAFIS run is **not** part of stage 4A. Deciding between
  stateless, persistent worker, batch bridge or container is a separate decision that
  needs the pilot's numbers first.
* Timing comparisons between SourceAFIS and the dummy adapter are meaningless at this
  stage, since one of them pays for a JVM and the other does not.
* If the persistent-worker path is taken later, it becomes an *optional capability* on
  the adapter contract rather than a change to it, so adapters that do not need a
  lifecycle stay unaffected ([ADR 0002](0002-minimal-adapter-contract.md)).
