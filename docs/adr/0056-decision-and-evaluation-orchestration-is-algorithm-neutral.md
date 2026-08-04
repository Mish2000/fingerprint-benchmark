# 0056 — Decision and evaluation orchestration is algorithm-neutral

*Status: Accepted — 2026-08-04, stage 7D*

## Context

Stage 5A wrote the decision derivation for one SourceAFIS run. Stage 6B
generalised it over *two SourceAFIS runs* and said so explicitly: the engine
still read a SourceAFIS validation report and still knew what a bridge jar was,
and hardening it for a second algorithm was deferred as separate work with a
different shape.

Stage 7D is that work, and it is not a tidiness exercise. The stage ends in a
comparison between SourceAFIS's decisions and NBIS's decisions over the same
6,000 pairs. If those two sets were produced by two modules, then any difference
between the two sets of numbers could be a difference in how they were derived —
a different failure mapping, a different ordering, a different eligibility join —
and no amount of care about thresholds would recover the argument.

Stage 7A had already established the pattern one layer down:
`ResearchAdapterIntegration` injects everything algorithm-specific into a shared
research engine, and a structural test proves the engine names no algorithm.

## Decision

`experiments/algorithm_decisions.py` and `experiments/algorithm_evaluation.py`
hold the whole decision and evaluation orchestration. Neither contains the
strings `sourceafis`, `nbis`, `bridge`, `jar`, `mindtct` or `bozorth`, in an
import, a branch or a literal.

Everything algorithm-specific arrives through `DecisionSourceIntegration`, which
answers one question: *is this run's evidence chain sound enough to decide?* It
returns a `VerifiedDecisionSource` — research state, run, plan, pairs, images,
pair manifest hash, result-set manifest and ordered entries, the algorithm
validation fingerprint, the preparation binding, and the identity of whatever
markers made the raw scores authoritative.

The two SourceAFIS wrappers and the NBIS wrapper build an integration, load a
config and hand a spec to the engine. They implement no threshold, derive no
eligibility, build no view, and write no receipt.

The SELF independence requirement is a spec field rather than a constant,
because adapters word their evidence differently: the NBIS route records template
*persistence* separately from template caching, and a requirement that checked
only the caching key would pass a route that wrote templates to disk and reused
them.

## Consequences

Any difference between the two algorithms' numbers is a difference in the
algorithms or in their documented operating points. It cannot be a difference in
the derivation, because there is one derivation.

`decisionset_0122544e71b1` and `decisionset_df0d584bdede`, and the eligibility
and metric sets above them, re-verify unmoved after the extraction — which is the
only acceptable outcome for a refactor of code that produced published evidence.

A third algorithm needs an integration and a wrapper, and no change to either
engine.
