"""Durable per-invoice claims for actions that can create external side effects."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from datetime import datetime, timezone
import json
from threading import Lock
from typing import Literal, cast
import uuid

ClaimState = Literal["pending", "running", "succeeded", "unknown", "failed"]
_TERMINAL_BLOCKING_STATES = {"running", "succeeded", "unknown"}


@dataclass(frozen=True)
class OperationClaim:
    invoice_id: str
    operation: str
    operation_id: str
    state: ClaimState
    acquired: bool
    error: str = ""


class InvoiceOperationClaimStore:
    """Serialize one external action across processes through SettingKV mutation."""

    _PREFIX = "rechnungen.invoice_claim.v1:"

    def __init__(self, settings_repo: object | None) -> None:
        self._settings = settings_repo
        self._local_lock = Lock()
        self._local: dict[str, dict[str, str]] = {}

    @staticmethod
    def _key(invoice_id: str, operation: str) -> str:
        clean_invoice = str(invoice_id or "").strip()
        clean_operation = str(operation or "").strip()
        if not clean_invoice or not clean_operation:
            raise ValueError("invoice_id und operation sind erforderlich")
        key = f"rechnungen.invoice_claim.v1:{clean_invoice}:{clean_operation}"
        if len(key) > 256:
            raise ValueError("Claim-Schluessel ist zu lang")
        return key

    def acquire(self, invoice_id: str, operation: str) -> OperationClaim:
        key = self._key(invoice_id, operation)
        decision: dict[str, str | bool] = {}

        def mutate(raw: str | None) -> str:
            previous = self._decode(raw)
            state = previous.get("state", "")
            if state in _TERMINAL_BLOCKING_STATES:
                decision.update(
                    acquired=False,
                    operation_id=previous.get("operation_id", ""),
                    state=state,
                )
                return raw or "{}"
            operation_id = previous.get("operation_id") or str(uuid.uuid4())
            payload = {"operation_id": operation_id, "state": "running", "error": ""}
            if previous.get("reconciliation_history"):
                payload["reconciliation_history"] = previous["reconciliation_history"]
            decision.update(acquired=True, operation_id=operation_id, state="running")
            return json.dumps(payload, separators=(",", ":"))

        self._mutate(key, mutate)
        return OperationClaim(
            invoice_id=str(invoice_id),
            operation=str(operation),
            operation_id=str(decision.get("operation_id", "")),
            state=cast(ClaimState, str(decision.get("state", "unknown"))),
            acquired=bool(decision.get("acquired", False)),
        )

    def acquire_new_run(self, invoice_id: str, operation: str) -> OperationClaim:
        """Start a deliberate new run after success, while blocking concurrent/unclear runs.

        Physical production is repeatable by operator intent. A succeeded prior run
        therefore advances to a fresh operation ID; a running or unknown result stays
        blocked so a second workstation cannot duplicate an in-flight/uncertain print.
        """
        key = self._key(invoice_id, operation)
        decision: dict[str, str | bool] = {}

        def mutate(raw: str | None) -> str:
            previous = self._decode(raw)
            state = previous.get("state", "")
            if state in {"running", "unknown"}:
                decision.update(
                    acquired=False,
                    operation_id=previous.get("operation_id", ""),
                    state=state,
                )
                return raw or "{}"
            operation_id = (
                str(uuid.uuid4()) if state == "succeeded" else previous.get("operation_id", "")
            ) or str(uuid.uuid4())
            payload = {"operation_id": operation_id, "state": "running", "error": ""}
            if previous.get("reconciliation_history"):
                payload["reconciliation_history"] = previous["reconciliation_history"]
            decision.update(acquired=True, operation_id=operation_id, state="running")
            return json.dumps(payload, separators=(",", ":"))

        self._mutate(key, mutate)
        return OperationClaim(
            invoice_id=str(invoice_id),
            operation=str(operation),
            operation_id=str(decision.get("operation_id", "")),
            state=cast(ClaimState, str(decision.get("state", "unknown"))),
            acquired=bool(decision.get("acquired", False)),
        )

    def finish(
        self,
        claim: OperationClaim,
        state: Literal["succeeded", "unknown", "failed"],
        *,
        error: str = "",
    ) -> bool:
        if not claim.acquired:
            return False
        key = self._key(claim.invoice_id, claim.operation)
        updated = False

        def mutate(raw: str | None) -> str:
            nonlocal updated
            payload = self._decode(raw)
            if payload.get("operation_id") != claim.operation_id or payload.get("state") != "running":
                return raw or "{}"
            payload.update(state=state, error=str(error or "")[:1000])
            updated = True
            return json.dumps(payload, separators=(",", ":"))

        self._mutate(key, mutate)
        return updated

    def get(self, invoice_id: str, operation: str) -> OperationClaim | None:
        key = self._key(invoice_id, operation)
        raw = self._get_raw(key)
        if raw is None:
            return None
        payload = self._decode(raw)
        state = payload.get("state", "unknown")
        return OperationClaim(
            invoice_id=str(invoice_id),
            operation=str(operation),
            operation_id=payload.get("operation_id", ""),
            state=cast(ClaimState, state),
            acquired=False,
            error=payload.get("error", ""),
        )

    def list_unknown(self) -> list[OperationClaim]:
        """Return durable claims requiring an operator-confirmed readback."""
        return self._list_states({"unknown"})

    def list_open(self) -> list[OperationClaim]:
        """Return uncertain and possibly orphaned running claims for review.

        Running claims are never released automatically: a live process may still
        own the operation. Operators must verify that no workstation is executing
        it before using the manual reconciliation command.
        """
        return self._list_states({"running", "unknown"})

    def _list_states(self, states: set[str]) -> list[OperationClaim]:
        method = getattr(self._settings, "list_values_json_by_prefix", None)
        if callable(method):
            values = method(self._PREFIX)
        elif self._settings is not None:
            raise RuntimeError("SettingKV-Repository kann Claims nicht nach Praefix auflisten")
        else:
            with self._local_lock:
                values = {
                    key: json.dumps(value, separators=(",", ":"))
                    for key, value in self._local.items()
                    if key.startswith(self._PREFIX)
                }
        claims: list[OperationClaim] = []
        for key, raw in values.items():
            payload = self._decode(raw)
            state = payload.get("state", "unknown")
            if state not in states:
                continue
            identity = key[len(self._PREFIX) :]
            invoice_id, separator, operation = identity.rpartition(":")
            if not separator or not invoice_id or not operation:
                raise ValueError(f"Ungueltiger Claim-Schluessel: {key}")
            claims.append(
                OperationClaim(
                    invoice_id=invoice_id,
                    operation=operation,
                    operation_id=payload.get("operation_id", ""),
                    state=cast(ClaimState, state),
                    acquired=False,
                    error=payload.get("error", ""),
                )
            )
        return sorted(claims, key=lambda claim: (claim.invoice_id, claim.operation))

    def reconcile_open(
        self,
        invoice_id: str,
        operation: str,
        operation_id: str,
        state: Literal["succeeded", "failed"],
        *,
        reconciled_by: str,
        evidence: str,
        expected_state: Literal["running", "unknown"] = "unknown",
        no_active_processes_confirmed: bool = False,
    ) -> OperationClaim:
        """Record a human-verified outcome for exactly the current open run.

        Choosing ``failed`` explicitly permits a later retry. Operators must only
        choose it after verifying that the external side effect did not occur.
        A ``running`` claim additionally requires the operator to verify that no
        workstation is still executing the operation.
        """
        clean_operation_id = str(operation_id or "").strip()
        operator = str(reconciled_by or "").strip()
        proof = str(evidence or "").strip()
        if not clean_operation_id:
            raise ValueError("Operation-ID ist erforderlich")
        if state not in {"succeeded", "failed"}:
            raise ValueError("Reconciliation-Status muss succeeded oder failed sein")
        if expected_state not in {"running", "unknown"}:
            raise ValueError("Nur running- oder unknown-Claims koennen abgeglichen werden")
        if expected_state == "running" and not no_active_processes_confirmed:
            raise ValueError(
                "running-Claims erfordern die Bestaetigung, dass kein Prozess mehr aktiv ist"
            )
        if not operator:
            raise ValueError("Operator ist erforderlich")
        if len(proof) < 8:
            raise ValueError("Abgleichnachweis muss mindestens 8 Zeichen enthalten")
        key = self._key(invoice_id, operation)
        updated: dict[str, str] = {}

        def mutate(raw: str | None) -> str:
            payload = self._decode(raw)
            if payload.get("operation_id") != clean_operation_id:
                raise ValueError("Operation-ID stimmt nicht mit dem aktuellen Claim ueberein")
            if payload.get("state") != expected_state:
                raise ValueError(
                    f"Claim-Status ist nicht mehr {expected_state}; Abgleich abgebrochen"
                )
            history_raw = payload.get("reconciliation_history", "[]")
            try:
                history = json.loads(history_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("Claim-Reconciliation-Historie ist unlesbar") from exc
            if not isinstance(history, list):
                raise ValueError("Claim-Reconciliation-Historie hat ein ungueltiges Format")
            history.append(
                {
                    "state": state,
                    "reconciled_from": expected_state,
                    "reconciled_at": datetime.now(timezone.utc).isoformat(),
                    "reconciled_by": operator[:200],
                    "evidence": proof[:2000],
                }
            )
            payload.update(
                state=state,
                reconciled_by=operator[:200],
                reconciled_at=history[-1]["reconciled_at"],
                reconciliation_history=json.dumps(history, separators=(",", ":")),
            )
            updated.update(payload)
            return json.dumps(payload, separators=(",", ":"))

        self._mutate(key, mutate)
        return OperationClaim(
            invoice_id=str(invoice_id),
            operation=str(operation),
            operation_id=clean_operation_id,
            state=state,
            acquired=False,
            error=updated.get("error", ""),
        )

    def reconcile_unknown(
        self,
        invoice_id: str,
        operation: str,
        operation_id: str,
        state: Literal["succeeded", "failed"],
        *,
        reconciled_by: str,
        evidence: str,
    ) -> OperationClaim:
        """Compatibility wrapper for reconciling an ``unknown`` claim."""
        return self.reconcile_open(
            invoice_id,
            operation,
            operation_id,
            state,
            reconciled_by=reconciled_by,
            evidence=evidence,
            expected_state="unknown",
        )

    def _mutate(self, key: str, mutator: Callable[[str | None], str]) -> None:
        method = getattr(self._settings, "mutate_value_json", None)
        if callable(method):
            method(key, mutator)
            return
        with self._local_lock:
            current = self._local.get(key)
            raw = json.dumps(current, separators=(",", ":")) if current is not None else None
            self._local[key] = self._decode(mutator(raw))

    def _get_raw(self, key: str) -> str | None:
        method = getattr(self._settings, "get_value_json", None)
        if callable(method):
            return cast(str | None, method(key))
        with self._local_lock:
            payload = self._local.get(key)
            return None if payload is None else json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str | None) -> dict[str, str]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invoice-Claim ist unlesbar; externe Aktion bleibt gesperrt") from exc
        if not isinstance(payload, dict):
            raise ValueError("Invoice-Claim hat ein ungueltiges Format; Aktion bleibt gesperrt")
        return {str(key): str(value or "") for key, value in payload.items()}


__all__ = ["ClaimState", "OperationClaim", "InvoiceOperationClaimStore"]
