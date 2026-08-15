# Neurotechnology FingerCell 3.3 — Algorithm 5 candidate

**Status: Stage 13A closed as `FINGERCELL_PREFLIGHT_FAIL`. Not selected, not
integrated, and no benchmark run was performed.**

| | |
|---|---|
| candidate id | `neurotechnology_fingercell_3_3_1to1` |
| slot | `algorithm_5` |
| origin | `VENDOR_OFFICIAL_SDK` |
| product | FingerCell SDK 3.3 |
| revision | `20211013` |
| acquisition | direct vendor download, self-service |

## Why this candidate

The Algorithm 5 slot opened when Stage 12A closed as `IDKIT_PREFLIGHT_FAIL` on a
vendor access refusal. What that failure cost was not a candidate but a *year* of
uncertainty about a category: proprietary SDKs whose acquisition depends on a
commercial relationship this project does not have.

FingerCell inverts that. Neurotechnology publishes a direct 30-day trial download
with no portal, no sales conversation and no approval step. Acquisition is an act
this project performs, not a request it makes.

The upstream API also settles, in advance and in public, the three things that
matter most and that most candidates leave ambiguous:

```text
image  -> template          FingerCellExtract(handle, image, &record)
1:1    -> native integer    FingerCellMatch(handle, reference, candidate, &score)
direction                   a bigger score means more similar
```

What remains is whether the archive this project actually downloaded keeps that
contract reproducibly — which is exactly the kind of uncertainty that can be
resolved locally.

## What is already established

All of the following was read out of the delivered archive, not from a product
page:

- the archive is 509,667,736 bytes, SHA-256
  `9ca7e275afa9e22cd6fa928b0273afbc447e49463f6f8259a3d5d39a555cde99`;
- the delivered `Revision.txt` reports revision `20211013`, agreeing with the
  vendor's published release notes;
- the matcher's own parameter names are `hReference` and `hCandidate`, which is
  where this stage's frozen pair binding takes its words from;
- the template format enumeration is `Proprietary = 0`, then ISO and MOC;
- the delivered tutorials obtain a licence for the component named `FingerCell`
  specifically, construct one object, and print the integer with no threshold;
- the licence grants use for "designing, developing, testing and distributing",
  and states no restriction on publishing measurements;
- the trial is 30 days, requires explicit activation, and requires a constant
  network connection while running.

## What is known to be harder than expected

The delivered C++ binding exposes typed accessors for three properties only:
`ImageQualityThreshold`, `MatchingAlgorithm`, `TemplateFormat`. The module carries
more — minutiae count limits, a large-template switch, and a quality-use switch
that appeared in no plan written in advance.

So the settings closure has to enumerate a constructed engine's properties through
the supported mechanism rather than tick off a list (docs/adr/0118).

## The binding

C++, decided by the archive rather than in advance. Java was the engineering
preference until the archive showed its only FingerCell Java sample targets
Android; .NET ships assemblies but no FingerCell sample at all (docs/adr/0116).

## The same-vendor hazard

Algorithm 4 is VeriFinger 2025.2 — the same vendor, sharing a component ecosystem
and a naming convention. The static module closure of the FingerCell route is
FingerCell plus the common, media and licensing runtimes, and does not include the
general biometrics module that carries the other fingerprint engine. That is
recorded as a candidate closure to be confirmed against the loaded module set, not
as a settled fact (docs/adr/0114, docs/adr/0120).

## Final disposition

The client trial switch was enabled before licensing initialisation, but the
delivered Linux entitlement route returned no FingerCell entitlement. The
subsystem reported `LICENSE_NOT_OBTAINED` before and after the request and did not
report `SERVER_OFFLINE`; no transport meaning is inferred from that distinction.

No template was extracted, no score was produced, no adapter was written and no
benchmark run occurred. The loaded runtime closure was not observed, so sibling
component presence remains unknown. Stage 13A publishes its final FAIL marker,
keeps Stage 13B closed and reopens the Algorithm 5 search.

See `evidence/stage13a-fingercell-preflight/` for the full state.
