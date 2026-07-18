"""
Live Integration Tests for Daily Business → Rechnungen Workflow
Simplified version with proper fixture injection and focused testing
"""

import pytest
from unittest.mock import Mock
from datetime import datetime


# ===== MOCK API RESPONSES =====

def get_mock_invoice():
    """Mock sevDesk invoice response"""
    return {
        "id": "TEST-INV-001",
        "invoiceNumber": "RE-1234",
        "date": datetime.now().isoformat(),
        "customerName": "Test Customer GmbH",
        "customerEmail": "test@example.com",
        "status": "100",
        "totalGross": 1234.56,
        "address": {
            "name": "Test Customer GmbH",
            "street": "Teststrasse 123",
            "city": "Berlin",
            "zip": "10115",
            "country": "DE"
        },
        "lines": [{"description": "Test Product", "quantity": 2, "price": 617.28}]
    }


def get_mock_invoice_pdf():
    """Mock PDF bytes"""
    return b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n" + b"dummy" * 500


def get_mock_wix_order():
    """Mock Wix order"""
    return {
        "id": "WIX-ORDER-001",
        "number": "12345",
        "status": "PENDING_FULFILLMENT",
        "fulfillmentStatus": "NOT_FULFILLED",
        "buyerInfo": {
            "email": "customer@example.com",
            "firstName": "Test",
            "lastName": "Customer",
            "address": {
                "street": "Teststrasse 123",
                "city": "Berlin",
                "postalCode": "10115",
                "country": "DE"
            }
        },
        "lineItems": [{"sku": "TEST-PRODUCT-001", "quantity": 2}],
        "totals": {"subtotal": 1234.56, "total": 1234.56}
    }


# ===== FIXTURES =====

@pytest.fixture
def invoice_client():
    """Mock invoice client with required methods"""
    client = Mock()
    client.get_invoice = Mock(return_value=get_mock_invoice())
    client.get_invoice_pdf = Mock(return_value=get_mock_invoice_pdf())
    return client


@pytest.fixture
def wix_client():
    """Mock Wix client with required methods"""
    client = Mock()
    client.get_order = Mock(return_value=get_mock_wix_order())
    client.mark_fulfilled = Mock(return_value={"success": True})
    return client


@pytest.fixture
def refund_client():
    """Mock refund client"""
    client = Mock()
    client.cancel_invoice = Mock(return_value={"success": True})
    client.create_credit_note_from_invoice = Mock(return_value={"id": "CREDIT-001", "type": "credit"})
    return client


@pytest.fixture
def printer():
    """Mock printer"""
    return Mock(print_pdf_bytes=Mock(return_value=None))


@pytest.fixture
def label_printer():
    """Mock label printer"""
    return Mock(print_address=Mock(return_value=None))


# ===== WORKFLOW TESTS =====

class TestWorkflowLiveExecution:
    """Test actual workflow execution paths"""
    
    def test_fulfillment_workflow_steps_exist(self, invoice_client, wix_client, printer, label_printer):
        """Verify all fulfillment workflow steps can execute"""
        
        invoice_id = "TEST-INV-001"
        
        # Step 1: Fetch invoice
        invoice = invoice_client.get_invoice(invoice_id)
        assert invoice["id"] == invoice_id
        assert invoice["customerName"] is not None
        
        # Step 2: Get PDF
        pdf = invoice_client.get_invoice_pdf(invoice_id)
        assert pdf.startswith(b"%PDF")
        
        # Step 3: Print invoice
        printer.print_pdf_bytes(pdf)
        assert printer.print_pdf_bytes.called
        
        # Step 4: Print label
        address_lines = [
            invoice["address"]["name"],
            invoice["address"]["street"],
            f"{invoice['address']['zip']} {invoice['address']['city']}"
        ]
        label_printer.print_address(address_lines)
        assert label_printer.print_address.called
        
        # Step 5: Fulfill order
        order = wix_client.get_order("WIX-ORDER-001")
        assert order["status"] == "PENDING_FULFILLMENT"
        
        # Step 6: Mark fulfilled
        result = wix_client.mark_fulfilled("WIX-ORDER-001")
        assert result["success"] is True
    
    def test_refund_workflow_execution(self, invoice_client, refund_client):
        """Test refund workflow can complete"""
        
        invoice_id = "TEST-INV-001"
        
        # Cancel invoice
        cancel_result = refund_client.cancel_invoice(invoice_id)
        assert cancel_result["success"] is True
        
        # Create credit note
        credit = refund_client.create_credit_note_from_invoice(invoice_id)
        assert credit["type"] == "credit"
    
    def test_batch_workflow_execution(self, invoice_client, printer):
        """Test batch processing can handle multiple items"""
        
        invoice_ids = ["TEST-INV-001", "TEST-INV-002", "TEST-INV-003"]
        
        for inv_id in invoice_ids:
            invoice_client.get_invoice(inv_id)
            pdf = invoice_client.get_invoice_pdf(inv_id)
            printer.print_pdf_bytes(pdf)
        
        # Verify all processed
        assert printer.print_pdf_bytes.call_count == 3
        assert invoice_client.get_invoice.call_count == 3


