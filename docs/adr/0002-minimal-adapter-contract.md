# 0002 — Adapters must implement `compare`, nothing more

## Status

Accepted. Implemented in `fpbench.adapters.base`, with the shared suite in
`tests/contract/test_adapter_contract.py` and `dummy_sha256` as the first
adapter to pass it. The optional capabilities are named but not yet declared by
any adapter — they arrive with the first matcher that offers one.

## Context

The obvious interface for a fingerprint matcher is:

```python
extract(image) -> template
match(template_a, template_b) -> score
```

It fits SourceAFIS well. It fits other candidates badly. Some implementations
never expose a template, some take two image paths and return a number, some
are command-line programs that write intermediate files, some combine
preprocessing with matching, and some require a specific temporary format.

Forcing all of them into `extract`/`match` produces wrappers that pretend the
two steps are separate when they are not, which is worse than admitting they
are not: the code then documents a structure that does not exist.

## Decision

The only mandatory method is:

```python
def compare(left: PreparedImage, right: PreparedImage, context) -> RawMatchResult
```

Everything else is an optional capability an adapter may declare:

```
TemplateExtractionCapability
TemplateSerializationCapability
NativeQualityCapability
MinutiaeExportCapability
BatchMatchingCapability
ExplainabilityCapability
```

Template caching, minutiae export and per-image quality are used when an
adapter offers them and simply absent when it does not.

## Alternatives

**Mandate `extract` + `match`.** Cleaner on paper. Rejected because it forces
fake decomposition for tools that do not work that way, and makes integrating
an external executable harder than integrating a library — the opposite of what
this project needs.

**One free-form interface per algorithm.** Rejected: there would be nothing to
write a shared contract test suite against.

## Consequences

* The main interface hides the extraction/matching distinction. It is recovered
  through capabilities, timing breakdowns and recorded intermediate artefacts,
  not through the type signature.
* Template caching cannot be assumed. An adapter that does not expose templates
  will re-extract on every comparison; that is a cost recorded in the timing
  data, not a correctness problem.
* `tests/contract/` becomes the most important test directory: every adapter
  must pass the same suite, which is what keeps the abstraction honest.
