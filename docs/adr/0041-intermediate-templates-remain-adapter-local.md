# 0041 — Templates are the adapter's working files, not a core model

*Status: Accepted — 2026-08-01, stage 7A*

## Context

A two-stage algorithm produces intermediates: a converted input, a template per
side, sometimes a quality map or a minutiae listing. The obvious next step is a
`TemplateArtifact` in `fpbench.core`, a `TemplateStore` beside `ResultStore`, and
a manifest binding templates to images — after which extraction could be done
once per image instead of once per side per pair, and the templates themselves
would become citable evidence.

Every part of that is plausible and none of it is yet justified. There is exactly
one real algorithm in the repository, and it does not decompose into extract and
match at all. A shared abstraction derived from one implementation that does not
have the thing being abstracted is a guess, and a persisted model is the most
expensive kind of guess: `TemplateManifest` v1 would be a schema this project had
to keep readable for ever.

The reuse it would enable is not free either. Extracting a template once per
image and reusing it across pairs makes every comparison depend on a cache
policy, and it is precisely the shortcut docs/adr/0035 forbids for SELF — where
independent extraction is the point rather than an inefficiency.

## Decision

**No template model, no template store, no template manifest and no template
cache.** `TemplateArtifact`, `TemplateStore`, `TemplateManifest` and
`TemplateCache` are deliberately not introduced.

A template is a file an adapter writes under `context.working_directory` and
never sees again. It is disposable by construction, it appears in no result field
automatically, and it is not reused between pairs.

Every new adapter defaults to:

```
template_cache        = disabled
template_persistence  = disabled
```

Both are declared in the descriptor's pipeline metadata, so they reach the
algorithm fingerprint — turning either one on produces a different algorithm
identity and therefore a different run. An adapter with an extraction stage also
records, per result, that it extracted twice:

```
extraction_policy = independent_both_sides
extraction_count  = 2
```

and its own validator is required to insist on it. There is no core rule
demanding these keys, because a core rule would assume every algorithm has
templates.

An adapter that wants a template to survive the job publishes it as an
`ArtifactReference` through `AdapterJobWorkspace.publish_artifact`, which copies
it into the artefact directory and records its digest and size. That path already
exists and needs no new model. **The template's contents never go into
`adapter_metadata`**: a result row is a description, not a payload.

## Consequences

An image appearing in several pairs is extracted several times. That is the cost
of not having a cache policy, and it is the same cost SELF already pays.

After a second real algorithm exists, there will be two implementations to
generalise from, and the question can be decided against code rather than
against an anticipation of it. Nothing in this decision makes that harder: the
adapters would gain a shared abstraction, and no stored artefact would have to be
migrated, because none was ever written.

## Alternatives considered

**Add the models now, unused.** An unused persisted schema is a promise the
project has to keep with no evidence it should have made it.

**Cache templates within a run, keyed by image.** Faster, and it would make SELF
independence a property of a cache rather than of the experiment.

**Let adapters store templates wherever they like.** They already may not:
`AdapterJobWorkspace` refuses any path outside the two directories the runner
allotted.
