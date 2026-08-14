# The bridge compiles before the trial clock starts

## Status

Accepted, implemented. Restates ADR 0111 for a trial whose clock this project
starts deliberately rather than receives.

## Context

The FingerCell trial runs for 30 days. The delivered activation guide makes
activation an explicit act — a wizard on Windows, or a manual step — rather than a
side effect of unpacking or of first use.

That is a gift, and it is easy to waste. The natural order is to write an adapter,
run it, discover the API is not what was assumed, and iterate — with the clock
running from the first attempt. Stage 11A already learned the general form of this
lesson; here the clock is short and the debugging is the expensive part.

## Decision

The order is frozen, and the gate machine enforces it by refusing to let a later
gate pass while an earlier action is outstanding:

```text
download -> hash -> unpack -> inventory -> read the terms and the samples
  -> select one binding -> write the bridge -> compile and link
  -> only then activate the trial -> only then run
```

`BRIDGE_NOT_COMPILED` is a distinct outstanding action at the identity gate,
separate from `TRIAL_NOT_ACTIVATED` at the licence gate, so the published evidence
says which side of the line the work is on.

Everything before activation is done against delivered text: headers, sample
sources, tutorials, the licence agreement and the revision stamp. None of it needs
a licence, and all of it can be got wrong cheaply.

## Alternatives

**Activate first and explore interactively.** Fastest to a first score and the
most likely to burn the window on questions the headers already answer.

**Do not model the order at all.** Then the evidence cannot distinguish "the
bridge does not compile" from "the trial would not activate", which are different
findings with different responses.

## Consequences

The 30-day window is spent on qualification rather than on compilation errors.

It costs a stage that sits at `INCOMPLETE` for longer, because the honest state
before activation is now visible rather than skipped over.
