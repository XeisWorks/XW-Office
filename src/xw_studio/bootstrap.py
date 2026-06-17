"""Register application services on the DI container."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker as SessionMaker

from xw_studio.core.container import Container
from xw_studio.core.database import create_session_factory
from xw_studio.services.calculation.service import CalculationService
from xw_studio.services.clearing.gateways import (
    MollieClearingGateway,
    SevdeskClearingGateway,
    StripeClearingGateway,
    WixClearingGateway,
)
from xw_studio.services.clearing.service import PaymentClearingService
from xw_studio.services.crm.service import CrmService
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.expenses.service import ExpenseAuditService
from xw_studio.services.finanzonline import (
    FinanzOnlineClient,
    SevdeskUvaPreviewProvider,
    UvaDocumentSelector,
    UvaPayloadService,
    UvaPreviewService,
    UvaService,
    SevdeskZmInvoiceProvider,
    ZmService,
)
from xw_studio.services.http_client import SevdeskConnection, build_sevdesk_connection
from xw_studio.services.ideas.stores import (
    MARKETING_IDEAS_KEY,
    NOTATION_IDEAS_KEY,
    MarketingIdeasStore,
    NotationIdeasStore,
    default_marketing_ideas_path,
    default_notation_ideas_path,
)
from xw_studio.services.inventory.service import InventoryService
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.draft_invoice.service import DraftInvoiceService
from xw_studio.services.sendungen.service import OffeneSendungenService
from xw_studio.services.layout.service import LayoutToolsService
from xw_studio.services.mailing.service import MailDeliveryService
from xw_studio.services.printing.print_queue import PrintQueueService
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sevdesk.contact_client import ContactClient
from xw_studio.services.sevdesk.invoice_client import InvoiceClient
from xw_studio.services.sevdesk.part_client import PartClient
from xw_studio.services.sevdesk.refund_client import SevDeskRefundClient
from xw_studio.services.statistics.service import StatisticsService
from xw_studio.services.products.catalog import ProductCatalogService
from xw_studio.services.products.brand_service import ProductBrandService
from xw_studio.services.products.field_bulk_service import ProductFieldBulkService
from xw_studio.services.products.print_decision import PrintDecisionEngine
from xw_studio.services.wix.client import WixProductsClient
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.services.wix.product_details_client import WixProductDetailsClient
from xw_studio.services.clickup.client import ClickUpClient
from xw_studio.services.xw_copilot.dry_run import XWCopilotDryRunService
from xw_studio.services.xw_copilot.ingress import XWCopilotIngress
from xw_studio.services.xw_copilot.live_dispatch import XWCopilotLiveDispatcher
from xw_studio.services.xw_copilot.service import XWCopilotService
from xw_studio.repositories import ApiSecretRepository, PcRegistryRepository, SettingKvRepository


def register_default_services(container: Container) -> None:
    """Wire default singletons (Phase 1–6 baseline)."""
    container.register(
        SecretService,
        lambda c: SecretService(
            c.config,
            c.resolve(ApiSecretRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        SevdeskConnection,
        lambda c: build_sevdesk_connection(
            c.config,
            api_token=c.resolve(SecretService).get_secret("SEVDESK_API_TOKEN"),
        ),
    )
    container.register(
        InvoiceClient,
        lambda c: InvoiceClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        ContactClient,
        lambda c: ContactClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        PartClient,
        lambda c: PartClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        SevDeskRefundClient,
        lambda c: SevDeskRefundClient(c.resolve(SevdeskConnection)),
    )
    container.register(
        ProductCatalogService,
        lambda c: ProductCatalogService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        PrintDecisionEngine,
        lambda c: PrintDecisionEngine(
            catalog=c.resolve(ProductCatalogService),
            part_client=c.resolve(PartClient),
        ),
    )
    container.register(
        WixOrdersClient,
        lambda c: WixOrdersClient(secret_service=c.resolve(SecretService)),
    )
    container.register(
        DraftInvoiceService,
        lambda c: DraftInvoiceService(
            c.resolve(SevdeskConnection),
            c.resolve(WixOrdersClient),
            c.resolve(PartClient),
            c.resolve(ContactClient),
            c.resolve(InvoiceClient),
        ),
    )
    container.register(
        PrintQueueService,
        lambda c: PrintQueueService(),
    )
    container.register(
        InvoiceProcessingService,
        lambda c: InvoiceProcessingService(
            c.config,
            c.resolve(InvoiceClient),
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            c.resolve(WixOrdersClient),
            c.resolve(MailDeliveryService),
            c.resolve(DraftInvoiceService),
            c.resolve(PrintQueueService),
        ),
    )
    container.register(
        OffeneSendungenService,
        lambda c: OffeneSendungenService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            c.resolve(SecretService),
        ),
    )

    container.register(
        FinanzOnlineClient,
        lambda c: FinanzOnlineClient(
            c.config,
            secret_service=c.resolve(SecretService),
        ),
    )
    container.register(
        UvaDocumentSelector,
        lambda c: UvaDocumentSelector(),
    )
    container.register(
        UvaPreviewService,
        lambda c: UvaPreviewService(
            SevdeskUvaPreviewProvider(c.resolve(SevdeskConnection)),
            selector=c.resolve(UvaDocumentSelector),
        ),
    )
    container.register(
        UvaPayloadService,
        lambda c: UvaPayloadService(c.resolve(UvaPreviewService)),
    )
    container.register(
        ZmService,
        lambda c: ZmService(SevdeskZmInvoiceProvider(c.resolve(SevdeskConnection))),
    )
    container.register(
        UvaService,
        lambda c: UvaService(
            c.config,
            c.resolve(FinanzOnlineClient),
            preview_service=c.resolve(UvaPreviewService),
            payload_service=c.resolve(UvaPayloadService),
            zm_service=c.resolve(ZmService),
        ),
    )
    def build_payment_clearing(c: Container) -> PaymentClearingService:
        secrets = c.resolve(SecretService)
        stripe_key = (
            secrets.get_secret("STRIPE_SECRET_KEY")
            or secrets.get_secret("STRIPE_API_KEY")
        )
        mollie_token = (
            secrets.get_secret("MOLLIE_ACCESS_TOKEN")
            or secrets.get_secret("MOLLIE_OAUTH_TOKEN")
            or secrets.get_secret("MOLLIE_API_KEY")
        )
        return PaymentClearingService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            stripe=StripeClearingGateway(stripe_key),
            mollie=MollieClearingGateway(mollie_token),
            wix=WixClearingGateway(
                secrets.get_secret("WIX_API_KEY"),
                secrets.get_secret("WIX_SITE_ID"),
            ),
            sevdesk=SevdeskClearingGateway(c.resolve(SevdeskConnection)),
        )

    container.register(PaymentClearingService, build_payment_clearing)
    container.register(
        ExpenseAuditService,
        lambda c: ExpenseAuditService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        StatisticsService,
        lambda c: StatisticsService(c.resolve(InvoiceClient)),
    )
    container.register(
        WixProductsClient,
        lambda c: WixProductsClient(secret_service=c.resolve(SecretService)),
    )
    container.register(
        WixProductDetailsClient,
        lambda c: WixProductDetailsClient(secret_service=c.resolve(SecretService)),
    )
    container.register(
        ClickUpClient,
        lambda c: ClickUpClient(secret_service=c.resolve(SecretService)),
    )
    container.register(
        XWCopilotService,
        lambda c: XWCopilotService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        XWCopilotLiveDispatcher,
        lambda c: XWCopilotLiveDispatcher(
            crm_service=c.resolve(CrmService) if (c.config.sevdesk.api_token or "").strip() else None,
            invoice_processing=c.resolve(InvoiceProcessingService),
            inventory_service=c.resolve(InventoryService),
        ),
    )
    container.register(
        XWCopilotDryRunService,
        lambda c: XWCopilotDryRunService(
            c.resolve(XWCopilotService),
            audit_service=c.resolve(XWCopilotService),
            live_dispatcher=c.resolve(XWCopilotLiveDispatcher),
        ),
    )
    container.register(
        XWCopilotIngress,
        lambda c: XWCopilotIngress(c.resolve(XWCopilotDryRunService)),
    )
    container.register(
        CrmService,
        lambda c: CrmService(
            c.config,
            c.resolve(ContactClient) if (c.config.sevdesk.api_token or "").strip() else None,
        ),
    )
    container.register(LayoutToolsService, lambda c: LayoutToolsService())
    container.register(
        MailDeliveryService,
        lambda c: MailDeliveryService(secret_service=c.resolve(SecretService)),
    )
    container.register(
        CalculationService,
        lambda c: CalculationService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        DailyBusinessService,
        lambda c: DailyBusinessService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            c.resolve(InvoiceProcessingService),
        ),
    )
    container.register(
        InventoryService,
        lambda c: InventoryService(
            c.config,
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            c.resolve(PrintQueueService),
        ),
    )
    container.register(
        ProductBrandService,
        lambda c: ProductBrandService(c.resolve(InventoryService), c.resolve(WixProductsClient)),
    )
    container.register(
        ProductFieldBulkService,
        lambda c: ProductFieldBulkService(c.resolve(InventoryService), c.resolve(WixProductDetailsClient)),
    )

    container.register(
        MarketingIdeasStore,
        lambda c: MarketingIdeasStore(
            default_marketing_ideas_path(),
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            MARKETING_IDEAS_KEY,
        ),
    )
    container.register(
        NotationIdeasStore,
        lambda c: NotationIdeasStore(
            default_notation_ideas_path(),
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            NOTATION_IDEAS_KEY,
        ),
    )

    # PostgreSQL persistence layer: only register when DATABASE_URL is configured.
    # This keeps local dev/test environments (no DB) working without needing env vars.
    if (container.config.database_url or "").strip():
        container.register(SessionMaker, lambda c: create_session_factory(c.config))
        container.register(PcRegistryRepository, lambda c: PcRegistryRepository(c.resolve(SessionMaker)))
        container.register(
            SettingKvRepository,
            lambda c: SettingKvRepository(c.resolve(SessionMaker)),
        )
        container.register(
            ApiSecretRepository,
            lambda c: ApiSecretRepository(c.resolve(SessionMaker)),
        )
