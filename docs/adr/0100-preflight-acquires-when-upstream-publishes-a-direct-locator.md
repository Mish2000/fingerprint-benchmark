# A preflight acquires when upstream publishes a direct locator

## Status

Accepted, implemented.

## Context

Stage 10B established a distinction this project needed: `NOT_OBTAINED` is a fact
about us, `UNAVAILABLE` is a fact about the vendor, and the two must never be
merged. It published the first and refused to imply the second, because nobody
had walked the route.

That was right, and it left a question open: when *should* a preflight walk the
route? A stage that never acquires anything can always report `NOT_OBTAINED`
honestly, and it can do so indefinitely, and the honesty stops being informative.

The two candidates make the difference concrete. id3 delivers its archive and its
activation key together, after a request a person makes and a vendor accepts —
a person-to-person exchange that a program should not conduct. Neurotechnology
publishes a URL on its download page that answers HTTP 200 with the bytes.

## Decision

Where upstream publishes a locator that needs no account, no form, no credential
and no vendor approval, the preflight acquires, and acquisition is its first real
act.

Before anything is imported from the bytes, seven fields are pinned: the official
locator category, the exact filename, the byte size, the SHA-256, the download
date, the declared version, and the target platform. Signed URLs, tokens,
credentials, cookies and machine identifiers never become evidence — the acquired
artifact type has no field one could be recorded in, and the record refuses a
locator carrying a query string or userinfo.

Where upstream does *not* publish such a locator, nothing changes: the route is
not walked by a program, and possession stays `NOT_OBTAINED` with obtainability
untested.

Acquisition is not activation. Fetching published bytes is reversible and touches
nothing outside a directory; activating a licence starts a clock, binds to a
machine, and excludes other products on it. The first is this stage's to do; the
second is the maintainer's.

## Alternatives

**Always acquire.** Would have required a program to conduct id3's request-and-
acceptance exchange, or to pretend a preflight could.

**Never acquire; qualify from documentation.** Leaves the benchmark qualifying
descriptions of algorithms rather than algorithms, and cannot distinguish a
manual that matches the shipped runtime from one that does not.

**Acquire lazily, when a gate needs it.** Spreads network access through the gate
runners and makes the cost of a preflight unpredictable. Acquisition first, once,
with a manifest, keeps the expensive irreversible-feeling step in one visible
place.

## Consequences

A preflight can now cost gigabytes rather than nothing, and the stage says so:
the report publishes the byte count downloaded beside the byte count added to
Git, which is zero.

The public CI does not acquire. It checks schemas, the state machine, the
finalization logic, the guards and fake fixtures; the tests that need the real
artifact carry their own marker and run locally. A CI that downloaded 4.4 GB per
push would be paying for the same bytes forever to learn what one digest already
records.
