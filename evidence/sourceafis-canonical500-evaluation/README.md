# Canonical 500 ppi evaluations

One JSON and one Markdown file per canonical metric set.

## What these prove

That the 6,000 canonical decisions were counted under the **same immutable
metric policy** the native evaluation used — same fourteen metrics, same
numerators, same named denominators, same pooling rule — and that every rate is
reproducible from the counts it was computed from.

Nothing was redefined because the input is canonical. A metric whose denominator
moved with the input would make the two evaluations incommensurable, which is the
opposite of the point.

## What these are not

Not an accuracy figure. Not a false-match rate. Not a statement that canonical
inputs are better or worse than native ones — this report makes no reference to
the native run at all. The comparison between them is a third artefact, under
`evidence/sourceafis-native-vs-canonical500/`, with its own identity and its own
refusals (docs/adr/0036).

The threshold behind every number here is SourceAFIS's documented 40,
transferred unchanged from the native profile. Nothing was calibrated
(docs/adr/0037).

## Reading them

The Markdown file is the report, byte-identical to the one verified in the
workspace. The JSON is the receipt: identities, structural counts, and each
metric as the two integers it was computed from — never a percentage, because a
percentage is a rendering and renderings get subtracted.
