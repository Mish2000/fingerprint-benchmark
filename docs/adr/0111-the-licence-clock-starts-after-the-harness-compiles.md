# The licence clock starts after the harness compiles

## Status

Accepted, implemented.

## Context

Stage 11A spent a 30-day VeriFinger trial. The clock started at activation, and
the first several days went on discovering that the main archive ships no Python
binding, that the qualification therefore had to run through the Java binding,
and that the Java binding needed a toolchain the machine did not have. Spec
correction 8 in that stage's own record says it plainly: an earlier version of
the preflight told every gate to activate the trial, which on a machine with no
Java would have started a 30-day clock to discover that nothing could compile.

Innovatrics licences are machine-bound, generated through a customer portal or a
REST interface, and — for an evaluation — time-limited. The same failure is
available here, with one difference that makes it worse: this project cannot
re-request a licence as casually as it can re-download an archive, because
obtaining one goes through a commercial relationship rather than a URL.

## Decision

An order of operations, stated as a rule and enforced by what the tooling will
and will not do.

```text
download
→ hash
→ inspect
→ select the official binding
→ identify the official 1:1 sample
→ build the qualification harness
→ compile and link successfully
→ only then generate or activate a licence
→ run ≤20 qualification comparisons
```

**There is no activate target, and there will not be one.** The Makefile has
`stage12a-acquire`, which reports where the vendor exchange stands and fetches
nothing, and `stage12a-qualify-fake`, which drives the entire harness against a
fake engine. Neither touches a licence. Generating one is a deliberate act by the
maintainer, taken once, by hand, after the harness compiles.

**The harness exists before the package does, and is proved before the package
does.** `QualificationEngine` is four methods behind a protocol; `FakeIdkitEngine`
implements it; CI drives every pass — both orientations, SELF from two
extractions, a real process restart, three provoked failures — on every run with
no package, no licence and no network. When a package arrives, one adapter
implements the protocol and the driver is unchanged.

**The fake can never answer a gate.** Every record carries an `EngineKind`, and
the preflight reads only `DELIVERED_SDK`. This is what makes it safe to run the
harness constantly: the thing that proves the plumbing cannot be mistaken for the
thing that qualifies the candidate.

**The qualification is capped at twenty score-producing comparisons**, enforced
in the budget object where the comparisons happen rather than checked afterwards.
This is a route check, not a measurement, and a clock is running.

## Alternatives

**Activate on delivery and figure the rest out afterwards.** What Stage 11A
effectively did. It works, and it costs days of a fixed budget on problems that
have nothing to do with the vendor.

**Build the harness against the real binding only.** Would mean no harness until
a package exists, and then writing one under time pressure with a clock running —
which is the exact circumstance in which somebody decides that four passes are
enough instead of six.

**Mock the binding inside the tests only.** Nearly this decision, and it leaves
the driver itself untested: the passes, the ceiling, the digest-instead-of-score
rule and the failed-run record all live in the driver, and those are the parts
that would be rewritten hastily.

## Consequences

The whole qualification path is exercised on every CI run today, months before a
package might arrive, and the twenty comparisons a real licence eventually pays
for go on the candidate rather than on debugging.

The cost is a fake engine that has to be kept honest. It is asymmetric because
the real one is documented to be, deterministic because a candidate that is not
would fail, and refuses a blank image with a status rather than a score — and if
the real binding turns out to differ from it in some fourth way, the fake proves
less than it appears to. The mitigation is that the fake proves the *driver*, not
the candidate, and the engine kind on every record says which is which.
