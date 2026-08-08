# 0081 — fpbench is personal educational research only

*Status: Accepted — 2026-08-08, stage 8E*

## Context

Every third-party question this project has faced so far was answered per
component, from scratch, with no stated premise. Stage 8A rejected a candidate
`LICENSE_BLOCKED` under a policy that required "use in an academic benchmark and
publication of the allowed evidence". Stage 8B executed the same artifact anyway,
under an owner instruction, and recorded the licence as unresolved. Both were
correct answers to the questions those stages asked. Neither said what the
project *is*, so neither could say which restrictions were relevant to it.

Without a stated purpose, every new algorithm restarts the argument, and the
argument is unwinnable: a licence that forbids commercial deployment is either a
blocker or not depending on whether this project deploys commercially, and
nothing in the repository said.

Two further facts made a written purpose necessary rather than merely tidy.

The repository is **public**. Whatever the owner intends personally, every byte
that enters Git is published, and the policy has to be written against that fact
rather than against an intention.

Stage 8A's gate spoke of an "academic benchmark". This project is not carried out
within any institution, has no supervisor of record, and is not a submission. A
vocabulary offering the word `academic` would see it used, and it would be a
claim nobody could support.

## Decision

The project's purpose is frozen as one declaration, with one term:

```
PERSONAL_EDUCATIONAL_RESEARCH
```

`fpbench.third_party.purpose` derives it in code, and the published
`project-purpose.json` is checked against that derivation rather than trusted.
The declaration carries six denials, each `False` and each enforced by the
declaration's own constructor:

```
commercial_use_by_project_owner          false
commercial_deployment                    false
commercial_service                       false
third_party_redistribution               false
third_party_sublicensing                 false
benchmark_publication_as_academic_work   false
```

Those denials are not decoration. They are what makes ADR 0082's operating rule
sound: a restriction on commercial deployment cannot block an operation that
never deploys, but only because the project has committed, in a fingerprinted
document, to never deploying.

The intended operation is one string, shared by every assessment in the
repository: local execution on the project owner's own machine, for personal
educational research, publishing no third-party bytes.

**No `LICENSE` file is added to this repository, and no bespoke "research only
licence" is written.** A purpose declaration says what this project intends to
do; a copyright licence says what others may do with its code. They are different
objects. Writing a custom licence to express a research purpose would create a
new legal question rather than answer one. In the absence of a licence, default
copyright applies to this repository's own code, which is the status quo and is
what the owner intends for now.

## Alternatives considered

**Call it academic research.** It would have matched Stage 8A's existing gate
vocabulary and it would have been false. The project has no institutional
affiliation, and an evidence trail that claimed one would be a claim a reader
could check and find wanting.

**Leave the purpose implicit and decide per component.** That is what the first
three algorithms did, and it produced three differently-shaped conclusions and no
rule. Algorithms 4 and 5 would have produced two more.

**Add a `LICENSE` describing the research purpose.** Rejected above: it conflates
two different instruments, and a bespoke licence is a licence nobody has
interpreted.

**Declare the purpose but leave the denials as prose.** Prose is not checkable.
A constructor that refuses `commercial_deployment: true` is; and the whole
policy's soundness depends on those six values, so they are the last thing that
should live in a paragraph.

## Consequences

Every research-use decision in the repository cites this declaration by
fingerprint. Changing any denial changes the fingerprint, which invalidates every
decision taken under it — deliberately, because a project that started deploying
commercially would need its whole third-party analysis redone rather than
inherited.

The declaration constrains the project, not upstream. It cannot create rights,
cannot resolve an ambiguity, and cannot make a prohibited use permitted. What it
does is make it possible to say, mechanically, which restrictions are relevant.

If the project's purpose ever changes, this is a new declaration with a new
fingerprint and a new stage — not an edit to this one.
