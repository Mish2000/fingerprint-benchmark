# 0098 — Licence material never enters public evidence or CI

*Status: Accepted — 2026-08-10, stage 10B*

## Context

Every third-party component this project has handled so far was public. NBIS
comes from NIST, SourceAFIS from Maven Central, FLARE's checkpoints from a Drive
folder, JIPNet's source from GitHub. ADR 0083 already forbids putting any of
their bytes in this repository, and the guards that enforce it hash tracked files
against known digests.

A licensed SDK adds a category none of those had: material that is not merely
*someone else's*, but **secret**. The vendor's own documentation shows what it
looks like — an activation key in a fixed `XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`
shape, a host hardware code, a licence file produced by binding the two, and the
customer identity the key was issued to.

These leak differently from bytes. Nobody accidentally commits a 200 MB
checkpoint; everybody eventually pastes a key into a document to explain what
went wrong, or writes a debug field into a JSON blob, or lets an activation
error message carry a serial into a log that is then quoted in evidence. And a
public repository with a real activation key in its history is not fixed by a
later commit.

CI adds a second surface. The natural instinct is to put the key in GitHub
Secrets so the SDK smoke test can run on every push. That would place licensed
material in a service this project does not control, for a test whose entire
purpose is to check something local.

## Decision

**A closed list of publishable licence facts.** Exactly five, and nothing else:

```text
license_type   enabled_module_names   expiry_category
remaining_days_category   sufficient_for_declared_workload
```

An expiry is published as a category, not a date, because a date plus an
activation window identifies the activation. If even the vendor's product
reference is considered sensitive in a delivered package, a fingerprint of it is
published instead of the value.

**A closed list of refused keys, checked at any depth.** Passwords, activation
keys, serials, hardware codes, licence bytes and buffers, customer logins and
account ids, product references, tokens, cookies and authorization headers. The
finalization verifier walks every published document as *data* and refuses the
publication if one appears.

**Value shapes are refused as well as key names.** A key does not stop being a
key because the field is called `note`. Five patterns are checked against every
published string: the vendor's activation-key shape, a bearer token, a private
key block, credentials embedded in a URL, and a long base64 blob.

**The guard runs twice, on two different things.** Once over the objects the
engine builds, before anything is written; once over the published bytes,
including the hand-written README. The two can differ — a document edited after
derivation, or a paragraph that quoted a key, would pass the first and fail the
second.

**Publication stops; it does not redact.** A redaction that silently succeeds is
how the second one gets missed.

**No activation in CI, and no credentials in CI.** The public workflow runs
schemas, gate logic, finalization rules and the guards themselves, over
synthetic fixtures. It fetches nothing, activates nothing, and reads no secret.
Anything needing the real SDK is marked `id3_artifact` and runs locally, against
a store outside the repository. The marker publishes
`license_activation_attempted_in_ci: false` and `credentials_stored_in_ci: false`.

**Vendor artifacts are refused by name as well as by digest.** Stage 10B has no
package digests to know — that is what its acquisition gate reports — so the
byte guard also refuses any tracked file named like a model (`.id3nn`), a
licence (`.lic`), or the vendor's activation tooling.

## Alternatives

**Keep the key in a gitignored local file and reference it from evidence.**
Rejected. The reference is fine; it is the "and then somebody quotes the error
message" path that is not, which is why the guard checks value shapes rather
than trusting the file boundary.

**Put the activation key in GitHub Secrets so CI can smoke the SDK.** Rejected.
It places licensed material in a third-party service to run a test that has to
be local anyway, since the package cannot be in CI either.

**Redact instead of refusing.** Rejected. A guard that repairs its input teaches
nobody, and the second leak arrives in a shape the redactor does not recognise.

**Trust review.** Rejected on the evidence of this repository's own history:
guards written against a moving `HEAD` have failed four separate times, and each
was written by someone who had reviewed it.

## Consequences

The evidence can describe a licence — its type, its modules, whether it covers
the workload — without carrying anything that would let a reader use it.

The refusal is testable, and it is tested: a synthetic document carrying an
activation-key-shaped string is refused by the guard in the contract suite,
without any real key existing anywhere.

Publication fails loudly rather than quietly succeeding with a hole in it, which
is the correct direction for a repository that is public and cannot be
un-published.
