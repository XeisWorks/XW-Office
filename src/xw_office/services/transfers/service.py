from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.mailing.graph_client import GraphMailClient, html_to_text
from xw_office.services.secrets.service import SecretService
from xw_office.services.transfers.models import (
    TransferAttachment,
    TransferCase,
    TransferCaseStatus,
    TransferFieldSource,
    TransferPaymentData,
)
from xw_office.services.transfers.payment_qr import (
    _extract_pdf_text,
    create_epc_qr_from_payment_data,
    extract_payment_data_from_sources,
    payment_to_json_dict,
)

logger = logging.getLogger(__name__)

_OPEN_CASES_KEY = "daily_business.open_transfers.cases"
_DONE_AUDIT_KEY = "daily_business.open_transfers.done_audit"
_MANUAL_FIELDS_KEY = "daily_business.open_transfers.manual_fields"
_RAW_GRAPH_KEY = "daily_business.open_transfers.raw_graph"
_QR_HISTORY_KEY = "daily_business.open_transfers.qr_history"
_LOCAL_STATE_PATH = Path(__file__).resolve().parents[4] / "state" / "open_transfers_state.json"
_DEFAULT_TRANSFER_MAILBOX = "transfer@xeisworks.at"


class OffeneUeberweisungenService:
    """Graph-backed transfer inbox workflow for Daily Business."""

    def __init__(self, settings_repo: SettingKvRepository | None, secrets: SecretService) -> None:
        self._repo = settings_repo
        self._secrets = secrets

    def open_count(self) -> int:
        return len(self.load_open_cases())

    def load_open_cases(self) -> list[TransferCase]:
        all_cases = self._load_cached_cases()
        return [case for case in all_cases if case.status == TransferCaseStatus.OPEN and case.outlook_flag_status != "complete"]

    def refresh_from_graph(
        self,
        *,
        lookback_days: int = 60,
        max_items: int = 150,
        allow_interactive_auth: bool = True,
    ) -> list[TransferCase]:
        messages = self._fetch_graph_messages(
            lookback_days=lookback_days,
            max_items=max_items,
            allow_interactive_auth=allow_interactive_auth,
        )
        cases = [self._to_case(msg, load_thread=allow_interactive_auth) for msg in messages]
        manual_map = self._load_manual_fields()
        for case in cases:
            self._apply_manual_fields(case, manual_map)
        self._save_cases(cases)
        return self.load_open_cases()

    def refresh_count_from_graph_silent(self, *, lookback_days: int = 60, max_items: int = 150) -> int:
        return len(
            self.refresh_from_graph(
                lookback_days=lookback_days,
                max_items=max_items,
                allow_interactive_auth=False,
            )
        )

    def needs_interactive_graph_login(self) -> bool:
        client = self._graph_client(write=False)
        if client is None:
            return False
        try:
            return not client.has_silent_token()
        except Exception:  # noqa: BLE001
            return True

    def summarize_case(self, case_id: str) -> str:
        case = self._find_case(case_id)
        if case is None:
            return ""
        context = (case.thread_text or case.body or case.snippet).strip()
        pdf_text = ""
        pdf_payment = TransferPaymentData()
        api_key = self._secrets.get_secret("OPENAI_API_KEY")
        if case.attachments:
            try:
                pdf_bytes = self.download_attachment_bytes(case.id, case.attachments[0].id)
                pdf_text = _extract_pdf_text(pdf_bytes)
                pdf_payment = extract_payment_data_from_sources(
                    mail_text=context,
                    pdf_bytes=pdf_bytes,
                    filename_hint=case.attachments[0].name,
                    use_openai_fallback=bool(api_key),
                    openai_api_key=api_key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Transfer summary PDF context failed for %s: %s", case.id, exc)
        if not context and not pdf_text:
            return "Keine Mailinhalte verfuegbar."
        if not api_key:
            return self._fallback_summary(case)
        payment_context = "\n".join(
            part
            for part in (
                f"Empfaenger: {pdf_payment.recipient}" if pdf_payment.recipient else "",
                f"IBAN: {pdf_payment.iban}" if pdf_payment.iban else "",
                f"BIC: {pdf_payment.bic}" if pdf_payment.bic else "",
                f"Betrag: {pdf_payment.amount} EUR" if pdf_payment.amount is not None else "",
                f"Referenz: {pdf_payment.remittance_text}" if pdf_payment.remittance_text else "",
                f"Rechnungsnummer: {pdf_payment.invoice_number}" if pdf_payment.invoice_number else "",
            )
            if part
        )
        prompt = (
            "Fasse den Mailverkehr fuer eine manuelle Ueberweisung zusammen.\n"
            "Nenne:\n"
            "1. Was soll bezahlt werden?\n"
            "2. Wer ist Zahlungsempfaenger?\n"
            "3. Welche Rechnung/Referenz gehoert dazu?\n"
            "4. Betrag und Faelligkeit, falls vorhanden.\n"
            "5. Welche Punkte sind unsicher oder fehlen?\n"
            "Antworte auf Deutsch, knapp, sachlich.\n\n"
            f"Betreff: {case.subject}\n"
            f"Von: {case.sender}\n"
            f"Erkannte Zahlungsdaten:\n{payment_context or '-'}\n\n"
            f"Mailinhalt:\n{context[:8000] or '-'}\n\n"
            f"PDF/Rechnungstext:\n{pdf_text[:8000] or '-'}"
        )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4.1-mini",
            "input": prompt,
            "max_output_tokens": 450,
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI summary failed for transfer %s: %s", case.id, exc)
            return self._fallback_summary(case)

        text = str(payload.get("output_text") or "").strip()
        if not text and isinstance(payload.get("output"), list):
            for item in payload["output"]:
                if not isinstance(item, dict):
                    continue
                for block in item.get("content") or []:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        text = block["text"].strip()
                        if text:
                            break
                if text:
                    break
        return text or self._fallback_summary(case)

    def extract_payment_data(self, case_id: str, attachment_id: str | None = None) -> TransferPaymentData:
        case = self._find_case(case_id)
        if case is None:
            return TransferPaymentData()
        manual_fields = self._load_manual_fields().get(case_id, {})
        pdf_bytes = b""
        if attachment_id:
            try:
                pdf_bytes = self.download_attachment_bytes(case_id, attachment_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Attachment download failed for %s: %s", case_id, exc)
        elif case.attachments:
            try:
                pdf_bytes = self.download_attachment_bytes(case_id, case.attachments[0].id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Attachment download failed for %s: %s", case_id, exc)

        extracted = extract_payment_data_from_sources(
            mail_text=case.body or case.snippet,
            thread_text=case.thread_text,
            pdf_bytes=pdf_bytes if pdf_bytes else None,
            filename_hint=case.subject,
            use_openai_fallback=True,
            openai_api_key=self._secrets.get_secret("OPENAI_API_KEY"),
        )
        extracted.currency = "EUR"
        self._apply_manual_payment(extracted, manual_fields)
        return extracted

    def generate_qr(self, case_id: str, payment: TransferPaymentData) -> Path:
        qr_path = create_epc_qr_from_payment_data(
            payment,
            output_dir=Path(__file__).resolve().parents[4] / "state" / "generated" / "transfer_qr",
            filename_hint=self._safe_filename(case_id),
        )
        self._append_qr_history(case_id, qr_path)
        return qr_path

    def mark_deferred(self, case_id: str, note: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        updated = False
        cases = self._load_cached_cases()
        for case in cases:
            if case.id != case_id:
                continue
            case.deferred_at = now
            case.defer_count = int(case.defer_count) + 1
            if note:
                case.done_note = str(note).strip()
            updated = True
            break
        if updated:
            self._save_cases(cases)

    def mark_done_in_outlook(
        self,
        case_id: str,
        payment: TransferPaymentData,
        qr_path: str = "",
        note: str = "",
    ) -> None:
        case = self._find_case(case_id)
        if case is None:
            return
        self.mark_outlook_flag_complete(case.id)

        done_at = datetime.now(timezone.utc).isoformat()
        cases = self._load_cached_cases()
        for item in cases:
            if item.id != case_id:
                continue
            item.status = TransferCaseStatus.DONE
            item.outlook_flag_status = "complete"
            item.outlook_completed_at = done_at
            item.done_at = done_at
            item.done_note = str(note or "").strip()
            if qr_path:
                item.qr_path = qr_path
            break
        self._save_cases(cases)
        self._append_done_audit(case, payment, qr_path=qr_path)

    def mark_outlook_flag_complete(self, message_id: str) -> None:
        client = self._graph_client(write=True)
        if client is None:
            raise RuntimeError("MS Graph ist nicht konfiguriert")
        client.mark_message_followup_complete(message_id)

    def list_pdf_attachments(self, case_id: str) -> list[TransferAttachment]:
        case = self._find_case(case_id)
        if case is None:
            return []
        client = self._graph_client(write=False)
        if client is None:
            return list(case.attachments)
        try:
            values = client.list_pdf_attachments(case.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Graph attachments failed for %s: %s", case.id, exc)
            return list(case.attachments)
        attachments = [
            TransferAttachment(
                id=str(item.get("id") or "").strip(),
                name=str(item.get("name") or "").strip(),
                content_type=str(item.get("contentType") or "").strip(),
                size=int(item.get("size")) if isinstance(item.get("size"), int) else None,
            )
            for item in values
            if str(item.get("id") or "").strip()
        ]
        self._replace_case_attachments(case.id, attachments)
        return attachments

    def download_attachment_bytes(self, case_id: str, attachment_id: str) -> bytes:
        case = self._find_case(case_id)
        if case is None:
            return b""
        client = self._graph_client(write=False)
        if client is None:
            return b""
        return client.download_attachment_bytes(case.id, attachment_id)

    def save_manual_payment(self, case_id: str, payment: TransferPaymentData) -> None:
        mapping = self._load_manual_fields()
        mapping[case_id] = payment_to_json_dict(payment)
        self._save_manual_fields(mapping)

    def _graph_client(self, *, write: bool = False) -> GraphMailClient | None:
        tenant_id = self._secrets.get_secret("MS_GRAPH_TENANT_ID")
        client_id = self._secrets.get_secret("MS_GRAPH_CLIENT_ID")
        mailbox = self._secrets.get_secret("MS_GRAPH_TRANSFER_MAILBOX") or _DEFAULT_TRANSFER_MAILBOX
        if not tenant_id or not client_id:
            return None
        scopes = [
            "Mail.Read",
            "Mail.Read.Shared",
            "Mail.Send",
            "Mail.Send.Shared",
        ]
        if write:
            scopes.extend(["Mail.ReadWrite", "Mail.ReadWrite.Shared"])
        return GraphMailClient(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_user=mailbox,
            scopes=scopes,
        )

    def _fetch_graph_messages(
        self,
        *,
        lookback_days: int,
        max_items: int,
        allow_interactive_auth: bool,
    ) -> list[dict[str, Any]]:
        client = self._graph_client(write=False)
        if client is None:
            return self._load_cached_raw_messages()
        if not allow_interactive_auth and not client.has_silent_token():
            logger.info("MS Graph silent token missing; using cached offene Ueberweisungen")
            return self._cached_cases_as_raw_messages() or self._load_cached_raw_messages()

        try:
            values = client.list_inbox_messages(days=max(1, lookback_days), top=max(1, min(max_items, 300)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("MS Graph fetch failed for offene Ueberweisungen: %s", exc)
            return self._load_cached_raw_messages()

        normalized = [self._normalize_graph_message(item) for item in values]
        filtered = [item for item in normalized if self._is_transfer_candidate(item)]
        self._save_raw_messages(filtered)
        return filtered

    @staticmethod
    def _normalize_graph_message(msg: dict[str, Any]) -> dict[str, Any]:
        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        content = str(body_obj.get("content") or "").strip()
        content_type = str(body_obj.get("contentType") or "").strip().lower()
        normalized = dict(msg)
        normalized["body"] = {
            "content": html_to_text(content) if content and content_type == "html" else content,
            "contentType": "text",
        }
        return normalized

    @staticmethod
    def _is_transfer_candidate(msg: dict[str, Any]) -> bool:
        subject = str(msg.get("subject") or "").strip().lower()
        preview = str(msg.get("bodyPreview") or "").strip().lower()
        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        body_text = str(body_obj.get("content") or "").strip().lower()
        hay = f"{subject} {preview} {body_text}"
        if any(token in hay for token in ("automatic reply", "out of office", "undeliverable", "delivery status")):
            return False
        flag_obj = msg.get("flag") if isinstance(msg.get("flag"), dict) else {}
        status = str(flag_obj.get("flagStatus") or "").strip().lower()
        return status != "complete"

    def _to_case(self, msg: dict[str, Any], *, load_thread: bool = True) -> TransferCase:
        from_obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        email_obj = from_obj.get("emailAddress") if isinstance(from_obj.get("emailAddress"), dict) else {}
        sender = str(email_obj.get("address") or email_obj.get("name") or "").strip()

        body_obj = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        body = str(body_obj.get("content") or "").strip()
        snippet = str(msg.get("bodyPreview") or "").strip()
        subject = str(msg.get("subject") or "").strip()
        message_id = str(msg.get("id") or "").strip()
        conversation_id = str(msg.get("conversationId") or "").strip()

        attachments = [
            TransferAttachment(
                id=str(att.get("id") or "").strip(),
                name=str(att.get("name") or "").strip(),
                content_type=str(att.get("contentType") or "").strip(),
                size=int(att.get("size")) if isinstance(att.get("size"), int) else None,
            )
            for att in (msg.get("attachments") if isinstance(msg.get("attachments"), list) else [])
            if isinstance(att, dict)
        ]

        flag_obj = msg.get("flag") if isinstance(msg.get("flag"), dict) else {}
        flag_status = str(flag_obj.get("flagStatus") or "notFlagged").strip() or "notFlagged"
        completed_obj = flag_obj.get("completedDateTime") if isinstance(flag_obj.get("completedDateTime"), dict) else {}
        completed_at = str(completed_obj.get("dateTime") or "").strip()

        thread_text = ""
        client = self._graph_client(write=False) if load_thread else None
        if client is not None and conversation_id:
            try:
                thread_text = client.get_conversation_thread_text(conversation_id, days=60, top=20)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Conversation fetch failed for %s: %s", conversation_id, exc)

        case = TransferCase(
            id=message_id,
            internet_message_id=str(msg.get("internetMessageId") or "").strip(),
            conversation_id=conversation_id,
            received_at=str(msg.get("receivedDateTime") or "").strip(),
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
            thread_text=thread_text,
            attachments=attachments,
            status=TransferCaseStatus.DONE if flag_status == "complete" else TransferCaseStatus.OPEN,
            outlook_flag_status=flag_status,
            outlook_completed_at=completed_at,
        )
        return case

    def _fallback_summary(self, case: TransferCase) -> str:
        text = (case.thread_text or case.body or case.snippet).strip()
        excerpt = text[:1000]
        return (
            f"Betreff: {case.subject}\n"
            f"Absender: {case.sender}\n"
            f"Empfangen: {case.received_at}\n\n"
            "Kurzinhalt:\n"
            f"{excerpt}"
        )

    def _load_cached_cases(self) -> list[TransferCase]:
        raw = self._get_value(_OPEN_CASES_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        out: list[TransferCase] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append(self._case_from_dict(item))
        return out

    def _save_cases(self, cases: list[TransferCase]) -> None:
        payload = [self._case_to_dict(case) for case in cases]
        self._set_value(_OPEN_CASES_KEY, json.dumps(payload, ensure_ascii=False))

    def _case_to_dict(self, case: TransferCase) -> dict[str, Any]:
        payment = payment_to_json_dict(case.payment)
        return {
            "id": case.id,
            "internet_message_id": case.internet_message_id,
            "conversation_id": case.conversation_id,
            "received_at": case.received_at,
            "sender": case.sender,
            "subject": case.subject,
            "snippet": case.snippet,
            "body": case.body,
            "thread_text": case.thread_text,
            "summary": case.summary,
            "attachments": [asdict(att) for att in case.attachments],
            "payment": payment,
            "status": case.status.value,
            "outlook_flag_status": case.outlook_flag_status,
            "outlook_completed_at": case.outlook_completed_at,
            "deferred_at": case.deferred_at,
            "defer_count": int(case.defer_count),
            "done_at": case.done_at,
            "done_note": case.done_note,
            "qr_path": case.qr_path,
        }

    def _case_from_dict(self, data: dict[str, Any]) -> TransferCase:
        attachments_raw = data.get("attachments") if isinstance(data.get("attachments"), list) else []
        attachments = [
            TransferAttachment(
                id=str(item.get("id") or "").strip(),
                name=str(item.get("name") or "").strip(),
                content_type=str(item.get("content_type") or item.get("contentType") or "").strip(),
                size=int(item.get("size")) if isinstance(item.get("size"), int) else None,
            )
            for item in attachments_raw
            if isinstance(item, dict)
        ]
        payment_raw = data.get("payment") if isinstance(data.get("payment"), dict) else {}
        payment_amount_raw = payment_raw.get("amount")
        amount: Decimal | None = None
        if payment_amount_raw not in (None, ""):
            try:
                amount = Decimal(str(payment_amount_raw))
            except Exception:  # noqa: BLE001
                amount = None
        source_raw = payment_raw.get("source_by_field") if isinstance(payment_raw.get("source_by_field"), dict) else {}
        source_by_field: dict[str, TransferFieldSource] = {}
        for key, value in source_raw.items():
            try:
                source_by_field[str(key)] = TransferFieldSource(str(value))
            except ValueError:
                source_by_field[str(key)] = TransferFieldSource.UNKNOWN
        payment = TransferPaymentData(
            recipient=str(payment_raw.get("recipient") or "").strip(),
            iban=str(payment_raw.get("iban") or "").strip(),
            bic=str(payment_raw.get("bic") or "").strip(),
            amount=amount,
            currency=str(payment_raw.get("currency") or "EUR").strip() or "EUR",
            remittance_text=str(payment_raw.get("remittance_text") or "").strip(),
            invoice_number=str(payment_raw.get("invoice_number") or "").strip(),
            due_date=str(payment_raw.get("due_date") or "").strip(),
            note=str(payment_raw.get("note") or "").strip(),
            source_by_field=source_by_field,
            confidence_by_field={
                str(k): float(v)
                for k, v in (payment_raw.get("confidence_by_field") or {}).items()
                if isinstance(v, (int, float))
            },
        )

        status_raw = str(data.get("status") or TransferCaseStatus.OPEN.value)
        try:
            status = TransferCaseStatus(status_raw)
        except ValueError:
            status = TransferCaseStatus.OPEN

        return TransferCase(
            id=str(data.get("id") or "").strip(),
            internet_message_id=str(data.get("internet_message_id") or "").strip(),
            conversation_id=str(data.get("conversation_id") or "").strip(),
            received_at=str(data.get("received_at") or "").strip(),
            sender=str(data.get("sender") or "").strip(),
            subject=str(data.get("subject") or "").strip(),
            snippet=str(data.get("snippet") or "").strip(),
            body=str(data.get("body") or "").strip(),
            thread_text=str(data.get("thread_text") or "").strip(),
            summary=str(data.get("summary") or "").strip(),
            attachments=attachments,
            payment=payment,
            status=status,
            outlook_flag_status=str(data.get("outlook_flag_status") or "notFlagged").strip() or "notFlagged",
            outlook_completed_at=str(data.get("outlook_completed_at") or "").strip(),
            deferred_at=str(data.get("deferred_at") or "").strip(),
            defer_count=int(data.get("defer_count") or 0),
            done_at=str(data.get("done_at") or "").strip(),
            done_note=str(data.get("done_note") or "").strip(),
            qr_path=str(data.get("qr_path") or "").strip(),
        )

    def _load_cached_raw_messages(self) -> list[dict[str, Any]]:
        raw = self._get_value(_RAW_GRAPH_KEY)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def _cached_cases_as_raw_messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for case in self.load_open_cases():
            messages.append(
                {
                    "id": case.id,
                    "internetMessageId": case.internet_message_id,
                    "receivedDateTime": case.received_at,
                    "subject": case.subject,
                    "bodyPreview": case.snippet,
                    "body": {"content": case.body, "contentType": "text"},
                    "from": {"emailAddress": {"address": case.sender}},
                    "conversationId": case.conversation_id,
                    "flag": {"flagStatus": case.outlook_flag_status or "notFlagged"},
                    "attachments": [
                        {
                            "id": att.id,
                            "name": att.name,
                            "contentType": att.content_type,
                            "size": att.size,
                        }
                        for att in case.attachments
                    ],
                }
            )
        return messages

    def _save_raw_messages(self, messages: list[dict[str, Any]]) -> None:
        self._set_value(_RAW_GRAPH_KEY, json.dumps(messages, ensure_ascii=False))

    def _load_manual_fields(self) -> dict[str, dict[str, Any]]:
        raw = self._get_value(_MANUAL_FIELDS_KEY)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_manual_fields(self, mapping: dict[str, dict[str, Any]]) -> None:
        self._set_value(_MANUAL_FIELDS_KEY, json.dumps(mapping, ensure_ascii=False))

    def _apply_manual_fields(self, case: TransferCase, mapping: dict[str, dict[str, Any]]) -> None:
        values = mapping.get(case.id)
        if not isinstance(values, dict):
            return
        self._apply_manual_payment(case.payment, values)

    @staticmethod
    def _apply_manual_payment(payment: TransferPaymentData, values: dict[str, Any]) -> None:
        recipient = str(values.get("recipient") or "").strip()
        if recipient:
            payment.recipient = recipient
            payment.source_by_field["recipient"] = TransferFieldSource.MANUAL
        iban = str(values.get("iban") or "").strip()
        if iban:
            payment.iban = iban
            payment.source_by_field["iban"] = TransferFieldSource.MANUAL
        bic = str(values.get("bic") or "").strip()
        if bic:
            payment.bic = bic
            payment.source_by_field["bic"] = TransferFieldSource.MANUAL
        amount_raw = values.get("amount")
        if amount_raw not in (None, ""):
            try:
                payment.amount = Decimal(str(amount_raw))
                payment.source_by_field["amount"] = TransferFieldSource.MANUAL
            except Exception:  # noqa: BLE001
                pass
        remittance = str(values.get("remittance_text") or "").strip()
        if remittance:
            payment.remittance_text = remittance
            payment.source_by_field["remittance_text"] = TransferFieldSource.MANUAL
        invoice_number = str(values.get("invoice_number") or "").strip()
        if invoice_number:
            payment.invoice_number = invoice_number
            payment.source_by_field["invoice_number"] = TransferFieldSource.MANUAL
        note = str(values.get("note") or "").strip()
        if note:
            payment.note = note

    def _append_done_audit(self, case: TransferCase, payment: TransferPaymentData, *, qr_path: str) -> None:
        raw = self._get_value(_DONE_AUDIT_KEY)
        current: list[dict[str, Any]]
        if raw:
            try:
                parsed = json.loads(raw)
                current = parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                current = []
        else:
            current = []
        current.append(
            {
                "message_id": case.id,
                "done_at": datetime.now(timezone.utc).isoformat(),
                "outlook_flag_status": "complete",
                "subject": case.subject,
                "received_at": case.received_at,
                "payment_snapshot": payment_to_json_dict(payment),
                "qr_path": qr_path,
            }
        )
        self._set_value(_DONE_AUDIT_KEY, json.dumps(current[-300:], ensure_ascii=False))

    def _append_qr_history(self, case_id: str, qr_path: Path) -> None:
        raw = self._get_value(_QR_HISTORY_KEY)
        mapping: dict[str, list[str]]
        if raw:
            try:
                parsed = json.loads(raw)
                mapping = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                mapping = {}
        else:
            mapping = {}
        entries = mapping.get(case_id)
        if not isinstance(entries, list):
            entries = []
        entries.append(str(qr_path))
        mapping[case_id] = entries[-20:]
        self._set_value(_QR_HISTORY_KEY, json.dumps(mapping, ensure_ascii=False))

    def _replace_case_attachments(self, case_id: str, attachments: list[TransferAttachment]) -> None:
        cases = self._load_cached_cases()
        updated = False
        for case in cases:
            if case.id != case_id:
                continue
            case.attachments = list(attachments)
            updated = True
            break
        if updated:
            self._save_cases(cases)

    def _find_case(self, case_id: str) -> TransferCase | None:
        cid = str(case_id or "").strip()
        if not cid:
            return None
        for case in self._load_cached_cases():
            if case.id == cid:
                return case
        return None

    def _get_value(self, key: str) -> str | None:
        if self._repo is not None:
            return self._repo.get_value_json(key)
        state = self._read_local_state()
        value = state.get(key)
        return str(value) if isinstance(value, str) else None

    def _set_value(self, key: str, value: str) -> None:
        if self._repo is not None:
            self._repo.set_value_json(key, value)
            return
        state = self._read_local_state()
        state[key] = value
        self._write_local_state(state)

    def _read_local_state(self) -> dict[str, Any]:
        if not _LOCAL_STATE_PATH.exists():
            return {}
        try:
            content = _LOCAL_STATE_PATH.read_text(encoding="utf-8")
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _write_local_state(self, state: dict[str, Any]) -> None:
        _LOCAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOCAL_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _safe_filename(raw: str) -> str:
        value = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(raw or "").strip())
        value = value.strip("_")
        return value[:40] or "transfer"