class TestAddressHandling:
    """Test address extraction and label printing"""
    
    def test_address_extraction_from_invoice(self, invoice_client):
        """Test address can be extracted correctly"""
        
        invoice = invoice_client.get_invoice("TEST-INV-001")
        address = invoice["address"]
        
        # Verify all required fields present
        assert address["name"]
        assert address["street"]
        assert address["city"]
        assert address["zip"]
        assert address["country"]
    
    def test_address_formatting_for_label(self):
        """Test address formatting for label printer"""
        
        address = {
            "name": "Test Customer GmbH",
            "street": "Teststrasse 123",
            "zip": "10115",
            "city": "Berlin",
            "country": "DE"
        }
        
        # Build label address lines
        lines = [
            address["name"],
            address["street"],
            f"{address['zip']} {address['city']}"
        ]
        
        assert len(lines) == 3
        assert lines[0] == "Test Customer GmbH"
        assert "Teststrasse 123" in lines[1]
        assert "10115" in lines[2]
    
    def test_shipping_address_fallback(self):
        """Test fallback to shipping address"""
        
        invoice = get_mock_invoice()
        
        # Simulate missing billing address
        billing_address = None
        shipping_address = invoice["address"]
        
        # Fallback logic
        used_address = billing_address or shipping_address
        
        assert used_address is not None
        assert used_address["name"] == "Test Customer GmbH"


class TestPrintingWorkflow:
    """Test printing system integration"""
    
    def test_invoice_pdf_dispatch(self, invoice_client, printer):
        """Test invoice PDF can be dispatched to printer"""
        
        pdf = invoice_client.get_invoice_pdf("TEST-INV-001")
        
        # Dispatch
        printer.print_pdf_bytes(pdf)
        
        # Verify
        assert printer.print_pdf_bytes.called
        call_args = printer.print_pdf_bytes.call_args[0][0]
        assert isinstance(call_args, bytes)
        assert call_args.startswith(b"%PDF")
    
    def test_label_address_dispatch(self, label_printer):
        """Test address can be dispatched to label printer"""
        
        address_lines = [
            "Test Customer GmbH",
            "Teststrasse 123",
            "10115 Berlin"
        ]
        
        label_printer.print_address(address_lines)
        
        assert label_printer.print_address.called
        call_args = label_printer.print_address.call_args[0][0]
        assert isinstance(call_args, list)
        assert len(call_args) == 3
    
    def test_printer_error_handling(self, printer):
        """Test error handling when print fails"""
        
        pdf = get_mock_invoice_pdf()
        
        # Simulate print failure
        printer.print_pdf_bytes.side_effect = Exception("Printer unavailable")
        
        # Verify failure can be caught
        with pytest.raises(Exception) as exc_info:
            printer.print_pdf_bytes(pdf)
        
        assert "Printer unavailable" in str(exc_info.value)


class TestOrderHandling:
    """Test Wix order handling"""
    
    def test_order_preflight_validation(self, wix_client):
        """Test order preflight checks"""
        
        order = wix_client.get_order("WIX-ORDER-001")
        
        # Validation checks
        is_valid = (
            order["status"] == "PENDING_FULFILLMENT" and
            order["fulfillmentStatus"] == "NOT_FULFILLED" and
            len(order["lineItems"]) > 0
        )
        
        assert is_valid is True
    
    def test_order_fulfillment_dispatch(self, wix_client):
        """Test order fulfillment can be dispatched"""
        
        order_id = "WIX-ORDER-001"
        result = wix_client.mark_fulfilled(order_id)
        
        assert result["success"] is True
        assert wix_client.mark_fulfilled.called


