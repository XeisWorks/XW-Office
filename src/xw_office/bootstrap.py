"""Register application services on the DI container."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker as SessionMaker

from xw_office.core.container import Container
from xw_office.core.database import create_session_factory
from xw_office.services.background_jobs.service import BackgroundJobManager
from xw_office.services.calculation.service import CalculationService
from xw_office.services.commission.service import CommissionService, SevdeskCommissionProvider
from xw_office.services.clearing.gateways import (
    MollieClearingGateway,
    SevdeskClearingGateway,
    StripeClearingGateway,
    WixClearingGateway,
)
from xw_office.services.clearing.service import PaymentClearingService
from xw_office.services.crm.service import CrmService
from xw_office.services.daily_business.service import DailyBusinessService
from xw_office.services.digital_licenses import DigitalLicenseService
from xw_office.services.expenses.service import ExpenseAuditService
from xw_office.services.finanzonline import (
    FinanzOnlineClient,
    OssService,
    OssQuarterSnapshotStore,
    SevdeskOssDocumentProvider,
    SevdeskUvaPreviewProvider,
    TaxMonthlySnapshotStore,
    UvaDocumentSelector,
    UvaPayloadService,
    UvaPreviewService,
    UvaService,
    SevdeskZmInvoiceProvider,
    ZmService,
)
from xw_office.services.http_client import SevdeskConnection, build_sevdesk_connection
from xw_office.services.ideas.stores import (
    MARKETING_IDEAS_KEY,
    NOTATION_IDEAS_KEY,
    MarketingIdeasStore,
    NotationIdeasStore,
    default_marketing_ideas_path,
    default_notation_ideas_path,
)
from xw_office.services.inventory.service import InventoryService
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.draft_invoice.service import DraftInvoiceService
from xw_office.services.sendungen.service import OffeneSendungenService
from xw_office.services.special_orders import SpecialOrderService
from xw_office.services.transfers.service import OffeneUeberweisungenService
from xw_office.services.layout.service import LayoutToolsService
from xw_office.services.qr_codes.service import QrCodeService
from xw_office.services.mailing.service import MailDeliveryService
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.plc.service import PlcShipmentService
from xw_office.services.plc.statistics import PlcStatisticsService
from xw_office.services.plc.webservice import PlcWebserviceClient
from xw_office.services.printer_status.service import PrinterStatusService
from xw_office.services.secrets.service import SecretService
from xw_office.services.sevdesk.contact_client import ContactClient
from xw_office.services.sevdesk.invoice_client import InvoiceClient
from xw_office.services.sevdesk.part_client import PartClient
from xw_office.services.sevdesk.refund_client import SevDeskRefundClient
from xw_office.services.statistics.service import StatisticsService
from xw_office.services.products.catalog import ProductCatalogService
from xw_office.services.products.classification_rules import ReferenceClassifier
from xw_office.services.products.brand_service import ProductBrandService
from xw_office.services.products.field_bulk_service import ProductFieldBulkService
from xw_office.services.products.print_decision import PrintDecisionEngine
from xw_office.services.wix.client import WixProductsClient
from xw_office.services.wix.client import WixOrdersClient
from xw_office.services.wix.order_cache import WixOrderCache
from xw_office.services.wix.product_details_client import WixProductDetailsClient
from xw_office.services.clickup.client import ClickUpClient
from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService
from xw_office.services.xw_copilot.ingress import XWCopilotIngress
from xw_office.services.xw_copilot.live_dispatch import XWCopilotLiveDispatcher
from xw_office.services.xw_copilot.service import XWCopilotService
from xw_office.repositories import (
    ApiSecretRepository,
    ExpenseCheckRepository,
    PcRegistryRepository,
    PlcShipmentRepository,
    SettingKvRepository,
)


def register_default_services(container: Container) -> None:
    """Wire default singletons (Phase 1–6 baseline)."""
    container.register(BackgroundJobManager, lambda c: BackgroundJobManager())
    container.register(PrinterStatusService, lambda c: PrinterStatusService(c.config))
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
        ReferenceClassifier,
        lambda c: ReferenceClassifier.from_config(c.config.sku_rules),
    )
    container.register(
        WixOrderCache,
        lambda c: WixOrderCache(),
    )
    container.register(
        WixOrdersClient,
        lambda c: WixOrdersClient(
            secret_service=c.resolve(SecretService),
            order_cache=c.resolve(WixOrderCache),
            product_details_client=c.resolve(WixProductDetailsClient),
        ),
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
    container.register(PlcWebserviceClient, lambda c: PlcWebserviceClient())
    container.register(
        PlcShipmentService,
        lambda c: PlcShipmentService(
            c.resolve(PlcWebserviceClient),
            c.resolve(PlcShipmentRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
    container.register(
        PlcStatisticsService,
        lambda c: PlcStatisticsService(
            c.resolve(PlcShipmentRepository) if (c.config.database_url or "").strip() else None
        ),
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
        OffeneUeberweisungenService,
        lambda c: OffeneUeberweisungenService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            c.resolve(SecretService),
        ),
    )
    container.register(
        SpecialOrderService,
        lambda c: SpecialOrderService(
            secret_service=c.resolve(SecretService),
            wix_products=c.resolve(WixProductsClient),
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
        TaxMonthlySnapshotStore,
        lambda c: TaxMonthlySnapshotStore(),
    )
    container.register(
        UvaService,
        lambda c: UvaService(
            c.config,
            c.resolve(FinanzOnlineClient),
            preview_service=c.resolve(UvaPreviewService),
            payload_service=c.resolve(UvaPayloadService),
            zm_service=c.resolve(ZmService),
            snapshot_store=c.resolve(TaxMonthlySnapshotStore),
        ),
    )
    container.register(
        OssService,
        lambda c: OssService(
            SevdeskOssDocumentProvider(c.resolve(SevdeskConnection)),
            snapshot_store=c.resolve(OssQuarterSnapshotStore),
        ),
    )
    container.register(
        OssQuarterSnapshotStore,
        lambda c: OssQuarterSnapshotStore(),
    )
    def build_payment_clearing(c: Container) -> PaymentClearingService:
        secrets = c.resolve(SecretService)
        stripe_key = (
            secrets.get_secret("STRIPE_SECRET_KEY")
            or secrets.get_secret("STRIPE_API_KEY")
        )
        mollie_token = secrets.get_secret("MOLLIE_OAUTH_TOKEN")
        return PaymentClearingService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            stripe=StripeClearingGateway(stripe_key),
            mollie=MollieClearingGateway(mollie_token),
            wix=WixClearingGateway(
                secrets.get_secret("WIX_API_KEY"),
                secrets.get_secret("WIX_SITE_ID"),
            ),
            sevdesk=SevdeskClearingGateway(c.resolve(SevdeskConnection)),
            sepa_lookback_days=c.config.clearing.sepa_lookback_days,
            b2b_year_prefixes=c.config.clearing.b2b_year_prefixes,
        )

    container.register(PaymentClearingService, build_payment_clearing)
    container.register(
        ExpenseAuditService,
        lambda c: ExpenseAuditService(
            c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            expense_check_repo=(
                c.resolve(ExpenseCheckRepository) if (c.config.database_url or "").strip() else None
            ),
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
            c.resolve(InvoiceClient) if (c.config.sevdesk.api_token or "").strip() else None,
        ),
    )
    container.register(LayoutToolsService, lambda c: LayoutToolsService())
    container.register(
        QrCodeService,
        lambda c: QrCodeService(
            settings_repo=c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
        ),
    )
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
        CommissionService,
        lambda c: CommissionService(
            SevdeskCommissionProvider(
                c.resolve(SevdeskConnection),
                c.resolve(PartClient),
            )
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
        DigitalLicenseService,
        lambda c: DigitalLicenseService(
            invoices=c.resolve(InvoiceProcessingService),
            wix_orders=c.resolve(WixOrdersClient),
            catalog=c.resolve(ProductCatalogService),
            layout=c.resolve(LayoutToolsService),
            secret_service=c.resolve(SecretService),
            settings_repo=c.resolve(SettingKvRepository) if (c.config.database_url or "").strip() else None,
            inventory=c.resolve(InventoryService),
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
        container.register(PlcShipmentRepository, lambda c: PlcShipmentRepository(c.resolve(SessionMaker)))
        container.register(
            SettingKvRepository,
            lambda c: SettingKvRepository(c.resolve(SessionMaker)),
        )
        container.register(
            ApiSecretRepository,
            lambda c: ApiSecretRepository(c.resolve(SessionMaker)),
        )
        container.register(
            ExpenseCheckRepository,
            lambda c: ExpenseCheckRepository(c.resolve(SessionMaker)),
        )
