from __future__ import annotations

import types

from xw_office.services.mailing import outlook_compose


def test_create_mail_item_prefers_target_account_drafts_folder() -> None:
    created = object()

    class _Items:
        def Add(self, message_class: str) -> object:  # noqa: N802
            assert message_class == "IPM.Note"
            return created

    class _Store:
        def GetDefaultFolder(self, folder_id: int) -> object:  # noqa: N802
            assert folder_id == 16
            return types.SimpleNamespace(Items=_Items())

    account = types.SimpleNamespace(DeliveryStore=_Store())
    outlook = types.SimpleNamespace(CreateItem=lambda _kind: object())

    assert outlook_compose._create_mail_item(outlook, account) is created  # noqa: SLF001


def test_create_mail_item_falls_back_to_default_create_item() -> None:
    fallback = object()
    account = types.SimpleNamespace(DeliveryStore=None)
    outlook = types.SimpleNamespace(CreateItem=lambda kind: fallback if kind == 0 else object())

    assert outlook_compose._create_mail_item(outlook, account) is fallback  # noqa: SLF001


def test_apply_html_body_replaces_outlook_signature() -> None:
    mail = types.SimpleNamespace(
        Body="Old plain signature",
        HTMLBody='<a href="mailto:office@xeisworks.at">old signature</a>',
    )

    outlook_compose._apply_body(mail, "Plain fallback", html_body="<p>Complete custom mail</p>")

    assert mail.HTMLBody == "<p>Complete custom mail</p>"
    assert "mailto:" not in mail.HTMLBody
