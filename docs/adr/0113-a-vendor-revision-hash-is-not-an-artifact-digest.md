# A vendor revision hash is not an artifact digest

## Status

Accepted, implemented. Applies ADR 0110's rule — a published version is not a
delivered package — to a specific and unusually dangerous field collision.

## Context

Neurotechnology's FingerCell release notes identify the current release with two
values: a product revision number, `20211013`, and a product revision hash,
`394e593011b1b1dca288371e0af499198f4a77d1`.

The second is forty hexadecimal characters. It looks exactly like something that
belongs in a field called `sha256`, and it is the value most readily to hand when
somebody is filling in an acquisition record. It is the vendor's own
source-revision identifier: it describes the vendor's tree, not the archive this
project downloaded, and nobody outside the vendor can recompute it.

An acquisition record that carried it as the artifact digest would look complete
and pin nothing. Every later gate is a question about specific bytes, and they
would all be answered about bytes that had never been identified.

## Decision

The revision hash is recorded as vendor metadata, in its own field, and it can
never stand in for a digest this project computed.

Three checks enforce it:

- the archive declaration requires `sha256` to be 64 hexadecimal characters, so a
  40-character value is refused by length alone;
- the declaration refuses a record whose `sha256` equals its
  `vendor_revision_hash`, which catches the case where somebody pads or
  substitutes;
- the identity module asserts at import that the published revision hash is not
  64 characters long — the one length at which the collision could pass unnoticed.

The delivered `Revision.txt` is what settles the revision, and the acquisition
manifest publishes whether it agrees with the public release notes. The two are
recorded as agreeing rather than one being assumed from the other.

## Alternatives

**Store only the vendor's hash.** It cannot be recomputed here, so it cannot
verify anything.

**Store only our digest.** It verifies the bytes and loses the ability to say
which upstream revision they claim to be, which is what makes a mismatch
detectable.

**Rely on review.** A forty-character hex string in a hash field is exactly the
kind of thing review passes over.

## Consequences

The acquisition record carries two identifiers with clearly different jobs, and a
reader can tell which one pins the bytes.

It costs three checks and one more field.

The wider rule stands: a public page indicates what to look for, and the archive
settles what was found.
