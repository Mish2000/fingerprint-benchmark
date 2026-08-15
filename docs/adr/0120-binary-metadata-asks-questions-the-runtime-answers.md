# Binary metadata asks questions the runtime answers

## Status

Accepted, implemented. Revised during Stage 13A: the first implementation kept
binary-derived facts as non-authoritative observations, and review removed them
altogether.

## Context

Two Stage 13A questions are most cheaply approached by looking at a compiled
module: which modules the algorithm depends on (the contamination question), and
which properties it carries (the settings closure question).

Reading a module's import table and its embedded printable strings answers both
quickly. Two things are wrong with letting that stand.

**The licence.** The delivered agreement forbids reverse engineering,
decompilation and disassembly. Reading a file's structure and its literals is not
translating its code, and it is what any dependency tool does — but "not
technically disassembly" is a poor foundation for a benchmark's evidence, and this
project does not need to stand on it.

**The epistemics.** A static import table describes what a module *can* load, not
what a process does load. An embedded string proves a name exists somewhere in a
binary, not that it is a supported, externally-selectable property. Both are
weaker than they look, and the second invites a settings closure built from
implementation internals — freezing symbols the benchmark could never have chosen
differently, which says nothing about reproducibility.

The decisive point is that neither question needed it. Both have supported
answers sitting in plain sight.

## Decision

Stage 13A does not inspect compiled modules at all. There is no evidence method
for it, so a fact obtained that way cannot be recorded even as an indication.

**The link closure comes from the delivered build files.** The tutorial's
`Makefile` and project file name the libraries for the official 1:1 route
outright:

```text
LDLIBS ?= -lFingerCell -lNMedia -lNCore -lNLicensing
```

and the bridge this project links records the same four as its own dynamic
dependencies. Both are ordinary build artifacts — one the vendor ships to be
read, one we produced.

**The settings surface comes from the documentation, the headers and the
runtime.** The delivered documentation names the extractor's parameters and
defaults; the binding exposes three of them directly; and the SDK's own property
capture reports what a constructed engine actually holds. A constant states that
the closure covers **externally-selectable values only** — what upstream offers,
not what a module contains.

The evidence method vocabulary is therefore all authorities:
`DELIVERED_TEXT_FILE`, `DELIVERED_HEADER`, `DELIVERED_SAMPLE_SOURCE`,
`DELIVERED_BUILD_FILE`, `DELIVERED_DOCUMENTATION`, `DIRECTORY_LISTING`.

## Alternatives

**Keep binary observations, marked non-authoritative.** The first implementation.
It is honest and it still leaves the licence question open and a tempting
almost-authority in the evidence. Removing it cost nothing, because the supported
sources say the same thing.

**Let the import table settle the contamination gate.** Strong evidence of the
wrong kind: a module can be loaded dynamically and a static table would not show
it.

**Skip the contamination question until runtime.** It is the highest-value
question this stage asks and the delivered build files answer it before anything
is executed.

## Consequences

The contamination claim rests on two ordinary build artifacts, and the settings
closure rests on documentation plus the SDK's own property mechanism. Nothing in
Stage 13A's evidence depends on having opened a vendor binary.

It costs the one genuinely surprising finding that binary inspection produced — a
property name absent from both the typed API and this project's prior plan. That
loss is bounded: the runtime property capture will report it if it is real and
externally selectable, and if it is not, it was never a setting this benchmark
could have chosen.
