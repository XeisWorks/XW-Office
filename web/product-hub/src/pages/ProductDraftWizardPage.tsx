import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, ConflictApiError } from "../api/client";
import type { ProductDraft, ProductDraftTemplate } from "../api/types";

export default function ProductDraftWizardPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<ProductDraftTemplate[]>([]);
  const [draft, setDraft] = useState<ProductDraft | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => { api.listDraftTemplates().then(setTemplates).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) onUnauthorized(); else setMessage("Vorlagen konnten nicht geladen werden.");
  }); }, [onUnauthorized]);

  async function start(templateCode = "") {
    try {
      const next = await api.createDraft({ template_code: templateCode, data: title ? { title_full: title } : {} });
      setDraft(next); setTitle(String(next.data.title_full ?? "")); setMessage("Entwurf gespeichert. Du kannst ihn später auf jedem Gerät fortsetzen.");
    } catch (e) { setMessage(e instanceof Error ? e.message : "Entwurf konnte nicht angelegt werden."); }
  }
  async function save(step: number) {
    if (!draft) return;
    try { setDraft(await api.saveDraft(draft.id, { expected_row_version: draft.row_version, current_step: step, completed_steps: [...new Set([...draft.completed_steps, step])], data: { ...draft.data, title_full: title } })); setMessage("Gespeichert."); }
    catch (e) { if (e instanceof ConflictApiError) { const current = e.current as ProductDraft; setDraft(current); setTitle(String(current.data.title_full ?? "")); setMessage("Der Entwurf wurde anderswo geändert; der aktuelle Stand wurde geladen."); } else setMessage(e instanceof Error ? e.message : "Speichern fehlgeschlagen."); }
  }
  return <section className="onboarding-page"><div className="onboarding-heading"><div><p className="eyebrow">Gemeinsamer Wizard</p><h1>Produktentwurf</h1><p className="hint">Unvollständige Angaben werden sicher gespeichert. Veröffentlichung startet erst nach vollständiger Prüfung.</p></div><button className="link-button" onClick={() => navigate("/products")}>Zurück</button></div>
    {!draft ? <div className="wizard-card"><label>Arbeitstitel <input value={title} onChange={(e) => setTitle(e.target.value)} /></label><div className="wizard-actions"><button className="primary-button" onClick={() => start()}>Leer beginnen</button>{templates.map((item) => <button key={item.code} onClick={() => start(item.code)}>{item.name}</button>)}</div></div> : <div className="wizard-card"><p>Schritt {draft.current_step} von 7 · Version {draft.row_version}</p><label>Vollständiger Titel <input value={title} onChange={(e) => setTitle(e.target.value)} /></label><div className="wizard-actions"><button onClick={() => save(Math.min(7, draft.current_step + 1))}>Speichern & weiter</button><button className="primary-button" onClick={() => save(draft.current_step)}>Jetzt speichern</button></div></div>}
    {message && <p className="hint">{message}</p>}</section>;
}
