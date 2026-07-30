# Committed run evidence

One file per research run, written by `finalize` and committed deliberately:

```
evidence/sourceafis-native-full/<run_id>.json
```

## What a receipt is

A receipt proves that a specific set of comparisons was carried out, by a specific build
of a specific matcher, driven by a specific commit of this harness, over a specific set
of pairs — and that the results were audited, indexed and found sound. Every field is an
identifier, a fingerprint or a count.

It is the only artefact of a run that leaves the workspace. Results belong in a
workspace; this belongs in version control, so that a reader who has the repository and
not the machine can still check what happened.

## What a receipt is not

It carries **no biometric performance conclusion**, and says so verbatim. There is no
FMR, no FNMR, no EER, no threshold, no accuracy figure and no statement about which
resolution performed better. That is not because the scores are unavailable — 6,000 of
them exist — but because the definitions that would make such a number honest do not
exist yet: decision profiles, SELF eligibility, metric definitions, failure denominators
and threshold provenance ([ADR 0003](../docs/adr/0003-decision-outside-adapter.md)).

It also carries no personal or biometric data: no score, no subject id, no image id, no
filename, no dataset path, no workspace path, no template, no minutiae, and no absolute
path to anything. That is enforced by
`fpbench.core.research_models.require_sanitised()` over the rendered document, not by
care.

## Checking one

Given the repository and a workspace holding the run:

```bash
git checkout <source_commit>
python -m fpbench.experiments.sourceafis_native_full status
```

`RESEARCH_READY` means every link the receipt names still holds: the audit, the runtime
bundle's digests, the source revision, the result set and the receipt itself. Any broken
link reports `INVALID` rather than degrading quietly
([ADR 0020](../docs/adr/0020-research-finalization-follows-runtime-revalidation.md)).
