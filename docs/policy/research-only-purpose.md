# The project's purpose

**This is not a licence.** It says what fpbench intends to do. What others may do
with fpbench's own code is a separate question, answered by copyright default —
this repository carries no `LICENSE` file, and that is deliberate
([ADR 0081](../adr/0081-fpbench-is-personal-educational-research-only.md)).

## The declaration

```
PROJECT PURPOSE

personal educational research
and technical learning only

commercial use by project owner: false
commercial deployment: false
commercial service: false

third-party redistribution: false
third-party sublicensing: false

benchmark publication as academic work: not a project goal
```

The term that accompanies the system, in every enum and every document, is:

```
PERSONAL_EDUCATIONAL_RESEARCH
```

It is deliberately not `academic`. This project is not carried out within any
institution and is not a submission; a vocabulary that offered the word would see
it claimed.

## The intended operation

One string, shared by every third-party assessment in this repository, so that
two records cannot quietly be about different things:

> local execution on the project owner's own machine, for personal educational
> research, publishing no third-party bytes

Every restriction the project meets is weighed against *that*, and nothing else.

## Where it lives

`fpbench.third_party.purpose` derives the declaration in code. The published
`evidence/stage8e-research-only-policy/project-purpose.json` is checked against
that derivation rather than trusted, so editing the committed JSON is a finding
rather than a new policy.

The declaration's constructor refuses any value but `False` for each of the six
denials. That is what makes the operating rule in
[third-party-usage.md](third-party-usage.md) sound: a restriction on commercial
deployment cannot block an operation that never deploys — but only because the
project has committed, in a fingerprinted document, to never deploying.

## What it does not do

It creates no rights. It resolves no ambiguity. It cannot make a prohibited use
permitted, and it says nothing about what upstream's terms allow — that is
recorded separately and faithfully
([ADR 0082](../adr/0082-third-party-license-observation-is-separate-from-local-research-use.md)).

It also does not extend to anybody else. A risk the owner accepted for their own
machine is theirs; a third party cloning this repository has made no such
decision and inherits none of it.

## Changing it

A different purpose is a different declaration with a different fingerprint, and
every research-use decision in the repository cites the current one. Changing a
denial invalidates all of them — deliberately, because a project that started
deploying commercially would need its whole third-party analysis redone rather
than inherited.
