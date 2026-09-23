"""Safe, resumable product onboarding from the Product Hub into sales channels.

The Hub is the write authority.  A product is committed there first as a draft and
then created as a hidden Wix product and as a sevDesk Part.  Provider calls cannot
share the database transaction, so every channel step is idempotent by SKU and a
partially completed onboarding can be resumed with the returned product id.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.repositories.product_hub import ProductHubRepository, normalize_sku
from xw_office.services.sevdesk.part_client import PartClient
from xw_office.services.wix.client import WixProductsClient
from xw_office.services.wix.product_details_client import WixProductDetailsClient


class _WixProduct(Protocol):
    id: str
    all_skus: tuple[str, ...]


@dataclass(frozen=True)
class ChannelOnboardingResult:
    channel: str
    state: str
    external_id: str = ""
    message: str = ""


@dataclass(frozen=True)
class ProductOnboardingResult:
    product_id: uuid.UUID
    variant_id: uuid.UUID
    sku: str
    hub_state: str
    channels: tuple[ChannelOnboardingResult, ...]

    @property
    def complete(self) -> bool:
        return all(item.state in {"created", "reused", "synced"} for item in self.channels)


@dataclass(frozen=True)
class VariantOnboardingResult:
    product_id: uuid.UUID
    variant_id: uuid.UUID
    sku: str
    hub_state: str
    channels: tuple[ChannelOnboardingResult, ...]

    @property
    def complete(self) -> bool:
        return all(item.state in {"created", "reused", "synced"} for item in self.channels)


class ProductOnboardingService:
    """Create the minimum viable product record in Hub, sevDesk and Wix."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        sevdesk_parts: PartClient,
        wix_catalog: WixProductsClient,
        wix_details: WixProductDetailsClient,
        sevdesk_configured: bool,
    ) -> None:
        self._session_factory = session_factory
        self._sevdesk = sevdesk_parts
        self._wix_catalog = wix_catalog
        self._wix_details = wix_details
        self._sevdesk_configured = sevdesk_configured

    def list_sevdesk_categories(self) -> list[dict[str, str]]:
        if not self._sevdesk_configured:
            raise RuntimeError("sevDesk-Zugangsdaten fehlen.")
        categories = self._sevdesk.list_part_categories()
        if not categories:
            raise RuntimeError(
                "Keine sevDesk-Produktkategorien gefunden oder sevDesk ist nicht erreichbar."
            )
        return categories

    def onboard(
        self,
        *,
        sku: str,
        name: str,
        product_type: str,
        price_gross: Decimal,
        tax_rate: Decimal,
        sevdesk_category_id: str,
        sevdesk_category_name: str = "",
        brand_name: str = "",
        category: str = "",
        weight_grams: Decimal | None = None,
        resume_product_id: uuid.UUID | None = None,
    ) -> ProductOnboardingResult:
        clean_sku = normalize_sku(sku)
        clean_name = str(name or "").strip()
        clean_type = str(product_type or "").strip().casefold()
        if not clean_sku or not clean_name:
            raise ValueError("SKU und Produktname sind erforderlich.")
        if clean_type not in {"physical", "digital"}:
            raise ValueError("Produkttyp muss 'physical' oder 'digital' sein.")
        if price_gross < 0:
            raise ValueError("Der Verkaufspreis darf nicht negativ sein.")
        if tax_rate < 0 or tax_rate > 100:
            raise ValueError("Der Steuersatz muss zwischen 0 und 100 liegen.")
        if not str(sevdesk_category_id or "").strip():
            raise ValueError("Eine sevDesk-Produktkategorie ist erforderlich.")

        product, variant, hub_state = self._ensure_hub_product(
            sku=clean_sku,
            name=clean_name,
            product_type=clean_type,
            price_gross=price_gross,
            tax_rate=tax_rate,
            brand_name=brand_name,
            category=category,
            weight_grams=weight_grams,
            resume_product_id=resume_product_id,
        )

        channel_results = (
            self._ensure_sevdesk(
                product_id=product.id,
                variant_id=variant.id,
                sku=clean_sku,
                name=clean_name,
                product_type=clean_type,
                price_gross=price_gross,
                tax_rate=tax_rate,
                category_id=sevdesk_category_id,
                category_name=sevdesk_category_name,
            ),
            self._ensure_wix(
                product_id=product.id,
                sku=clean_sku,
                name=clean_name,
                product_type=clean_type,
                price_gross=price_gross,
            ),
        )
        return ProductOnboardingResult(
            product_id=product.id,
            variant_id=variant.id,
            sku=clean_sku,
            hub_state=hub_state,
            channels=channel_results,
        )

    def onboard_variant(
        self,
        *,
        product_id: uuid.UUID,
        sku: str,
        name: str,
        option_name: str,
        option_value: str,
        existing_default_option_value: str,
        price_gross: Decimal,
        tax_rate: Decimal,
        sevdesk_category_id: str,
        sevdesk_category_name: str = "",
        weight_grams: Decimal | None = None,
        resume_variant_id: uuid.UUID | None = None,
    ) -> VariantOnboardingResult:
        clean_sku = normalize_sku(sku)
        required_values = (
            clean_sku,
            str(name).strip(),
            str(option_name).strip(),
            str(option_value).strip(),
        )
        if not all(required_values):
            raise ValueError("SKU, Variantenname, Option und Auswahl sind erforderlich.")
        if not str(existing_default_option_value).strip():
            raise ValueError("Die Bezeichnung der bestehenden Variante ist erforderlich.")
        if price_gross < 0 or tax_rate < 0 or tax_rate > 100:
            raise ValueError("Preis oder Steuersatz ist ungültig.")
        if not str(sevdesk_category_id or "").strip():
            raise ValueError("Eine sevDesk-Produktkategorie ist erforderlich.")
        product, variant, hub_state = self._ensure_hub_variant(
            product_id=product_id, sku=clean_sku, name=name,
            option_name=option_name, option_value=option_value,
            existing_default_option_value=existing_default_option_value,
            price_gross=price_gross, tax_rate=tax_rate,
            weight_grams=weight_grams, resume_variant_id=resume_variant_id,
        )
        sevdesk = self._ensure_sevdesk(
            product_id=product.id, variant_id=variant.id, sku=clean_sku,
            name=f"{product.name} – {name}", product_type=product.product_type,
            price_gross=price_gross, tax_rate=tax_rate,
            category_id=sevdesk_category_id, category_name=sevdesk_category_name,
        )
        wix = self._ensure_wix_variant(
            product_id=product.id, variant_id=variant.id, sku=clean_sku,
            option_name=option_name, option_value=option_value,
            existing_default_option_value=existing_default_option_value,
            price_gross=price_gross, weight_grams=weight_grams,
        )
        return VariantOnboardingResult(
            product_id=product.id, variant_id=variant.id, sku=clean_sku,
            hub_state=hub_state, channels=(sevdesk, wix),
        )

    def _ensure_hub_variant(self, **values: object):
        product_id = values["product_id"]
        resume_variant_id = values.get("resume_variant_id")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            product = repo.get_product(product_id)  # type: ignore[arg-type]
            if product is None:
                raise ValueError("Das Hauptprodukt wurde nicht gefunden.")
            if resume_variant_id:
                variant = repo.get_variant(resume_variant_id)  # type: ignore[arg-type]
                resume_matches = (
                    variant is not None
                    and variant.product_id == product.id
                    and variant.sku == values["sku"]
                )
                if not resume_matches:
                    raise ValueError("Variante und Wiederaufnahme-ID passen nicht zusammen.")
                assert variant is not None
                return product, variant, "reused"
            default_variant = repo.get_default_variant(product.id)
            if default_variant is not None and not default_variant.option_values:
                default_variant.option_values = {
                    str(values["option_name"]): str(values["existing_default_option_value"])
                }
                default_variant.row_version += 1
            variant = repo.create_variant(
                product_id=product.id, sku=str(values["sku"]), name=str(values["name"]),
                option_values={str(values["option_name"]): str(values["option_value"])},
                stock_enabled=product.product_type != "digital",
                weight_grams=values.get("weight_grams"),  # type: ignore[arg-type]
            )
            price_list = repo.get_price_list_by_code("RETAIL_EUR")
            if price_list is None:
                raise RuntimeError("Preisliste RETAIL_EUR fehlt im Product Hub.")
            gross = values["price_gross"]  # type: ignore[assignment]
            tax = values["tax_rate"]  # type: ignore[assignment]
            net = (gross / (Decimal(1) + tax / Decimal(100))).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            repo.set_price(variant.id, price_list_id=price_list.id, currency="EUR",
                           net_amount=net, gross_amount=gross, tax_rate=tax,
                           source="variant_onboarding_wizard")
            repo.record_audit(actor_type="user", actor_id="variant-onboarding-wizard",
                              source="product_hub_web", entity_type="product_variant",
                              entity_id=variant.id, action="create",
                              changed_fields=["sku", "name", "option_values", "price"])
            return product, variant, "created"

    def _ensure_wix_variant(self, *, product_id: uuid.UUID, variant_id: uuid.UUID, sku: str,
                            option_name: str, option_value: str,
                            existing_default_option_value: str, price_gross: Decimal,
                            weight_grams: Decimal | None) -> ChannelOnboardingResult:
        mapping = self._existing_mapping(
            channel="wix", entity_type="variant", internal_id=variant_id
        )
        if mapping is not None:
            return ChannelOnboardingResult("wix", "synced", mapping.external_id)
        parent_mapping = self._existing_mapping(
            channel="wix", entity_type="product", internal_id=product_id
        )
        if parent_mapping is None:
            return ChannelOnboardingResult(
                "wix", "error", message="Das Hauptprodukt ist nicht mit Wix verknüpft."
            )
        try:
            external_id, _version, operation = self._wix_details.ensure_product_variant(
                parent_mapping.external_id, option_name=option_name, option_value=option_value,
                existing_default_option_value=existing_default_option_value, sku=sku,
                price=str(price_gross),
                weight_grams=float(weight_grams) if weight_grams is not None else None,
            )
            if not external_id:
                raise RuntimeError("Wix hat die Variante ohne Varianten-ID zurückgegeben.")
            ProductHubRepository(self._session_factory).create_channel_mapping(
                channel="wix", entity_type="variant", internal_entity_id=variant_id,
                external_id=external_id, external_parent_id=parent_mapping.external_id,
                sync_status="synced",
            )
            return ChannelOnboardingResult("wix", operation, external_id)
        except Exception as exc:  # noqa: BLE001 - provider boundary; resumable Hub variant
            return ChannelOnboardingResult("wix", "error", message=str(exc))

    def _ensure_hub_product(
        self,
        *,
        sku: str,
        name: str,
        product_type: str,
        price_gross: Decimal,
        tax_rate: Decimal,
        brand_name: str,
        category: str,
        weight_grams: Decimal | None,
        resume_product_id: uuid.UUID | None,
    ):
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            existing = repo.get_product_by_sku(sku)
            if resume_product_id is not None:
                product = repo.get_product(resume_product_id)
                if product is None:
                    raise ValueError("Das fortzusetzende Hub-Produkt wurde nicht gefunden.")
                if existing is None or existing.id != product.id or product.sku != sku:
                    raise ValueError("SKU und fortzusetzendes Hub-Produkt passen nicht zusammen.")
                variant = repo.get_default_variant(product.id)
                if variant is None:
                    raise ValueError("Das Hub-Produkt hat keine Standardvariante.")
                return product, variant, "reused"
            if existing is not None:
                raise ValueError(
                    f"SKU {sku} existiert bereits im Product Hub. "
                    "Bitte das bestehende Produkt öffnen."
                )

            product, variant = repo.create_product(
                sku=sku,
                name=name,
                status="draft",
                product_type=product_type,
                brand_name=brand_name,
                category=category,
                stock_enabled=product_type != "digital",
            )
            if weight_grams is not None:
                variant.weight_grams = weight_grams
            price_list = repo.get_price_list_by_code("RETAIL_EUR")
            if price_list is None:
                raise RuntimeError("Preisliste RETAIL_EUR fehlt im Product Hub.")
            divisor = Decimal(1) + tax_rate / Decimal(100)
            net = (price_gross / divisor).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            repo.set_price(
                variant.id,
                price_list_id=price_list.id,
                currency="EUR",
                net_amount=net,
                gross_amount=price_gross,
                tax_rate=tax_rate,
                source="onboarding_wizard",
            )
            repo.record_audit(
                actor_type="user",
                actor_id="product-onboarding-wizard",
                source="product_hub_web",
                entity_type="product",
                entity_id=product.id,
                action="create",
                changed_fields=["sku", "name", "product_type", "price"],
                after_data={"sku": sku, "name": name, "product_type": product_type},
            )
            return product, variant, "created"

    def _existing_mapping(self, *, channel: str, entity_type: str, internal_id: uuid.UUID):
        repo = ProductHubRepository(self._session_factory)
        return next(
            (
                row
                for row in repo.list_channel_mappings(
                    entity_type=entity_type, internal_entity_id=internal_id
                )
                if row.channel == channel
            ),
            None,
        )

    def _ensure_sevdesk(
        self,
        *,
        product_id: uuid.UUID,
        variant_id: uuid.UUID,
        sku: str,
        name: str,
        product_type: str,
        price_gross: Decimal,
        tax_rate: Decimal,
        category_id: str,
        category_name: str,
    ) -> ChannelOnboardingResult:
        mapping = self._existing_mapping(
            channel="sevdesk", entity_type="variant", internal_id=variant_id
        )
        if mapping is not None:
            return ChannelOnboardingResult("sevdesk", "synced", mapping.external_id)
        if not self._sevdesk_configured:
            return ChannelOnboardingResult(
                "sevdesk", "error", message="sevDesk-Zugangsdaten fehlen."
            )
        try:
            part = self._sevdesk.find_part_by_sku(sku, strict=True)
            state = "reused"
            if part is None:
                payload: dict[str, object] = {
                    "name": name,
                    "partNumber": sku,
                    "text": f"[{category_name}]" if category_name else "",
                    "internalComment": "Angelegt im XW Product Hub",
                    "priceGross": float(price_gross),
                    "taxRate": float(tax_rate),
                    "unity": {"id": 1, "objectName": "Unity"},
                    "category": {"id": category_id, "objectName": "Category"},
                    "stockEnabled": product_type != "digital",
                    "stock": 0,
                    "status": 100,
                }
                part = self._sevdesk.create_part(payload)
                state = "created"
            ProductHubRepository(self._session_factory).assign_sevdesk_part_to_variant(
                product_id=product_id, variant_id=variant_id, part_id=part.id
            )
            return ChannelOnboardingResult("sevdesk", state, part.id)
        except Exception as exc:  # noqa: BLE001 - provider boundary; Hub draft remains resumable
            return ChannelOnboardingResult("sevdesk", "error", message=str(exc))

    def _ensure_wix(
        self,
        *,
        product_id: uuid.UUID,
        sku: str,
        name: str,
        product_type: str,
        price_gross: Decimal,
    ) -> ChannelOnboardingResult:
        mapping = self._existing_mapping(
            channel="wix", entity_type="product", internal_id=product_id
        )
        if mapping is not None:
            return ChannelOnboardingResult("wix", "synced", mapping.external_id)
        if not self._wix_details.has_credentials():
            return ChannelOnboardingResult("wix", "error", message="Wix-Zugangsdaten fehlen.")
        try:
            matches: list[_WixProduct] = [
                row
                for row in self._wix_catalog.list_products(include_hidden=True, strict=True)
                if sku.casefold() in {value.strip().casefold() for value in row.all_skus}
                and row.id.strip()
            ]
            if len(matches) > 1:
                raise ValueError(f"Wix enthält mehrere Produkte mit der SKU {sku}.")
            state = "reused"
            if matches:
                external_id = matches[0].id.strip()
            else:
                external_id, _version = self._wix_details.create_product(
                    name=name,
                    sku=sku,
                    product_type=product_type,
                    price=str(price_gross),
                )
                state = "created"
            ProductHubRepository(self._session_factory).create_channel_mapping(
                channel="wix",
                entity_type="product",
                internal_entity_id=product_id,
                external_id=external_id,
                sync_status="synced",
            )
            return ChannelOnboardingResult("wix", state, external_id)
        except Exception as exc:  # noqa: BLE001 - provider boundary; Hub draft remains resumable
            return ChannelOnboardingResult("wix", "error", message=str(exc))


__all__ = [
    "ChannelOnboardingResult",
    "ProductOnboardingResult",
    "VariantOnboardingResult",
    "ProductOnboardingService",
]
