"""Platform TLS setup for desktop API clients."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_native_tls() -> None:
    """Use the Windows certificate store for requests/httpx/MSAL clients."""
    if os.name != "nt":
        return
    try:
        import truststore
    except ImportError:
        logger.warning("truststore is unavailable; Python CA bundle remains active")
        return
    truststore.inject_into_ssl()
