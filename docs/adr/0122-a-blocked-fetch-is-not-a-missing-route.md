# A blocked fetch is not a missing route

## Status

Accepted, implemented.

## Context

Stage 14A's central finding is a negative: *no official Griaule route serves the
GBS Fingerprint SDK package*. A negative claim of that shape is only as good as
the walk behind it, and the walk hit a case earlier stages did not.

The vendor's support host answered an automated client with an HTTP 403. Read
carelessly, that is three different things at once:

- the route does not exist;
- the route exists and is unreachable;
- the route exists, is up, and declined *this client*.

Only the third is true. The same host, loaded in a browser, serves a knowledge
base with an FAQ, guides and a request form. Recording it as unreachable would
have quietly shrunk the set of routes the finding rests on, and recording it as
absent would have been simply false — while making the conclusion look *stronger*
than the evidence supports.

The general hazard: a preflight whose whole output is "we looked and it is not
there" can be corrupted by a fetch that failed for reasons having nothing to do
with what is there.

## Decision

`RetrievalStatus.BLOCKED` is its own state, distinct from `UNREACHABLE` and from
`NOT_RETRIEVED`. A host that answers with a refusal is a host that is up.

A route recorded as `BLOCKED` may not report what it found. The observation
module enforces the general form of this at import: any route whose retrieval is
not `RETRIEVED` may only carry the outcome `CONTACT_ROUTE_ONLY`, because what a
page says is not knowable from the fact that it exists.

Where an automated fetch is blocked, the route is retrieved **by another means**
and recorded as `RETRIEVED` with what that means found. Stage 14A did exactly
this: the knowledge base was read in a browser, its sections enumerated, and its
article search run for the SDK — returning nothing. That is a real observation,
and it is what the evidence carries.

Finally, the negative claim is checked rather than asserted. At import, the
observations module requires that at least three routes were genuinely retrieved
and that every official delivery channel has at least one walked route, so
`SELF_SERVICE_LOCATOR_FOUND = False` cannot be published on the back of a thin
walk.

## Alternatives

**Treat 403 as unreachable.** Simpler, and it would have removed a live vendor
route from the evidence while making the conclusion sound better supported.

**Treat 403 as absent.** False, and it would have published a claim about
Griaule's support offering that a browser disproves in one load.

**Omit the route.** The worst option: the finding would rest on a set of routes
chosen partly by which ones a command-line client happened to like.

## Consequences

Each route row carries its retrieval status, its date and what was found, and the
distinction survives into the published evidence rather than living in a
maintainer's memory. A reader can see which routes were walked, by what means,
and what each one actually offered.

The cost is that a blocked fetch is not the end of the walk — somebody has to go
and look properly. That is the correct cost for a stage whose entire output is a
claim about what does not exist.
