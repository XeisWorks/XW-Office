"""Persistence for the durable conflict wizard workflow."""

from __future__ import annotations

from contextlib import contextmanager
import datetime
import hashlib
import json
import uuid
from collections.abc import Generator, Sequence
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub_conflicts import (
    ConflictAction,
    ConflictCase,
    ConflictField,
    ConflictObservation,
    ConflictScan,
)

ACTIVE_STATUSES = ("OPEN", "IN_PROGRESS", "WAITING", "PARTIALLY_RESOLVED")


class ConflictOptimisticLockError(RuntimeError):
    pass


class ConflictRepository:
    def __init__(self, session_or_factory: Session | sessionmaker[Session]) -> None:
        self._session_or_factory = session_or_factory

    @contextmanager
    def _scope(self) -> Generator[Session, None, None]:
        if isinstance(self._session_or_factory, Session):
            yield self._session_or_factory
        else:
            with session_scope(self._session_or_factory) as session:
                yield session

    def start_scan(
        self, *, scan_type: str, source_scope: Sequence[str], product_scope: dict[str, object]
    ) -> ConflictScan:
        with self._scope() as session:
            row = ConflictScan(
                id=uuid.uuid4(),
                scan_type=scan_type,
                source_scope=list(source_scope),
                product_scope=product_scope,
                started_at=_now(),
            )
            session.add(row)
            session.flush()
            return row

    def finish_scan(self, scan_id: uuid.UUID, **counts: int) -> ConflictScan:
        with self._scope() as session:
            row = session.get(ConflictScan, scan_id)
            if row is None:
                raise KeyError(f"Conflict scan {scan_id} not found")
            for key, value in counts.items():
                setattr(row, key, value)
            row.finished_at = _now()
            session.flush()
            return row

    def get_case(self, case_id: uuid.UUID) -> ConflictCase | None:
        with self._scope() as session:
            return session.get(ConflictCase, case_id)

    def get_active_case(self, dedupe_key: str) -> ConflictCase | None:
        with self._scope() as session:
            return session.scalar(
                select(ConflictCase)
                .where(
                    ConflictCase.dedupe_key == dedupe_key, ConflictCase.status.in_(ACTIVE_STATUSES)
                )
                .order_by(ConflictCase.occurrence.desc())
            )

    def latest_case(self, dedupe_key: str) -> ConflictCase | None:
        with self._scope() as session:
            return session.scalar(
                select(ConflictCase)
                .where(ConflictCase.dedupe_key == dedupe_key)
                .order_by(ConflictCase.occurrence.desc())
            )

    def create_case(self, **values: Any) -> ConflictCase:
        with self._scope() as session:
            latest = session.scalar(
                select(ConflictCase)
                .where(ConflictCase.dedupe_key == values["dedupe_key"])
                .order_by(ConflictCase.occurrence.desc())
            )
            row = ConflictCase(
                id=uuid.uuid4(),
                occurrence=(latest.occurrence + 1 if latest else 1),
                reopened_from_case_id=(latest.id if latest else None),
                **values,
            )
            session.add(row)
            session.flush()
            return row

    def touch_case(
        self,
        case_id: uuid.UUID,
        *,
        scan_id: uuid.UUID,
        severity: str,
        priority_score: int,
        hub_row_version: int,
        summary: str | None = None,
    ) -> ConflictCase:
        with self._scope() as session:
            row = _required(session, ConflictCase, case_id)
            row.last_seen_at = _now()
            row.source_scan_id = scan_id
            row.severity = severity
            row.priority_score = priority_score
            row.hub_row_version = hub_row_version
            if summary:
                row.summary = summary
            row.row_version += 1
            session.flush()
            return row

    def get_or_create_field(self, case_id: uuid.UUID, field_path: str) -> ConflictField:
        with self._scope() as session:
            row = session.scalar(
                select(ConflictField).where(
                    ConflictField.conflict_case_id == case_id,
                    ConflictField.field_path == field_path,
                )
            )
            if row is None:
                row = ConflictField(
                    id=uuid.uuid4(), conflict_case_id=case_id, field_path=field_path
                )
                session.add(row)
                session.flush()
            return row

    def add_observation(
        self,
        field_id: uuid.UUID,
        *,
        source: str,
        raw_value: object,
        normalized_value: object,
        source_external_id: str | None = None,
        source_revision: str | None = None,
    ) -> ConflictObservation:
        digest = hashlib.sha256(
            json.dumps(raw_value, sort_keys=True, default=str, ensure_ascii=False).encode()
        ).hexdigest()
        with self._scope() as session:
            existing = session.scalar(
                select(ConflictObservation).where(
                    ConflictObservation.conflict_field_id == field_id,
                    ConflictObservation.source == source,
                    ConflictObservation.source_hash == digest,
                )
            )
            if existing is not None:
                return existing
            row = ConflictObservation(
                id=uuid.uuid4(),
                conflict_field_id=field_id,
                source=source,
                raw_value=raw_value,
                normalized_value=normalized_value,
                source_external_id=source_external_id,
                source_revision=source_revision,
                source_hash=digest,
                observed_at=_now(),
            )
            session.add(row)
            session.flush()
            return row

    def list_cases(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        channel: str | None = None,
        conflict_type: str | None = None,
        product_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ConflictCase], int]:
        with self._scope() as session:
            stmt = select(ConflictCase)
            if status:
                stmt = stmt.where(ConflictCase.status == status)
            else:
                stmt = stmt.where(ConflictCase.status.in_(ACTIVE_STATUSES))
            if severity:
                stmt = stmt.where(ConflictCase.severity == severity)
            if conflict_type:
                stmt = stmt.where(ConflictCase.conflict_type == conflict_type)
            if product_id:
                stmt = stmt.where(ConflictCase.product_id == product_id)
            if channel:
                stmt = (
                    stmt.join(ConflictField, ConflictField.conflict_case_id == ConflictCase.id)
                    .join(
                        ConflictObservation,
                        ConflictObservation.conflict_field_id == ConflictField.id,
                    )
                    .where(ConflictObservation.source == channel)
                    .distinct()
                )
            total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            rows = list(
                session.scalars(
                    stmt.order_by(ConflictCase.priority_score.desc(), ConflictCase.detected_at)
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
            return rows, total

    def fields(self, case_id: uuid.UUID) -> list[ConflictField]:
        with self._scope() as session:
            return list(
                session.scalars(
                    select(ConflictField)
                    .where(ConflictField.conflict_case_id == case_id)
                    .order_by(ConflictField.created_at)
                ).all()
            )

    def observations(self, field_id: uuid.UUID) -> list[ConflictObservation]:
        with self._scope() as session:
            return list(
                session.scalars(
                    select(ConflictObservation)
                    .where(ConflictObservation.conflict_field_id == field_id)
                    .order_by(ConflictObservation.observed_at)
                ).all()
            )

    def actions(self, case_id: uuid.UUID) -> list[ConflictAction]:
        with self._scope() as session:
            return list(
                session.scalars(
                    select(ConflictAction)
                    .where(ConflictAction.conflict_case_id == case_id)
                    .order_by(ConflictAction.created_at)
                ).all()
            )

    def transition(
        self, case_id: uuid.UUID, *, expected_row_version: int, status: str, **values: Any
    ) -> ConflictCase:
        with self._scope() as session:
            row = _required(session, ConflictCase, case_id)
            if row.row_version != expected_row_version:
                raise ConflictOptimisticLockError(
                    f"Expected case row_version {expected_row_version}, found {row.row_version}"
                )
            row.status = status
            for key, value in values.items():
                setattr(row, key, value)
            if status == "IN_PROGRESS" and row.started_at is None:
                row.started_at = _now()
            if status in {"RESOLVED", "IGNORED", "OBSOLETE"}:
                row.resolved_at = _now()
            row.row_version += 1
            session.flush()
            return row

    def save_decision(
        self,
        case_id: uuid.UUID,
        *,
        expected_row_version: int,
        resolution_type: str,
        selected_source: str | None,
        selected_value: object,
        note: str | None,
    ) -> ConflictCase:
        with self._scope() as session:
            case = _required(session, ConflictCase, case_id)
            if case.row_version != expected_row_version:
                raise ConflictOptimisticLockError(
                    f"Expected case row_version {expected_row_version}, found {case.row_version}"
                )
            fields = list(
                session.scalars(
                    select(ConflictField).where(ConflictField.conflict_case_id == case_id)
                ).all()
            )
            for field in fields:
                field.selected_source = selected_source
                field.selected_value = selected_value
                field.resolution_type = resolution_type
                field.status = "DECIDED"
            case.resolution_type = resolution_type
            case.resolution_note = note
            case.status = "IN_PROGRESS"
            case.row_version += 1
            session.flush()
            return case

    def replace_plan(
        self, case_id: uuid.UUID, actions: Sequence[dict[str, Any]]
    ) -> list[ConflictAction]:
        with self._scope() as session:
            old = list(
                session.scalars(
                    select(ConflictAction).where(
                        ConflictAction.conflict_case_id == case_id,
                        ConflictAction.status == "PLANNED",
                    )
                ).all()
            )
            for row in old:
                session.delete(row)
            result = [
                ConflictAction(id=uuid.uuid4(), conflict_case_id=case_id, **data)
                for data in actions
            ]
            session.add_all(result)
            session.flush()
            return result

    def summary(self) -> dict[str, int]:
        with self._scope() as session:
            rows = session.execute(
                select(ConflictCase.status, ConflictCase.severity, func.count()).group_by(
                    ConflictCase.status, ConflictCase.severity
                )
            ).all()
        result = {"open": 0, "critical": 0, "waiting": 0, "partially_resolved": 0, "resolved": 0}
        for status, severity, count in rows:
            if status in ACTIVE_STATUSES:
                result["open"] += count
            if status in ACTIVE_STATUSES and severity == "CRITICAL":
                result["critical"] += count
            if status == "WAITING":
                result["waiting"] += count
            if status == "PARTIALLY_RESOLVED":
                result["partially_resolved"] += count
            if status == "RESOLVED":
                result["resolved"] += count
        return result

    def obsolete_unseen(self, *, scan_id: uuid.UUID, source_sync_ids: set[uuid.UUID]) -> int:
        with self._scope() as session:
            rows = list(
                session.scalars(
                    select(ConflictCase).where(
                        ConflictCase.status.in_(ACTIVE_STATUSES),
                        ConflictCase.origin_sync_conflict_id.is_not(None),
                    )
                ).all()
            )
            changed = 0
            for row in rows:
                if row.origin_sync_conflict_id not in source_sync_ids:
                    row.status = "OBSOLETE"
                    row.resolution_type = "OBSOLETE"
                    row.resolved_at = _now()
                    row.row_version += 1
                    changed += 1
            session.flush()
            return changed


T = TypeVar("T")


def _required(session: Session, model: type[T], row_id: uuid.UUID) -> T:
    row = session.get(model, row_id)
    if row is None:
        raise KeyError(f"{model.__name__} {row_id} not found")
    return row


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)
