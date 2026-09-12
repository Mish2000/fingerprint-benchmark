# 0141 — The L3 bridge is a bounded development pilot outside the frozen baseline

## Status

Accepted for the first L3 bridge execution, 2026-09-12.

## Context

V2 contains a Survey-FCN/SIFT/spatial composite route, and Experiment 004 in
`fingerprint-new-method` supplies a frozen pore detector. Neither establishes
full-print SD300B matching performance. Stage 21A reserves the existing 50
subjects for future evaluation across all resolutions of their physical cards.
The proposed bridge needs native high-resolution development inputs and local
per-image caching; it must not change the frozen benchmark's image-to-score
contract or its source closure to obtain either.

## Decision

Keep the pilot in `V2/experiments/l3_bridge_v1/`. This is a separate experimental
driver, not a new baseline adapter or a published stage. It does not change
shared runner, storage, decision, image preparation or publication semantics.
The existing stateless SourceAFIS integration is reused for the control. There
is no missing extension point to patch in the frozen baseline: persistent
per-image pore features belong to this local experimental route.

Select 20 development subjects by the declared hash ordering of the actual
eligible candidates after subject-level exclusion of all 50 reserved subjects.
Execute only the first five: 100 original SD300B images at declared 1000 PPI,
50 genuine and 200 directed same-position cross-subject impostor pairs. Freeze
selection before inference. No quality, score, SELF or registration condition
may change those pairs. Record known historical exposure without claiming the
remaining candidates are unexposed or revising the historical test cohort.

P1 and P2 are two configurations of one composite chain. P2 uses seed40401 by
seed order, not by measured results, with its original scale guard and detection
settings. Both use the same SIFT/matcher implementation and runtime, and native
image coordinates. P1's proven zero-based coordinate correction has a new route
identity; old V2 code/results remain unchanged. Failed normalization is recorded,
not repaired through undocumented guard changes. A later estimator, guard,
matching or fusion change needs a separately declared variant before execution.

Keep features, images, scores, identifiers and examples in the ignored local
workspace. Version acquisition instructions, source/weight hashes, settings,
tests and an aggregate operational account. Preserve zero as a native score and
failures as failures. The report distinguishes planned/executed/scored/failure/
blocked counts, physical matcher calls and scored-only descriptive sweeps with
atomic ties. It does not choose an operating threshold or claim final FAR.

ADR 0017 still applies: execution pins a clean implementation commit; no source
edit or commit occurs during any research process. Permission to proceed locally
is a working decision, not evidence of supervisor or sponsor approval. No
messages, purchases, new commercial activation, external biometric upload,
retraining or automatic full-cohort extension is part of this pilot.

## Alternatives

Extending frozen baseline infrastructure to cache features would alter its
contract and the source closures that downstream evidence binds. Reusing the
reserved 50 for convenience would violate the development boundary. Relaxing
P2's scale band to secure successful outputs would silently create another
research configuration. None is necessary for this bounded experiment.

## Consequences

The pilot can complete with blocked routes, preprocessing failures or weak
separation. A software pass is not research success. P1 and control results are
reported when available even if P2 cannot score. The pilot's 200 impostors
cannot establish performance at FAR=0.1%; timings differ from Stage 21C. A
20-subject extension and an independent screening/confirmation protocol remain
separate decisions after review of this first execution.
