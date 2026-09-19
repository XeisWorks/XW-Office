import type { ConflictCaseDetail } from "../api/types";

type JsonRecord = Record<string, unknown>;

const TYPE_LABELS: Record<string, string> = {
  WRONG_PRODUCT_MAPPING: "Wix-Verknüpfung stimmt nicht",
  DUPLICATE_SKU: "SKU ist mehrfach vergeben",
  ASIN_CONFLICT: "ASIN-Konflikt",
  FNSKU_CONFLICT: "FNSKU-Konflikt",
  IDENTIFIER_COLLISION: "Kennnummer ist mehrfach vergeben",
  PRICE_DRIFT: "Preis weicht ab",
  VAT_DRIFT: "Steuersatz weicht ab",
  STOCK_DRIFT: "Lagerbestand weicht ab",
  ACTIVE_STATUS_DRIFT: "Sichtbarkeit weicht ab",
  TITLE_DRIFT: "Produkttitel weicht ab",
  BRAND_DRIFT: "Marke weicht ab",
  CATEGORY_DRIFT: "Kategorie weicht ab",
  DESCRIPTION_DRIFT: "Beschreibung weicht ab",
  BULLET_DRIFT: "Stichpunkte weichen ab",
  TAG_DRIFT: "Schlagwörter weichen ab",
};

const FIELD_LABELS: Record<string, string> = {
  mapping: "Produkt-Verknüpfung",
  name: "Produkttitel",
  description: "Beschreibung",
  active: "Aktiv",
  visible: "Sichtbar",
  price: "Preis",
  stock: "Lagerbestand",
  category: "Kategorie",
  brand_name: "Marke",
};

const STATE_LABELS: Record<string, string> = {
  mapped: "Verknüpfung gespeichert",
  not_found: "Produkt bei Wix nicht gefunden",
  permission_denied: "Wix-Zugriff nicht erlaubt",
  temporary_error: "Wix vorübergehend nicht erreichbar",
  invalid_response: "Wix-Antwort konnte nicht gelesen werden",
  configuration_error: "Wix-Zugangsdaten fehlen",
  invalid_mapping: "Gespeicherte Wix-ID ist ungültig",
  api_error: "Wix-Abruf fehlgeschlagen",
};

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function shortenedId(value: unknown): string {
  const text = String(value ?? "");
  return text.length > 28 ? `${text.slice(0, 18)}…${text.slice(-6)}` : text;
}

export function conflictTypeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type.replaceAll("_", " ");
}

export function conflictFieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field.replaceAll("_", " ");
}

export function conflictSummary(item: Pick<ConflictCaseDetail, "conflict_type" | "summary">): string {
  if (item.conflict_type === "WRONG_PRODUCT_MAPPING") {
    return "Gespeicherte Wix-ID nicht bestätigt; beim Öffnen werden mögliche Ersatz-IDs gesucht.";
  }
  return item.summary || "Product Hub und Channel enthalten unterschiedliche Werte.";
}

export function displayConflictValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (field === "mapping") {
    const record = asRecord(value);
    if (record) {
      const state = String(record.state ?? "");
      const label = STATE_LABELS[state] ?? "Verknüpfungsstatus unbekannt";
      const id = shortenedId(record.external_id);
      return id ? `${label} · ${id}` : label;
    }
  }
  if (typeof value === "boolean") return value ? "Ja" : "Nein";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(String).join(", ");
  return "Strukturierte Daten – siehe technische Details";
}

export interface DeterministicGuidance {
  title: string;
  explanation: string;
  recommendation: string;
  possibleCauses: string[];
}

export function deterministicGuidance(item: ConflictCaseDetail): DeterministicGuidance {
  if (item.conflict_type === "WRONG_PRODUCT_MAPPING") {
    const wixValue = item.fields
      .flatMap((field) => field.observations)
      .find((observation) => observation.source === "wix")?.raw_value;
    const state = String(asRecord(wixValue)?.state ?? "");
    const explanations: Record<string, string> = {
      not_found: "Der Product Hub ist mit einer Wix-Produkt-ID verbunden, aber Wix hat unter dieser ID kein Produkt gefunden.",
      permission_denied: "Der Product Hub kennt die Wix-Produkt-ID, Wix hat den Abruf aber wegen fehlender Berechtigung abgelehnt.",
      temporary_error: "Die Wix-Verknüpfung ist vorhanden, der Produktabruf ist jedoch vorübergehend fehlgeschlagen.",
      invalid_response: "Wix hat geantwortet, aber keine lesbaren Produktdaten geliefert.",
      invalid_mapping: "Die gespeicherte Wix-Produkt-ID ist leer oder ungültig.",
      configuration_error: "Die Wix-Verknüpfung konnte wegen fehlender Zugangsdaten nicht geprüft werden.",
    };
    return {
      title: "Wix-Verknüpfung prüfen",
      explanation: explanations[state] ?? "Die gespeicherte Wix-Verknüpfung konnte beim letzten Vergleich nicht bestätigt werden.",
      recommendation: "Prüfe zuerst erneut. Bleibt der Fehler bestehen, suche das Produkt in Wix und ordne die korrekte Wix-Produkt-ID manuell zu. Entferne die Verknüpfung erst, wenn du sicher bist, dass sie veraltet ist.",
      possibleCauses: [
        "Das Wix-Produkt wurde gelöscht oder ersetzt.",
        "Die gespeicherte Wix-ID ist veraltet.",
        "Berechtigung, Wix-API oder Netzwerk haben den Abruf verhindert.",
      ],
    };
  }
  return {
    title: conflictTypeLabel(item.conflict_type),
    explanation: "Der Product Hub und mindestens ein angebundener Verkaufskanal enthalten für dasselbe Feld unterschiedliche Werte.",
    recommendation: "Vergleiche die angezeigten Quellen und wähle nur dann einen Wert aus, wenn du seine fachliche Richtigkeit geprüft hast.",
    possibleCauses: ["Der Wert wurde nur in einem System geändert.", "Eine ältere Synchronisierung ist noch nicht abgeschlossen."],
  };
}

export function technicalValue(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? String(value);
}
