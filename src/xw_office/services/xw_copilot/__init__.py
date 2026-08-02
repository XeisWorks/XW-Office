"""XW-Copilot integration services."""

from xw_office.services.xw_copilot.contracts import (
    XWCopilotError,
    XWCopilotRequest,
    XWCopilotResponse,
)
from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService
from xw_office.services.xw_copilot.ingress import XWCopilotIngress, XWCopilotIngressSignals
from xw_office.services.xw_copilot.live_dispatch import XWCopilotLiveDispatcher
from xw_office.services.xw_copilot.security import (
    generate_hmac_signature,
    is_within_replay_window,
    verify_hmac_signature,
)
from xw_office.services.xw_copilot.service import AuditEntry, XWCopilotService

__all__ = [
    "AuditEntry",
    "XWCopilotDryRunService",
    "XWCopilotError",
    "XWCopilotIngress",
    "XWCopilotIngressSignals",
    "XWCopilotLiveDispatcher",
    "XWCopilotRequest",
    "XWCopilotResponse",
    "XWCopilotService",
    "generate_hmac_signature",
    "is_within_replay_window",
    "verify_hmac_signature",
]
