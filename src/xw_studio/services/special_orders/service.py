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
    """Thin client for the website's authenticated special-payment-link endpoint."""

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
        endpoint = self._endpoint()
        secret = self._secret()
        if not endpoint:
            raise RuntimeError("XW_SPECIAL_ORDER_ENDPOINT fehlt")
        if not secret:
            raise RuntimeError("XW_SPECIAL_ORDER_SECRET fehlt")
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
        if not isinstance(data, dict) or not data.get("ok"):
            raise RuntimeError(str(data.get("message") or data.get("error") or "Payment Link fehlgeschlagen"))
        link = SpecialOrderLink(
            id=str(data.get("id") or ""),
            url=str(data.get("url") or ""),
            status=str(data.get("status") or ""),
            title=str(data.get("title") or title),
        )
        if not link.url:
            raise RuntimeError("Website lieferte keinen Payment-Link-URL")
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
    def _response_error_message(response: httpx.Response, data: object) -> str:
        message = ""
        error = ""
        if isinstance(data, dict):
            message = str(data.get("message") or "").strip()
            error = str(data.get("error") or "").strip()
        if not message:
            message = response.text.strip()
        if len(message) > 1000:
            message = f"{message[:1000]}..."
        prefix = f"Payment-Link-Endpunkt {response.status_code}"
        if error and message and error != message:
            return f"{prefix}: {error} - {message}"
        if message:
            return f"{prefix}: {message}"
        return prefix

    def _endpoint(self) -> str:
        return str(self._secrets.get_secret("XW_SPECIAL_ORDER_ENDPOINT") or "").strip()

    def _secret(self) -> str:
        return str(self._secrets.get_secret("XW_SPECIAL_ORDER_SECRET") or "").strip()
