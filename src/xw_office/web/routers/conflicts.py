"""Persistent Product Hub conflict wizard API."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from html import escape
from html.parser import HTMLParser

from fastapi import APIRouter, Depends, HTTPException, Query, status

from xw_office.repositories.product_hub_conflicts import ConflictOptimisticLockError
from xw_office.services.product_hub.conflicts.advisor import (
    ConflictAdviceError,
    ConflictAdviceService,
    find_wix_mapping_candidates,
)
from xw_office.services.product_hub.conflicts.service import (
    ConflictWizardService,
    StaleConflictError,
    UnsupportedConflictAction,
)
from xw_office.services.product_hub.wix_snapshot import WixSnapshotService
from xw_office.services.wix.client import WixProductsClient
from xw_office.services.wix.product_details_client import WixProductDetailsClient
from xw_office.web.schemas.conflicts import (
    ConflictActionOut,
    ConflictAdviceOut,
    ConflictCaseDetailOut,
    ConflictCaseOut,
    ConflictCreateWixProductOut,
    ConflictDecisionRequest,
    ConflictFieldOut,
    ConflictMappingRequest,
    ConflictObservationOut,
    ConflictPageOut,
    ConflictPreviewRequest,
    ConflictScanOut,
    ConflictSnoozeRequest,
    ConflictSummaryOut,
    VersionedRequest,
    WixSnapshotScanOut,
)


def _compact_description(value: object, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class _WixDescriptionHTMLSanitizer(HTMLParser):
    """Keep a small, safe subset of Wix formatting for the conflict comparison."""

    _ALLOWED_TAGS = {"p", "strong", "b", "em", "i", "ul", "ol", "li", "br"}
    _VOID_TAGS = {"br"}
    _BLOCKED_TAGS = {"script", "style", "iframe", "object"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.open_tags: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag in self._BLOCKED_TAGS:
            self.blocked_depth += 1
            return
        if self.blocked_depth:
            return
        if tag not in self._ALLOWED_TAGS:
            return
        self.parts.append(f"<{tag}>")
        if tag not in self._VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self._BLOCKED_TAGS:
            return
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._BLOCKED_TAGS and self.blocked_depth:
            self.blocked_depth -= 1
            return
        if self.blocked_depth:
            return
        if tag not in self.open_tags:
            return
        while self.open_tags:
            closing_tag = self.open_tags.pop()
            self.parts.append(f"</{closing_tag}>")
            if closing_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.parts.append(escape(data))

    def rendered(self) -> str:
        while self.open_tags:
            self.parts.append(f"</{self.open_tags.pop()}>")
        return "".join(self.parts).strip()


def _sanitize_wix_description(value: object) -> str:
    parser = _WixDescriptionHTMLSanitizer()
    parser.feed(str(value or "")[:4000])
    parser.close()
    return parser.rendered()


def _wix_description(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    return _sanitize_wix_description(raw.get("description") or raw.get("plainDescription"))


def _wix_product_type(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    product_type = str(raw.get("productType") or "").strip().casefold()
    physical = (
        raw.get("physicalProperties") if isinstance(raw.get("physicalProperties"), dict) else {}
    )
    if product_type == "digital" or physical.get("shippable") is False or raw.get("digitalFile"):
        return "digital"
    return "physisch" if product_type or physical else ""


def build_conflicts_router(
    get_service: Callable[[], ConflictWizardService],
    get_wix_snapshot_service: Callable[[], WixSnapshotService],
    require_scan_enabled: Callable[[], None],
    require_edit_enabled: Callable[[], None],
    channel_apply_enabled: Callable[[], bool],
    get_advice_service: Callable[[], ConflictAdviceService],
    get_wix_catalog_client: Callable[[], WixProductsClient] | None = None,
    get_wix_details_client: Callable[[], WixProductDetailsClient] | None = None,
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

    @router.post("/{case_id}/advice", response_model=ConflictAdviceOut)
    def advice(
        case_id: uuid.UUID, service: ConflictWizardService = Depends(get_service)
    ) -> ConflictAdviceOut:
        """Generate a labelled, read-only draft explanation; never decide or apply."""
        try:
            bundle = service.detail(case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        case = bundle["case"]
        product = bundle["product"]
        snapshot = {
            "product": {"sku": product.sku, "name": product.name},
            "conflict": {
                "type": case.conflict_type,
                "severity": case.severity,
                "summary": case.summary,
            },
            "fields": [
                {
                    "field": item["field"].field_path,
                    "observations": [
                        {"source": row.source, "value": row.raw_value}
                        for row in item["observations"]
                    ],
                }
                for item in bundle["fields"]
            ],
        }
        mapping_search_status = "not_mapping"
        mapping_search_terms: list[str] = []
        mapping_candidates: list[dict[str, object]] = []
        mapping_comparison: dict[str, object] | None = None
        if case.conflict_type == "WRONG_PRODUCT_MAPPING":
            mapping_search_terms = [
                term for term in (product.sku, product.name) if str(term or "").strip()
            ]
            current_external_id = ""
            old_status = ""
            for field in snapshot["fields"]:
                if field["field"] != "mapping":
                    continue
                for observation in field["observations"]:
                    if observation["source"] == "hub" and isinstance(observation["value"], dict):
                        current_external_id = str(observation["value"].get("external_id") or "")
                    if observation["source"] == "wix" and isinstance(observation["value"], dict):
                        old_status = str(observation["value"].get("state") or "")
            if get_wix_catalog_client is None:
                mapping_search_status = "unavailable"
            else:
                try:
                    catalog_rows = get_wix_catalog_client().list_products(include_hidden=True)
                    candidates = find_wix_mapping_candidates(
                        catalog_rows,
                        product_name=product.name,
                        product_sku=product.sku,
                        current_external_id=current_external_id,
                    )
                    mapping_search_status = "found" if candidates else "none"
                    mapping_candidates = [candidate.as_dict() for candidate in candidates]
                    if mapping_candidates and get_wix_details_client is not None:
                        try:
                            raw = get_wix_details_client().get_product_raw(
                                str(mapping_candidates[0]["external_id"])
                            )
                            mapping_candidates[0]["description"] = _wix_description(raw)
                            mapping_candidates[0]["product_type"] = _wix_product_type(raw)
                        except Exception:  # noqa: BLE001 - candidate metadata is optional
                            mapping_candidates[0]["description"] = ""
                except Exception:  # noqa: BLE001 - advice remains useful if search fails
                    mapping_search_status = "unavailable"
                    # Keep provider details out of the beginner-facing search terms;
                    # the structured advice still receives the unavailable status.
            snapshot["mapping_lookup"] = {
                "status": mapping_search_status,
                "search_terms": mapping_search_terms[:2],
                "current_external_id": current_external_id,
                "candidates": mapping_candidates,
            }
            mapping_comparison = {
                "hub_name": product.name,
                "hub_sku": product.sku,
                "hub_description": _compact_description(product.description),
                "hub_product_type": product.product_type,
                "hub_category": product.category or "",
                "hub_status": product.status,
                "hub_active": product.active,
                "old_external_id": current_external_id,
                "old_status": old_status,
                "candidate": mapping_candidates[0] if mapping_candidates else None,
            }
        try:
            result = get_advice_service().advise(snapshot)
        except ConflictAdviceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ConflictAdviceOut(
            **result.__dict__,
            mapping_search_status=mapping_search_status,
            mapping_search_terms=mapping_search_terms[:2],
            mapping_candidates=mapping_candidates,
            mapping_comparison=mapping_comparison,
        )

    @router.post(
        "/{case_id}/mapping",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def remap(
        case_id: uuid.UUID,
        body: ConflictMappingRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        """Apply a user-selected, Wix-verified replacement mapping."""
        if get_wix_details_client is None:
            raise HTTPException(status_code=503, detail="Wix-Prüfung ist nicht konfiguriert")
        candidate = str(body.external_id).strip()
        try:
            raw = get_wix_details_client().get_product_raw(candidate)
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail=f"Wix-Kandidat konnte nicht geprüft werden: {exc}"
            ) from exc
        raw_id = str((raw or {}).get("id") or "").strip()
        if (
            not raw_id
            or raw_id.removeprefix("product_").casefold()
            != candidate.removeprefix("product_").casefold()
        ):
            raise HTTPException(
                status_code=400,
                detail="Diese Wix-ID wurde nicht als erreichbares Produkt bestätigt.",
            )
        try:
            row = service.remap_wix_mapping(
                case_id,
                expected_row_version=body.expected_row_version,
                external_id=candidate,
                note=body.note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictOptimisticLockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ConflictCaseOut.model_validate(row)

    @router.post(
        "/{case_id}/create-wix-product",
        response_model=ConflictCreateWixProductOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def create_wix_product(
        case_id: uuid.UUID,
        body: VersionedRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCreateWixProductOut:
        """Create a hidden Wix draft from the Hub product, then map it here."""
        if get_wix_details_client is None or get_wix_catalog_client is None:
            raise HTTPException(status_code=503, detail="Wix-Anbindung ist nicht konfiguriert")
        created_external_id: str | None = None
        operation = "created_and_mapped"
        try:
            bundle = service.detail(case_id)
            case = bundle["case"]
            if case.conflict_type != "WRONG_PRODUCT_MAPPING":
                raise ValueError("Nur Wix-Mapping-Konflikte koennen ein Wix-Produkt anlegen")
            if case.row_version != body.expected_row_version:
                raise ConflictOptimisticLockError("Der Konflikt wurde zwischenzeitlich geaendert")
            product = bundle["product"]
            normalized_sku = product.sku.strip().casefold()
            existing = [
                row
                for row in get_wix_catalog_client().list_products(include_hidden=True)
                if normalized_sku in {sku.strip().casefold() for sku in row.all_skus} and row.id.strip()
            ]
            if len(existing) > 1:
                raise ValueError(
                    f"Wix enthält mehrere Produkte mit der SKU {product.sku}; bitte zuerst in Wix bereinigen."
                )
            catalog_version = get_wix_details_client().detect_catalog_version()
            if existing:
                external_id = existing[0].id.strip()
                operation = "reused_existing"
            else:
                price = service.wix_creation_price(product.id)
                if price is None:
                    raise ValueError("Dem Hub-Produkt fehlt ein aktueller Verkaufspreis in EUR")
                external_id, catalog_version = get_wix_details_client().create_product(
                    name=product.name,
                    sku=product.sku,
                    product_type=product.product_type,
                    price=price,
                )
                created_external_id = external_id
            row = service.map_new_wix_product(
                case_id, expected_row_version=body.expected_row_version, external_id=external_id
            )
        except KeyError as exc:
            if created_external_id:
                raise HTTPException(
                    status_code=502,
                    detail=f"Wix-Produkt {created_external_id} wurde erstellt, aber die Hub-Verknüpfung ist fehlgeschlagen: {exc}",
                ) from exc
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictOptimisticLockError as exc:
            if created_external_id:
                raise HTTPException(
                    status_code=502,
                    detail=f"Wix-Produkt {created_external_id} wurde erstellt, aber der Konflikt war inzwischen veraltet; die Hub-Verknüpfung wurde nicht gespeichert.",
                ) from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HTTPException:
            raise
        except ValueError as exc:
            if created_external_id:
                raise HTTPException(
                    status_code=502,
                    detail=f"Wix-Produkt {created_external_id} wurde erstellt, aber die Hub-Verknüpfung ist fehlgeschlagen: {exc}",
                ) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - translate provider failures into API detail
            detail = str(exc)
            if created_external_id:
                detail = f"Wix-Produkt {created_external_id} wurde erstellt, aber die Hub-Verknüpfung ist fehlgeschlagen: {detail}"
            raise HTTPException(status_code=502, detail=detail) from exc
        return ConflictCreateWixProductOut(
            **ConflictCaseOut.model_validate(row).model_dump(),
            external_id=external_id,
            catalog_version=catalog_version.value,
            operation=operation,
        )

    @router.post(
        "/{case_id}/archive-hub-product",
        response_model=ConflictCaseOut,
        dependencies=[Depends(require_edit_enabled)],
    )
    def archive_hub_product(
        case_id: uuid.UUID,
        body: VersionedRequest,
        service: ConflictWizardService = Depends(get_service),
    ) -> ConflictCaseOut:
        try:
            row = service.archive_hub_product(
                case_id, expected_row_version=body.expected_row_version
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictOptimisticLockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ConflictCaseOut.model_validate(row)

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
        force: bool = Query(
            False, description="Fetch every mapped product detail, bypassing the catalog index"
        ),
        service: ConflictWizardService = Depends(get_service),
    ) -> dict[str, object]:
        """Incrementally refresh mapped Wix products, then materialise conflict cases."""
        source = get_wix_snapshot_service().run(force=force)
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
