# The binding is chosen from the archive, not in advance

## Status

Accepted, implemented. Applies ADR 0105 — one upstream sample is the route — to
the choice of language binding.

## Context

The specification for this stage stated a preference for Java, on the strength of
the published API reference: it documents `NBuffer extract(NImage)` and
`int match(NBuffer, NBuffer)`, which is exactly the shape this benchmark needs.

The preference was explicitly conditional: Java *if the package actually contains
a complete and suitable sample*. That condition turned out to matter.

The delivered archive ships all three candidate bindings. It does not ship all
three samples:

| Binding | Shipped | FingerCell sample |
|---------|---------|-------------------|
| C++ | yes | desktop sample and three tutorials, one of them 1:1 verification |
| Java | yes | Android only |
| .NET | yes, two flavours | none |

The only delivered Java sample targets Android — a different platform, a different
build, and a different licensing route from the Windows/Linux x86-64 target this
benchmark runs on.

## Decision

The binding is selected against seven criteria applied to what the archive
actually contains, in order: shipped in this trial, an official FingerCell sample
exists, exposes extract, exposes match, exposes or allows reading the settings,
supports runtime and module inspection, needs the least glue.

C++ is selected. It is the only binding that satisfies every criterion here.

The preference for Java is recorded as what it was — an engineering preference,
never a frozen requirement — and a constant says so, so that a later reader does
not mistake the outcome for a reversal of policy.

**Bindings are not mixed.** A route that took a sample from one, a default from
another and a signature from a third would be a route nobody could reproduce.

## Alternatives

**Keep Java and write the missing desktop sample.** That sample would be this
project's invention, and the settings and lifecycle it demonstrated would have no
upstream authority behind them. It is precisely what ADR 0105 refuses.

**Use the Android sample as the Java reference.** It is a real upstream sample,
for a platform this benchmark does not run on and a licensing route it does not
use.

**Choose .NET.** Nothing upstream demonstrates FingerCell through it.

## Consequences

The route follows a delivered, working, upstream example end to end.

It costs a compiled bridge instead of a JVM one, on a project whose other vendor
integration is Java — so the toolchain is wider than it would otherwise be.

The general rule generalises: freeze the criteria in advance, never the answer.
