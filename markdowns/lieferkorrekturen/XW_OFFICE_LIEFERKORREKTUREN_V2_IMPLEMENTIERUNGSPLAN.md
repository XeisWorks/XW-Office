# XW-Office – Lieferkorrekturen / Nachsendungen V2

## Ziel

XW-Office soll E-Mails an `shop@xeisworks.at`, die eine Lieferkorrektur betreffen, automatisch erkennen, durch KI vorstrukturieren und in einen dauerhaften, kontrollierbaren Case überführen.

Der Benutzer soll nicht mehrere getrennte Systeme bedienen. Stattdessen gibt es **einen gemeinsamen Lieferkorrektur-Case** mit unterschiedlichen Falltypen und Policies.

Wichtig:
- Die KI darf **vorentscheiden**, aber keine irreversible Aktion eigenmächtig ausführen.
- Die Typisierung wird in XW-Office in einem kompakten Bestätigungsdialog geprüft.
- B2B-Fälle warten bevorzugt auf die nächste Bestellung desselben Händlers, jedoch maximal 20 Tage.
- Nach Ablauf von 20 Tagen wird der Case automatisch fällig.
- Rechnungen werden erst bei Fälligkeit bzw. bewusster Benutzeraktion erzeugt.
- Das bestehende Graph-, Wix-, sevDesk- und Lieferschein-System wird wiederverwendet.
- `Kulanz` ist standardmäßig aktiviert.

---

## 1. Einheitliches Fachmodell

Ein Case kann gleichzeitig enthalten:

- falsch gelieferte Artikel
- eigentlich geschuldete / fehlende Artikel
- Nachsendung erforderlich
- zusätzliche Rechnung erforderlich oder optional
- Kulanz aktiv/deaktiviert

Der häufigste Fall wird damit sauber abgebildet:

> Händler erhielt Artikel A statt Artikel B.  
> Artikel A darf beim Händler bleiben.  
> Artikel B fehlt und muss noch geliefert werden.  
> Für Artikel A kann später eine zusätzliche Rechnung erstellt werden.

---

## 2. Falltypen

### 2.1 `B2B_WRONG_DELIVERY`

XeisWorks hat falsch geliefert.

Typisch:
- `wrong_items`: falsch gelieferte Artikel beim Händler
- `missing_items`: eigentlich bestellte, noch fehlende Artikel
- Rechnung für `wrong_items`: optional
- Nachsendung für `missing_items`: erforderlich

Policy:

```yaml
wait_for_next_order: true
max_wait_days: 20
wrong_item_invoice: optional
requires_replacement: true
courtesy_default: true
```

**Kulanz aktiv:**
- 30 % Händlerrabatt auf Produkte
- 100 % Rabatt auf Versand
- korrekte USt-/TaxSet-Logik bleibt erhalten

**Kulanz deaktiviert:**
- normale Wix-B2B-Rabatte
- normale Versandkosten
- korrekte USt-/TaxSet-Logik

---

### 2.2 `B2B_MISSING_ITEMS`

XeisWorks hat einen oder mehrere bestellte Artikel nicht geliefert.

Policy:

```yaml
wait_for_next_order: true
max_wait_days: 20
wrong_item_invoice: false
requires_replacement: true
courtesy_default: true
```

Bei nächster Bestellung:
- Case wird fällig
- fehlender Artikel wird bevorzugt kostenlos beigelegt
- keine zusätzliche Rechnung

Nach 20 Tagen ohne neue Bestellung:
- Case wird automatisch fällig
- XW-Office fordert zur separaten Nachsendung auf

---

### 2.3 `B2C_WRONG_DELIVERY`

XeisWorks hat bei einem Endkunden falsch geliefert.

Policy:

```yaml
wait_for_next_order: false
trigger_immediately: true
wrong_item_invoice: false
requires_replacement: true
courtesy_default: true
```

Ablauf:
- sofort fällig
- richtiges Produkt nachsenden
- falsch geliefertes Produkt darf in der Regel behalten werden
- keine Zusatzrechnung
- Lieferschein wie im bestehenden Nachsendungsworkflow

---

### 2.4 `B2B_CUSTOMER_ORDER_ERROR`

Der Händler hat sich verklickt / selbst falsch bestellt.

