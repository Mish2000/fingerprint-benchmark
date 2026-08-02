# 0050 — NBIS templates live for one comparison and are then gone

*Status: Accepted — 2026-08-02, stage 7B*

## Context

This route writes real intermediate files. Each comparison produces two staged
PNGs and, per side, an XYT template plus seven map files MINDTCT writes beside it
— eighteen files per comparison, and 108,000 over a full SD300 run.

Three temptations follow, and each is reasonable in isolation:

**Cache the templates.** A SELF comparison hands in the same image twice, and a
full run extracts each image several times across the four protocol stages. A
cache would remove roughly half the extraction work.

**Persist the templates.** They are the interesting intermediate. Keeping them
would allow later analysis of minutiae counts and quality without re-running.

**Publish the XYT as an artefact.** The harness already has an artefact
mechanism, with digests and workspace-relative paths.

All three are refused, and the reasons are different for each.

## Decision

**No template cache.** Both sides of every comparison are extracted
independently, always, including when they are the same file. SELF exists to
detect the failures that have nothing to do with cross-impression matching
(docs/adr/0035); if SELF were the one stage that skipped an extraction, it would
stop detecting exactly the class of failure it is there for. Every stored result
records `extraction_count=2`, and the validator refuses a success that says
anything else.

**No template persistence and no template store.** docs/adr/0041 keeps
intermediates adapter-local until two algorithms exist that would share a model.
Two algorithms now exist, and they share nothing: SourceAFIS's template is an
opaque CBOR blob and NBIS's is four integers a line. A common model over those two
would be a model of neither.

**No XYT among the artefacts.** A template is a derived representation of a
fingerprint. Publishing 12,000 of them into a workspace that is copied, archived
and referenced by a thesis is a redistribution decision about biometric data, and
this stage has no reason to make one. Every result carries zero artefacts and the
validator treats an artefact as an error.

**Everything is removed in a `finally`.** Success, extraction failure on either
side, matching failure, unusable output, no score, timeout — the working directory
holds nothing afterwards, and neither does the artefact directory. The runner does
not clear the directory between jobs, so an adapter that left its files behind
would accumulate them for the length of the run.

Cleanup is scoped rather than wildcarded: the two staged inputs by name, then
anything whose name begins with one of the two known output roots. That catches an
output the official build writes and this project has not named, without ever
touching a file outside the two roots.

**What is kept is a count.** `left_minutiae_count` and `right_minutiae_count` are
recorded on every result that got that far — one integer per side, which is a
description of the extraction rather than a copy of it.

## Consequences

The route is slower than it could be. A full SD300 run performs 12,000 extractions
where 6,000 would arithmetically suffice, and the timing summary will show it.
That is the price of SELF meaning what it says.

Any later question about minutiae — how many, how reliable, where — needs a
separate, deliberate stage that says what it is publishing and why. It cannot be
answered by reaching into a workspace, because there is nothing there to reach
into.

## Alternatives considered

**Cache within a comparison but not across.** That is what a SELF comparison
already is, and it would make SELF exactly the special case this refuses.

**Cache across comparisons but re-extract for SELF.** Then SELF takes a different
code path from every other stage, which is the same objection with more machinery.

**Persist templates behind a flag.** A flag that changes what a run leaves behind
is a flag that will be on for some runs and off for others, and the receipts would
not distinguish them.

**Publish the XYT and let a later stage decide.** Published evidence is hard to
unpublish; the decision would already have been made.
