# 0045 — Adapter tools own regular files and complete process trees

*Status: Accepted — 2026-08-02, stage 7A*

## Context

Resolving a path before asking whether it was a symlink erases the fact that a
link was traversed. Killing only the direct subprocess after a timeout likewise
leaves a wrapper's descendants able to modify templates after the runner has
recorded `TIMEOUT`. Both defects cross the adapter boundary after the harness
believes the call has ended.

## Decision

`AdapterJobWorkspace` inspects every existing path component with `lstat` before
resolution. Final and intermediate symlinks are rejected whether they point in
or out. Artifact sources and targets must be regular single-link files, and
publication uses an exclusive, system-created copy. Conformance verification
applies the same non-following checks to returned artifact references.

External commands run in a new POSIX session or a Windows Job Object. A timeout
terminates the complete group/job, waits, escalates to a forced kill where the
platform supports it, and waits again. If the harness cannot prove termination,
it raises `ProcessTreeTerminationError`; it does not return an ordinary timeout
result.

Each conformance invocation receives fresh `forward-1`, `forward-2` and
`reverse-1` directories. Exceptions, input mutation, stray writes and artifact
integrity are checked separately after every call. A generic reverse call does
not claim to detect silent input sorting; adapters for which direction changes
the answer may supply a directional golden.

## Consequences

An adapter cannot publish a link to mutable bytes, and a fixed immutable artifact
name is valid because repeated conformance calls no longer share a directory.
A timed-out wrapper cannot leave a descendant writing after the result returns.

The rules are deliberately stricter than containment alone: a link pointing to
another file inside the job is still rejected because the evidence must own its
bytes and identity directly.

## Alternatives considered

**Accept inward-pointing symlinks.** Rejected because target replacement would
make artifact identity depend on indirection and timing.

**Kill only the root process.** Rejected because multi-stage adapters routinely
launch child tools.

**Treat uncertain termination as timeout.** Rejected because subsequent jobs
would race a process the harness no longer controls.