Policy:

```yaml
wait_for_next_order: false
trigger_immediately: true
invoice_required: true
requires_replacement: true
courtesy_default: true
```

**Kulanz aktiv:**
- 30 % Rabatt auf Produkte
- 100 % Rabatt auf Versand

**Kulanz deaktiviert:**
- normale Wix-B2B-Rabatte
- normale Versandkosten

Der Falltyp sagt damit, **wer den Fehler verursacht hat**.  
Die Checkbox `Kulanz` entscheidet, **welche Preislogik gilt**.

---

## 3. Mail-Eingang bleibt `shop@xeisworks.at`

Es wird vorerst **kein zusätzlicher Alias** benötigt.

Ablauf:

1. Benutzer sendet/leitet kurze Mail an `shop@xeisworks.at`
2. XW-Office liest sie über Microsoft Graph
3. KI erkennt Lieferkorrektur
4. KI extrahiert:
   - Kunde / Händler
   - Ausgangsbestellung
   - falsch gelieferte Artikel
   - fehlende / richtige Artikel
   - vermuteten Verursacher
   - Falltyp
   - Kulanz-Vorschlag
   - Notiz
5. XW-Office zeigt Review-Popup
6. Benutzer bestätigt / korrigiert
7. Erst danach entsteht ein aktiver Case

Die KI erzeugt **keine Rechnung, kein Label und keinen endgültigen Versandauftrag**.

---

## 4. Review-Popup in PySide6

Titel:

> Lieferkorrektur erkannt

Anzeigen:
- Kunde
- Wix-Bestellung
- Falltyp
- falsch geliefert
- fehlt / nachzusenden
- Verursacher
- Kulanz
- Trigger
- Fälligkeit
- Notiz

Typ-Auswahl:
- B2B – XeisWorks falsch geliefert
- B2B – Artikel fehlt
- B2C – XeisWorks falsch geliefert
- B2B – Händler hat falsch bestellt
- Sonstiges / manuell prüfen

Checkbox:

> ☑ Kulanz anwenden

Tooltip:

> Aktiv: 30 % Produktrabatt und 100 % Versandrabatt.  
> Deaktiviert: normale Wix-B2B-Rabatte und normale Versandkosten.

Buttons:
- **Übernehmen**
- **Bearbeiten**
- **Ignorieren**

---

## 5. Triggerlogik

Für `B2B_WRONG_DELIVERY` und `B2B_MISSING_ITEMS`:

```text
WAITING
   |
   +-- neue Bestellung desselben Händlers --> TRIGGERED
   |
   +-- 20 Tage erreicht -------------------> TRIGGERED
```

`due_at` wird beim Anlegen fix gespeichert:

```python
due_at = created_at + timedelta(days=20)
```

### Kundenmatching

Priorität:
1. Wix `buyerInfo.contactId`
2. normalisierte E-Mail-Adresse als Fallback
3. Name nur als Hinweis, niemals alleiniger Auto-Trigger

Ausschließen:
- Ursprungsbestellung
- ältere Bestellungen
- bereits verwendete Trigger-Bestellung

Statuswechsel muss atomar/idempotent sein.

---

## 6. Verhalten bei Ablauf der 20 Tage

### B2B_MISSING_ITEMS
Meldung:

> 20 Tage ohne neue Bestellung. Fehlenden Artikel jetzt separat nachsenden.

### B2B_WRONG_DELIVERY
Meldung:

> 20 Tage ohne neue Bestellung. Richtigen Artikel ggf. separat nachsenden und entscheiden, ob der falsch gelieferte Artikel verrechnet wird.

---

## 7. Tagesgeschäft

Neue UI-Elemente:

### Permanenter Button
`Lieferkorrekturen`

### Badge
`KORREKTUR ZU PRÜFEN (n)`

für KI-erkannt, aber noch nicht bestätigt.

### Roter Badge
`LIEFERKORREKTUR FÄLLIG (n)`

für getriggerte / überfällige Fälle.

Manager-Filter:
- Zu prüfen
- Fällig
- Wartet
- Erledigt
- Alle

---

## 8. Rechnungslogik

Rechnung niemals bei KI-Erkennung.

### `B2B_WRONG_DELIVERY`