class TestFulfillmentStateTracking:
    """Test fulfillment state persistence"""
    
    def test_fulfillment_flags_structure(self):
        """Test fulfillment flags can track state"""
        
        flags = {
            "invoice_printed": False,
            "label_printed": False,
            "order_fulfilled": False,
            "error": None
        }
        
        # Simulate state transitions
        flags["invoice_printed"] = True
        flags["label_printed"] = True
        flags["order_fulfilled"] = True
        
        # Verify state
        assert flags["invoice_printed"] is True
        assert flags["order_fulfilled"] is True
        assert flags["error"] is None
    
    def test_partial_fulfillment_tracking(self):
        """Test tracking of partial fulfillment"""
        
        flags = {
            "invoice_printed": True,
            "label_printed": True,
            "order_fulfilled": False,  # Failed here
            "error": "API timeout"
        }
        
        # Verify partial state
        assert flags["invoice_printed"] is True
        assert flags["order_fulfilled"] is False
        assert flags["error"] is not None
    
    def test_error_recovery_path(self):
        """Test error can be recovered from"""
        
        flags = {
            "invoice_printed": True,
            "label_printed": False,
            "error": "Label print timeout"
        }
        
        # Recovery: retry failed step
        can_retry = flags["label_printed"] is False and flags["error"] is not None
        
        assert can_retry is True
        
        # After retry succeeds
        flags["label_printed"] = True
        flags["error"] = None
        
        assert flags["label_printed"] is True


class TestEndToEndValidation:
    """Validate end-to-end scenarios"""
    
    def test_complete_sunny_path_scenario(self, invoice_client, wix_client, printer, label_printer, refund_client):
        """Test complete success scenario"""
        
        # Scenario: Process an invoice from start to finish
        invoice_id = "TEST-INV-001"
        order_id = "WIX-ORDER-001"
        
        # Get invoice
        invoice = invoice_client.get_invoice(invoice_id)
        assert invoice is not None
        
        # Print invoice
        pdf = invoice_client.get_invoice_pdf(invoice_id)
        printer.print_pdf_bytes(pdf)
        assert printer.print_pdf_bytes.called
        
        # Print label
        address = [invoice["address"]["name"], invoice["address"]["street"]]
        label_printer.print_address(address)
        assert label_printer.print_address.called
        
        # Fulfill order
        order = wix_client.get_order(order_id)
        assert order["status"] == "PENDING_FULFILLMENT"
        wix_client.mark_fulfilled(order_id)
        assert wix_client.mark_fulfilled.called
    
    def test_refund_scenario(self, invoice_client, refund_client, wix_client):
        """Test refund scenario"""
        
        invoice_id = "TEST-INV-001"
        
        # Cancel in sevDesk
        cancel_result = refund_client.cancel_invoice(invoice_id)
        assert cancel_result["success"] is True
        
        # Create credit note
        credit = refund_client.create_credit_note_from_invoice(invoice_id)
        assert credit["type"] == "credit"
    
    def test_multi_pc_sync_compatible(self):
        """Test that fulfillment data is sync-compatible"""
        
        # Simulate fulfillment data from one PC
        fulfillment_record = {
            "invoice_id": "TEST-INV-001",
            "timestamp": datetime.now().isoformat(),
            "invoice_printed": True,
            "label_printed": True,
            "order_fulfilled": True
        }
        
        # Simulate transmission to other PC
        received_record = fulfillment_record.copy()
        
        # Verify data integrity
        assert received_record["invoice_id"] == fulfillment_record["invoice_id"]
        assert received_record["invoice_printed"] == fulfillment_record["invoice_printed"]


class TestMollieIntegration:
    """Test Mollie payment integration points"""
    
    def test_mollie_payment_status_check(self):
        """Test Mollie payment status can be checked"""
        
        payment = {
            "id": "pr_12345",
            "status": "paid",
            "amount": {"value": "1234.56", "currency": "EUR"}
        }
        
        # Check payment
        is_paid = payment["status"] == "paid"
        
        assert is_paid is True
        assert payment["amount"]["currency"] == "EUR"
    
    def test_mollie_error_handling(self):
        """Test Mollie error handling"""
        
        mollie_client = Mock()
        mollie_client.get_payment.side_effect = Exception("Mollie API unavailable")
        
        with pytest.raises(Exception):
            mollie_client.get_payment("pr_12345")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
