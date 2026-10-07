from __future__ import annotations

from xw_office.services.expenses.reference_parser import project_expense_text


def test_card_descriptor_extracts_merchant_after_time() -> None:
    projection = project_expense_text(
        payee_name="",
        payment_reference="",
        purpose=(
            "Bezahlung Karte MC/000008551E-COMM 25,16 USD D002 04.09. 04:34"
            "GITHUB, INC.\\SAN FRANCISCO\\94SPESEN: 1,25 KURS: 1,151363"
        ),
    )

    assert projection.payee == "GitHub Inc."
    assert projection.purpose == "Online-Kartenzahlung · 25,16 USD"
    assert projection.source == "card_descriptor"
    assert projection.merchant_key == "github inc"


def test_card_aliases_are_stable_for_future_profile_rules() -> None:
    projection = project_expense_text(
        payee_name="",
        payment_reference="",
        purpose=(
            "Bezahlung Karte MC/000008594E-COMM 20,00 USD D002 23.09. 03:40"
            "OPENAI *CHATGPT SUBSCR\\SAN FRSPESEN: 1,22"
        ),
    )

    assert projection.payee == "OpenAI"
    assert projection.merchant_key == "openai"


def test_direct_references_keep_only_business_meaning() -> None:
    assert project_expense_text(
        payee_name="A1 Telekom Austria AG",
        payment_reference="",
        purpose="A1 RECHNUNG 08/26 523730090/1 001386748674 825838OG/000008563...",
    ).purpose == "Rechnung 08/26"
    assert project_expense_text(
        payee_name="Dagmar Holl",
        payment_reference="",
        purpose="Lohn 09/26 FE/000008592RZSTAT2G215 AT1438...",
    ).purpose == "Lohn 09/26"


def test_amazon_and_social_insurance_references_are_compact() -> None:
    amazon = project_expense_text(
        payee_name="AMAZON PAYMENTS EUROPE S.C.A.",
        payment_reference="",
        purpose="303-0809267-9193163 AMZN Mktp DE 22SMCL18LQZSFSANOG/000008556...",
    )
    sva = project_expense_text(
        payee_name="SVA der Selbstaendigen",
        payment_reference="",
        purpose="2714 300784 FE/000008535AT423200006500089219 SVA der Selbstaendigen",
    )

    assert amazon.purpose == "Bestellung 303-0809267-9193163"
    assert sva.purpose == "—"


def test_sepa_and_paypal_metadata_do_not_leak_into_the_main_table() -> None:
    insurance = project_expense_text(
        payee_name="Allianz Elementar Lebensversicherun",
        payment_reference="",
        purpose="SEPA-Lastschrift L953754972 13OLN OG/000008539BKAUATWWXXX ...",
    )
    paypal = project_expense_text(
        payee_name="PayPal Europe S.a.r.l. et Cie S.C.A",
        payment_reference="",
        purpose="1053054755051/PAYPAL OG/000008571PPLXLUL2XXX ...",
    )

    assert insurance.purpose == "Lastschrift"
    assert paypal.purpose == "PayPal-Zahlung"


def test_empty_reference_has_a_safe_fallback() -> None:
    projection = project_expense_text(payee_name="Unbekannter Empfänger", payment_reference="", purpose="")

    assert projection.payee == "Unbekannter Empfänger"
    assert projection.purpose == "—"
