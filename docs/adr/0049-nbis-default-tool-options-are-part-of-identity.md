# 0049 — The tool options this route does not pass are part of its identity

*Status: Accepted — 2026-08-02, stage 7B*

## Context

MINDTCT and BOZORTH3 both take options that change what they compute:

```
mindtct  -b            contrast-boost the image before extraction
mindtct  -m1           write minutiae in the alternative format
bozorth3 -n <max>      maximum minutiae used (default 150)
bozorth3 -A minminutiae=<n>   minimum for a non-zero score (default 10)
bozorth3 -T <n>        print only scores at or above a threshold
bozorth3 -m1, -q, -O, -o, -e, -v
```

Every one of them is a knob, and a knob in a configuration file is an invitation
to change it. The tempting design is to expose them in
`configs/algorithms/…​.yaml` so an experiment can be varied without a code change.

That design is wrong here, for a reason that is easy to state and easy to forget:
**a run under `mindtct -b` is not the same algorithm as a run without it.** Its
scores are not comparable with the ones already stored, its threshold is not
transferable, and the only thing distinguishing the two runs would be a line in a
config file that no fingerprint covers.

`bozorth3 -T` is worse than a knob. It filters *which scores are printed at all*,
so a run under it is not a raw-score run: the missing rows are indistinguishable
from comparisons that never happened.

## Decision

**MINDTCT runs with no options.** `mindtct <input.png> <output-root>`, exactly.
**BOZORTH3 runs with no options.** `bozorth3 <probe.xyt> <gallery.xyt>`, exactly,
which means its documented defaults of 150 maximum and 10 minimum minutiae apply.

Those defaults are **recorded in the algorithm identity** rather than passed on a
command line:

```
mindtct_contrast_boost   disabled
mindtct_m1               disabled
bozorth3_m1              disabled
bozorth3_threshold       none
bozorth3_max_minutiae    default_150
bozorth3_min_minutiae    default_10
score_type               nonnegative_integer_similarity
input_effective_ppi      500
```

so that a build whose defaults differ, or a future route that passes one of them,
produces a different `descriptor_fingerprint` and cannot be confused with this
one.

**No YAML key exists for any of them.** `boost`, `m1`, `threshold`,
`max_minutiae`, `min_minutiae`, `reverse_match`, `average_directions`,
`cache_templates` and `persist_templates` are refused as unknown configuration
keys, and a test asserts that each stays refused.

**`left` is the probe and `right` is the gallery**, fixed. The reverse direction
is never run, and the two directions are never averaged, maximised or minimised —
BOZORTH3's documentation says its scores are not necessarily symmetric, so
combining them would be a different measurement with no name.

**Every score is stored**, including 0. What a score means biometrically belongs
to a decision profile applied later to unchanged raw scores (docs/adr/0003).

## Consequences

Varying a tool option means writing a new adapter identity, with its own
`algorithm_id`, its own runs and its own artefacts. That is deliberately more
work than editing a config file, because it is a bigger claim.

The two algorithms in this project can be compared at all only because neither is
tuned. Both run at their published defaults on the same pixels.

## Alternatives considered

**Expose the options and record them in the descriptor metadata.** The descriptor
would then be built from configuration, so two runs could share a config path and
differ in content — and the fingerprint would be honest about the values while
nothing would stop them changing between runs.

**Expose only the "harmless" ones, such as `-n`.** `-n` changes how many minutiae
are compared. There is no harmless one.

**Pass the defaults explicitly, to be clear about them.** Then a change in the
tool's own default would silently stop being a change, and the manifest would
record this project's opinion rather than the build's behaviour.
