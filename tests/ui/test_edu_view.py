from unittest.mock import Mock

from xw_office.services.crm.edu_client import EduClient
from xw_office.ui.modules.crm.edu_view import EduView


def test_edu_view_shows_school_mail_and_invoice_sync_independently(qtbot):
    client = Mock(spec=EduClient)
    school = {
        "id": "school-1",
        "version": "revision",
        "status": "pending",
        "institutionName": "Musikschule",
        "billingEntityName": "Gemeinde",
        "billingEmail": "school@example.test",
        "mailConfirmed": False,
    }
    client.command.side_effect = lambda command, **_: (
        {"schools": [school]}
        if command == "list"
        else {"school": school, "teachers": [], "admins": [], "invitations": [], "history": []}
    )
    client.school_orders.side_effect = RuntimeError("Rechnungspipeline nicht erreichbar")
    view = EduView(client)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitUntil(lambda: "Rechnungspipeline nicht erreichbar" in view._status.text(), timeout=3000)

    assert view._fields["billingEntityName"].text() == "Gemeinde"
    assert "Rechnungs-Mail offen" in view._school_status.text()
    assert any(view._tabs.tabText(index) == "Rechnungssync" for index in range(view._tabs.count()))
