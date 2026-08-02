"""sevDesk Contact API client."""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from xw_office.services.crm.types import ContactRecord
from xw_office.services.http_client import SevdeskConnection, raise_for_sevdesk

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100


class ContactSummary(BaseModel):
    """Subset of Contact returned by sevDesk."""

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str | None = None


def _parse_contact_record(raw: dict[str, Any]) -> ContactRecord:
    cid = str(raw.get("id") or "")
    name = str(raw.get("name") or raw.get("surename") or "").strip()
    email_list: list[Any] = raw.get("emails") or []
    email: str | None = None
    if email_list and isinstance(email_list[0], dict):
        email = str(email_list[0].get("value") or "").strip() or None
    phone_list: list[Any] = raw.get("phones") or []
    phone: str | None = None
    if phone_list and isinstance(phone_list[0], dict):
        phone = str(phone_list[0].get("value") or "").strip() or None
    addresses: list[Any] = raw.get("addresses") or []
    city: str | None = None
    for addr in addresses:
        if isinstance(addr, dict) and addr.get("city"):
            city = str(addr["city"]).strip() or None
            break
    return ContactRecord(id=cid, name=name, email=email, phone=phone, city=city)


class ContactClient:
    """Fetch and list contacts from sevDesk."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection

    def list_contacts(
        self,
        *,
        max_pages: int = 20,
        depth: int = 0,
    ) -> list[ContactRecord]:
        """Fetch all contacts (paginated).

        Args:
            max_pages: Safety cap — stops after this many API pages.
            depth: sevDesk depth level (0 = plain fields, 1 = includes embedded objects).
        """
        results: list[ContactRecord] = []
        offset = 0
        for _ in range(max_pages):
            params = {
                "depth": depth,
                "limit": _PAGE_SIZE,
                "offset": offset,
            }
            try:
                response = self._conn.get("/Contact", params=params)
            except Exception:
                logger.exception("ContactClient.list_contacts failed at offset %s", offset)
                break
            data = response.json()
            objects: list[Any] = []
            if isinstance(data, dict):
                objects = data.get("objects") or []
            if not isinstance(objects, list):
                break
            for raw in objects:
                if isinstance(raw, dict):
                    results.append(_parse_contact_record(raw))
            if len(objects) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        logger.info("ContactClient: fetched %s contacts", len(results))
        return results

    def get_contact(self, contact_id: str) -> ContactSummary:
        """GET ``/Contact/{id}`` — raises if not found or API error."""
        response = self._conn.get(f"/Contact/{contact_id}")
        data = response.json()
        obj: dict[str, Any]
        if isinstance(data, dict) and "objects" in data:
            seq = data["objects"]
            if not isinstance(seq, list) or not seq:
                raise ValueError("Empty objects in Contact response")
            first = seq[0]
            if not isinstance(first, dict):
                raise ValueError("Invalid Contact object")
            obj = first
        elif isinstance(data, dict):
            obj = data
        else:
            raise ValueError("Unexpected Contact payload")
        cid = obj.get("id", contact_id)
        return ContactSummary.model_validate({**obj, "id": str(cid)})

    def update_contact(self, contact_id: str, payload: dict[str, Any]) -> None:
        """Update sevDesk contact by id."""
        response = self._conn.client.put(f"/Contact/{contact_id}", json=payload)
        raise_for_sevdesk(response)

    def delete_contact(self, contact_id: str) -> None:
        """Delete sevDesk contact by id."""
        response = self._conn.client.delete(f"/Contact/{contact_id}")
        raise_for_sevdesk(response)

    def update_contact_fields(self, record: ContactRecord) -> None:
        """Write name/email/phone/city to sevDesk, falling back to a minimal payload."""
        payload: dict[str, Any] = {"name": record.name}
        if record.email:
            payload["emails"] = [{"value": record.email, "type": "work"}]
        if record.phone:
            payload["phones"] = [{"value": record.phone, "type": "work"}]
        if record.city:
            payload["addresses"] = [{"city": record.city}]

        # Try rich payload first; on API-schema mismatch, fallback to minimal update.
        try:
            self.update_contact(record.id, payload)
        except Exception:
            logger.warning("Contact rich update failed for %s; retry with minimal payload", record.id)
            self.update_contact(record.id, {"name": record.name})

    def archive_contact(
        self,
        contact_id: str,
        *,
        current_name: str,
        name_prefix: str = "[MERGED] ",
    ) -> None:
        """Best-effort archive marker for a merge loser sevDesk refuses to delete.

        sevDesk blocks deleting a contact with linked documents. Rather than
        letting that surface as a raw API error, mark the loser's name so
        it's clearly recognizable and excluded from future duplicate scans
        by convention.
        """
        marked_name = current_name if current_name.startswith(name_prefix) else f"{name_prefix}{current_name}".strip()
        self.update_contact(contact_id, {"name": marked_name})

    def merge_contacts(self, master: ContactRecord, duplicate: ContactRecord) -> None:
        """Write merge result to sevDesk: update master and delete duplicate.

        Simple unconditional merge, kept for direct callers that don't need
        the preflight/loser-policy split — see ``CrmService.merge_contacts``
        for the safer default flow.
        """
        self.update_contact_fields(master)
        self.delete_contact(duplicate.id)
