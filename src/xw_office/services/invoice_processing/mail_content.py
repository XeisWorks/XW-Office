"""Customer-facing invoice mail content shared by START and the settings preview."""

from __future__ import annotations

import html
import re

from xw_office.services.mailing.graph_client import html_to_text

SHOP_MAILBOX = "shop@xeisworks.at"
CONTACT_MAILBOX = "office@xeisworks.at"
DEFAULT_SUBJECT = "Ihre Rechnung {{invoice_number}}"
ORDER_INVOICE_SUBJECT = "Rechnung zu Bestellung {{order_number}} ({{invoice_number}})"
SHIPPING_SUBJECT = "Rechnung und Versandbestätigung zu Bestellung {{order_number}} ({{invoice_number}})"
DIGITAL_SUBJECT = "Rechnung zu Bestellung {{order_number}} ({{invoice_number}})"
DEFAULT_BODY = (
    "Guten Tag,\n\n"
    "herzlichen Dank für Ihre Bestellung bei XeisWorks! Ihre Rechnung {{invoice_number}} "
    "finden Sie als PDF im Anhang dieser E-Mail.\n\n"
    "Wenn Sie Fragen zu Ihrer Bestellung oder Rechnung haben, antworten Sie uns gerne. "
    "Wir helfen Ihnen weiter.\n\n"
    "Vielen Dank für Ihr Vertrauen und viel Freude mit Ihrer Musik!"
)
ORDER_INVOICE_BODY = (
    "Guten Tag,\n\n"
    "herzlichen Dank für Ihre Bestellung {{order_number}} bei XeisWorks! "
    "Ihre Rechnung {{invoice_number}} finden Sie als PDF im Anhang dieser E-Mail.\n\n"
    "Wenn Sie Fragen zu Ihrer Bestellung oder Rechnung haben, antworten Sie uns gerne. "
    "Wir helfen Ihnen weiter.\n\n"
    "Vielen Dank für Ihr Vertrauen und viel Freude mit Ihrer Musik!"
)
SHIPPING_BODY = (
    "Guten Tag,\n\n"
    "herzlichen Dank für Ihre Bestellung {{order_number}} bei XeisWorks! "
    "Wir freuen uns, Ihnen mitteilen zu können, dass Ihre Bestellung versendet wurde "
    "und nun auf dem Weg zu Ihnen ist.\n\n"
    "Ihre Rechnung {{invoice_number}} finden Sie als PDF im Anhang dieser E-Mail. "
    "Je nach Versandart und Zielort kann die Zustellung einige Werktage dauern. "
    "Wenn Sie Fragen zu Ihrer Bestellung oder zum Versand haben, antworten Sie uns gerne. "
    "Wir helfen Ihnen weiter. "
    "Vielen Dank für Ihr Vertrauen und viel Freude mit Ihrer Musik!"
)
DIGITAL_BODY = (
    "Guten Tag,\n\n"
    "herzlichen Dank für Ihre Bestellung {{order_number}} bei XeisWorks! "
    "Ihre Rechnung {{invoice_number}} finden Sie als PDF im Anhang dieser E-Mail.\n\n"
    "Den Download-Link für Ihre digitalen Produkte erhalten Sie in einer gesonderten E-Mail. "
    "Falls Sie ihn nicht finden oder Fragen haben, antworten Sie uns gerne. "
    "Wir helfen Ihnen weiter.\n\n"
    "Vielen Dank für Ihr Vertrauen und viel Freude mit Ihrer Musik!"
)

_OLD_DEFAULT_BODY = (
    "Guten Tag,\n\n"
    "wir freuen uns, Ihnen mitteilen zu können, dass Ihre Bestellung soeben versendet wurde.\n\n"
    "Die bestellten Produkte befinden sich nun auf dem Weg zu Ihnen. Je nach Versandart und Zielort kann die Zustellung einige Werktage in Anspruch nehmen.\n\n"
    "Die zugehörige Rechnung finden Sie im Anhang dieser E-Mail.\n\n"
    "Sollten Sie in der Zwischenzeit Fragen zu Ihrer Bestellung oder zum Lieferstatus haben, stehen wir Ihnen selbstverständlich gerne zur Verfügung.\n\n"
    "Vielen Dank für Ihr Vertrauen und Ihre Bestellung.\n\n"
    "Mit freundlichen Grüßen\n"
    "XeisWorks\n"
    "Mag. Bernhard Holl\n"
    "Johnsbach 92\n"
    "8912 Admont\n"
    "office@xeisworks.at\n"
    "www.xeisworks.at"
)

_OLD_FOOTER = re.compile(
    r"\n+Mit freundlichen Grüßen\s*\nXeisWorks\s*\nMag\. Bernhard Holl"
    r"[\s\S]*$",
    re.IGNORECASE,
)


def normalize_body_template(value: str) -> str:
    """Upgrade the old default copy and remove its embedded signature."""
    normalized = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if re.search(r"</?(?:html|body|p|div|br|span|strong|a)\b", normalized, re.IGNORECASE):
        normalized = html_to_text(normalized)
    if not normalized or normalized == _OLD_DEFAULT_BODY:
        return DEFAULT_BODY
    return _OLD_FOOTER.sub("", normalized).strip()


def render_invoice_mail(body: str) -> tuple[str, str]:
    """Return matching plain text and HTML with one controlled team signature."""
    content = normalize_body_template(body)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    html_parts = []
    for part in paragraphs:
        escaped = html.escape(part).replace("\n", "<br>")
        html_parts.append(f'<p style="margin:0 0 16px 0;">{escaped}</p>')
    inner = "\n".join(html_parts)
    signature_text = (
        "Mit musikalischen Grüßen\n\n"
        "Ihr XeisWorks-Team\n\n\n"
        "XeisWorks\n"
        "Musikverlag Mag. Bernhard Holl\n"
        f"{CONTACT_MAILBOX}\n"
        "www.xeisworks.at\n"
        "+43 3611 93012"
    )
    text_body = f"{content}\n\n{signature_text}"
    html_body = (
        '<html><body style="font-family:Arial,Segoe UI,sans-serif;'
        'font-size:15px;line-height:1.5;color:#242424;">'
        f"{inner}"
        '<p style="margin:20px 0 0 0;">Mit musikalischen Grüßen</p>'
        '<p style="margin:22px 0 44px 0;">Ihr XeisWorks-Team</p>'
        '<div style="font-family:Georgia,serif;font-size:12px;line-height:1.35;color:#808080;">'
        '<strong style="font-size:15px;">XeisWorks</strong><br>'
        'Musikverlag Mag. Bernhard Holl<br>'
        f'<a href="mailto:{CONTACT_MAILBOX}" style="color:#808080;">{CONTACT_MAILBOX}</a><br>'
        '<a href="https://www.xeisworks.at" style="color:#808080;">www.xeisworks.at</a><br>'
        '+43 3611 93012'
        '</div></body></html>'
    )
    return text_body, html_body
