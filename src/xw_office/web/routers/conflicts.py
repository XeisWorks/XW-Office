"""Persistent Product Hub conflict wizard API."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status

from xw_office.repositories.product_hub_conflicts import ConflictOptimisticLockError
from xw_office.services.product_hub.conflicts.service import (
    ConflictWizardService,
    StaleConflictError,
    UnsupportedConflictAction,
)
from xw_office.services.product_hub.wix_snapshot import WixSnapshotService
from xw_office.web.schemas.conflicts import (
    ConflictActionOut,
    ConflictCaseDetailOut,
    ConflictCaseOut,
    ConflictDecisionRequest,
    ConflictFieldOut,
    ConflictPageOut,
    ConflictPreviewRequest,
    ConflictScanOut,
    ConflictSnoozeRequest,
    ConflictSummaryOut,
    WixSnapshotScanOut,
    ConflictObservationOut,
    VersionedRequest,
)


def build_conflicts_router(
    get_service: Callable[[], ConflictWizardService],
    get_wix_snapshot_service: Callable[[], WixSnapshotService],
    require_scan_enabled: Callable[[], None],
    require_edit_enabled: Callable[[], None],
    channel_apply_enabled: Callable[[], bool],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/conflicts", tags=["product-hub-conflicts"])

    @router.get("/summary", response_model=ConflictSummaryOut)
    def summary(service: ConflictWizardService = Depends(get_service)) -> dict[str, int]:
        return service.repository.summary()

    @router.get("", response_model=ConflictPageOut)
    def list_cases(
        status_filter: str | None = Query(None, alias="status"),
        severity: str | None = None,
        channel: str | None = None,
        conflict_type: str | None = None,
        product_id: uuid.UUID | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictPageOut:
        rows, total = service.repository.list_cases(
            status=status_filter,
            severity=severity,
            channel=channel,
            conflict_type=conflict_type,
            product_id=product_id,
            limit=limit,
            offset=offset,
        )
        return ConflictPageOut(
            items=[ConflictCaseOut.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get("/{case_id}", response_model=ConflictCaseDetailOut)
    def detail(
        case_id: uuid.UUID, service: ConflictWizardService = Depends(get_service)
    ) -> ConflictCaseDetailOut:
        try:
            bundle = service.detail(case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        case = ConflictCaseOut.model_validate(bundle["case"])
        fields: list[ConflictFieldOut] = []
        for item in bundle["fields"]:
            field = item["field"]
            field_out = ConflictFieldOut.model_validate(field)
            fields.append(
                ConflictFieldOut(
                    **field_out.model_dump(exclude={"observations"}),
                    observations=[
                        ConflictObservationOut.model_validate(observation)
                        for observation in item["observations"]
                    ],
                )
            )
        product = bundle["product"]
        return ConflictCaseDetailOut(
            **case.model_dump(),
            product_sku=product.sku,
            product_name=product.name,
            fields=fields,
            actions=[ConflictActionOut.model_validate(action) for action in bundle["actions"]],
        )

    @router.post(
        "/scan", response_model=ConflictScanOut, dependencies=[Depends(require_scan_enabled)]
    )
    def scan(
        product_id: uuid.UUID | None = None, service: ConflictWizardService = Depends(get_service)
    ) -> dict[str, object]:
        return service.scan_low_level_conflicts(product_id=product_id)

    @router.post(
        "/scan/wix", response_model=WixSnapshotScanOut, dependencies=[Depends(require_scan_enabled)]
    )
    def scan_wix(
        service: ConflictWizardService = Depends(get_service),
    ) -> dict[str, object]:
        """Fetch only mapped Wix products, then materialise their conflict cases."""
        source = get_wix_snapshot_service().run()
        scan_result = service.scan_low_level_conflicts()
        return {**scan_result, "source": source.as_dict()}

    @router.post(
        "/{case_id}/start",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def start(
        case_id: uuid.UUID,
        body: VersionedRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        return _transition(service, case_id, body.expected_row_version, "IN_PROGRESS")

    @router.post(
        "/{case_id}/decision",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def decision(
        case_id: uuid.UUID,
        body: ConflictDecisionRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        try:
            row = service.decide(
                case_id,
                expected_row_version=body.expected_row_version,
                resolution_type=body.resolution_type,
                selected_source=body.selected_source,
                custom_value=body.custom_value,
                note=body.note,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ConflictOptimisticLockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ConflictCaseOut.model_validate(row)

    @router.post(
        "/{case_id}/preview",
        response_model=list[ConflictActionOut],
        dependencies=[Depends(require_edit_enabled)],
    )
    def preview(
        case_id: uuid.UUID,
        body: ConflictPreviewRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> list[ConflictActionOut]:
        try:
            return [
                ConflictActionOut.model_validate(row)
                for row in service.preview(case_id, channels=body.channels)
            ]
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post(
        "/{case_id}/apply",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def apply(
        case_id: uuid.UUID,
        body: VersionedRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        try:
            row = service.apply(
                case_id,
                expected_row_version=body.expected_row_version,
                channel_apply_enabled=channel_apply_enabled(),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ConflictOptimisticLockError, StaleConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, UnsupportedConflictAction) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ConflictCaseOut.model_validate(row)

    @router.post(
        "/{case_id}/snooze",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def snooze(
        case_id: uuid.UUID,
        body: ConflictSnoozeRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        return _transition(
            service,
            case_id,
            body.expected_row_version,
            "WAITING",
            snoozed_until=body.until,
            resolution_note=body.note,
        )

    @router.post(
        "/{case_id}/ignore",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def ignore(
        case_id: uuid.UUID,
        body: VersionedRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        return _transition(
            service, case_id, body.expected_row_version, "IGNORED", resolution_type="IGNORE"
        )

    return router


def _transition(
    service: ConflictWizardService, case_id: uuid.UUID, version: int, target: str, **values: object
) -> ConflictCaseOut:
    try:
        row = service.repository.transition(
            case_id, expected_row_version=version, status=target, **values
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictOptimisticLockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ConflictCaseOut.model_validate(row)
