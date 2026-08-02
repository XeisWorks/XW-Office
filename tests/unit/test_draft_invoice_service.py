from __future__ import annotations

from xw_office.services.draft_invoice.service import DraftInvoiceService, ProductIssueDecision, ProductIssueTarget
from xw_office.services.sevdesk.part_client import SevdeskPart


class _ConnectionStub:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    def post(self, path: str, json: dict | None = None):  # noqa: A002
        self.posts.append((path, dict(json or {})))
        if path == "/Invoice/Factory/saveInvoice":
            return _ResponseStub({"invoice": {"id": "INV-NEW-1", "invoiceNumber": "RE-TEST-1"}})
        if path == "/Contact":
            return _ResponseStub({"objects": [{"id": "C-1"}]})
        raise AssertionError(path)

    def get(self, path: str, params: dict | None = None):
        if path == "/SevUser":
            return _ResponseStub({"objects": [{"id": "U-1"}]})
        if path == "/Invoice/Factory/getNextInvoiceNumber":
            return _ResponseStub({"objects": [{"invoiceNumber": "RE-TEST-1"}]})
        raise AssertionError((path, params))


class _ResponseStub:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.content = b"x"

    def json(self) -> dict:
        return dict(self._payload)


class _WixOrdersStub:
    def __init__(self) -> None:
        self.order = {
            "id": "ORDER-1",
            "number": "20519",
            "buyerInfo": {"email": "max@example.test", "firstName": "Max", "lastName": "Mustermann"},
            "lineItems": [
                {
                    "id": "LI-1",
                    "productName": {"translated": "Produkt Eins"},
                    "quantity": 2,
                    "price": {"amount": "12.50"},
                    "taxInfo": {"taxRate": "0"},
                    "descriptionLines": [
                        {
                            "name": {"translated": "Rabatt"},
                            "plainText": {"translated": "B2B-Rabatt 25%"},
                        }
                    ],
                    "physicalProperties": {"sku": "XW-100", "shippable": True},
                }
            ],
        }

    def has_credentials(self) -> bool:
        return True

    def resolve_order(self, reference: str) -> dict:
        return dict(self.order)

    def fetch_order_line_items(self, reference: str) -> list[object]:
        from xw_office.services.wix.client import _parse_order_line_item

        return [_parse_order_line_item(self.order["lineItems"][0])]

    def line_item_is_digital(self, raw_item: dict) -> bool:
        return False

    @staticmethod
    def best_address_lines_from_order(order: dict) -> list[str]:
        return ["Max Mustermann", "Teststrasse 1", "1010 Wien", "Oesterreich"]


class _PartClientStub:
    def __init__(self) -> None:
        self.parts: dict[str, SevdeskPart] = {}
        self.created_payloads: list[dict] = []

    def find_part_by_sku(self, sku: str) -> SevdeskPart | None:
        return self.parts.get(str(sku).strip().upper())

    def list_parts(self, *, max_pages: int = 20) -> list[SevdeskPart]:
        return list(self.parts.values())

    @staticmethod
    def list_part_categories() -> list[dict[str, str]]:
        return [
            {"id": "CAT-1", "name": "Noten"},
            {"id": "CAT-2", "name": "Digital"},
        ]

    def create_part(self, payload: dict) -> SevdeskPart:
        self.created_payloads.append(dict(payload))
        created = SevdeskPart(
            id="P-1",
            sku=str(payload.get("partNumber") or ""),
            name=str(payload.get("name") or ""),
            price_eur=str(payload.get("priceGross") or ""),
            stock_enabled=bool(payload.get("stockEnabled")),
        )
        self.parts[created.sku] = created
        return created


class _ContactClientStub:
    class _Contact:
        def __init__(self) -> None:
            self.id = "C-EXIST"
            self.email = "max@example.test"

    def list_contacts(self, *, max_pages: int = 20, depth: int = 1) -> list[object]:
        return [self._Contact()]


