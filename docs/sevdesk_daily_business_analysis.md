# sevDesk Repository - Daily Business (Fulfillment) Complete Analysis

**Analysis Date:** April 2026  
**Repository:** XeisWorks/sevDesk  
**Main Module:** `sevdesk_wix_fulfillment/` 

---

## Table of Contents

1. [Menu Structure](#menu-structure)
2. [Daily Business UI Layout](#daily-business-ui-layout)
3. [Core Features & Operations](#core-features--operations)
4. [Sub-Panels & Auxiliary Sections](#sub-panels--auxiliary-sections)
5. [Services & Dependencies](#services--dependencies)
6. [Configuration Reference](#configuration-reference)
7. [Data Storage & API Endpoints](#data-storage--api-endpoints)
8. [Special Configurations](#special-configurations)

---

## Menu Structure

### Main Launcher (launcher.py)

The application launcher displays **12 main modules** as icon buttons:

| Module | Choice ID | Purpose |
|--------|-----------|---------|
| **Daily Business** | `fulfillment` | Invoice processing, fulfillment, printing |
| Zahlungsclearing | `clearing` | Payment reconciliation |
| Provision & Kalkulation | `analysis` | Article profitability analysis |
| Steuern-Management | `uva` | VAT/Tax declarations |
| Statistik | `statistik` | Statistics & reports |
| Ausgaben-Check | `ausgaben` | Expense verification |
| PRINT | `print_products` | Direct product printing (inventory-aware) |
| Media | `notes_layout` | Media assets & layout tools |
| Produkte Advanced | `wix_products` | Advanced product management |
| CRM | `crm` | Customer relationship management |
| WüdaraMusi | `wuedaramusi` | WüdaraMusi specific tools |
| Reisekostenabrechnung | `travel_costs` | Travel expense accounting |

**File Location:** `sevdesk_wix_fulfillment/ui/launcher.py` (lines 85-97)

---

## Daily Business UI Layout

### Two-Panel Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Toolbar: [Refresh Invoices] [Select All] [Dry Run] [HOME]      │
├──────────────────────────┬──────────────────────────────────────┤
│                          │                                      │
│   LEFT PANEL             │      RIGHT PANEL                    │
│  (Lists & Aux)           │   (Batch Controls & Analysis)       │
│                          │                                      │
│  ┌──────────────────┐    │  ┌──────────────────────────────┐  │
│  │ OPEN INVOICES    │    │  │ Summary & Printer Status     │  │
│  │ (Treeview)       │    │  │ Batch Operation Buttons:     │  │
│  │ Many rows        │    │  │ • START ALL                  │  │
│  │ Sortable         │    │  │ • PRINT ALL                  │  │
│  │ Multi-select     │    │  │ • CHECK PRODUCTS             │  │
│  └──────────────────┘    │  │ • START SELECTED             │  │
│                          │  │ • STOP                       │  │
│  ┌──────────────────┐    │  │ Progress Bar & Status        │  │
│  │ COMPLETED (Last) │    │  └──────────────────────────────┘  │
│  │ [Load More...]   │    │                                      │
│  └──────────────────┘    │  ┌──────────────────────────────┐  │
│                          │  │ ANALYSIS PANEL               │  │
│  ┌──────────────────┐    │  │ • Buyer Note                 │  │
│  │ Aux. Sections:   │    │  │ • Products to Print          │  │
│  │ • Sendungen      │    │  │ • Shipping Address (edit)    │  │
│  │ • Überweisungen  │    │  │ • Printing Buttons           │  │
│  │ • Mollie         │    │  │ • Error/Processing Log       │  │
│  │ • Gutscheine     │    │  └──────────────────────────────┘  │
│  │ • Refunds        │    │                                      │
│  │ • Download-Links │    │                                      │
│  │ • Drafts         │    │                                      │
│  └──────────────────┘    │                                      │
│                          │                                      │
└──────────────────────────┴──────────────────────────────────────┘
```

### Left Panel - Invoice Lists

#### Open Invoices Section (top)
- **Type:** Multi-select Treeview
- **Columns:**
  - Date (invoice date)
  - Name (customer name)
  - Amount (sum including tax)
  - kg (estimated weight)
  - Order (Wix order reference, e.g., "20001")
  - Country (shipping country)
  - Addr (address preview)
  - Unrel (unreleased product indicator)
  - Note (short notes)
  - PLC (Pick-Label-Confirm status)

- **Default Text:** "--- Keine offenen Rechnungen ---"
- **Features:**
  - Updates on app startup
  - Manual refresh via toolbar
  - Multi-select for batch operations
  - Dynamic loading with spinner indicator
  - Hover tooltips for truncated text

**Invoked from:** `app.py:_build_ui()` line 430

#### Completed Invoices Section (middle)
- **Type:** Same Treeview structure as open invoices
- **Display:** Last 15 completed invoices
- **Sorting:** Newest first
- **Additional Column:** Invoice number (explicit)
- **Pagination:** "Load More" button fetches next 15
- **Lookback Window:** Starts at 7 days, extends dynamically

**Default Text:** "--- Keine abgeschlossenen Rechnungen ---"

**Implementation:** `app.py:_load_more_completed_invoices()` line 2308

#### Auxiliary Sections Navigation (bottom left)
- **Type:** Radio button group with dynamic labels
- **State Management:** `tk.StringVar` (`_aux_var`)
- **Active Section:** Displayed in adjacent container

**Available Sections:**

| Label | Key | Panel Class | Dynamic Counter |
|-------|-----|-------------|-----------------|
| Offene Sendungen | `to_send` | `ToSendPanel` | [OPEN X] if X > 0 |
| Offene Überweisungen | `transfer` | `ToSendPanel` | [OPEN X] if X > 0 |
| Mollie - Authorized Orders | `mollie` | `MollieAuthorizedOrdersPanel` | [OPEN X] if X > 0 |
| Gutscheine | `coupons` | `CouponsPanel` | (no counter) |
| Rückerstattungen | `refunds` | `RefundsPanel` | [OPEN X] if X > 0 |
| Download-Links | `download_links` | `DownloadLinksPanel` | [OPEN X] if X > 0 |
| Rechnungsentwurf | `drafts` | `DraftInvoiceApp` | (no counter) |

**Style Logic:** Button color changes based on state
- Red/danger if count > 0 and selected
- Red/danger-outline if count > 0 and not selected
- Blue/primary if selected
- Gray/secondary if not selected

**Code:** `app.py:_add_aux_option()` line 734, `_update_aux_nav_styles()` line 760

---

### Right Panel - Batch Controls & Analysis

#### Batch Controls Section (top)

**Summary Display**
- Label: "Übersicht:"
- Value: Number of selected invoices + queue status

**Printer Status Display**
- Label: "Druckercheck:"
- Value: "✅ X/Y verfügbar" or "⛔ X/Y verfügbar"
- Details Toggle Button: "Details anzeigen"
- Expandable text area showing:
  - Printer name
  - Printer status (label in parentheses)
  - Health indicator (✅/⛔)

**Button Row** (disabled during operation):
1. **START ALL** - Processes all open invoices
2. **PRINT ALL** - Prints all selected items (invoice + label)
3. **CHECK PRODUCTS** - Validates product preflight
4. **START SELECTED** - Processes only selected invoices
5. **STOP** - Aborts current operation (enabled during processing)

**Progress Display**
- Progress bar: Current/Total visual indicator
- Label: "X/Y" (numeric progress)
- Loading spinner with text status

**Last Action Display**
- Shows what was executed (e.g., "Drucke Label...")

**Code:** `ui/batch_controls.py`, `app.py:_build_ui()` line 410

#### Analysis Panel (bottom)

**Buyer Note Section**
- Label: "BuyerNote:"
- Content: Read-only text display of buyer's special notes from order
- Height: 4 lines
- Display: Hidden if no notes present

**Products Section**
- Label: "Produkte:"
- Content: List of pieces/titles to be printed
- Features:
  - Bold title for each product
  - Small font for metadata (qty, options)
  - **Button:** "PRINT SELECTED" (opens print dialog)
- Implementation: `_set_custom_text()` method formats analysis blocks

**Shipping Address Section**
- Label: "Lieferadresse:"
- Content: **Editable** text field (8 lines)
- Features:
  - Real-time edit detection
  - Horizontal scroll for long lines
  - Callbacks triggered on edit
  - Address history/override support
- Buttons:
  - **RECHNUNG DRUCKEN** (Reprint invoice PDF)
  - **LABEL DRUCKEN** (Print shipping label)

**Error Log Section** (expandable)
- Label: "Fehlerlog:"
- Content: Error messages from last operation
- Height: 4 lines
- Display: Collapsed by default

**Processing Log Section** (expandable)
- Label: "Verarbeitungslog:"
- Type: Treeview with columns:
  - Order-Nr (Order number)
  - Name (Customer name)
  - Label (✅/⛔ status)
  - Invoice (✅/⛔ status)
  - Product (✅/⛔ status)
  - Mail (✅/⛔ status)
  - Wix (✅/⛔ status)
  - Payment (✅/⛔ status)
- Height: 8 rows
- Display: Collapsed by default, expands during operations

**Code:** `ui/analysis_panel.py`, `app.py:_build_ui()` line 410

---

## Core Features & Operations

### Feature 1: Invoice Printing

#### Print Invoice PDF
- **Button Location:** Analysis Panel → "PRINT SELECTED"
- **Button Location (Reprint):** Analysis Panel → "RECHNUNG DRUCKEN"
- **Service:** `InvoicePrinter` class
- **Printer:** Configured as `printing.invoice_printer` in config.json
- **DPI:** 600 dots per inch
- **Process:**
  1. Retrieve invoice PDF from sevDesk API
  2. Load configured printer
  3. Create QPrinter with "Draft" mode (300 DPI) or full quality (600 DPI)
  4. Render PDF to printer
  5. Log result
- **Trigger Points:**
  - During START ALL operation (automatic)
  - Manual via PRINT SELECTED button
  - Reprint via RECHNUNG DRUCKEN button

**Code Location:** 
- Invocation: `app.py:_on_print_invoice_clicked()` line 930
- Service: `printing/invoice_printer.py`

---

### Feature 2: Label Printing

#### Print Shipping Label
- **Button Location:** Analysis Panel → "LABEL DRUCKEN"
- **Service:** `LabelPrinter` class
- **Configuration:**
  - Model: `printing.label_model` (e.g., "dymo_4x6")
  - Printer: `printing.label_printer`
  - Template: `printing.label_template_path`
  - Size: `printing.label_size` (e.g., "4x6")
- **Input Data:**
  - Shipping address (from invoice or user-edited)
  - Optional buyer name and weight
  - Carrier hints (extracted from notes)
- **Output:**
  - DYMO or other label format
  - 4x6 inch standard format (configurable)
- **Trigger Points:**
  - During START ALL operation (automatic)
  - Manual via LABEL DRUCKEN button
  - PLC (Pick-Label-Confirm) mode for batch label printing

#### PLC (Pick-Label-Confirm) Mode
- **Function:** Direct label printing from invoice list
- **Button Location:** InvoiceListFrame context menu
- **Use Case:** Quickly print labels for multiple orders without full processing
- **Code:** `app.py:_open_plc_dialog()` line 1631

**Code Location:**
- Invocation: `app.py:_on_print_label_clicked()` line 965
- Service: `printing/label_printer.py`

---

### Feature 3: Product Preflight Validation

#### Check Products Operation
- **Button:** "CHECK PRODUCTS" in batch controls
- **Service:** `ProductPreflightService` class
- **Purpose:** Validate product configuration before printing
- **Checks Performed:**
  1. **Missing Part:** SKU/product doesn't exist in sevDesk
  2. **Link Missing:** Invoice position not linked to part
  3. **Description Mismatch:** Wix product name ≠ sevDesk part name
  4. **Category Issues:** Product category mismatches
  5. **Digital Detection:** Skip physical printing for digital products

#### Issue Categorization
```
issue_type:
  - "missing_part": Product part doesn't exist
  - "link_missing": Position needs to be linked
  - "link_and_description": Both issues present
  - "description_mismatch": Name mismatch only
  - "none": All checks passed
```

#### User Actions (Dialog)
- **Create Part:** If part missing in sevDesk
- **Update Part:** If description mismatch
- **Link Position:** If position not linked
- **Skip:** Ignore issue for this operation
- Actions cached for batch processing

**Code Location:**
- Service: `services/product_preflight.py`
- Dialog: `ui/product_preflight_dialog.py`
- Invocation: `app.py:start_product_check_all()` line 3283

---

### Feature 4: Refund Processing

#### Refund Manager
- **Panel:** "Rückerstattungen" (Refunds)
- **Service:** `RefundManager` class

#### Search Functionality
- **Search Modes:**
  - Invoice number (exact match)
  - Customer name (contains)
  - Order reference (contains)
- **Input:** Query string
- **Result:** List of matching invoices with:
  - Invoice number
  - Customer name
  - Amount
  - Date
  - Order reference

#### Load Invoice Context
- **Input:** Selected invoice from search results
- **Output:** Refund context object with:
  - Invoice positions (line items)
  - Order data from Wix
  - Refundability information (what can be refunded)
  - Shipping amount
  - Tax rates

#### Process Refund
- **Line-Item Refunds:** Select individual items to refund
- **Partial Amounts:** Adjust line quantities/amounts
- **Shipping:** Include/exclude shipping in refund
- **Tax Handling:** Automatic tax recalculation
- **Wix Update:** Create refund in Wix order

**Code Location:**
- Service: `services/refund_manager.py`
- Panel: `ui/widgets/refunds_panel.py`
- Method: `search_candidates()` line 18, `load_invoice_context()` line 52

---

### Feature 5: Gutscheine (Vouchers/Coupons)

#### Voucher Management Panel
- **Panel:** "Gutscheine" (Coupons)
- **Service:** `WixCouponsClient` class

#### Features
- **Generate Unique Codes**
  - Prefix: "XW" (configurable as `code_prefix`)
  - Pattern: XW000001, XW000002, etc.
  - Max retry attempts: 8 (configurable)
  - Currency: EUR (configurable)

- **Browse Recent Coupons**
  - Displays recently created vouchers
  - Metadata display (usage, amount, validity)
  - Link back to Wix coupon management

#### Configuration
```json
{
  "wix_coupons": {
    "base_url": "https://www.wixapis.com",
    "endpoint_path": "/stores/v2/coupons",
    "site_id": "...",
    "auth_token": "...",
    "wrap_specification": true,
    "code_prefix": "XW",
    "max_code_attempts": 8,
    "default_currency": "EUR"
  }
}
```

**Code Location:**
- Service: `services/wix_coupons_client.py`
- Panel: `ui/widgets/coupons_panel.py`

---

### Feature 6: Download Links

#### Download Links Panel
- **Panel:** "Download-Links"
- **Service:** `DownloadLinksPanel` class
- **Purpose:** Generate download links for customers

#### Search Capability
- **Search By:**
  - Invoice Number (pattern: `A-Za-z{1,5}-?\d{3,}`)
  - Order Number (pattern: `^\d{5}$`)
  - Invoice ID (direct lookup)

- **Search Window:** Last 365 days (configurable)
- **Search Caching:** 180-second TTL

#### Generate Links
- Resolve order context from:
  - sevDesk invoice data
  - Wix order information
  - Invoice analysis (items, addresses)
- Create shareable download URLs
- Link integration with Wix Orders Dashboard

#### Configuration
```json
{
  "app": {
    "download_links_search_days": 365
  }
}
```

**Code Location:**
- Panel: `ui/widgets/download_links_panel.py`
- Methods: `_search_orders()`, `_generate_links()`

---

### Feature 7: Email & Mail Management

#### Offene Sendungen (To Send Emails)
- **Panel:** "Offene Sendungen"
- **Service:** `ToSendPanel` class
- **Integration:** Microsoft Graph API (Outlook)

#### Functionality
- **Fetch Emails**
  - Lookback: 20 days (configurable)
  - Filter: Subject/sender specific
  - Exclude: "no-reply@mystore.wix.com" emails

- **Extract Shipping Info**
  - OpenAI integration (optional) to parse email content
  - Extract:
    - Shipping address
    - Weight/volume
    - Special instructions
    - Carrier preferences

- **Email Processing**
  - Mark as processed (state file tracking)
  - Print labels directly from emails
  - Generate payment QR codes (EPC/SEPA format)
  - Reply to customer

- **State Management**
  - State file: `state/to_send_state.json`
  - Tracks: Processed emails, extractions, replies

#### Offene Überweisungen (Transfer Emails)
- **Panel:** "Offene Überweisungen"
- **Same Functionality** as "Offene Sendungen" but for:
  - Transfer/payment confirmation emails
  - QR code tools enabled (disabled for shipments)
  - Separate mailbox source
  - State file: `state/open_transfers_state.json`

#### Configuration
```json
{
  "graph": {
    "tenant_id": "...",
    "client_id": "...",
    "mail_days": 20,
    "mailbox_user": "inbox@xeisworks.at",
    "transfer_mailbox_user": "transfer@xeisworks.at",
    "msal_cache_path": "%LOCALAPPDATA%/XeisWorks/sevdesk_wix_fulfillment/msal_cache.json"
  },
  "email": {
    "subject_template": "Bestellung #{order_number} - Versand",
    "body_template": "...",
    "body_template_html": "..."
  }
}
```

**Code Location:**
- Panel: `ui/to_send_panel.py`
- Service: `integrations/ms_graph_mail.py`
- QR Generation: `services/payment_qr.py`

---

### Feature 8: Payment Processing (Mollie)

#### Mollie Authorized Orders
- **Panel:** "Mollie - Authorized Orders"
- **Service:** `MollieClient` class
- **Integration:** Mollie Payment API

#### Functionality
- **Fetch Authorized Orders**
  - Orders with AUTHORIZED status (not yet captured)
  - Lookback: 14 days (configurable)
  - Cache: Auto-refresh on panel switch

- **Display**
  - Order ID
  - Amount
  - Date authorized
  - Customer info
  - Payment method

- **Actions**
  - Capture payment (finalize)
  - Decline/cancel
  - Issue refund

#### Configuration
```json
{
  "mollie": {
    "api_key": "...",  // or via MOLLIE_API_KEY env var
    "days": 14
  }
}
```

**Code Location:**
- Panel: `ui/widgets/mollie_authorized_panel.py`
- Service: `integrations/mollie_client.py`

---

### Feature 9: Draft Invoices

#### Draft Invoice Editor
- **Panel:** "Rechnungsentwurf"
- **Service:** `DraftInvoiceApp` class
- **Embedded:** Within Daily Business (not standalone)

#### Functionality
- **Create New Invoice**
  - Select customer (lookup from existing contacts)
  - Add line items (select products)
  - Set quantities and prices
  - Apply discounts
  - Calculate tax

- **Edit Draft**
  - Modify line items
  - Update customer info
  - Recalculate amounts
  - Add special notes

- **Finalize**
  - Create invoice in sevDesk from draft
  - Auto-send to customer (optional)
  - Trigger fulfillment workflow

**Code Location:**
- Panel: `ui/draft_invoice_app.py`

---

## Sub-Panels & Auxiliary Sections

### Panel: ToSendPanel
- **Files:** `ui/to_send_panel.py`
- **Features:**
  - Email list (Treeview)
  - Text extraction/parsing
  - Label printing
  - QR code generation
  - State persistence
  - Mark as done workflow
  - Optional OpenAI extraction

### Panel: RefundsPanel
- **Files:** `ui/widgets/refunds_panel.py`
- **Features:**
  - Invoice search (3 modes)
  - Refund line selection
  - Amount adjustment
  - Wix refund creation
  - Status tracking

### Panel: DownloadLinksPanel
- **Files:** `ui/widgets/download_links_panel.py`
- **Features:**
  - Order search (invoice # or order #)
  - Link generation
  - Wix dashboard integration
  - Search result caching

### Panel: CouponsPanel
- **Files:** `ui/widgets/coupons_panel.py`
- **Features:**
  - Coupon code generation
  - Recent coupon browser
  - Metadata display

### Panel: MollieAuthorizedOrdersPanel
- **Files:** `ui/widgets/mollie_authorized_panel.py`
- **Features:**
  - Authorized order listing
  - Capture/decline actions
  - Amount display
  - Status updates

### Panel: DraftInvoiceApp
- **Files:** `ui/draft_invoice_app.py`
- **Features:**
  - Customer selection
  - Product line items
  - Tax calculation
  - Finalization workflow

---

## Services & Dependencies

### Core Service: InvoiceProcessor
**File:** `services/invoice_processor.py`
**Responsibility:** Main fulfillment orchestration

**Key Methods:**
- `process_invoice()` - Execute full fulfillment workflow
- `analyze_invoice()` - Extract order/product/address info
- `classify_order_reference()` - B2C/B2B classification
- `extract_shipping_info()` - Parse address from order
- `send_confirmation_email()` - Email customer
- `positions_digital()` - Detect digital products

**Dependencies:**
- SevDeskClient
- WixClient
- InvoicePrinter
- LabelPrinter
- GraphMailClient (optional)

**Configuration Keys:**
- `tax.allowed_tax_rates`
- `tax.allowed_tax_types`
- `email.subject_template`
- `email.body_template`
- `email.body_template_html`

---

### Core Service: SevDeskClient
**File:** `services/sevdesk_client.py`
**Responsibility:** sevDesk API integration

**Key Methods:**
- `fetch_open_invoices()` - GET invoices with status
- `fetch_completed_invoices()` - GET invoices by state
- `fetch_invoice_positions()` - GET line items
- `fetch_contact()` - GET customer data
- `update_invoice_status()` - PUT invoice state
- `link_payment()` - POST payment link
- `invoice_reference()` - Extract order reference

**Configuration Keys:**
- `sevdesk.api_token`
- `sevdesk.base_url`
- `sevdesk.check_account_id`

---

### Core Service: WixClient
**File:** `services/wix_client.py`
**Responsibility:** Wix/eCommerce integration

**Key Methods:**
- `get_order()` - Fetch order by ID
- `get_order_refundability()` - Check what can be refunded
- `fulfill_order()` - Mark order as fulfilled
- `create_refund()` - Process refund
- `update_line_item_fulfillment_status()` - Update fulfillment

**Configuration Keys:**
- `wix.api_key`
- `wix.site_id`
- `wix.base_url`

**B2B Support:**
- Optional `WIX_B2B_SITE_ID` environment variable
- Separate client instance for B2B orders

---

### Service: ProductPreflightService
**File:** `services/product_preflight.py`
**Responsibility:** Product validation

**Key Methods:**
- `check_issues()` - Scan for problems
- `check_one()` - Single product validation
- `get_issue_reasons()` - List why validation failed
- `resolve_part_draft()` - Build Pydantic model for creation

---

### Service: RefundManager
**File:** `services/refund_manager.py`
**Responsibility:** Refund processing

**Key Methods:**
- `search_candidates()` - Find invoices
- `load_invoice_context()` - Build refund context
- `process_refund()` - Execute refund in Wix

---

### Service: InvoicePrinter
**File:** `printing/invoice_printer.py`
**Responsibility:** Print invoices via QPrinter

**Key Methods:**
- `print_invoice()` - Render invoice PDF to printer
- `print_invoice_to_file()` - Save as file instead

---

### Service: LabelPrinter
**File:** `printing/label_printer.py`
**Responsibility:** Print shipping labels

**Key Methods:**
- `print_label()` - Render label to label printer
- `print_label_to_file()` - Save as file

---

### Integration: GraphMailClient
**File:** `integrations/ms_graph_mail.py`
**Responsibility:** Microsoft Graph API (Outlook email)

**Key Methods:**
- `fetch_messages()` - GET emails from mailbox
- `send_message()` - POST email to mailbox
- `get_attachment()` - Download attachment

**Configuration:**
- Azure AD tenant ID
- Client ID (App registration)
- MSAL cache path for tokens
- Mailbox user email addresses

---

### Integration: MollieClient
**File:** `integrations/mollie_client.py`
**Responsibility:** Mollie payment API

**Key Methods:**
- `fetch_authorized_orders()` - GET authorized payments
- `capture_payment()` - POST capture

---

### Integration: WixCouponsClient
**File:** `services/wix_coupons_client.py`
**Responsibility:** Wix coupons/vouchers

**Key Methods:**
- `generate_code()` - Create unique coupon code
- `create_coupon()` - POST coupon to Wix
- `list_coupons()` - GET all coupons

---

## Configuration Reference

### config.json Structure

```json
{
  "sevdesk": {
    "api_token": "YOUR_API_TOKEN",
    "base_url": "https://my.sevdesk.de/api/v1",
    "user_agent": "sevdesk-wix-fulfillment",
    "check_account_id": null
  },
  "wix": {
    "api_key": "YOUR_WIX_API_KEY",
    "site_id": "YOUR_SITE_ID",
    "base_url": "https://www.wixapis.com"
  },
  "printing": {
    "invoice_printer": "Brother HL-L9310CDWT series",
    "label_printer": "DYMO LabelWriter 4XL",
    "label_model": "dymo_4x6",
    "label_size": "4x6",
    "label_template_path": "printing/templates/label.lbx"
  },
  "tax": {
    "allowed_tax_rates": [0, 0.1, 0.19, 0.07],
    "allowed_tax_types": ["default", "reduced", "reverse"]
  },
  "email": {
    "subject_template": "Bestellung #{order_number} - Versand",
    "body_template": "Liebe/r {name},\n\nDeine Bestellung wurde versandt.\n\nBeste Grüße",
    "body_template_html": "<p>Liebe/r {name},</p>..."
  },
  "graph": {
    "tenant_id": "YOUR_TENANT_ID",
    "client_id": "YOUR_CLIENT_ID",
    "mail_days": 20,
    "mailbox_user": "inbox@xeisworks.at",
    "transfer_mailbox_user": "transfer@xeisworks.at",
    "msal_cache_path": "%LOCALAPPDATA%/XeisWorks/sevdesk_wix_fulfillment/msal_cache.json"
  },
  "mollie": {
    "api_key": null,
    "days": 14
  },
  "wix_coupons": {
    "base_url": "https://www.wixapis.com",
    "endpoint_path": "/stores/v2/coupons",
    "site_id": "YOUR_COUPON_SITE_ID",
    "auth_token": "YOUR_COUPON_TOKEN",
    "wrap_specification": true,
    "authorization_header": "Authorization",
    "site_id_header": "wix-site-id",
    "user_agent": "sevdesk-wix-fulfillment",
    "default_currency": "EUR",
    "max_code_attempts": 8,
    "code_prefix": "XW"
  },
  "app": {
    "request_timeout_sec": 45,
    "download_links_search_days": 365
  }
}
```

### Environment Variables

```bash
# Mollie (overrides config)
MOLLIE_API_KEY=your_mollie_key

# Wix Coupons (overrides config)
WIX_COUPON_BASE_URL=https://www.wixapis.com
WIX_COUPON_ENDPOINT_PATH=/stores/v2/coupons
WIX_COUPON_SITE_ID=...
WIX_COUPON_API_KEY=...

# Wix Site ID (overrides config, used for coupons if not set)
WIX_SITE_ID=...
WIX_API_KEY=...

# B2B Support
WIX_B2B_SITE_ID=...

# MSAL Cache Path
SEVDESK_MSAL_CACHE_PATH=/path/to/msal_cache.json
```

---

## Data Storage & API Endpoints

### Local Data Files

**Directory:** `sevdesk_wix_fulfillment/data/`

| File | Purpose | Format |
|------|---------|--------|
| `inventory_store.json` | Product inventory state | JSON |
| `fulfillment_log.jsonl` | Detailed fulfillment log | JSON Lines |
| `transfer_qr/` | Payment QR codes (PNG files) | Images |
| `wix_sevdesk_product_sync_map.json` | Wix↔sevDesk product mapping | JSON |

**Directory:** `sevdesk_wix_fulfillment/state/`

| File | Purpose |
|------|---------|
| `to_send_state.json` | Tracks processed/sent emails |
| `open_transfers_state.json` | Tracks transfer emails processed |
| `msal_cache.json` | Microsoft authentication tokens |

### sevDesk API Endpoints

**Base URL:** `https://my.sevdesk.de/api/v1`

| Operation | Method | Endpoint | Purpose |
|-----------|--------|----------|---------|
| List Invoices | GET | `/Invoices` | Fetch open/completed invoices |
| Get Invoice | GET | `/Invoices/{id}` | Single invoice details |
| Positions | GET | `/Invoices/{id}/Positions` | Line items for invoice |
| Get Contact | GET | `/Contacts/{id}` | Customer information |
| Update Invoice | PUT | `/Invoices/{id}` | Change invoice status/data |
| Change Send Type | PUT | `/Invoices/{id}/changeSendType` | Mark as sent/fulfilled |
| Get Document | GET | `/Documents` | Invoice PDF document |
| List Payments | GET | `/Invoices/{id}/Payments` | Payment history |
| Create Payment | POST | `/Invoices/{id}/Payments` | Link payment to invoice |

**Authentication:** Bearer token in `Authorization` header

**Headers:**
```
Authorization: Bearer {api_token}
Content-Type: application/json
User-Agent: sevdesk-wix-fulfillment
```

### Wix APIs

**Base URL:** `https://www.wixapis.com`

| Operation | Method | Endpoint | Purpose |
|-----------|--------|----------|---------|
| Get Order | GET | `/stores/orders/{id}` | Single order details |
| List Orders | GET | `/stores/orders` | Fetch orders |
| Fulfill Order | POST | `/stores/orders/{id}/fulfill` | Mark as fulfilled |
| Get Refundability | GET | `/stores/orders/{id}/refundability` | Refund availability |
| Create Refund | POST | `/stores/refunds` | Process refund |
| Update Fulfillment | PUT | `/stores/orders/{id}/trackings` | Update fulfillment tracking |
| List Coupons | GET | `/stores/coupons` | Browse coupons |
| Create Coupon | POST | `/stores/coupons` | New coupon |
| Get Product | GET | `/stores/products` | Product details |

**Authentication:**
```
Authorization: {api_key}
wix-site-id: {site_id}
```

### Microsoft Graph API

**Base URL:** `https://graph.microsoft.com/v1.0`

| Operation | Method | Endpoint | Purpose |
|-----------|--------|----------|---------|
| Get Messages | GET | `/me/mailFolders/inbox/messages` | Fetch emails |
| Send Mail | POST | `/me/sendMail` | Send email |
| Get Attachment | GET | `/me/messages/{id}/attachments` | Download attachment |

**Authentication:** OAuth2 with MSAL (token from tenant/client ID)

### Mollie API

**Base URL:** `https://api.mollie.com/v2`

| Operation | Method | Endpoint |
|-----------|--------|----------|
| List Orders | GET | `/orders?status=authorized` |
| Get Order | GET | `/orders/{id}` |
| List Payments | GET | `/payments?status=authorized` |

**Authentication:** Bearer token (API key)

---

## Special Configurations

### Product Print Planning

**File:** `services/print_plan_resolver.py`

**Configuration Files:**
- `sku_flags.json` - Unreleased SKU markers
- `sku_besetzung.json` - Instrumentation/arrangement configs
- Product PDF mappings in config.json

**Unreleased Products:**
- Defined by exact SKU or prefix
- Example: `["XW-010", "XW-011"]`
- Special handling: Multi-title split support

**Print Plans:**
- Auto: Automatic PDF selection
- Manual: User-selected PDF
- Fallback: Secondary PDF if primary unavailable

### Address Normalization

**Function:** `_normalize_address_line()`
- Converts special characters (ä→ae, etc.)
- Removes extra spaces
- Normalizes street names
- Case-insensitive comparison

**Country Name Translation:**
- ISO 2-letter codes mapped to English names
- Example: "AT" → "Austria"
- Critical for shipping label generation

### Order Reference Classification

**Function:** `classify_order_reference()`
- **B2C:** Reference starts with "2"
- **B2B:** Reference starts with "1"
- **UNKNOWN:** Non-numeric or invalid format
- Used for: Different fulfillment profiles, pricing, communication

### Weight Calculation

**Default:** 0.30 kg per item
- Used for PLC/label generation if not specified
- Aggregated across line items
- Impacts fulfillment decision logic

### Digital Products

**Detection:** `positions_digital()`
- SKUs marked as digital (no physical goods)
- Skip: Physical printing, label generation
- Include: Email delivery, order confirmation only

**Examples:**
- Sheet music (digital delivery)
- Downloads
- Subscriptions

### Custom Text Handling

**Fields:**
- `CUSTOM_TEXT_SKUS`: SKUs that accept custom text
- `CUSTOM_TEXT_NAME_KEY`: "Name des Stückes / der Stücke"
- `CUSTOM_TEXT_NOTE_KEY`: "Sonstige Bemerkungen"
- `PIECE_NOTE_ONLY_SKUS`: Only notes, no custom title

**Multi-Title Split:**
- For unreleased products with multiple titles
- User provides comma-separated list
- System splits into individual pieces
- Each printed separately

---

## Summary Table: All Features at a Glance

| Feature | Entry Point | Key Service | Files |
|---------|-------------|------------|-------|
| **Invoice Printing** | "PRINT SELECTED" button | InvoicePrinter | app.py, invoice_printer.py |
| **Label Printing** | "LABEL DRUCKEN" button | LabelPrinter | app.py, label_printer.py |
| **Product Validation** | "CHECK PRODUCTS" button | ProductPreflightService | product_preflight.py, product_preflight_dialog.py |
| **Refund Processing** | "Rückerstattungen" panel | RefundManager | refunds_panel.py, refund_manager.py |
| **Vouchers** | "Gutscheine" panel | WixCouponsClient | coupons_panel.py, wix_coupons_client.py |
| **Download Links** | "Download-Links" panel | DownloadLinksPanel | download_links_panel.py |
| **Email Management** | "Offene Sendungen" panel | ToSendPanel, GraphMailClient | to_send_panel.py, ms_graph_mail.py |
| **Transfer Emails** | "Offene Überweisungen" panel | ToSendPanel, GraphMailClient | to_send_panel.py, ms_graph_mail.py |
| **Mollie Payments** | "Mollie - Authorized" panel | MollieClient | mollie_authorized_panel.py, mollie_client.py |
| **Draft Invoices** | "Rechnungsentwurf" panel | DraftInvoiceApp | draft_invoice_app.py |
| **START ALL** | "START ALL" button | InvoiceProcessor | app.py, invoice_processor.py |
| **PRINT ALL** | "PRINT ALL" button | Multiple printers | app.py, batch printing logic |
| **START SELECTED** | "START SELECTED" button | InvoiceProcessor | app.py, invoice_processor.py |

---

## Integration with XW-Office

### Mapping Old Features to New Architecture

**Old (sevDesk) → New (XW-Office)**

| Old Feature | Old Location | New Feature | New Location |
|-------------|--------------|------------|--------------|
| Daily Business | fulfillment tab | Rechnungen (Invoices) module | ui/modules/rechnungen/ |
| Invoice Printing | InvoicePrinter | Invoice Printing | services/printing/ |
| Label Printing | LabelPrinter | Label Printing | services/printing/ |
| Batch Operations | START ALL button | Batch Processing | services/batch_processor/ |
| Refunds | RefundManager | Refund Service | services/refunds/ |
| Coupons | CouponsPanel | Vouchers | ui/modules/? |
| Email Integration | ToSendPanel+Graph | Email Service | services/mail/ |
| Download Links | DownloadLinksPanel | Customer Links | services/customer_downloads/ |
| Product Preflight | ProductPreflightService | Product Validation | services/products/ |
| Payment Mollie | MollieClient | Payment Service | services/payments/ |

### Migration Notes for XW-Office

1. **Configuration**: Port config.json settings to database/Railway for multi-PC sync
2. **Services**: Migrate services to DI container pattern (already done)
3. **UI**: Rebuild with PySide6 (card-based layout)
4. **Analysis Panel**: Create right-sidebar widget showing invoice analysis
5. **Batch Controls**: Implement as floating panel or toolbar
6. **Auxiliary Panels**: Implement as nested views/tabs
7. **Data**: Migr JSON state files to PostgreSQL tables
8. **API Integration**: Keep external APIs (Graph, Mollie, Wix, sevDesk) same

---

## Document Metadata

- **Analysis Scope:** Complete Daily Business (Fulfillment) module
- **Repository:** `XeisWorks/sevDesk` (old application)
- **Key Files Analyzed:**
  - `sevdesk_wix_fulfillment/ui/app.py` (2900+ lines)
  - `sevdesk_wix_fulfillment/ui/launcher.py` (600+ lines)
  - `sevdesk_wix_fulfillment/ui/batch_controls.py`
  - `sevdesk_wix_fulfillment/ui/analysis_panel.py`
  - `sevdesk_wix_fulfillment/ui/to_send_panel.py`
  - `sevdesk_wix_fulfillment/services/invoice_processor.py` (1500+ lines)
  - `sevdesk_wix_fulfillment/services/refund_manager.py`
  - `sevdesk_wix_fulfillment/services/product_preflight.py`
  - All widget files in `ui/widgets/`
  - All integration files in `integrations/`
  - Configuration: `config.json`

- **Total Features Documented:** 12 major features + sub-operations
- **Total Services Documented:** 12 core services
- **Total Configuration Keys:** 40+
- **API Endpoints Documented:** 20+

---

**End of Document**
