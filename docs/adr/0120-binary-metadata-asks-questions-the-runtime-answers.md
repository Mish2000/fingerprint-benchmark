# Binary metadata asks questions the runtime answers

## Status

Accepted, implemented.

## Context

Two Stage 13A questions are most cheaply approached by looking at a compiled
module: which modules the algorithm depends on (the contamination question), and
which properties it carries (the settings closure question).

Reading a module's import table and its embedded printable strings answers both
quickly. It is also uncomfortably close to a line the delivered licence draws: the
agreement forbids reverse engineering, decompilation and disassembly.

Reading a file's structure and its literals is not translating its code, and it is
what any packaging or dependency tool does. But "not technically disassembly" is a
poor foundation for a gate, and there is a second problem that is purely
technical: a static import table describes what a module *can* load, not what a
process *does* load, and an embedded string proves a name exists somewhere in a
binary, not that it is a live, settable property.

## Decision

Facts obtained from compiled-module metadata are recorded with their method named,
and they **settle nothing**.

The observation register carries an explicit method for each delivered fact.
`DELIVERED_TEXT_FILE`, `DELIVERED_HEADER`, `DELIVERED_SAMPLE_SOURCE`,
`DELIVERED_DOCUMENTATION` and `DIRECTORY_LISTING` are authorities.
`COMPILED_MODULE_METADATA` is not: a property on the record reports that it may
not settle a gate, and its weight is downgraded to an indication.

What it is for is generating questions. The import table says which modules to
expect, and the runtime's own module reporting confirms what was loaded. The
embedded names say which properties to ask for, and the SDK's supported property
mechanism confirms which exist and what they hold.

The contamination claim and the settings closure are therefore both settled by
supported calls against a running engine, with the delivered headers and samples
as the documentary authority — and the static observation recorded as the reason
anybody knew to ask.

## Alternatives

**Let the import table settle the contamination gate.** It is strong evidence and
it is still the wrong kind: a module can be loaded dynamically, and a static table
would not show it.

**Do not inspect the binary at all.** The settings surface being wider than the
typed API is the single most useful thing this stage has learned so far, and
nothing in the documentation said it.

## Consequences

Two gates that could have been closed quickly and weakly are instead open and
recorded as awaiting a runtime observation.

The evidence states how every delivered fact was obtained, so a reader can weigh
each one without taking the conclusion on trust.
