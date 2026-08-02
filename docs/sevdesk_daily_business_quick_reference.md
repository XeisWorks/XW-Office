# sevDesk Daily Business - Quick Reference

## All Features - Checklist

### ✅ Core Fulfillment Operations
- [ ] **START ALL** - Process all open invoices (print invoice + label + send + update statuses)
- [ ] **PRINT ALL** - Print selected items (invoice or label)
- [ ] **CHECK PRODUCTS** - Validate product configuration before printing
- [ ] **START SELECTED** - Process only user-selected invoices
- [ ] **STOP** - Abort current batch operation

### ✅ Invoice Management
- [ ] Load/refresh open invoices from sevDesk
- [ ] Load/refresh completed invoices with pagination
- [X] Multi-select invoices for batch processing
- [ ] Display invoice list with: Date, Name, Amount, Weight, Order, Country, Address, Status
- [ ] PLC (Pick-Label-Confirm) mode for direct label printing

### ✅ Printing
- [ ] **PRINT SELECTED** button → Print invoice PDF
- [ ] **RECHNUNG DRUCKEN** button → Reprint invoice
- [ ] **LABEL DRUCKEN** button → Print shipping label
- [ ] Invoice printing at 600 DPI
- [ ] Label printing (DYMO 4x6 format configurable)
- [ ] Product preflight validation before printing (missing part, link missing, description mismatch)

### ✅ Panels: Auxiliary Sections

#### Offene Sendungen (To Send Emails)
- [ ] Fetch emails from Outlook (20-day lookback)
- [ ] Extract shipping address (with OpenAI optional parsing)
- [ ] Print labels directly from emails
- [ ] Mark emails as processed
- [ ] Generate payment QR codes (EPC/SEPA)
- [ ] State tracking in `to_send_state.json`

#### Offene Überweisungen (Transfer Emails)
- [ ] Fetch transfer/payment confirmation emails
- [ ] Extract payment references and IBANs
- [ ] Generate payment QR codes
- [ ] Email processing workflow
- [ ] State tracking in `open_transfers_state.json`

#### Mollie - Authorized Orders
- [ ] Fetch authorized (pending capture) orders from Mollie API
- [ ] Display order details with amount and date
- [ ] Capture payment action
- [ ] 14-day lookback window

#### Gutscheine (Coupons)
- [ ] Generate unique coupon codes (XW000001, XW000002, etc.)
- [ ] Browse recently created coupons
- [ ] Link coupons to orders/customers
- [ ] Store and retrieve coupon metadata

#### Rückerstattungen (Refunds)
- [ ] Search for invoices: by invoice number, customer name, or order reference
- [ ] Load invoice context with positions and refundability info
- [ ] Process line-item partial refunds
- [ ] Adjust shipping in refunds
- [ ] Create refund in Wix

#### Download-Links
- [ ] Search for orders by invoice number or order number
- [ ] Search window: 365 days (configurable)
- [ ] Generate download links for customers
- [ ] Cache search results (180-second TTL)
- [ ] Link to Wix Orders Dashboard

#### Rechnungsentwurf (Draft Invoices)
- [ ] Create new invoice draft
- [ ] Select customer from existing
- [ ] Add line items (products)
- [ ] Set quantities and prices
- [ ] Calculate tax
- [ ] Finalize to create in sevDesk

### ✅ Analysis Panel (Right side)
- [ ] Display buyer note from order
- [ ] Show products/pieces to print with titles and metadata
- [ ] **PRINT SELECTED** button for direct printing
- [ ] **Editable shipping address** with real-time edit detection
- [ ] **RECHNUNG DRUCKEN** button
- [ ] **LABEL DRUCKEN** button
- [ ] Error log (expandable)
- [ ] Processing log (Treeview with operation status)

### ✅ Batch Controls Panel (Right top)
- [ ] Summary: Show number of selected invoices
- [ ] Printer status display: ✅/⛔ X/Y available
- [ ] Printer details toggle
- [ ] Last action feedback
- [ ] Progress bar: X/Y with visual indicator
- [ ] All 5 operation buttons
- [ ] Enable/disable buttons based on batch running state

---

## Configuration Keys

### Printing
```
printing.invoice_printer     → Printer name for invoices
printing.label_printer       → Printer name for labels
printing.label_model         → Label model (e.g., dymo_4x6)
printing.label_size          → Label dimensions (e.g., 4x6)
printing.label_template_path → Path to label template (.lbx)
```

