# ADR 0140 — configuration is read with its types, and a cohort is checked

## Status

Accepted.

## Context

`fpbench.core.config_values` already exists, and its module docstring already
makes the argument: `bool("false")` is `True`, `int(True)` is `1`, and a YAML
scalar carries a type that is part of the configuration. Adapters read their
config through it.

The SD300 protocol loader did not. It read the file that decides *which 50
subjects the entire benchmark studies* with plain Python coercions:

```python
size=int(cohort["size"]),
require_all_ten_plain=bool(require.get("all_ten_plain", True)),
```

So `all_ten_plain: "false"` — the obvious way to write it if you are thinking in
JSON — *enabled* the requirement it was written to turn off. `size: true` drew a
one-subject cohort. `seed: "20260728"` was accepted. An unknown key, including a
misspelling of a real one, was ignored and its default silently used. A run
under any of these starts, completes and reports success under a protocol nobody
wrote down.

`CohortCriteria` did not check its own values either, and `select_cohort`'s
sufficiency test is `len(candidates) < criteria.size` — which every pool passes
for a negative size. `size=-1` then reached `sorted(...)[:-1]`, and `size=0`
reached `[:0]`. A cohort of nobody has a denominator, and every rate derived
from it is a number with nothing under it.

## Decision

**The SD300 loader reads every scalar through `fpbench.core.config_values`, and
`CohortCriteria` refuses a value it cannot describe a cohort with.**

At the loader:

* `require_yaml_bool` for every boolean, so `"false"` is refused rather than
  read as `True`;
* `require_yaml_exact_int` for `size` (minimum 1) and `seed`, so `true`,
  `"50"` and `50.0` are each refused;
* `reject_unknown_keys` on all five sections, so a misspelled key stops the load
  instead of falling back to a default;
* `releases` must be a list of distinct non-empty strings — a bare
  `releases: SD300A` is refused rather than read character by character, and a
  repeated release is refused rather than deduplicated, because deduplicating it
  would make `require_common_across_releases` look satisfied by one release;
* `role` must name a declared `CohortRole`, because `role` decides whether
  calibrating on this cohort is permitted and an unrecognised value must not
  fall back;
* every comparison stage disabled is refused, since the protocol would generate
  no pairs at all.

At the model, `CohortCriteria.__post_init__` requires a positive integer size,
an exact integer seed, at least one release, no repeated release, a real
`CohortRole` and actual booleans — so the API is closed as well as the file.

## Consequences

* `configs/protocols/sd300_50_subjects.yaml` loads to exactly the same
  configuration it did before; this was verified before the change was kept.
* A config that used to load and quietly mean something else now fails at load,
  which is the intended outcome and is not backwards compatible on purpose.
* Callers constructing `CohortCriteria` directly with a non-positive size now
  get `ProtocolError` at construction rather than a short cohort later.

## What is deliberately still open

`MetricDefinition` accepts any `MetricNumerator` over any `MetricDenominator`.
Some combinations are not interpretable — an eligibility numerator over
`DECIDED_ATTEMPTS`, for instance — and the constructor does not refuse them.
Closing that means deciding, metric family by metric family, which pairings are
meaningful; the pairings currently in use are correct, and inventing the rule
here without that analysis would risk refusing a legitimate metric a later stage
needs. It is named here so it is not mistaken for having been overlooked.

## Alternatives

**A schema library.** `core` imports nothing outside the standard library, and
that is what keeps it safe to import everywhere. The helpers already existed;
the defect was not using them.

**Validate in `select_cohort` only.** It is the wrong place twice: it runs long
after the config was read, so the error names a cohort rather than a line in a
file, and it leaves the API open to callers who never go through the loader.
