# Stage 11A qualifies VeriFinger from the artifact itself

## Status

Accepted, implemented.

## Context

Stage 10B preflighted the id3 Finger SDK and stopped at its second gate. The
vendor publishes no self-service download, nobody had requested a package, and
eight of the ten gates were therefore questions about an archive that did not
exist. The result was correct and it was cheap, but it was also *thin*: almost
everything Stage 10B could say, it said about web pages.

VeriFinger is the next candidate and it is not in that position.
Neurotechnology publishes a direct download link with no form, no account and no
approval step. A preflight that stopped at "we have read the product page" here
would be choosing to stay ignorant of facts that were one HTTP request away, and
it would repeat the exact substitution this project keeps warning about: a
version printed on a page standing in for the identity of the thing that would
compute the score.

There is a second reason. The questions that decide whether a commercial matcher
can enter this benchmark — which representation is compared, whether one scalar
score exists, whether a threshold is baked into it, which settings can change it —
are answered in a vendor's *manual*, and a vendor's manual on the web describes
whatever version is current. The manual that ships inside a pinned archive
describes the runtime that ships beside it, and cannot drift away from it.

## Decision

Stage 11A's conclusions come from bytes it pinned. Concretely:

* the artifact is acquired, hashed and opened before any gate about it is
  answered;
* every recorded fact carries a **source class**, and the observation type
  refuses an artifact-class statement whose locator is a URL;
* the documentation is pinned as an artifact in its own right, and this stage
  checked that the standalone manual is byte-for-byte the manual inside the
  archive;
* a gate whose answer needs a *running licensed engine* says so, and does not
  accept documentation in its place.

Stage 8E remains the owner of the third-party question and is not extended.
Its observation vocabulary has no member for a proprietary commercial SDK
licence; the narrowest true member is used, the mismatch is published in the
usage-binding document, and the closed stage stays closed.

## Alternatives

**Repeat Stage 10B's shape — public research only, no download.** Cheap, and
wrong here: it would publish "unresolved" for questions the artifact answers in
plain text, and a reader could not tell which unresolved items were genuinely
open from those nobody had looked at.

**Add a proprietary member to Stage 8E's vocabulary.** It would model this
component better and it would re-open a stage whose published marker pins those
models byte for byte. A corrective policy stage is the response, not an edit
from here.

**Download and also activate, in one stage.** Rejected as a decision this stage
gets to take. Activation starts a 30-day clock bound to one machine and excludes
the simultaneous use of licensed Neurotechnology products on it. That belongs to
the maintainer, and the stage is built so that taking it later re-runs cleanly.

## Consequences

Stage 11A reaches five gates on artifact evidence where its predecessor reached
two on page evidence, and the gate it stops at is a gate about behaviour rather
than about access. Its blocker is correspondingly weaker and more liftable: not
"we could not get it" but "we have not run it".

The cost is real. Roughly 4.8 GB of vendor bytes now sit in the local artifact
store on one machine, none of them in Git, and the stage carries a byte guard
that refuses the repository if any of them ever appear there. The conclusions
are also bound tightly: they hold for one digest, and re-running against a
2025.3 archive is a new preflight rather than an amendment to this one.
