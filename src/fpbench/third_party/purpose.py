"""What fpbench is for, frozen once so that every later decision has a premise.

This is the shortest module Stage 8E added and the one everything else rests on.
Two things had to be written down before any third-party component could be
assessed:

**The purpose.** One person, one machine, learning. Not a product, not a service,
not a paper. The term is ``PERSONAL_EDUCATIONAL_RESEARCH`` and it is deliberately
not ``academic``: this project is not carried out within any institution, and a
vocabulary that offered the word would eventually see it claimed
(docs/adr/0081).

**The denials.** Six of them, all ``False``, all enforced by the declaration's
own constructor. They are what makes the policy in :mod:`fpbench.third_party.policy`
sound rather than convenient: a restriction on commercial use, on redistribution
or on sublicensing cannot block an operation that does none of those things — but
only because this project has committed, in a document with a fingerprint, to
doing none of them.

Nothing here is a licence for fpbench itself, and nothing here grants anybody any
right. A purpose declaration says what this project intends to do; a copyright
licence says what others may do with its code. Conflating them would create a new
legal question instead of answering one (docs/adr/0081).
"""

from __future__ import annotations

from fpbench.core.third_party_models import ProjectPurpose, ProjectPurposeDeclaration

__all__ = [
    "PROJECT_PURPOSE_STATEMENT",
    "PROJECT_PURPOSE_TERM",
    "project_purpose",
    "purpose_fingerprint",
]

#: The term that accompanies the system, in every document and every enum.
PROJECT_PURPOSE_TERM = ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH.value

#: The declaration in prose, and the exact bytes the fingerprint covers. Written
#: as one paragraph rather than a bulleted list because it is quoted verbatim
#: into the published evidence and into the README banner.
PROJECT_PURPOSE_STATEMENT = (
    "fpbench is a personal educational research project. It exists so that one "
    "person can learn how fingerprint recognition systems are measured, by "
    "running them locally on one machine. It is not a product, not a service, "
    "and not an academic submission. It makes no commercial use of any "
    "third-party component, deploys nothing commercially, offers no commercial "
    "service, redistributes no third-party bytes, sublicenses nothing, and does "
    "not treat publication of its benchmark as an academic work."
)


def project_purpose() -> ProjectPurposeDeclaration:
    """The one declaration, rebuilt from source rather than read from a file.

    Deriving it in code is what lets the published ``project-purpose.json`` be
    *checked* rather than trusted: the evidence gate rebuilds this object and
    compares fingerprints, so an edit to the committed JSON is a finding rather
    than a new policy.
    """
    return ProjectPurposeDeclaration(
        schema_version="1",
        purpose=ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH,
        statement=PROJECT_PURPOSE_STATEMENT,
        commercial_use_by_project_owner=False,
        commercial_deployment=False,
        commercial_service=False,
        third_party_redistribution=False,
        third_party_sublicensing=False,
        benchmark_publication_as_academic_work=False,
    )


def purpose_fingerprint() -> str:
    """The identity every research-use decision in this repository cites."""
    return project_purpose().purpose_fingerprint