Bei Fälligkeit:

> Falsch gelieferten Artikel verrechnen?

Aktionen:
- Zusatzrechnung erstellen
- Ohne Rechnung erledigen
- Später

**Kulanz aktiv**
- Produktpositionen: exakt 30 % Rabatt
- Versand: effektiv 100 % rabattiert / 0 €
- Steuer unverändert korrekt

**Kulanz deaktiviert**
- normale Wix-B2B-Rabatte
- normale Versandkosten

### `B2B_CUSTOMER_ORDER_ERROR`

Rechnung grundsätzlich vorgesehen.

**Kulanz aktiv**
- 30 % Produkt
- 100 % Versand

**Kulanz deaktiviert**
- normale Wix-B2B-Konditionen
- normale Versandkosten

---

## 9. Zentrale PricingPolicy

Keine Preislogik im UI.

Neue Klasse:

```python
class CustomerAftercarePricingPolicy:
    def resolve_product_discount(case, customer, order_context):
        ...

    def resolve_shipping_discount(case, customer, order_context):
        ...
```

Regeln:

```yaml
courtesy:
  product_discount_percent: 30
  shipping_discount_percent: 100

normal:
  product_discount_source: wix_b2b_rules
  shipping_cost_source: existing_wix_shipping_logic
```

---

## 10. Steuerlogik

Rabatt und Steuer strikt getrennt behandeln.

Auch bei Kulanz:
- bestehende TaxSet-/OSS-/B2B-Regeln
- 0%-B2B bleibt 0 %
- Export / innergemeinschaftlich korrekt
- Positions-Steuersatz aus Wix/Produktkontext erhalten

Neue Bausteine:
- `sevdesk/tax_policy.py`
- `sevdesk/tax_set_client.py`

Fachliche Parität mit `wix-sevdesk-api`, ohne kompletten sevDesk-Umbau.

---

## 11. Lieferschein / Nachsendung

Bestehenden Lieferschein-/Offene-Sendungen-Code wiederverwenden.

Mögliche Hinweise:
- `Kostenlose Nachlieferung zu Bestellung 21842`
- `Lieferkorrektur – nicht verrechnen`
- `Nachsendung aufgrund Falschlieferung`

Bei Kombination mit neuer Bestellung:
- Nachlieferartikel klar als **kostenlose Nachlieferung – nicht verrechnen** kennzeichnen.

---

## 12. Persistenz

Neue relationale Tabellen.

### `customer_aftercare_case`

Wichtige Felder:

```text
id UUID PK
case_type
status

source_message_id
source_thread_id
source_subject

ai_suggested_type
ai_confidence
ai_payload_json
classification_confirmed_at

customer_type
wix_contact_id
customer_email
customer_name

source_wix_order_id
source_wix_order_number
source_order_created_at

courtesy BOOLEAN DEFAULT TRUE

wait_for_next_order
due_at
triggered_at
trigger_reason
trigger_wix_order_id
trigger_wix_order_number

invoice_required
invoice_status
sevdesk_invoice_id
sevdesk_invoice_number
invoice_error

created_at
updated_at
resolved_at
cancelled_at
```

### `customer_aftercare_item`

```text
id UUID PK
case_id FK
role
sku
name
quantity
sevdesk_part_id
source_unit_price
source_tax_rate
source_discount_percent
created_at
```

Rollen:
- `WRONG_DELIVERED`
- `MISSING_TO_SEND`
- `CORRECTED_ORDER_ITEM`
- `SHIPPING`

---

## 13. Statusmodell

```text
PENDING_REVIEW
    |
    +--> WAITING
    |
    +--> TRIGGERED
    |
    +--> IGNORED

WAITING --> TRIGGERED

TRIGGERED --> RESOLVED

aktive Zustände --> CANCELLED
```

---

## 14. Idempotenz

### Mail
`source_message_id` eindeutig.

### Trigger
`WAITING -> TRIGGERED` atomar.

### sevDesk
Marker:

```text
LIEFERKORREKTUR:<case_uuid> | WIX:<source_order_number>
```

Vor Retry vorhandene Rechnung per Marker suchen und wieder verknüpfen.

---

## 15. Konfiguration

