# Stage 20B — MINDTCT + MCC SDK v2.0, canonical raw run

The candidate Stage 20A qualified, built into a real fpbench adapter and run over
the same 6,000 canonical comparisons as every other algorithm in this benchmark.

```text
canonical gray8 500 ppi image
        ↓
NBIS MINDTCT 5.0.0            (the certified Linux build Algorithm 2 runs)
        ↓
mechanical minutiae translation
        ↓
official MCC SDK v2.0         (University of Bologna, unmodified)
        ↓
baseline MCC template
        ↓
official MCC matcher
        ↓
raw System.Double similarity in [0,1]
```

**Outcome: `MINDTCT_MCC_SDK_V2_CANONICAL_RAW_COMPLETE`.** 6,000 attempted, 6,000
stored, 6,000 score-bearing, 0 missing, 0 failures of any kind.

## What this stage did not produce

No `MATCH`, no `NON_MATCH`, no threshold, no TAR, no FAR, no FRR, no FMR, no
FNMR, no EER, no calibration and no ranking. The MCC SDK gave Stage 20A no native
decision threshold, so Stage 20B does not invent one. The supervisor's question
about processing matched and non-matched results is a separate stage.

## The identity, and why it names two things

`nbis_mindtct_mcc_sdk_v2` — *NBIS MINDTCT + MCC SDK v2.0*, not "MCC".

The official SDK contains no image extractor; it accepts minutiae. MINDTCT
therefore produces half of every score here, and a method called "MCC" would be
claiming an extractor Bologna never shipped. This route shares that extractor
with the NBIS/BOZORTH3 method and differs in the matcher, which is exactly what
makes the pair worth comparing and exactly why the sharing is stated rather than
glossed.

Nothing of the vendor's was modified. `MccSdk.dll` is loaded as downloaded
(`7267ea9f…2eb01`, the assembly Stage 20A hashed), at its own optimal parameters,
with not one parameter setter called anywhere in the route — `validate_environment`
reads all thirty of them back off the assembly and refuses to start if any differs
from what Stage 20A recorded.

## Two gates, and no more

Stage 20A did the research and closed the route. Stage 20B checks the plumbing
built on top of it, and nothing else.

**Gate A — the production bridge reproduces Stage 20A exactly.** Five comparisons
over Bologna's own `SampleMinutiae`, through the production bridge and the
production payload format, against the doubles Stage 20A's qualification probe
recorded. **5/5 bit-identical, both symmetry pairs preserved, no tolerance
applied.**

```text
self               0.6463866269440767
related  A→B / B→A 0.18989714373119645 / 0.18989714373119645
unrelated A→B / B→A 0.10158917843359545 / 0.10158917843359545
```

Gate A goes through the *production* `CreateMccTemplate(int, int, int, Minutia[])`
rather than the text-template API the Stage 20A probe used. Appendix A of the SDK
manual defines the sample text format as image width, height, resolution and one
`x y direction` row per minutia — the exact arguments the production API takes —
so the two carry identical input. It therefore exercises the payload format, the
bridge, the template API and the matcher together. It exercises nothing about
MINDTCT, and says so in its own record.

**Gate B — this route's MINDTCT is Algorithm 2's, byte for byte.** Twelve
canonical images, frozen in source before any extraction (two plain and two roll
per release, at most one per subject, taken in the preparation set's published
order), put through *both adapters' own extraction paths*. **12/12 XYT outputs
identical.** Two runs of one script would only have shown that MINDTCT is
deterministic; this shows the two routes agree. No score is read anywhere in it.

## The run

Same preparation set (`prepset_be560e047991`), same 6,000-row pair manifest
(`ee4d942e…7dfe3b`), same row order. No pair was regenerated, no dataset changed.

| protocol stage | n | min | median | max |
|---|---|---|---|---|
| `plain_self` | 1500 | 0.5749 | 0.6562 | 0.7911 |
| `roll_self` | 1500 | 0.6486 | 0.6918 | 0.7297 |
| `plain_roll_mated` | 1500 | 0.0786 | 0.2066 | 0.3916 |
| `plain_roll_non_mated` | 1500 | 0.0813 | 0.0938 | 0.1671 |

6,000 distinct score values, no zeros, nothing outside `[0,1]`. MINDTCT found a
median of 137 minutiae per side (9 to 373); 6,232 of the 12,000 sides carry more
than 128, which the MCC SDK accepts without complaint.

Median per comparison: MINDTCT 70 ms and 119 ms, translation 0.04 ms and 0.08 ms,
MCC template construction 32 ms and 6.9 ms, MCC matching 19 ms, 435 ms in total.
The whole run took 2,652 s. The asymmetry in the two template timings is JIT
warm-up in a fresh CLR, not a difference between the sides.

## How it runs on two operating systems

`MccSdk.dll` is a Windows .NET Framework assembly; the certified MINDTCT is a
Linux binary. Rather than compile a second MINDTCT for Windows — which would have
made "the same extractor as Algorithm 2" a claim about two similar binaries — the
route spans both:

```text
fpbench and MINDTCT on the certified linux/x86_64 target under WSL
        ↓
the MCC bridge as a Windows .NET Framework process, reached by interop
        ↓
MccSdk.dll
```

**One bridge process per comparison**, not a persistent worker. It costs about
50 ms of process launch and 30 ms of JIT per pair; it buys no state between pairs,
no configuration that can leak, every comparison starting from the SDK's own
defaults, and one pair's failure unable to contaminate the next.

Every comparison also re-checks that the five runtime assets are still the ones
preflight approved. A drift would have ended the run rather than producing
outcomes attributed to tools that changed underneath them.

## The one comparison the diagnostics are allowed to make

Because Gate B proves the extractor really is shared, rank agreement between
`MINDTCT → BOZORTH3` and `MINDTCT → MCC` means something. Over all 6,000 pairs,
both of which scored every one: **Spearman ρ = 0.897**.

It does not say which is better. The two scales are unrelated, no common operating
point exists, and "better" needs a calibration that has not happened.

## Why this route is preferred, and when that was decided

Frozen in source *before* the run, and for a reason knowable before it:

```text
MCC          official SDK, unmodified upstream matcher, vendor's own defaults
OpenAFIS 19B project-defined capacity extension, modified upstream source
```

Both share MINDTCT, so OpenAFIS has no independence advantage to weigh against
that. `selection_based_on_sd300_accuracy` is `false` and the numbers above played
no part in it (`docs/adr/0137`).

The capacity-extended OpenAFIS result is **not** deleted. It remains valid and
moves to *additional experimentally evaluated methods*.

## What is here, and what is not

Eight documents and a marker. No vendor byte: the archive, `MccSdk.dll`, the
sample minutiae and the compiled bridge all stay in the local artifact store,
because Stage 20A recorded
`official_artifact_cannot_be_redistributed_by_this_repository` and that has not
changed. What is committed is the bridge's source, the hashes, the documentation
of provenance and the tests.

## The disclosure this number travels with

> NBIS MINDTCT + MCC SDK v2.0 — a composition defined by this project. It shares
> the MINDTCT extractor with the NBIS/BOZORTH3 method and differs in the matcher:
> minutiae are passed to the official Minutia Cylinder-Code SDK v2.0 published by
> the University of Bologna, unmodified and at its own optimal parameters. The SDK
> contains no image extractor, which is why the extractor is named in the method.
> Scores are the SDK's raw similarity in [0,1]; no threshold, calibration or
> decision was applied.
