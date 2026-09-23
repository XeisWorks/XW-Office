import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { ProductDetail, ProductOnboardingOptions, ProductOnboardingResult, ProductVariant, VariantOnboardingRequest } from "../api/types";

interface Props { onUnauthorized: () => void }

function inferredExistingChoice(product: ProductDetail, variants: ProductVariant[]): string {
  const firstOptions = variants[0]?.option_values ?? {};
  const firstValue = Object.values(firstOptions).find((value) => typeof value === "string");
  if (typeof firstValue === "string") return firstValue;
  const music = product.attributes?.music_attributes;
  if (music && typeof music === "object") {
    const scoring = (music as Record<string, unknown>).scoring;
    if (typeof scoring === "string") return scoring;
  }
  const scoring = product.attributes?.scoring;
  return typeof scoring === "string" ? scoring : "";
}

export default function VariantOnboardingPage({ onUnauthorized }: Props) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [product, setProduct] = useState<ProductDetail | null>(null);
  const [options, setOptions] = useState<ProductOnboardingOptions | null>(null);
  const [form, setForm] = useState<VariantOnboardingRequest>({
    sku: "", name: "Kleine Besetzung", option_name: "Besetzung",
    option_value: "Kleine Besetzung", existing_default_option_value: "",
    price_gross: "", tax_rate: "10", sevdesk_category_id: "", sevdesk_category_name: "",
    weight_grams: "",
  });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ProductOnboardingResult | null>(null);

  useEffect(() => {
    Promise.all([api.getProduct(id), api.getVariants(id), api.getProductOnboardingOptions()])
      .then(([loadedProduct, loadedVariants, loadedOptions]) => {
        setProduct(loadedProduct); setOptions(loadedOptions);
        setForm((current) => ({ ...current,
          existing_default_option_value: inferredExistingChoice(loadedProduct, loadedVariants),
          weight_grams: loadedVariants[0]?.weight_grams ?? "",
        }));
      })
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 401) onUnauthorized();
        else setError(reason instanceof Error ? reason.message : "Daten konnten nicht geladen werden.");
      }).finally(() => setLoading(false));
  }, [id, onUnauthorized]);

  const selectedCategory = useMemo(() => options?.sevdesk_categories.find((item) => item.id === form.sevdesk_category_id), [options, form.sevdesk_category_id]);
  function update<K extends keyof VariantOnboardingRequest>(key: K, value: VariantOnboardingRequest[K]) { setForm((current) => ({ ...current, [key]: value })); }

  async function submit(event: FormEvent) {
    event.preventDefault(); setSubmitting(true); setError("");
    try {
      const response = await api.onboardVariant(id, { ...form,
        sku: form.sku.trim().toUpperCase(), sevdesk_category_name: selectedCategory?.name ?? "",
        weight_grams: product?.product_type === "digital" || form.weight_grams === ""
          ? undefined : form.weight_grams,
        ...(result && !result.complete ? { resume_variant_id: result.variant_id } : {}),
      });
      setResult(response);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onUnauthorized();
      else setError(reason instanceof Error ? reason.message : "Variante konnte nicht angelegt werden.");
    } finally { setSubmitting(false); }
  }

  if (loading) return <p className="hint">Wird geladen …</p>;
  return <section className="onboarding-page">
    <p><Link to={`/products/${id}`}>&larr; zurück zu {product?.name ?? "Produkt"}</Link></p>
    <div className="onboarding-heading"><div><p className="eyebrow">Bestehendes Produkt</p><h1>Variante zu {product?.name}</h1><p className="hint">Die neue Variante erhält eine eigene SKU und einen eigenen Preis, bleibt aber in Wix unter demselben Produkt.</p></div></div>
    <form className="wizard-card" onSubmit={submit}>
      {!result || !result.complete ? <fieldset>
        <legend>Varianten- und Verkaufsdaten</legend>
        <div className="form-grid">
          <label>Neue SKU *<input required value={form.sku} onChange={(e) => update("sku", e.target.value.toUpperCase())} /></label>
          <label>Variantenname *<input required value={form.name} onChange={(e) => update("name", e.target.value)} /></label>
          <label>Wix-Option *<input required value={form.option_name} onChange={(e) => update("option_name", e.target.value)} /></label>
          <label>Neue Auswahl *<input required value={form.option_value} onChange={(e) => update("option_value", e.target.value)} /></label>
          <label>Bezeichnung der bestehenden Variante *<input required value={form.existing_default_option_value} onChange={(e) => update("existing_default_option_value", e.target.value)} placeholder="z. B. 7-stimmig" /><small>Wird benötigt, falls Wix bisher nur eine Standardvariante hat.</small></label>
          <label>Bruttopreis EUR *<input required type="number" min="0" step="0.01" value={form.price_gross} onChange={(e) => update("price_gross", e.target.value)} /></label>
          <label>Umsatzsteuer *<select value={form.tax_rate} onChange={(e) => update("tax_rate", e.target.value)}><option value="10">10 %</option><option value="20">20 %</option><option value="0">0 %</option></select></label>
          <label>sevDesk-Kategorie *<select required value={form.sevdesk_category_id} onChange={(e) => update("sevdesk_category_id", e.target.value)}><option value="">Bitte wählen</option>{options?.sevdesk_categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          {product?.product_type !== "digital" && <label>Gewicht in Gramm<input type="number" min="0" step="0.001" value={form.weight_grams ?? ""} onChange={(e) => update("weight_grams", e.target.value)} /></label>}
        </div>
        <div className="publish-note"><strong>Wix:</strong> „{form.option_name || "Option"}“ wird um „{form.option_value || "neue Auswahl"}“ erweitert. Bestehende Varianten werden vollständig mitgesendet und nicht überschrieben.</div>
        {result && !result.complete && <div className="channel-result-list">{result.channels.map((item) => <div key={item.channel} className={`channel-result ${item.state === "error" ? "failure" : "success"}`}><strong>{item.channel}</strong><span>{item.state === "error" ? item.message : "Erfolgreich"}</span></div>)}</div>}
        {error && <p className="error-message">{error}</p>}
        <div className="wizard-actions"><button type="button" onClick={() => navigate(`/products/${id}`)}>Abbrechen</button><button className="primary-button" disabled={submitting}>{submitting ? "Wird synchronisiert …" : result ? "Fehlenden Sync erneut versuchen" : "Variante in Hub, sevDesk und Wix anlegen"}</button></div>
      </fieldset> : <fieldset><legend>Variante wurde angelegt</legend><div className="channel-result-list"><div className="channel-result success"><strong>Product Hub</strong><span>{result.sku}</span></div>{result.channels.map((item) => <div key={item.channel} className="channel-result success"><strong>{item.channel}</strong><span>Verknüpft</span></div>)}</div><div className="wizard-actions"><button type="button" className="primary-button" onClick={() => navigate(`/products/${id}`)}>Produkt öffnen</button></div></fieldset>}
    </form>
  </section>;
}