### APIs
```
sevdesk.api_token            → API key for sevDesk REST API
sevdesk.base_url             → https://my.sevdesk.de/api/v1
wix.api_key                  → API key for Wix APIs
wix.site_id                  → Wix site UUID
graph.tenant_id              → Azure AD tenant ID
graph.client_id              → Azure AD app client ID
mollie.api_key               → Mollie payment API key
```

### Email/Mail
```
graph.mail_days              → Email lookback days (default: 20)
graph.mailbox_user           → Inbox email address
graph.transfer_mailbox_user  → Transfer email address
email.subject_template       → Email subject line template
email.body_template          → Plain text email body
email.body_template_html     → HTML email body
```

### Search/Display
```
app.download_links_search_days  → Download link search window (default: 365)
app.request_timeout_sec         → API timeout in seconds (default: 45)
mollie.days                      → Mollie authorized orders lookback (default: 14)
```

### Tax
```
tax.allowed_tax_rates        → Array of valid tax rates [0, 0.1, 0.19, 0.07]
tax.allowed_tax_types        → Array of tax type names
```

### Coupons
```
wix_coupons.code_prefix      → Coupon code prefix (e.g., "XW")
wix_coupons.max_code_attempts → Max retry attempts for generation
wix_coupons.default_currency → Default currency code (e.g., "EUR")
```

---

## Database/Data Files

### Local State Files
```
data/inventory_store.json              → Product inventory
data/fulfillment_log.jsonl             → Operation log (JSON Lines)
data/wix_sevdesk_product_sync_map.json → Product mapping

state/to_send_state.json               → Processed emails
state/open_transfers_state.json        → Processed transfer emails
state/msal_cache.json                  → Authentication tokens

sku_flags.json                         → Product flags (unreleased, etc.)
sku_besetzung.json                     → Product instrumentation config
```

### No Database Tables
- Old sevDesk is file-based only
- New XW-Office will use PostgreSQL for multi-PC sync

---

## Services Overview

| Service | File | Purpose |
|---------|------|---------|
| **InvoiceProcessor** | invoice_processor.py | Main fulfillment orchestration |
| **SevDeskClient** | sevdesk_client.py | sevDesk REST API |
| **WixClient** | wix_client.py | Wix eCommerce APIs |
| **RefundManager** | refund_manager.py | Refund processing |
| **ProductPreflightService** | product_preflight.py | Product validation |
| **InvoicePrinter** | invoice_printer.py | QPrinter for invoices |
| **LabelPrinter** | label_printer.py | Label printer wrapper |
| **GraphMailClient** | ms_graph_mail.py | Microsoft Graph (Outlook) |
| **MollieClient** | mollie_client.py | Mollie payment API |
| **WixCouponsClient** | wix_coupons_client.py | Wix coupons API |

---

## Key Files

### Main UI
- `ui/app.py` (2900+ lines) - Main Daily Business view
- `ui/launcher.py` (600+ lines) - Module launcher
- `ui/batch_controls.py` - Batch operation controls
- `ui/analysis_panel.py` - Right-side invoice analysis
- `ui/invoice_list.py` - Invoice table (Treeview)

### Auxiliary Panels
- `ui/to_send_panel.py` - Email/shipment management
- `ui/widgets/refunds_panel.py` - Refund processing
- `ui/widgets/download_links_panel.py` - Download link generation
- `ui/widgets/coupons_panel.py` - Coupon management
- `ui/widgets/mollie_authorized_panel.py` - Payment capture
- `ui/draft_invoice_app.py` - Invoice creation

### Services
- `services/invoice_processor.py` - Fulfillment logic
- `services/sevdesk_client.py` - sevDesk API
- `services/wix_client.py` - Wix API
- `services/refund_manager.py` - Refund logic
- `services/product_preflight.py` - Product validation

### Integrations
- `integrations/ms_graph_mail.py` - Outlook integration
- `integrations/mollie_client.py` - Mollie API
- `services/wix_coupons_client.py` - Wix coupons

### Printing
- `printing/invoice_printer.py` - Invoice printing
- `printing/label_printer.py` - Label printing

---

## UI Element Map

