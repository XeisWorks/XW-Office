"""Create Wix payment links for XW-Office special orders."""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import httpx

if TYPE_CHECKING:
    from xw_office.repositories.settings_kv import SettingKvRepository
    from xw_office.services.secrets.service import SecretService
    from xw_office.services.wix.client import WixProduct, WixProductsClient

SpecialOrderMode = Literal["physical_custom", "digital_custom", "digital_sheet_music"]


@dataclass(slots=True)
class SpecialOrderItem:
    name: str
    price: str
    quantity: int = 1
    description: str = ""
    sku: str = ""
    type: str = "CUSTOM"
    catalog_item_id: str = ""


@dataclass(slots=True)
class SpecialOrderLink:
    id: str
    url: str
    status: str
    title: str


class SpecialOrderService:
    """Create Wix payment links for special-order workflows."""

    def __init__(
        self,
        *,
        secret_service: "SecretService",
        wix_products: "WixProductsClient",
        settings_repo: "SettingKvRepository | None" = None,
    ) -> None:
        self._secrets = secret_service
        self._wix_products = wix_products
        from xw_office.services.invoice_processing.operation_claims import InvoiceOperationClaimStore

        self._claims = InvoiceOperationClaimStore(settings_repo)

    def list_wix_products(self) -> list[WixProduct]:
        return self._wix_products.list_products()

    def create_payment_link(
        self,
        *,
        mode: SpecialOrderMode,
        title: str,
        description: str,
        items: list[SpecialOrderItem],
        customer_email: str,
        customer_first_name: str,
        customer_last_name: str,
        expiration_date: str = "",
    ) -> SpecialOrderLink:
        payload: dict[str, object] = {
            "mode": mode,
            "title": title.strip(),
            "description": description.strip(),
            "currency": "EUR",
            "expirationDate": expiration_date.strip(),
            "customer": {
                "email": customer_email.strip(),
                "firstName": customer_first_name.strip(),
                "lastName": customer_last_name.strip(),
            },
            "items": [self._item_payload(item) for item in items],
        }
        intent = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        intent_id = hashlib.sha256(intent.encode("utf-8")).hexdigest()
        claim = self._claims.acquire_new_run(f"special-order-{intent_id}", "payment_link")
        if not claim.acquired:
            if claim.state == "succeeded":
                raise RuntimeError("Payment Link wurde bereits erstellt; bitte den bestehenden Link verwenden.")
            if claim.state == "unknown":
                try:
                    matches = self._readback_payment_links_by_request_key(claim.operation_id)
                except Exception:
                    matches = []
                if len(matches) == 1:
                    recovered = matches[0]
                    self._claims.reconcile_unknown(
                        claim.invoice_id,
                        claim.operation,
                        claim.operation_id,
                        "succeeded",
                        reconciled_by="Wix request-key readback",
                        evidence=(
                            "Payment-link readback returned exactly one payment link with "
                            f"an exact clientRequestKey match; link_id={recovered.id}"
                        ),
                    )
                    return recovered
            raise RuntimeError(
                "Payment-Link-Ergebnis ist noch offen oder unklar. Keine automatische Wiederholung; "
                "bitte den bestehenden Wix-Link manuell abgleichen."
            )
        payload["clientRequestKey"] = claim.operation_id
        try:
            if self._wix_api_key() and self._wix_site_id():
                link = self._create_payment_link_rest(payload, fallback_title=title)
            else:
                link = self._create_payment_link_via_endpoint(payload, fallback_title=title)
        except Exception as exc:
            self._claims.finish(claim, "unknown", error=str(exc))
            raise
        if not self._claims.finish(claim, "succeeded"):
            raise RuntimeError("Payment Link wurde erstellt, der Vorgangsstatus konnte nicht gespeichert werden.")
        return link

    def _create_payment_link_via_endpoint(self, payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        endpoint = self._endpoint()
        secret = self._secret()
        if not endpoint:
            raise RuntimeError("XW_SPECIAL_ORDER_ENDPOINT fehlt")
        if not secret:
            raise RuntimeError("XW_SPECIAL_ORDER_SECRET fehlt")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-xw-special-order-secret": secret,
                },
                json=payload,
            )
            data = self._response_json(response)
            if response.status_code >= 400:
                raise RuntimeError(self._response_error_message(response, data))
        return self._link_from_endpoint_response(data, fallback_title=fallback_title)

    def _create_payment_link_rest(self, payload: dict[str, object], *, fallback_title: str) -> SpecialOrderLink:
        payment_link = self._payment_link_payload(payload)
        headers = {
            "Authorization": self._wix_api_key(),
            "wix-site-id": self._wix_site_id(),
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "https://www.wixapis.com/payment-links/v1/payment-links",
                headers=headers,
                json={"paymentLink": payment_link},
            )
            data = self._response_json(response)
            if response.status_code >= 400:
                raise RuntimeError(self._response_error_message(response, data, prefix="Wix Payment Links API"))
        return self._link_from_rest_response(data, fallback_title=fallback_title)

    def search_payment_links_by_request_key(self, request_key: str) -> list[SpecialOrderLink]:
        """Read back exact Wix matches for an uncertain create request.

        Wix indexes ``note.text`` for Search Payment Links. Search results are
        only accepted when their JSON note contains the exact request key; the
        fuzzy text search itself is never treated as proof of a match.
        """
        key = str(request_key or "").strip()
        if not key:
            raise ValueError("Payment-Link-Request-Key fehlt")
        api_key = self._wix_api_key()
        site_id = self._wix_site_id()
        if not api_key or not site_id:
            raise RuntimeError("Wix API-Key und Site-ID sind fuer den Payment-Link-Readback erforderlich")

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "https://www.wixapis.com/payment-links/v1/payment-links/search",
                headers={
                    "Authorization": api_key,
                    "wix-site-id": site_id,
                    "Content-Type": "application/json",
                },
                json={
                    "search": {
                        "search": {"expression": key, "fields": ["note.text"], "fuzzy": False},
                        "cursorPaging": {"limit": 100},
                    }
                },
            )
            data = self._response_json(response)
            if response.status_code >= 400:
                raise RuntimeError(
                    self._response_error_message(response, data, prefix="Wix Payment-Link-Suche")
                )

        response_data = self._string_keyed_dict(data)
        if response_data is None:
            raise RuntimeError("Wix Payment-Link-Suche lieferte keine JSON-Antwort")
        raw_links = response_data.get("paymentLinks")
        if not isinstance(raw_links, list):
            raise RuntimeError("Wix Payment-Link-Suche lieferte keine Ergebnisliste")
        if len(raw_links) >= 100:
            raise RuntimeError("Wix Payment-Link-Suche erreichte das 100-Ergebnisse-Limit")

        matches: list[SpecialOrderLink] = []
        for raw_link in raw_links:
            payment_link = self._string_keyed_dict(raw_link)
            if payment_link is None:
                continue
            note = self._string_keyed_dict(payment_link.get("note")) or {}
            try:
                note_data = json.loads(str(note.get("text") or ""))
            except (TypeError, ValueError):
                continue
            if not isinstance(note_data, dict) or note_data.get("clientRequestKey") != key:
                continue
            link = self._link_from_rest_response(
                {"paymentLink": payment_link},
                fallback_title=str(payment_link.get("title") or "Payment Link"),
            )
            matches.append(link)
        return matches

    def _readback_payment_links_by_request_key(self, request_key: str) -> list[SpecialOrderLink]:
        if self._wix_api_key() and self._wix_site_id():
            return self.search_payment_links_by_request_key(request_key)
        endpoint = self._endpoint()
        secret = self._secret()
        if not endpoint:
            raise RuntimeError("XW_SPECIAL_ORDER_ENDPOINT fehlt")
        if not secret:
            raise RuntimeError("XW_SPECIAL_ORDER_SECRET fehlt")

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-xw-special-order-secret": secret,
                },
                json={"action": "readback", "clientRequestKey": request_key},
            )
            data = self._response_json(response)
            if response.status_code >= 400:
                raise RuntimeError(self._response_error_message(response, data, prefix="Payment-Link-Readback"))

        result = self._string_keyed_dict(data)
        raw_matches = result.get("matches") if result and result.get("ok") is True else None
        if not isinstance(raw_matches, list):
            raise RuntimeError("Payment-Link-Readback lieferte keine Ergebnisliste")
        matches: list[SpecialOrderLink] = []
        for raw_match in raw_matches:
            match = self._string_keyed_dict(raw_match)
            if match is None:
                raise RuntimeError("Payment-Link-Readback lieferte einen ungueltigen Treffer")
            matches.append(
                self._link_from_endpoint_response(
                    {"ok": True, **match}, fallback_title="Payment Link"
                )
            )
        return matches

    def _payment_link_payload(self, payload: dict[str, object]) -> dict[str, object]:
        mode = str(payload.get("mode") or "").strip()
        raw_items = payload.get("items")
        normalized_items = [
            self._line_item_for_rest(item, mode)
            for raw_item in (raw_items if isinstance(raw_items, list) else [])
            if (item := self._string_keyed_dict(raw_item)) is not None
        ]
        payment_link: dict[str, object] = {
            "title": str(payload.get("title") or "").strip(),
            "description": str(payload.get("description") or "").strip() or None,
            "currency": str(payload.get("currency") or "EUR").strip() or "EUR",
            "paymentsLimit": 1,
            "type": "ECOM",
            "ecomPaymentLink": {
                "lineItems": normalized_items,
            },
            "note": {
                "text": json.dumps(
                    {
                        "source": "XW-Office",
                        "mode": mode,
                        "clientRequestKey": str(payload.get("clientRequestKey") or ""),
                    },
                    ensure_ascii=False,
                )
            },
        }
        expiration_date = str(payload.get("expirationDate") or "").strip()
        if expiration_date:
            payment_link["expirationDate"] = expiration_date
        return payment_link

    @staticmethod
    def _line_item_for_rest(item: dict[str, object], mode: str) -> dict[str, object]:
        shippable = mode == "physical_custom"
        name = str(item.get("name") or "").strip()
        if not name:
            raise RuntimeError("Position ohne Name")
        try:
            price = float(str(item.get("price") or "0").replace(",", "."))
        except ValueError as exc:
            raise RuntimeError(f"Ungueltiger Preis fuer '{name}'") from exc
        if price <= 0:
            raise RuntimeError(f"Preis fuer '{name}' muss groesser als 0 sein")
        custom_item: dict[str, object] = {
            "quantity": int(str(item.get("quantity") or 1)),
            "name": name,
            "price": f"{price:.2f}",
            "physicalProperties": {
                "sku": str(item.get("sku") or "").strip() or None,
                "shippable": shippable,
            },
        }
        description = str(item.get("description") or "").strip()
        if description:
            custom_item["description"] = description
        return {
            "type": "CUSTOM",
            "customItem": custom_item,
        }

    @staticmethod
    def _link_from_endpoint_response(data: object, *, fallback_title: str) -> SpecialOrderLink:
        payload = SpecialOrderService._string_keyed_dict(data)
        if payload is None:
            raise RuntimeError("Website lieferte keine JSON-Antwort")
        if payload.get("ok") is not True:
            raise RuntimeError(str(payload.get("message") or payload.get("error") or "Payment Link fehlgeschlagen"))
        link = SpecialOrderLink(
            id=str(payload.get("id") or ""),
            url=str(payload.get("url") or ""),
            status=str(payload.get("status") or ""),
            title=str(payload.get("title") or fallback_title),
        )
        if not link.url:
            raise RuntimeError("Website lieferte keinen Payment-Link-URL")
        return link

    @staticmethod
    def _link_from_rest_response(data: object, *, fallback_title: str) -> SpecialOrderLink:
        response = SpecialOrderService._string_keyed_dict(data)
        if response is None:
            raise RuntimeError("Wix Payment Links API lieferte keine JSON-Antwort")
        payment_link = SpecialOrderService._string_keyed_dict(response.get("paymentLink")) or response
        links = SpecialOrderService._string_keyed_dict(payment_link.get("links")) or {}
        raw_url = links.get("url") or links.get("originalUrl") or payment_link.get("url") or ""
        if isinstance(raw_url, dict):
            url_data = SpecialOrderService._string_keyed_dict(raw_url) or {}
            raw_url = url_data.get("url") or url_data.get("originalUrl") or ""
        url = str(raw_url).strip()
        link = SpecialOrderLink(
            id=str(payment_link.get("_id") or payment_link.get("id") or ""),
            url=url,
            status=str(payment_link.get("status") or ""),
            title=str(payment_link.get("title") or fallback_title),
        )
        if not link.url:
            raise RuntimeError("Wix Payment Links API lieferte keinen Payment-Link-URL")
        return link

    @staticmethod
    def _string_keyed_dict(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            return None
        return value

    def open_link_mail_draft(
        self,
        *,
        to_email: str,
        first_name: str,
        title: str,
        link: SpecialOrderLink,
    ) -> None:
        sender = str(self._secrets.get_secret("OUTLOOK_SENDER_EMAIL") or "").strip()
        if not sender:
            raise RuntimeError("OUTLOOK_SENDER_EMAIL fehlt")
        payload = json.dumps(
            {
                "to": to_email,
                "subject": f"Payment link for {title}",
                "sender": sender,
                "body": self._mail_body(first_name=first_name, title=title, url=link.url),
            },
            ensure_ascii=False,
        )
        env = dict(os.environ)
        src_path = str(Path(__file__).resolve().parents[3])
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_path
        completed = subprocess.run(
            [sys.executable, "-m", "xw_office.services.mailing.outlook_compose"],
            input=payload,
            text=True,
            capture_output=True,
            timeout=25,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "Outlook draft failed").strip())

    @staticmethod
    def _item_payload(item: SpecialOrderItem) -> dict[str, object]:
        if item.type.upper() == "CATALOG":
            return {
                "type": "CATALOG",
                "catalogItemId": item.catalog_item_id,
                "name": item.name,
                "description": item.description,
                "price": item.price,
                "quantity": item.quantity,
                "sku": item.sku,
            }
        return {
            "type": "CUSTOM",
            "name": item.name,
            "description": item.description,
            "price": item.price,
            "quantity": item.quantity,
            "sku": item.sku,
        }

    @staticmethod
    def _mail_body(*, first_name: str, title: str, url: str) -> str:
        greeting = first_name.strip() or "there"
        return (
            f"Dear {greeting},\n\n"
            f"Thank you for your request. You can complete your order for {title} using this secure payment link:\n\n"
            f"{url}\n\n"
            "After payment, your order will be processed through our regular checkout workflow.\n\n"
            "Best regards,\n"
            "XeisWorks"
        )

    @staticmethod
    def _response_json(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _response_error_message(response: httpx.Response, data: object, *, prefix: str = "Payment-Link-Endpunkt") -> str:
        message = ""
        error = ""
        if isinstance(data, dict):
            message = str(data.get("message") or "").strip()
            error = str(data.get("error") or "").strip()
        if not message:
            message = response.text.strip()
        if len(message) > 1000:
            message = f"{message[:1000]}..."
        prefix = f"{prefix} {response.status_code}"
        if error and message and error != message:
            return f"{prefix}: {error} - {message}"
        if message:
            return f"{prefix}: {message}"
        return prefix

    def _endpoint(self) -> str:
        return str(self._secrets.get_secret("XW_SPECIAL_ORDER_ENDPOINT") or "").strip()

    def _secret(self) -> str:
        return str(self._secrets.get_secret("XW_SPECIAL_ORDER_SECRET") or "").strip()

    def _wix_api_key(self) -> str:
        return str(self._secrets.get_secret("WIX_API_KEY") or "").strip()

    def _wix_site_id(self) -> str:
        return str(self._secrets.get_secret("WIX_SITE_ID") or "").strip()
