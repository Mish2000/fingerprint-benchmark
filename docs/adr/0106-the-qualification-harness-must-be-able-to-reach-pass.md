# The qualification harness must be able to reach PASS, and must not overstate what it read

## Status

Accepted, implemented. Refines ADR 0104.

## Context

ADR 0104 gave Stage 11A a third outcome so that an unperformed run would stop
being reported as a failure. That was necessary and it was not sufficient: it
made `INCOMPLETE` reachable without making `PASS` reachable. A review of the
harness that was supposed to close the nine outstanding gates found seven ways it
could not have done so honestly, or could have appeared to.

* Two of the six failure classes had no cause at all — `missing runtime
  component` and `licence or runtime failure` were listed and never provoked —
  and the four that were provoked shared fixtures loosely enough that a reader
  could not tell which cause produced which outcome.
* A setting the engine would not report came back as `UNREADABLE:...`, and the
  profile gate compared it against a *membership* test. An unreadable profile
  would have passed a gate about values nobody may guess.
* The record was bound to the archive digest and nothing else. The same archive
  with a different harness, a different driver or different fixtures would have
  produced a record indistinguishable from this one.
* Extraction was treated as verification. A truncated write or a stale tree from
  an earlier archive produces files that exist.
* A run that started and died wrote no record, so its failure was indistinguishable
  from never having run — which meant the stage could never leave `INCOMPLETE` by
  discovering something wrong. The one outcome ADR 0104 was written to enable was
  the one the harness could not produce.
* The record called the Java version a runtime version. The Java version is a
  fact about the JVM, not about VeriFinger.
* The "extraction latency" it measured was the cost of constructing two
  `NSubject` objects. The extraction happens inside `verify`, so the number
  measured object allocation and the capacity arithmetic multiplied it by 12,000.
* Every gate told the reader to activate a 30-day trial, including on a machine
  with no Java — which would have burned a clock to discover that nothing could
  compile.

## Decision

A harness this stage relies on has to be able to produce all three outcomes, and
has to be unable to claim more than it saw.

**Every failure class gets a named, controlled cause**, and the three that need a
runtime missing something get their own process, because a process cannot un-load
a data file it has already loaded:

```text
invalid image               PNG signature over a broken body
unsupported image           bytes that are not an image in any container
extraction failure          a valid grey image with no ridge structure
matcher failure             a reference side whose template does not exist
missing runtime component   a pass against an install without Fingers.ndf
licence or runtime failure  a pass that deliberately obtains no licence
```

**`UNREADABLE:*` is unresolved**, filtered at the reader and refused by the
record validator. A setting nobody could read is exactly as unfrozen as a setting
nobody looked for.

**The record is bound to everything that could change it** — the archive, every
component actually loaded, the Java harness, the Python driver and the fixture
version — in one `inputs_fingerprint`, and a record without one answers nothing.

**Extraction is verified before anything loads it.** Every component this stage
pinned is re-hashed out of the installation and compared.

**A run that starts and fails writes a `FAILED` record**, which the preflight
turns into a real blocker at the first execution-dependent gate. That is what
makes `VERIFINGER_PREFLIGHT_FAIL` reachable by observation rather than only by
assumption.

**Runtime identity comes from `NModule.getLoadedModules()`** — the native modules
the process actually loaded, each with its own product and version. The Java
version is still recorded, under its own name, as a property of the JVM.

**One latency, measured end to end.** `verify(reference, candidate)` loads both
images, extracts both templates and matches them behind one call, so
`end_to_end_verify_latency` is the only honest number and capacity is that
latency times 6,000 verification attempts. The protocol's 12,000 extractions
remain its logical execution semantics — two per comparison — and are not billed
separately, because the route bills per verify call.

**Outstanding actions are ordered.** A missing toolchain says *install Java, then
run the check that starts no clock*; only once that passes does anything mention
the trial.

## Alternatives

**Provoke the two missing-runtime classes by mutating the live installation.**
Cheaper than extra processes, and it would leave the tree the other passes
measure in an unknown state.

**Treat `UNREADABLE` as a delivered default with a note.** A note is not a value,
and the gate is about values.

**Bind the record to the archive digest only.** What was tried. It cannot tell
two harnesses apart.

**Let a failed run raise and write nothing.** What was tried. It makes failure
and absence identical, which is precisely the confusion ADR 0104 removed one
layer up.

## Consequences

The harness compiles against the pinned 2025.2 bindings — `javac` exit 0 — so
every API name in it is real rather than plausible: `NModule.getLoadedModules`,
`getProperty`, `verify`, `NMatchingSpeed.LOW`, `NBiometricStatus.MATCH_NOT_FOUND`
and the rest all exist and type-check. That is checked by a test that runs
locally and skips where there is no JDK.

Four processes per run instead of one, and about a gigabyte extracted into the
artifact store. Both are the price of causes that are controlled rather than
incidental.

The stage can now end in all three states for the right reasons, which is the
only condition under which finishing it means anything.
