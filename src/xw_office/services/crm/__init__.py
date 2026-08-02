"""CRM services."""

from xw_office.services.crm.matching import contact_match_score, find_duplicate_candidates
from xw_office.services.crm.service import CrmService, MergeResult
from xw_office.services.crm.types import ContactRecord, DuplicateCandidate

__all__ = [
    "ContactRecord",
    "DuplicateCandidate",
    "CrmService",
    "MergeResult",
    "contact_match_score",
    "find_duplicate_candidates",
]
