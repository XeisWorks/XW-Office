"""Code-owned connector registrations for the desktop invoice collector."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable

from xw_office.services.invoice_collection.auth.graph import (
    GraphTokenProvider,
    MsalInteractiveGraphTokenProvider,
)
from xw_office.services.invoice_collection.auth.secrets import KeyringSecretStore, SecretStore
from xw_office.services.invoice_collection.connectors.graph_mail import (
    GraphMailAttachmentConnector,
    MailMatchPolicy,
)
from xw_office.services.invoice_collection.connectors.graph_reader import (
    GraphMailAttachmentReader,
)
from xw_office.services.invoice_collection.connectors.mollie_invoices import (
    MollieInvoiceApi,
    MollieInvoicesConnector,
    MollieInvoicesHttpClient,
)
from xw_office.services.invoice_collection.domain import (
    DateRange,
    DocumentType,
    ProviderConnection,
    RouteSettings,
)
from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)
from xw_office.services.invoice_collection.factories import ConnectorFactoryRegistry
from xw_office.services.invoice_collection.security import ensure_invoice_collection_dirs


def build_connector_factories(
    *,
    token_provider_factory: Callable[..., GraphTokenProvider] | None = None,
    secret_store_factory: Callable[[], SecretStore] | None = None,
    mollie_api_factory: Callable[[str], MollieInvoiceApi] | None = None,
) -> ConnectorFactoryRegistry:
    """Register generic adapters; provider manifests never select executable imports."""
    factories = ConnectorFactoryRegistry()

    def graph_mail(
        connection: ProviderConnection,
        settings: RouteSettings,
        period: DateRange | None,
    ) -> GraphMailAttachmentConnector:
        options = settings.options
        mailbox = str(options.get("mailbox") or "").strip()
        sender_domains = frozenset(
            item.strip().casefold()
            for item in str(options.get("sender_domains") or "").split(",")
            if item.strip()
        )
        if not mailbox or not sender_domains:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONFIGURATION_ERROR,
                "Rechnungs-Postfach oder bestätigte Absenderdomains fehlen",
            )
        client_id = os.environ.get("MS_GRAPH_CLIENT_ID", "").strip()
        tenant_id = os.environ.get("MS_GRAPH_TENANT_ID", "").strip()
        if not client_id or not tenant_id:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONFIGURATION_ERROR,
                "Microsoft Graph Client-ID oder Mandanten-ID ist nicht eingerichtet",
            )
        mailbox_key = hashlib.sha256(mailbox.casefold().encode("utf-8")).hexdigest()[:20]
        cache_path = (
            ensure_invoice_collection_dirs()["auth"]
            / f"graph-{connection.tenant_id.value}-{mailbox_key}.cache"
        )
        provider_factory = token_provider_factory or MsalInteractiveGraphTokenProvider
        token_provider = provider_factory(
            client_id=client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            scopes=("Mail.Read",),
            cache_path=cache_path,
        )
        raw_type = str(options.get("document_type") or DocumentType.UNKNOWN.value)
        try:
            document_type = DocumentType(raw_type)
        except ValueError as exc:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONFIGURATION_ERROR,
                "Unbekannter Dokumenttyp für die Mailroute",
            ) from exc
        date_start = period.start if period else None
        date_end = period.end if period else None
        reader = GraphMailAttachmentReader(mailbox=mailbox, token_provider=token_provider)
        return GraphMailAttachmentConnector(
            connection=connection,
            reader=reader,
            policy=MailMatchPolicy(
                sender_domains=sender_domains,
                document_type=document_type,
            ),
            start=date_start,
            end=date_end,
        )

    factories.register("graph_mail_attachment", graph_mail)

    def mollie_invoices(
        connection: ProviderConnection,
        settings: RouteSettings,
        period: DateRange | None,
    ) -> MollieInvoicesConnector:
        if not settings.secret_ref:
            raise InvoiceCollectionError(
                InvoiceErrorCode.AUTH_REQUIRED,
                "Mollie-Zugang muss lokal im geschützten Speicher hinterlegt werden",
            )
        store = (secret_store_factory or KeyringSecretStore)()
        token = store.get(settings.secret_ref)
        api = (mollie_api_factory or MollieInvoicesHttpClient)(token)
        return MollieInvoicesConnector(
            connection=connection,
            api=api,
            start=period.start if period else None,
            end=period.end if period else None,
        )

    factories.register("mollie_invoices_v2", mollie_invoices)
    return factories
