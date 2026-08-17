# OpenAFIS raw 1:1 bridge (Stage 18A)

The smallest program that turns two minutiae template files into one raw OpenAFIS
similarity score. It is **not** an adapter: no ResultSet, no threshold, no
decision, no cache, and no knowledge of the benchmark's protocol beyond which side
of a pair is the probe.

Built against `neilharan/openafis` at commit
`3ae1c757c6dafea977a33ef51380e37f1715e626` (BSD-2-Clause), which lives in the
local artifact store outside this repository. No upstream byte is copied in here.

```bash
make FPBENCH_OPENAFIS_SOURCE=/path/to/openafis
```

## It is a transcription, not a design

Upstream's README publishes the 1:1 usage verbatim, and the bridge follows it
without addition — load two `TemplateISO19794_2_2005`, construct one
`MatchSimilarity`, call `compute`. The only deliberate difference is the id type
(`std::string` rather than `uint32_t`, so a score line can carry its pair id);
both are explicitly instantiated in upstream's own source, so this is a choice
between two shipped types and not a new one.

## The score is upstream's arithmetic, untouched

```text
result = (uint8_t)((maxMatched * maxMatched * 100)
                   / (probe.minutiaeCount() * candidate.minutiaeCount()))
```

assigned only when `maxMatched > Param::MinimumMinutiae` (4). When too little
structure pairs up, `result` keeps its initial 0 — so **0 is a valid raw score and
never a failure**. The ratio is unclamped, so values above 100 are possible and
have been observed. Nothing here transforms, scales, clamps or thresholds it.

## No template cache

Every comparison loads both sides fresh from disk, exactly as upstream's example
does. Parsing is a pure function of the file bytes, so a cache would be sound —
but it would be a question to answer later, and the parse is cheap. What Stage 18A
caches is the *extractor's* output on disk, which is a different thing.

## Subcommands

| Command | What it does |
|---------|--------------|
| `identity` | report the build's instruction set, matching parameters and template limits |
| `match <left> <right>` | one pair → one line |
| `batch` | stdin `id \t left \t right` → one line each, over one held-open process |

Output is tab-separated: `id status score load_left_us load_right_us match_us`.
`score` is the raw integer on `OK` and `-1` on every other status, so a failure can
never be read as a number. A per-pair problem is a status, not an exit code,
because the run must not stop for one bad template.

## Two build deviations, both plumbing

`-Werror` is dropped (upstream pairs it with `-Wall -Wextra -Wshadow
-pedantic-errors`, and a 2021 tree does not compile clean under gcc 13), and
`-fno-exceptions` is dropped (delaunator-cpp throws on degenerate minutiae; with
exceptions off, one bad template aborts the process and takes the rest of the run
with it). Everything that could move a score is upstream's: `-O3 -march=native
-mtune=native -fstrict-aliasing`, C++17, and no `-ffast-math`.

`src/fpbench_openafis_csv_instantiation.cpp` supplies the one explicit template
instantiation upstream's CSV reader is missing, so Stage 18A's fallback C is
reachable without editing the pinned tree.
