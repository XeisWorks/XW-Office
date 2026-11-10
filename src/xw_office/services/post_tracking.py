"""Parse the Austrian Post TrackingData v2 XML customer feed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

from lxml import etree


@dataclass(frozen=True)
class PostTrackingEvent:
    tracking_code: str
    event_id: str
    occurred_at: datetime
    event_type: str
    event_reason: str
    event_postal_code: str
    event_city: str
    event_country: str
    source_sha256: str


def parse_post_tracking_xml(raw: bytes) -> tuple[PostTrackingEvent, ...]:
    """Parse the documented feed; timestamps without offset stay as supplied by Post."""
    if len(raw) > 20_000_000 or b"<!DOCTYPE" in raw.upper():
        raise ValueError("Ungültige oder zu große Post-Trackingdatei")
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise ValueError("Post-Trackingdatei ist kein gültiges XML") from exc
    if etree.QName(root).localname != "TrackingData":
        raise ValueError("Keine Post-TrackingData-Datei")

    def child_text(node: etree._Element, name: str) -> str:
        for child in node:
            if etree.QName(child).localname == name:
                return (child.text or "").strip()
        return ""

    tracking = next((node for node in root if etree.QName(node).localname == "TrackingEvents"), None)
    if tracking is None:
        raise ValueError("Post-TrackingEvents fehlen")
    header = next((node for node in tracking if etree.QName(node).localname == "Header"), None)
    if header is None or child_text(header, "TrackingVersion") != "2":
        raise ValueError("Nur Post-TrackingVersion 2 wird unterstützt")
    digest = sha256(raw).hexdigest()
    events: list[PostTrackingEvent] = []
    for node in tracking:
        if etree.QName(node).localname != "Event":
            continue
        code = child_text(node, "IdentCode")
        event_id = child_text(node, "ParcelEventId")
        timestamp = child_text(node, "EventTimestamp")
        event_type = child_text(node, "ParcelEventTypeCode")
        if not code or not event_id or not timestamp or not event_type:
            raise ValueError("Post-Ereignis ohne Code, ID, Zeit oder Typ")
        try:
            occurred_at = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise ValueError(f"Ungültige Post-Ereigniszeit: {timestamp}") from exc
        if occurred_at.tzinfo is not None:
            occurred_at = occurred_at.astimezone(ZoneInfo("Europe/Vienna")).replace(tzinfo=None)
        events.append(PostTrackingEvent(
            tracking_code=code, event_id=event_id, occurred_at=occurred_at,
            event_type=event_type, event_reason=child_text(node, "ParcelEventReasonCode"),
            event_postal_code=child_text(node, "EventPostalCode"),
            event_city=child_text(node, "EventCity"),
            event_country=child_text(node, "EventCountry"), source_sha256=digest,
        ))
    expected = child_text(header, "EventCount")
    if expected and expected.isdigit() and int(expected) != len(events):
        raise ValueError("Post-Trackingdatei enthält weniger Ereignisse als im Header angegeben")
    return tuple(events)
