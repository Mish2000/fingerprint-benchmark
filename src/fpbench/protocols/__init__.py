"""Who takes part in an experiment, and which comparisons that implies.

Dependency rule: ``protocols`` may import ``core`` and reads dataset *records*,
but must not import ``adapters`` or any algorithm-specific code.
"""

from fpbench.protocols.base import Protocol
from fpbench.protocols.cohorts import CohortCriteria, eligible_subjects, select_cohort
from fpbench.protocols.cross_subject import (
    CROSS_SUBJECT_POPULATION,
    CrossSubjectPairAudit,
    CrossSubjectProtocolConfig,
    SD300CrossSubjectProtocol,
    audit_cross_subject_pairs,
    generate_cross_subject_pairs,
    load_cross_subject_protocol_config,
)
from fpbench.protocols.pair_generation import PairPlan, build_image_index, generate_pairs
from fpbench.protocols.sd300_protocol import (
    SD300Protocol,
    SD300ProtocolConfig,
    load_protocol_config,
)
from fpbench.protocols.self_filtering import (
    build_self_eligibility,
    collect_failed_fingers,
    select_self_eligible_pairs,
)

__all__ = [
    "CROSS_SUBJECT_POPULATION",
    "CohortCriteria",
    "CrossSubjectPairAudit",
    "CrossSubjectProtocolConfig",
    "PairPlan",
    "Protocol",
    "SD300CrossSubjectProtocol",
    "SD300Protocol",
    "SD300ProtocolConfig",
    "audit_cross_subject_pairs",
    "build_image_index",
    "build_self_eligibility",
    "collect_failed_fingers",
    "eligible_subjects",
    "generate_pairs",
    "generate_cross_subject_pairs",
    "load_cross_subject_protocol_config",
    "load_protocol_config",
    "select_cohort",
    "select_self_eligible_pairs",
]
