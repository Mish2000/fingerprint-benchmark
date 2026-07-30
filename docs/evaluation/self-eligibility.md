# SELF eligibility

Which fingers may take part in the conditional PLAIN–ROLL report, and why each one
either can or cannot.

## The unit

An eligibility unit is **one anatomical finger, of one subject, in one release**:

```
(SD300A, subject 00001012, finger 3)
(SD300B, subject 00001012, finger 3)     ← a different unit
(SD300C, subject 00001012, finger 3)     ← a third
```

The release is part of the key because each release is a separate scan at a separate
resolution. A finger may extract cleanly at 2000 ppi and not at 500, and a rule that
pooled them would let one resolution excuse another — which is exactly the comparison a
later stage wants to make.

50 subjects × 10 fingers × 3 releases = **1,500 units**, 500 per release.

The unit id is opaque:

```
selfunit_3f9a1c2e77b04d16
```

a digest over protocol, cohort, release, subject and finger. The subject reaches the
digest and never the id's text, because eligibility tables are the most join-friendly
artefact this stage produces and therefore the most likely to be copied somewhere less
careful.

## The rule

A unit is eligible when **both** of its SELF comparisons matched — the plain image
against itself, and the rolled image against itself — under one decision profile.

| PLAIN SELF | ROLL SELF | status | reason |
|---|---|---|---|
| MATCH | MATCH | `ELIGIBLE` | `both_self_match` |
| NON_MATCH | MATCH | `INELIGIBLE` | `plain_self_non_match` |
| MATCH | NON_MATCH | `INELIGIBLE` | `roll_self_non_match` |
| NON_MATCH | NON_MATCH | `INELIGIBLE` | both |
| MATCH | UNDECIDABLE | `UNDETERMINED` | `roll_self_undecidable` |
| UNDECIDABLE | MATCH | `UNDETERMINED` | `plain_self_undecidable` |
| UNDECIDABLE | UNDECIDABLE | `UNDETERMINED` | both |
| NON_MATCH | UNDECIDABLE | `INELIGIBLE` | non-match plus undecidable |
| UNDECIDABLE | NON_MATCH | `INELIGIBLE` | non-match plus undecidable |

Failing **either** SELF stage is enough, exactly as the protocol says. It does not matter
which.

### Why three statuses and not two

`UNDETERMINED` exists because "we could not tell" is not "it failed".

A `NON_MATCH` is knowledge: this finger did not match itself, so it can never satisfy
"both matched", whatever happened on the other side — which is why `NON_MATCH +
UNDECIDABLE` is still `INELIGIBLE`. An undecidable alone is the absence of knowledge: the
unit might have qualified, and recording it as ineligible would assert something nobody
measured.

Both are excluded from the conditional view, and they are excluded *for different,
recorded reasons* — which is what lets a later stage account for them differently if it
decides to.

## Eligibility depends on the threshold

There is no such thing as a finger that is eligible in general. Eligibility is derived
from *decisions*, and a decision only exists under a profile.

Every eligibility set therefore names, in its own fingerprint:

* the result set the scores came from;
* the decision set they were thresholded into;
* the decision profile that did the thresholding;
* the pair manifest the units were mapped from;
* the eligibility policy id and version.

and it is stored beneath the decision set it belongs to:

```
results/<run_id>/decisions/<decision_set_id>/self-eligibility/
├── manifest.json
└── entries.parquet
```

Raising the threshold from 40 to 46 produces a different decision set, a different
eligibility set with a different id, and a different answer — without touching either of
the originals.

## Two extractions, or no verdict

A SELF comparison is an image against itself. If a matcher extracted one template and
matched it with itself, the comparison would score perfectly and prove nothing — and
detecting fingers a matcher cannot handle is the entire purpose of the SELF stage.

So before any verdict rests on a SELF result, the result must still carry:

```yaml
extraction_policy: independent_both_sides
extraction_count: "2"
template_cache: disabled
artifacts: []
```

Failed SELF results are exempt: a comparison that produced no score made no claim about
how it was performed, and its contribution is `UNDECIDABLE` regardless.

## The mapping is derived, never guessed

The three comparisons of a unit — PLAIN SELF, ROLL SELF and the mated PLAIN–ROLL pair
they govern — are taken from the frozen pair manifest, joined through the image manifest
for subject, finger, release and impression.

Nothing parses a filename. A mapping rebuilt from names would be a second implementation
of the protocol, free to disagree with the one that generated the pairs.

Every way it can be wrong is a hard error rather than a skipped unit:

```
missing PLAIN SELF          duplicate PLAIN SELF
missing ROLL SELF           duplicate ROLL SELF
missing mated pair          a pair spanning two releases
a rolled image used as a plain one      a pair spanning two fingers
a pair spanning two subjects            an image with no anatomical finger
```

A missing SELF comparison does not mean "exclude this finger". It means the pair manifest
and the protocol disagree, and no answer derived from it would mean anything.

## What is not stored

The manifest records `total_units` and nothing else about the contents. How many units
were eligible, ineligible or undetermined is a **result**, and it appears in no manifest,
no fingerprint and no committed receipt. It is derivable from the entries in the
workspace whenever a later stage has the definitions to make it mean something
([ADR 0023](../adr/0023-self-eligibility-is-profile-specific.md)).

## Superseded

`fpbench.protocols.self_filtering` predates decision profiles and takes a pre-computed
set of failed pairs as input. It has no threshold binding, no three-valued status and no
identity of its own. It must not be used for research output.
