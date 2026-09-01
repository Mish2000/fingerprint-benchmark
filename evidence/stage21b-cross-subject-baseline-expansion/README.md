# Stage 21B — frozen cross-subject baseline expansion

Stage 21B is an execution-only boundary. It runs the 73,500 frozen
`plain_roll_cross_subject_non_mated` pairs from the accepted Stage 21A protocol
against every member of `final_baseline_roster_v1`, using the existing certified
adapter routes and the immutable `prepset_be560e047991` canonical-500 input set.

The raw result tables live under the local workspace and are not duplicated in
Git. After all six result sets are complete, integrity-checked and sealed, this
directory receives non-score receipts containing their identities, counts,
failure classifications, timings and provenance hashes. The finalization marker
is written last. Its absence means Stage 21B is not complete.

Before that marker can be written, the publisher re-reads the unchanged legacy
6,000-pair manifest, binds the six accepted legacy raw-result identities from
the Stage 21A roster, re-derives every route's complete execution-source
closure, runs the Stage 21B contract/regression suite itself, and verifies all
six raw result stores. Adapter cleanup must also succeed before each result set
can be sealed.

This stage deliberately does not compute or publish TAR, FAR, FRR, thresholds,
score sweeps, calibration, normalization, cross-algorithm score comparisons or
rankings. Those operations belong to the final-baseline reporting component.
Operational status may report
completion, failures and timing, but never raw score values or score summaries.
