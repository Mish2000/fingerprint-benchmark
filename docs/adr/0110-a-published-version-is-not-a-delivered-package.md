# A published version is not a delivered package

## Status

Accepted, implemented. Sharpens ADR 0097 for a vendor whose public material is
older than its product.

## Context

Innovatrics' learning portal currently publishes course material for **IDKit SDK
7.6**. That is the only public statement of a current version this project could
find, and it is tempting to write `7.6` into the candidate identity and get on
with it.

Three things found while walking the acquisition routes say why not.

The support material that describes the product names an `IEngine_*` C API and a
customer CRM at a host that now serves a notice saying it has been retired. The
articles have not been updated. So the public description of the product is
demonstrably older than the product, and by an unknown amount.

A course listing is not a release. It says a course exists about a version; it
does not say which version a customer receives today, which builds exist for
which platforms, or which of those a portal would offer this project.

And the identity a benchmark needs is not a marketing version. It is the exact
package: the product name, the family, the version, the build, the filename, the
size, the digest, the delivery channel and the platform. `7.6` answers one of
nine.

ADR 0097 already established that extractor and matcher defaults are part of an
algorithm's identity. This is the same principle one level up: the *package* is
part of the identity, and a number from a web page is not the package.

## Decision

```text
implementation_version = UNRESOLVED_UNTIL_PACKAGE
```

The candidate identity carries that string until a delivered package reports its
own version, and the contract suite asserts `IMPLEMENTATION_VERSION_UNRESOLVED !=
"7.6"`.

**`7.6` is recorded, as an advertisement.** It lives in the observations module
as `ADVERTISED_VERSION_INDICATION`, beside
`ADVERTISED_VERSION_IS_NOT_AUTHORITATIVE = True`, and the published package
manifest carries `advertised_version_is_authoritative: false`. It is useful — it
is what to look for — and it is not evidence.

**Public statements cannot be recorded as authorities at all.**
`PublicObservation` has a `freezes_a_value` field which is validated to be
`False`; there is no way to construct one that claims otherwise. Each carries its
locator, its retrieval date, and a
`what_it_tells_this_stage_to_check` sentence, so the record reads as a list of
questions rather than a list of facts.

**A `PASS` marker refuses the unresolved version.** If the run ever reaches a
pass with `implementation_version` still `UNRESOLVED_UNTIL_PACKAGE`, the marker
raises.

**The same rule covers the platform.** `windows/x86_64` is recorded as
`PREFERRED_TARGET_PLATFORM` with `PLATFORM_IS_FINAL_ONLY_WITH_A_PACKAGE = True`.
A platform is chosen from what a vendor actually delivers.

## Alternatives

**Freeze `7.6` and correct it later if wrong.** The correction would have to
propagate through a candidate identity, a source fingerprint and a published
marker, and the whole point of those is that they do not move quietly.

**Freeze nothing and record no version at all.** Loses the one genuinely useful
thing the public material provides: knowing which generation to expect makes the
`IEngine_*`-era support articles legible as history rather than as documentation.

**Treat the support articles as documentation of the delivered package.** This is
the failure mode. It would let a gate be answered — the input format, the DPI
rule, the score shape — from a page whose own vendor has retired the portal it
points at.

## Consequences

Nine gates are unanswerable until a package exists, and the stage says so rather
than answering them from pages. The nine public observations that were retrieved
are not wasted: they are exactly the checklist the package will be held to, and
each names the specific risk it points at.

The cost is that the stage looks emptier than it could. A version, an input
format, a DPI rule and a score shape could all have been written down today, and
four of the ten gates would have looked answered. They would have been answered
about a product rather than about a package.