```yaml
customer_aftercare:
  enabled: true

  ai:
    enabled: true
    min_confidence_for_prefill: 0.75

  b2b:
    wait_for_next_order: true
    max_wait_days: 20

  courtesy:
    default_enabled: true
    product_discount_percent: 30
    shipping_discount_percent: 100

  polling:
    inbox_seconds: 300
    due_check_seconds: 60
    wix_order_check_seconds: 60
```

---

## 16. Neue Dateien

```text
src/xw_office/models/customer_aftercare.py
src/xw_office/repositories/customer_aftercare.py
src/xw_office/migrations/versions/007_customer_aftercare.py

src/xw_office/services/customer_aftercare/__init__.py
src/xw_office/services/customer_aftercare/inbox_service.py
src/xw_office/services/customer_aftercare/service.py
src/xw_office/services/customer_aftercare/ai_classifier.py
src/xw_office/services/customer_aftercare/pricing_policy.py
src/xw_office/services/customer_aftercare/invoice_service.py

src/xw_office/services/sevdesk/tax_policy.py
src/xw_office/services/sevdesk/tax_set_client.py

src/xw_office/ui/modules/rechnungen/customer_aftercare_review_dialog.py
src/xw_office/ui/modules/rechnungen/customer_aftercare_manager_dialog.py
src/xw_office/ui/modules/rechnungen/customer_aftercare_invoice_dialog.py
```

Zu ändern:
- `models/__init__.py`
- `repositories/__init__.py`
- `bootstrap.py`
- `tagesgeschaeft_view.py`
- `rechnungen/view.py`
- ggf. bestehender Lieferschein-/Draft-Invoice-/Wix-Code nur dort, wo Wiederverwendung nötig ist

---

## 17. Implementierungsreihenfolge

1. Datenmodell + Migration + Repository
2. Mail/KI + PENDING_REVIEW
3. Review-Popup
4. Wix-Matching + 20-Tage-Trigger
5. Tagesgeschäft-Badges + Manager
6. PricingPolicy
7. TaxSet/USt
8. idempotente sevDesk-Rechnung
9. Lieferschein-/Fulfillment-Integration
10. Regression/Tests

---

## 18. Pflicht-Testmatrix

1. B2B falsch geliefert, neue Bestellung nach 5 Tagen
2. B2B falsch geliefert, keine Bestellung, Tag 20
3. B2B fehlt, neue Bestellung nach 2 Tagen
4. B2B fehlt, Tag 20 -> separat senden
5. B2C falsch -> sofort fällig
6. Händler selbst falsch bestellt -> sofort fällig
7. Kulanz aktiv -> 30 % Produkt, 100 % Versand
8. Kulanz deaktiviert -> normale Wix-B2B-Konditionen
9. 0%-B2B bleibt 0 %
10. OSS korrekt
11. Export korrekt
12. gleiche Mail doppelt -> kein Doppelcase
13. gleiche Wix-Bestellung mehrfach gepollt -> ein Trigger
14. sevDesk-Timeout -> Retry ohne Dublette
15. falsche KI-Typisierung manuell korrigierbar
16. UNKNOWN manuell typisierbar
17. Case mit wrong + missing gleichzeitig
18. mehrere Cases desselben Händlers dürfen durch dieselbe neue Bestellung triggern
19. Ausgangsbestellung darf nicht selbst triggern
20. Name allein darf keinen Auto-Match auslösen

---

## 19. Definition of Done

Fertig, wenn:

- alle vier Falltypen unterstützt sind
- wrong + missing in einem Case möglich ist
- KI nur vorentscheidet
- manuelle Bestätigung/Korrektur vorhanden ist
- B2B bei nächster Bestellung oder spätestens nach 20 Tagen fällig wird
- Tag 20 bei Missing zur separaten Nachsendung auffordert
- Kulanz standardmäßig aktiv ist
- Kulanz exakt 30 % Produkt / 100 % Versand bedeutet
- ohne Kulanz normale Wix-B2B-Rabatte und Versandkosten gelten
- Steuerlogik korrekt bleibt
- Rechnungen erst bei Fälligkeit/Benutzeraktion entstehen
- bestehender Lieferscheinworkflow wiederverwendet wird
- alle kritischen Schritte idempotent sind
- UI nicht blockiert
- Tests grün sind