class _InvoiceClientStub:
    def __init__(self) -> None:
        self.updated_invoice: dict | None = None
        self.updated_positions: list[dict] | None = None

    def fetch_invoice_by_id(self, invoice_id: str) -> dict:
        return {
            "id": invoice_id,
            "invoiceDate": "2026-04-14",
            "deliveryDate": "2026-04-14",
            "status": 100,
            "invoiceType": "RE",
            "currency": "EUR",
            "discount": 0,
            "taxRate": 0,
            "taxType": "default",
            "customerInternalNote": "20519",
            "showNet": False,
            "header": "Rechnung",
            "contact": {"id": "C-EXIST"},
        }

    def fetch_invoice_positions(self, invoice_id: str) -> list[dict]:
        return [
            {
                "id": "POS-1",
                "objectName": "InvoicePos",
                "name": "Gepruefte Positionsbezeichnung",
                "text": "Die richtige Produktbeschreibung",
                "quantity": 2,
                "price": 12.5,
                "taxRate": 0,
                "positionNumber": 0,
                "unity": {"id": 1, "objectName": "Unity"},
            }
        ]

    def update_invoice_draft(self, invoice: dict, positions: list[dict], *, take_default_address: bool = False) -> dict:
        self.updated_invoice = dict(invoice)
        self.updated_positions = [dict(position) for position in positions]
        return {"invoice": {"id": invoice.get("id")}}


def _service() -> tuple[DraftInvoiceService, _ConnectionStub, _PartClientStub, _InvoiceClientStub]:
    connection = _ConnectionStub()
    parts = _PartClientStub()
    invoices = _InvoiceClientStub()
    service = DraftInvoiceService(
        connection,
        _WixOrdersStub(),  # type: ignore[arg-type]
        parts,  # type: ignore[arg-type]
        _ContactClientStub(),  # type: ignore[arg-type]
        invoices,  # type: ignore[arg-type]
    )
    return service, connection, parts, invoices


def test_preview_marks_missing_part_as_dialog_candidate() -> None:
    service, _connection, _parts, _invoices = _service()

    preview = service.preview_wix_order_number("20519")

    assert preview["can_create"] is True
    assert preview["missing_skus"] == []
    assert preview["auto_create_skus"] == ["XW-100"]
    assert preview["items"][0]["status"] == "Produktdialog vor Erstellung"


def test_create_draft_keeps_unmapped_position_when_part_missing() -> None:
    service, connection, parts, _invoices = _service()

    result = service.create_draft_from_wix_order_number("20519")

    assert result["invoice_id"] == "INV-NEW-1"
    assert parts.created_payloads == []
    save_invoice = next(payload for path, payload in connection.posts if path == "/Invoice/Factory/saveInvoice")
    first_pos = save_invoice["invoicePosSave"][0]
    assert "part" not in first_pos
    assert first_pos["name"] == "Produkt Eins"
    assert first_pos["price"] == 12.5
    assert first_pos["taxRate"] == 0


def test_apply_missing_product_plan_creates_part_and_patches_existing_draft() -> None:
    service, _connection, parts, invoices = _service()

    plan = service.build_missing_product_plan(
        ["20519"],
        targets_by_reference={
            "20519": [
                ProductIssueTarget(
                    invoice_id="INV-1",
                    invoice_number="RE-TEST-1",
                    wix_order_number="20519",
                    customer_name="Max Mustermann",
                ),
            ]
        },
    )
    issue = plan.issues[0]
    result = service.apply_missing_product_plan(
        plan,
        {issue.sku: ProductIssueDecision(action="create_part", draft=issue.draft)},
    )

    assert result.created_skus == ("XW-100",)
    assert len(parts.created_payloads) == 1
    assert parts.created_payloads[0]["priceGross"] == 12.5
    assert parts.created_payloads[0]["text"] == "[Noten]"
    assert invoices.updated_positions is not None
    assert invoices.updated_positions[0]["part"] == {"id": "P-1", "objectName": "Part"}
    assert invoices.updated_positions[0]["name"] == "Gepruefte Positionsbezeichnung"
    assert invoices.updated_positions[0]["text"] == "Die richtige Produktbeschreibung"
    assert invoices.updated_positions[0]["taxRate"] == 0


def test_repair_draft_product_mapping_only_adds_part_reference_without_auto_create() -> None:
    service, _connection, parts, invoices = _service()
    parts.parts["XW-100"] = SevdeskPart(
        id="P-1",
        sku="XW-100",
        name="Produkt Eins",
        text="Rabatt: B2B-Rabatt 25%",
        tax_rate=19,
    )

    repaired = service.repair_draft_product_mapping("INV-1", "20519")

    assert repaired is True
    assert len(parts.created_payloads) == 0
    assert invoices.updated_positions is not None
    assert invoices.updated_positions[0]["part"] == {"id": "P-1", "objectName": "Part"}
    assert invoices.updated_positions[0]["name"] == "Gepruefte Positionsbezeichnung"
    assert invoices.updated_positions[0]["text"] == "Die richtige Produktbeschreibung"
    assert invoices.updated_positions[0]["taxRate"] == 0
