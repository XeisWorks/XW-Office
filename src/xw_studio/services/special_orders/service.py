"""Create Wix payment links for XW-Studio special orders."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import httpx

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService
    from xw_studio.services.wix.client import WixProductsClient

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
    ) -> None:
        self._secrets = secret_service
        self._wix_products = wix_products

    def list_wix_products(self) -> list[object]:
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
        payload = {
            "mode": mode,
            "title": title.strip(),
            "description": description.strip(),
            "currency": "EUR",
            "expirationDate": expiration_date.strip(),
            "clientRequestKey": str(uuid.uuid4()),
            "customer": {
                "email": customer_email.strip(),
                "firstName": customer_first_name.strip(),
                "lastName": customer_last_name.strip(),
            },
            "items": [self._item_payload(item) for item in items],
        }
        if self._wix_api_key() and self._wix_site_id():
            return self._create_payment_link_rest(payload, fallback_title=title)
        return self._create_payment_link_via_endpoint(payload, fallback_title=title)

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
        account_id = self._wix_account_id()
        if account_id:
            headers["wix-account-id"] = account_id
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

    def _payment_link_payload(self, payload: dict[str, object]) -> dict[str, object]:
        mode = str(payload.get("mode") or "").strip()
        normalized_items = [self._line_item_for_rest(item, mode) for item in payload.get("items", []) if isinstance(item, dict)]
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
                        "source": "XW-Studio",
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
            "quantity": int(item.get("quantity") or 1),
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
        if not isinstance(data, dict) or not data.get("ok"):
            raise RuntimeError(str(data.get("message") or data.get("error") or "Payment Link fehlgeschlagen"))
        link = SpecialOrderLink(
            id=str(data.get("id") or ""),
            url=str(data.get("url") or ""),
            status=str(data.get("status") or ""),
            title=str(data.get("title") or fallback_title),
        )
        if not link.url:
            raise RuntimeError("Website lieferte keinen Payment-Link-URL")
        return link

    @staticmethod
    def _link_from_rest_response(data: object, *, fallback_title: str) -> SpecialOrderLink:
        if not isinstance(data, dict):
            raise RuntimeError("Wix Payment Links API lieferte keine JSON-Antwort")
        payment_link = data.get("paymentLink") if isinstance(data.get("paymentLink"), dict) else data
        links = payment_link.get("links") if isinstance(payment_link, dict) and isinstance(payment_link.get("links"), dict) else {}
        url = str(links.get("url") or links.get("originalUrl") or payment_link.get("url") or "").strip()
        link = SpecialOrderLink(
            id=str(payment_link.get("_id") or payment_link.get("id") or ""),
            url=url,
            status=str(payment_link.get("status") or ""),
            title=str(payment_link.get("title") or fallback_title),
        )
        if not link.url:
            raise RuntimeError("Wix Payment Links API lieferte keinen Payment-Link-URL")
        return link

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
            [sys.executable, "-m", "xw_studio.services.mailing.outlook_compose"],
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

    def _wix_account_id(self) -> str:
        return str(self._secrets.get_secret("WIX_ACCOUNT_ID") or "").strip()
