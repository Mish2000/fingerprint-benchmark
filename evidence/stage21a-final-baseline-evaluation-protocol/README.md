# Stage 21A — final baseline evaluation protocol freeze

`FINAL_BASELINE_EVALUATION_PROTOCOL_READY` freezes the comparison before any
cross-subject score exists. This stage generated metadata and a pair manifest;
it ran no matcher, read no raw score value, selected no operating threshold,
performed no calibration, and changed no algorithm parameter.

## Frozen comparison roster

The comparison contains the five primary baselines and, under the explicit
allowance to retain more than five methods that completed the full protocol,
the publication-eligible OpenAFIS capacity-extended method:

1. SourceAFIS Java 3.18.1
2. NBIS MINDTCT 5.0.0 + BOZORTH3
3. FLX DeepPrint TexMinu 512 without localization
4. VeriFinger 2025.2
5. NBIS MINDTCT + MCC SDK v2.0
6. NBIS MINDTCT + OpenAFIS (capacity-extended), labelled as an additional
   experimentally evaluated method

`baseline-roster.json` binds every method to its adapter or integration,
implementation identity, immutable raw result identity, score direction,
canonical preparation set, original pair-manifest hash, finalization
fingerprint, attempts, score-bearing outcomes and algorithm failures. Those
bindings were derived from manifests and finalization metadata, not score
values.

The earlier `fingerprints-matching` route is not in the roster. Its own Stage
15A publication says its score-bearing coverage is not a basis for comparison.
The exclusion uses that published operational-coverage conclusion and counts;
it does not inspect or rank score values.

## Legacy protocol remains invariant

`configs/protocols/sd300_50_subjects.yaml` still regenerates the exact stored
6,000 rows, in the exact order, under pair-manifest hash
`ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b`.
The extension has its own protocol and cohort identities and cannot overwrite
the legacy manifest.

## Cross-subject impostor population

For each release, subject A, different subject B and anatomical finger, the new
manifest contains exactly one directed pair:

```text
PLAIN(A, finger) -> ROLL(B, same finger)
```

All 50 × 49 ordered subject pairs and all ten fingers are present: 24,500 pairs
per release and 73,500 pooled. Ordering is release, left subject, right subject,
finger position. `cross-subject-pair-audit.json` re-derives impression,
subject, finger, release, ground truth, membership, uniqueness, collision and
balance invariants from image metadata.

## Frozen reporting semantics

Only TAR, FAR and FRR are biometric result columns. The primary view uses every
planned genuine and impostor attempt without SELF eligibility filtering.

- A genuine failure is not accepted, so it contributes to FRR and remains in
  the genuine denominator.
- An impostor failure is not a false accept, but remains in the FAR denominator.
- Planned attempts, score-bearing attempts and algorithm failures are shown as
  operational counts beside each result.

Each algorithm is swept over its own unique raw score values. Equal scores move
together. The sweep includes accept-none and accept-all-score-bearing
endpoints, performs no score normalization and never compares raw score scales
between algorithms. The reporting point is the highest observed TAR at or
below each predeclared FAR target; no interpolation is permitted. The targets
are 1%, 0.1% (primary) and 0.01%.

Results will be reported for SD300A, SD300B, SD300C and pooled. Pooled counts
sum numerators and denominators; they are not an average of release rates.
The releases are different-resolution digitizations of the same physical cards,
not independent biometric populations. A common-score population across all
six roster methods is secondary only; all-attempt remains primary.

The old same-subject, different-finger population remains unchanged and is
labelled `same-subject different-finger negative sanity`. It is not the primary
FAR denominator. Native documented rules, where one exists, belong in a
separate contextual table and are not treated as equal operating points.

## Future high-resolution method reservation

SD300B at native 1000 ppi and the same frozen 50 subjects is reserved as a
future test set. Training, parameter tuning and threshold tuning are forbidden.
SD300C may be supplementary 2000 ppi evaluation, but it is not an independent
development set because it derives from the same cards. `canonical500` remains
unchanged; any future pore-aware method uses a separate native-resolution lane.

## Evidence map

- `baseline-roster.json` — six frozen method identities and counts
- `predecessor-bindings.json` — content hashes of the metadata authorities
- `legacy-protocol-invariance.json` — exact 6,000-row regression binding
- `cross-subject-pair-binding.json` — new manifest identity and generation bind
- `cross-subject-pair-audit.json` — the complete 73,500-row structural audit
- `evaluation-policy.json` — TAR/FAR/FRR, failure and sweep semantics
- `high-resolution-test-reservation.json` — protected SD300B reservation
- `no-leakage-audit.json` — explicit absence of runs, scores and tuning
- `stage-21a-finalization.json` — all-or-nothing PASS marker

Regenerate the manifest and evidence from metadata only:

```bash
python scripts/stage21a_freeze.py --source-tree-clean-attested
```

The contract and evidence tests require no matcher, vendor runtime or raw score
file. The real-manifest regression additionally uses the local workspace
manifests.