### Left Panel
```
OFFENE RECHNUNGEN
├─ Treeview (multi-select)
├─ Date | Name | Amount | kg | Order | Country | Addr | Unrel | Note | PLC
└─ [Refresh button in toolbar]

ABGESCHLOSSENE RECHNUNGEN
├─ Treeview (last 15)
└─ [Load More] button

Bereich (Radio buttons)
├─ Offene Sendungen [OPEN X]
├─ Offene Überweisungen [OPEN X]
├─ Mollie - Authorized Orders [OPEN X]
├─ Gutscheine
├─ Rückerstattungen [OPEN X]
├─ Download-Links [OPEN X]
└─ Rechnungsentwurf

Panel Container
└─ [Dynamic panel based on selection]
```

### Right Panel
```
Batch Controls
├─ Summary: -
├─ Druckercheck: ✅ X/Y verfügbar [Details anzeigen]
├─ Letzte Aktion: -
├─ Progress bar [0% | 0/0]
├─ Status: "Bereit"
└─ Buttons: [START ALL] [PRINT ALL] [CHECK PRODUCTS] [START SELECTED] [STOP]

Analysis Panel (scrollable)
├─ BuyerNote: [Text, read-only]
├─ Produkte: [List] [PRINT SELECTED]
├─ Lieferadresse: [Text, editable]
├─ [RECHNUNG DRUCKEN] [LABEL DRUCKEN]
├─ Fehlerlog: [Text, collapsed]
└─ Verarbeitungslog: [Treeview, collapsed]
```

---

## Workflow: START ALL

1. **Collect invoices** → All open invoices from sevDesk
2. **For each invoice:**
   - Extract order reference (B2C/B2B classification)
   - Analyze invoice (get order, positions, address)
   - Validate products (preflight check)
   - Generate/print invoice PDF
   - Generate/print shipping label
   - Extract shipping address (update if edited)
   - Send confirmation email (optional)
   - Mark Wix order as fulfilled
   - Update sevDesk invoice status
   - Post payment if available
   - Update inventory
   - Log operation result
3. **Show summary** → Successes/failures in processing log
4. **Update UI** → Refresh invoice lists

---

## Workflow: PRINT ALL

1. **Collect selected items** → From invoice list
2. **For each item:**
   - Determine print type (invoice/label/product)
   - Resolve PDF path and configuration
   - Execute print job
   - Track success/failure
3. **Handle failures:**
   - Missing PDF → Prompt user for config
   - Printer error → Show error dialog
   - Skip on error (user optional)
4. **Update log** → Show all print operations

---

## Workflow: CHECK PRODUCTS

1. **Collect invoices** → All or selected
2. **For each position in each invoice:**
   - Check if part exists in sevDesk
   - Verify description matches
   - Check if position linked to part
   - Detect digital products (skip physical printing)
3. **Categorize issues:**
   - missing_part
   - link_missing
   - description_mismatch
   - link_and_description
   - none
4. **Show results:**
   - Dialog listing all issues
   - Allow user to: Create part, Update part, Link, Skip
   - Cache actions for batch processing

---

## Workflow: Process Refund

1. **Search** → Find invoice by number/name/order reference
2. **Load context** → Get positions, order data, refundability
3. **Select lines** → Choose which items to refund
4. **Adjust amounts** → Set quantities, shipping, tax
5. **Create refund** → POST to Wix API
6. **Update status** → Show confirmation

---

## Environment Variables

```bash
# Payment APIs
MOLLIE_API_KEY=...
WIX_B2B_SITE_ID=...

# Wix Coupons (overrides config.json)
WIX_COUPON_BASE_URL=...
WIX_COUPON_ENDPOINT_PATH=...
WIX_COUPON_SITE_ID=...
WIX_COUPON_API_KEY=...
WIX_SITE_ID=...
WIX_API_KEY=...

# Graph/Mail
SEVDESK_MSAL_CACHE_PATH=...
```

---

## Quick Start for XW-Office Migration

1. **Services Layer** → Already migrated (keep services, add DI container)
2. **UI Layer** → Rebuild with PySide6:
   - Invoice list as main view
   - Right sidebar for batch controls + analysis
   - Nested tabs/views for auxiliary panels
3. **Configuration** → Migrate from JSON to PostgreSQL:
   - Create config table with key-value pairs
   - Sync across PCs via Railway
4. **State** → Migrate JSON files to PostgreSQL:
   - `email_state` table (to_send, transfers)
   - `fulfillment_log` table (operations)
5. **API Integration** → No changes needed (Graph, Mollie, Wix, sevDesk all same)
6. **Testing** → Verify printing still works with QPrinter

---

**Last Updated:** April 4, 2026  
**For:** XW-Office PySide6 Rebuild  
**From:** XeisWorks/sevDesk Legacy Analysis
