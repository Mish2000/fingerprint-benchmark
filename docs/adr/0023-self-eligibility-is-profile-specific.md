# 0023 — SELF eligibility is per release, per finger, and per decision profile

## Status

Accepted. Implemented in `fpbench.core.eligibility_models` and `fpbench.eligibility`.

## Context

The supervisor's protocol reports the PLAIN–ROLL stage twice: over all 500 pairs per
release, and over only those whose finger "survived both SELF stages". Turning that
sentence into a table forces three questions the sentence does not answer.

**What is a unit?** A finger belongs to a subject, but the same anatomical finger is
scanned separately in SD300A, SD300B and SD300C, at 500, 1000 and 2000 ppi. Finger 3 of
subject 12 may extract cleanly at 2000 ppi and not at 500. Those are three measurements,
and a rule about "that finger" would silently merge them.

**Survived according to whom?** "Passed SELF" is only meaningful under a threshold. At 40
a finger passes; at 46 it may not. There is no such thing as a finger that is eligible in
general.

**And what if the SELF comparison never produced a score?** The protocol was written
assuming SELF comparisons produce scores. Some will not.

## Decision

**An eligibility unit is (release, subject, anatomical finger), and an eligibility set
names the decision set it was derived from.**

* The unit id is `selfunit_<16 chars>` of a digest over protocol, cohort, release,
  subject and finger. It is opaque: the subject reaches the digest and never the id's
  text, because eligibility tables are the most join-friendly artefact this stage
  produces and therefore the most likely to be copied somewhere less careful.
* The eligibility set fingerprint covers the result set, the decision set, the decision
  profile, the pair manifest and the policy version. Change the threshold and you get a
  different set with a different id.
* The set is stored *beneath the decision set*, at
  `decisions/<decision_set_id>/self-eligibility/`, so it cannot be mis-joined to a
  different threshold's decisions.
* The mapping is derived from the frozen pair manifest, never from filenames, and every
  way it could be wrong — a missing SELF, a duplicate, a pair spanning two releases or
  two fingers, a plain image used as a rolled one — is a hard error rather than a skipped
  unit.
* A SELF result must still carry evidence of **two independent extractions** before a
  verdict may rest on it. A self-comparison that reused one template would score
  perfectly and prove nothing, which would defeat the purpose of the stage.

**Three statuses, not two:**

| PLAIN SELF | ROLL SELF | status |
|---|---|---|
| MATCH | MATCH | ELIGIBLE |
| NON_MATCH | anything | INELIGIBLE |
| anything | NON_MATCH | INELIGIBLE |
| UNDECIDABLE | MATCH or UNDECIDABLE | UNDETERMINED |
| MATCH | UNDECIDABLE | UNDETERMINED |

The asymmetry is the substance. A `NON_MATCH` is *knowledge*: this finger did not match
itself, so it can never satisfy "both matched", whatever the other side did — even if the
other side is unknown. An undecidable is the *absence* of knowledge: the unit might have
qualified, and recording it as ineligible would assert something nobody measured. It is
the same distinction as [ADR 0006](0006-self-failure-semantics.md), one layer up.

Every unit gets a record, including the ones that failed. An eligibility set that
described only the fingers that worked would be a biased description of the protocol.

## Alternatives

**Unit = (subject, finger), pooled across releases.** Simpler and wrong: it would let a
2000 ppi success excuse a 500 ppi failure, which is the opposite of what a
resolution comparison needs.

**Two statuses, folding UNDETERMINED into INELIGIBLE.** Loses the distinction between "we
know it failed" and "we could not tell", and silently shrinks the conditional
denominator using an assumption nobody stated.

**Eligibility stored beneath the run.** It reads naturally — eligibility feels like a
fact about fingers — and it is exactly the mis-join this ADR exists to prevent.

**Deriving eligibility from the mated score.** Would be circular: the mated comparison is
what the conditional view is *about*.

## Consequences

* 50 subjects × 10 fingers × 3 releases = 1,500 units per derivation, 500 per release.
* Changing the threshold produces a new eligibility set rather than editing one.
* A run whose SELF comparisons all failed still produces 1,500 records, all
  `UNDETERMINED`, and the conditional view is then empty *for a stated reason*.
* The Phase-2 helper `fpbench.protocols.self_filtering` predates this model and takes a
  pre-computed set of failed pairs. It is superseded and must not be used for research
  output; it should be removed once nothing depends on it.
