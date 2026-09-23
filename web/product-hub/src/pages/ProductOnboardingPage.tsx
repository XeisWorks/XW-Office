import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  ProductOnboardingOptions,
  ProductOnboardingRequest,
  ProductOnboardingResult,
} from "../api/types";

interface Props {
  onUnauthorized: () => void;
}

const INITIAL: ProductOnboardingRequest = {
  sku: "",
  name: "",
  product_type: "physical",
  price_gross: "",
  tax_rate: "10",
  sevdesk_category_id: "",
  sevdesk_category_name: "",
  brand_name: "XeisWorks",
  category: "",
  weight_grams: "",
};

export default function ProductOnboardingPage({ onUnauthorized }: Props) {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<ProductOnboardingRequest>(INITIAL);
  const [options, setOptions] = useState<ProductOnboardingOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [result, setResult] = useState<ProductOnboardingResult | null>(null);

  useEffect(() => {
    api.getProductOnboardingOptions().then(setOptions).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 401) onUnauthorized();
      else setOptionsError(error instanceof Error ? error.message : "sevDesk-Kategorien konnten nicht geladen werden.");
    });
  }, [onUnauthorized]);

  const selectedCategory = useMemo(
    () => options?.sevdesk_categories.find((item) => item.id === form.sevdesk_category_id),
    [options, form.sevdesk_category_id],
  );

  const basisValid = form.sku.trim().length > 0 && form.name.trim().length > 0;
  const commerceValid =
    form.price_gross !== "" && Number(form.price_gross) >= 0 &&
    form.tax_rate !== "" && Number(form.tax_rate) >= 0 && Number(form.tax_rate) <= 100 &&
    Boolean(form.sevdesk_category_id);

  function update<K extends keyof ProductOnboardingRequest>(key: K, value: ProductOnboardingRequest[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError("");
    try {
      const response = await api.onboardProduct({
        ...form,
        sku: form.sku.trim().toUpperCase(),
        name: form.name.trim(),
        sevdesk_category_name: selectedCategory?.name ?? form.sevdesk_category_name,
        ...(result && !result.complete ? { resume_product_id: result.product_id } : {}),
      });
      setResult(response);
      setStep(4);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized();
      else setSubmitError(error instanceof Error ? error.message : "Produkt konnte nicht angelegt werden.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="onboarding-page">
      <div className="onboarding-heading">
        <div>
          <p className="eyebrow">Geführte Anlage</p>
          <h1>Neues Produkt</h1>
          <p className="hint">Der Product Hub ist der Produktstamm. Wix wird unsichtbar angelegt; Bilder, Langtext und Shopgestaltung ergänzt du anschließend direkt in Wix.</p>
        </div>
        <button type="button" className="link-button" onClick={() => navigate("/products")}>Abbrechen</button>
      </div>

      <ol className="wizard-steps" aria-label="Fortschritt">
        {["Grunddaten", "Verkauf", "Prüfen", "Ergebnis"].map((label, index) => (
          <li key={label} className={step === index + 1 ? "active" : step > index + 1 ? "done" : ""}>
            <span>{index + 1}</span>{label}
          </li>
        ))}
      </ol>

      <form className="wizard-card" onSubmit={submit}>
        {step === 1 && (
          <fieldset>
            <legend>Was wird verkauft?</legend>
            <div className="form-grid">
              <label>SKU *<input autoFocus required value={form.sku} onChange={(e) => update("sku", e.target.value.toUpperCase())} placeholder="z. B. XW-123" /></label>
              <label>Produktname *<input required value={form.name} onChange={(e) => update("name", e.target.value)} /></label>
              <label>Produkttyp *<select value={form.product_type} onChange={(e) => update("product_type", e.target.value as "physical" | "digital")}><option value="physical">Physisch</option><option value="digital">Digital</option></select></label>
              <label>Marke<input value={form.brand_name ?? ""} onChange={(e) => update("brand_name", e.target.value)} /></label>
              <label>Interne Kategorie<input value={form.category ?? ""} onChange={(e) => update("category", e.target.value)} placeholder="optional" /></label>
              {form.product_type === "physical" && <label>Gewicht in Gramm<input type="number" min="0" step="0.001" value={form.weight_grams ?? ""} onChange={(e) => update("weight_grams", e.target.value)} placeholder="optional" /></label>}
            </div>
            <div className="wizard-actions"><button className="primary-button" type="button" disabled={!basisValid} onClick={() => setStep(2)}>Weiter</button></div>
          </fieldset>
        )}

        {step === 2 && (
          <fieldset>
            <legend>Preis und Buchhaltung</legend>
            <div className="form-grid">
              <label>Bruttopreis EUR *<input autoFocus required type="number" min="0" step="0.01" value={form.price_gross} onChange={(e) => update("price_gross", e.target.value)} /></label>
              <label>Umsatzsteuer *<select value={form.tax_rate} onChange={(e) => update("tax_rate", e.target.value)}><option value="10">10 %</option><option value="20">20 %</option><option value="0">0 %</option></select></label>
              <label>sevDesk-Kategorie *
                <select required value={form.sevdesk_category_id} disabled={!options} onChange={(e) => update("sevdesk_category_id", e.target.value)}>
                  <option value="">Bitte wählen</option>
                  {options?.sevdesk_categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
            </div>
            {optionsError && <p className="error-message">{optionsError}</p>}
            <div className="wizard-actions"><button type="button" onClick={() => setStep(1)}>Zurück</button><button className="primary-button" type="button" disabled={!commerceValid} onClick={() => setStep(3)}>Weiter</button></div>
          </fieldset>
        )}

        {step === 3 && (
          <fieldset>
            <legend>Produkt anlegen</legend>
            <dl className="review-grid">
              <div><dt>SKU</dt><dd>{form.sku}</dd></div><div><dt>Name</dt><dd>{form.name}</dd></div>
              <div><dt>Typ</dt><dd>{form.product_type === "digital" ? "Digital" : "Physisch"}</dd></div>
              <div><dt>Preis</dt><dd>{Number(form.price_gross).toLocaleString("de-AT", { style: "currency", currency: "EUR" })}</dd></div>
              <div><dt>USt.</dt><dd>{form.tax_rate} %</dd></div><div><dt>sevDesk</dt><dd>{selectedCategory?.name}</dd></div>
            </dl>
            <div className="publish-note"><strong>Danach in Wix ergänzen:</strong> Produktbilder, ausführliche Beschreibung, SEO, Kategorien/Collections und Sichtbarkeit. Das neue Wix-Produkt bleibt bis dahin verborgen.</div>
            {submitError && <p className="error-message">{submitError}</p>}
            <div className="wizard-actions"><button type="button" onClick={() => setStep(2)}>Zurück</button><button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Wird angelegt …" : "In Hub, sevDesk und Wix anlegen"}</button></div>
          </fieldset>
        )}

        {step === 4 && result && (
          <fieldset>
            <legend>{result.complete ? "Produkt wurde angelegt" : "Product Hub angelegt – Channel-Sync unvollständig"}</legend>
            <div className="channel-result-list">
              <div className="channel-result success"><strong>Product Hub</strong><span>{result.hub_state === "created" ? "Angelegt" : "Bereits angelegt"}</span></div>
              {result.channels.map((item) => <div key={item.channel} className={`channel-result ${item.state === "error" ? "failure" : "success"}`}><strong>{item.channel === "wix" ? "Wix (verborgen)" : "sevDesk"}</strong><span>{item.state === "error" ? item.message : item.state === "created" ? "Angelegt und verknüpft" : "Gefunden und verknüpft"}</span></div>)}
            </div>
            {!result.complete && <p className="hint">Du kannst den fehlgeschlagenen Sync sicher erneut ausführen. Bereits angelegte Datensätze werden über SKU bzw. Mapping wiederverwendet.</p>}
            <div className="wizard-actions">
              {!result.complete && <button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Erneuter Versuch …" : "Fehlenden Sync erneut versuchen"}</button>}
              <button type="button" onClick={() => navigate(`/products/${result.product_id}`)}>Produkt im Hub öffnen</button>
            </div>
          </fieldset>
        )}
      </form>
    </section>
  );
}
