from xw_office.services.invoice_processing.mail_content import (
    DEFAULT_BODY,
    SHIPPING_BODY,
    normalize_body_template,
    render_invoice_mail,
)


def test_old_saved_default_is_upgraded_and_signature_is_rendered_once() -> None:
    old = (
        "Guten Tag,\n\n"
        "wir freuen uns, Ihnen mitteilen zu können, dass Ihre Bestellung soeben versendet wurde.\n\n"
        "Die bestellten Produkte befinden sich nun auf dem Weg zu Ihnen. Je nach Versandart und Zielort kann die Zustellung einige Werktage in Anspruch nehmen.\n\n"
        "Die zugehörige Rechnung finden Sie im Anhang dieser E-Mail.\n\n"
        "Sollten Sie in der Zwischenzeit Fragen zu Ihrer Bestellung oder zum Lieferstatus haben, stehen wir Ihnen selbstverständlich gerne zur Verfügung.\n\n"
        "Vielen Dank für Ihr Vertrauen und Ihre Bestellung.\n\n"
        "Mit freundlichen Grüßen\nXeisWorks\nMag. Bernhard Holl\n"
        "Johnsbach 92\n8912 Admont\noffice@xeisworks.at\nwww.xeisworks.at\n"
    )

    assert normalize_body_template(old) == DEFAULT_BODY
    plain, markup = render_invoice_mail(old)

    assert "soeben versendet" not in plain
    assert plain.count("Ihr XeisWorks-Team") == 1
    assert plain.count("Musikverlag Mag. Bernhard Holl") == 1
    assert "office@xeisworks.at" in plain
    assert "shop@xeisworks.at" not in plain
    assert "Mit musikalischen Grüßen\n\nIhr XeisWorks-Team\n\n\nXeisWorks" in plain
    assert 'font-size:12px;line-height:1.35;color:#808080' in markup
    assert 'margin:22px 0 44px 0;">Ihr XeisWorks-Team' in markup


def test_html_template_tags_do_not_appear_as_visible_mail_text() -> None:
    plain, markup = render_invoice_mail(
        '<html><body><p>Guten Tag,</p><p>Ihre Rechnung ist angehängt.</p></body></html>'
    )

    assert "<html>" not in plain
    assert "</html>" not in plain
    assert markup.count("<html") == 1
    assert markup.count("</html>") == 1
    assert "Ihre Rechnung ist angehängt." in plain
    assert "Ihr XeisWorks-Team" in markup


def test_shipping_details_and_closing_are_one_paragraph() -> None:
    text, markup = render_invoice_mail(SHIPPING_BODY)

    assert "dauern. Wenn Sie Fragen" in text
    assert "weiter. Vielen Dank" in text
    assert markup.count("<p style=") == 5  # three content paragraphs and two sign-off lines
