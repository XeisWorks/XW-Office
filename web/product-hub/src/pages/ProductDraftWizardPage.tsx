import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, ConflictApiError } from "../api/client";
import type { CoverConfiguration, CoverFontReadiness, CoverTemplate, OneDriveBrowseItem, ProductDraft, ProductDraftTemplate } from "../api/types";

export default function ProductDraftWizardPage({ onUnauthorized }: { onUnauthorized: () => void }) {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<ProductDraftTemplate[]>([]);
  const [draft, setDraft] = useState<ProductDraft | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [oneDriveItems, setOneDriveItems] = useState<OneDriveBrowseItem[]>([]);
  const [oneDriveTrail, setOneDriveTrail] = useState<OneDriveBrowseItem[]>([]);
  const [oneDriveLoading, setOneDriveLoading] = useState(false);
  const [coverTemplates, setCoverTemplates] = useState<CoverTemplate[]>([]);
  const [coverConfig, setCoverConfig] = useState<CoverConfiguration | null>(null);
  const [coverFontReadiness, setCoverFontReadiness] = useState<CoverFontReadiness | null>(null);
  const [coverThumbnailUrls, setCoverThumbnailUrls] = useState<Record<string, string>>({});
  const [coverLoading, setCoverLoading] = useState(false);
  const [coverError, setCoverError] = useState("");

  useEffect(() => { api.listDraftTemplates().then(setTemplates).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) onUnauthorized(); else setMessage("Vorlagen konnten nicht geladen werden.");
  }); }, [onUnauthorized]);

  async function loadOneDriveFolder(itemId?: string, trail: OneDriveBrowseItem[] = []) {
    setOneDriveLoading(true);
    try {
      setOneDriveItems(await api.listOneDriveChildren(itemId));
      setOneDriveTrail(trail);
      setMessage("");
    } catch (e) {
      setMessage(e instanceof Error ? `OneDrive konnte nicht geladen werden: ${e.message}` : "OneDrive konnte nicht geladen werden.");
    } finally { setOneDriveLoading(false); }
  }

  useEffect(() => {
    if (draft) void loadOneDriveFolder();
    // A new draft begins at the configured server root. Folder navigation calls
    // loadOneDriveFolder explicitly and does not get reset by autosave.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.id]);

  useEffect(() => {
    if (!draft?.id) return;
    let cancelled = false;
    const generatedUrls: string[] = [];
    async function loadCoverSetup() {
      setCoverLoading(true);
      try {
        const [configuration, templates, fontReadiness] = await Promise.all([
          api.getCoverConfiguration(), api.listCoverTemplates(), api.getCoverFontReadiness(),
        ]);
        const entries = await Promise.all(templates.map(async (template) => {
          const url = URL.createObjectURL(await api.getCoverTemplateThumbnail(template.item_id));
          generatedUrls.push(url);
          return [template.item_id, url] as const;
        }));
        if (cancelled) return;
        setCoverConfig(configuration);
        setCoverTemplates(templates);
        setCoverFontReadiness(fontReadiness);
        setCoverThumbnailUrls(Object.fromEntries(entries));
        setCoverError("");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) onUnauthorized();
        else setCoverError(e instanceof Error ? e.message : "Cover-Vorlagen konnten nicht geladen werden.");
      } finally {
        if (!cancelled) setCoverLoading(false);
      }
    }
    void loadCoverSetup();
    return () => { cancelled = true; generatedUrls.forEach((url) => URL.revokeObjectURL(url)); };
  }, [draft?.id, onUnauthorized]);

  async function start(templateCode = "") {
    try {
      const next = await api.createDraft({ template_code: templateCode, data: title ? { title_full: title } : {} });
      setDraft(next); setTitle(String(next.data.title_full ?? "")); setMessage("Entwurf gespeichert. Du kannst ihn später auf jedem Gerät fortsetzen.");
    } catch (e) { setMessage(e instanceof Error ? e.message : "Entwurf konnte nicht angelegt werden."); }
  }
  async function save(step: number, additions: Record<string, unknown> = {}) {
    if (!draft) return;
    try {
      setDraft(await api.saveDraft(draft.id, {
        expected_row_version: draft.row_version,
        current_step: step,
        completed_steps: [...new Set([...draft.completed_steps, step])],
        data: { ...draft.data, ...additions, title_full: title },
      }));
      setMessage("Gespeichert.");
    } catch (e) {
      if (e instanceof ConflictApiError) {
        const current = e.current as ProductDraft;
        setDraft(current); setTitle(String(current.data.title_full ?? ""));
        setMessage("Der Entwurf wurde anderswo geändert; der aktuelle Stand wurde geladen.");
      } else setMessage(e instanceof Error ? e.message : "Speichern fehlgeschlagen.");
    }
  }
  async function selectOneDriveFile(item: OneDriveBrowseItem) {
    await save(2, { source_asset: {
      provider: "onedrive", drive_id: item.drive_id, item_id: item.item_id,
      etag: item.etag, original_filename: item.name, size_bytes: item.size,
    } });
  }
  async function selectCoverTemplate(template: CoverTemplate) {
    await save(3, { cover_background: {
      provider: "onedrive", item_id: template.item_id, etag: template.etag,
      original_filename: template.name, size_bytes: template.size,
    } });
  }

  const selectedSource = draft?.data.source_asset;
  const selectedName = typeof selectedSource === "object" && selectedSource !== null
    ? String((selectedSource as Record<string, unknown>).original_filename ?? "") : "";
  const parentTrail = oneDriveTrail.slice(0, -1);
  const parentId = parentTrail.length ? parentTrail[parentTrail.length - 1].item_id : undefined;
  const selectedCover = draft?.data.cover_background;
  const selectedCoverId = typeof selectedCover === "object" && selectedCover !== null
    ? String((selectedCover as Record<string, unknown>).item_id ?? "") : "";

  return <section className="onboarding-page"><div className="onboarding-heading"><div><p className="eyebrow">Gemeinsamer Wizard</p><h1>Produktentwurf</h1><p className="hint">Unvollständige Angaben werden sicher gespeichert. Veröffentlichung startet erst nach vollständiger Prüfung.</p></div><button className="link-button" onClick={() => navigate("/products")}>Zurück</button></div>
    {!draft ? <div className="wizard-card"><label>Arbeitstitel <input value={title} onChange={(e) => setTitle(e.target.value)} /></label><div className="wizard-actions"><button className="primary-button" onClick={() => start()}>Leer beginnen</button>{templates.map((item) => <button key={item.code} onClick={() => start(item.code)}>{item.name}</button>)}</div></div> : <><div className="wizard-card"><p>Schritt {draft.current_step} von 7 · Version {draft.row_version}</p><label>Vollständiger Titel <input value={title} onChange={(e) => setTitle(e.target.value)} /></label><div className="wizard-actions"><button onClick={() => save(Math.min(7, draft.current_step + 1))}>Speichern & weiter</button><button className="primary-button" onClick={() => save(draft.current_step)}>Jetzt speichern</button></div></div><div className="wizard-card"><h2>Noten-PDF aus OneDrive</h2><p className="hint">Es werden nur Metadaten aus dem freigegebenen Produkt-Ordner angezeigt. Es gibt keinen öffentlichen PDF-Link.</p>{oneDriveTrail.length > 0 && <button onClick={() => { void loadOneDriveFolder(parentId, parentTrail); }}>Ordner zurück</button>}<p className="hint">{oneDriveTrail.map((item) => item.name).join(" / ") || "Stammordner"}</p>{oneDriveLoading ? <p>Lade OneDrive…</p> : <ul className="wizard-list">{oneDriveItems.map((item) => <li key={item.item_id}><button onClick={() => item.is_folder ? void loadOneDriveFolder(item.item_id, [...oneDriveTrail, item]) : void selectOneDriveFile(item)}>{item.is_folder ? "Ordner: " : "PDF: "}{item.name}</button>{!item.is_folder && <span className="hint"> ({Math.ceil(item.size / 1024)} KB)</span>}</li>)}</ul>}{selectedName && <p className="hint">Ausgewählt: {selectedName}. Die stabile OneDrive-Referenz wird beim Produktabschluss übernommen.</p>}</div></>}
    {draft && <div className="wizard-card"><h2>Coverhintergrund</h2><p className="hint">Vorlagen und Miniaturen bleiben im angemeldeten Wizard privat. Schild, Schatten und Balken werden nicht neu gezeichnet.</p>{coverLoading ? <p>Lade Cover-Vorlagen…</p> : <div className="wizard-actions">{coverTemplates.map((item) => <button key={item.item_id} onClick={() => void selectCoverTemplate(item)} className={selectedCoverId === item.item_id ? "primary-button" : ""}>{coverThumbnailUrls[item.item_id] && <img src={coverThumbnailUrls[item.item_id]} alt="" width={72} height={96} style={{ objectFit: "contain", verticalAlign: "middle", marginRight: 8 }} />}{item.name}</button>)}</div>}{coverConfig && <p className="hint">Ausgabe: {coverConfig.output_width_px} × {coverConfig.output_height_px} px, proportional skaliert.</p>}{coverFontReadiness && !coverFontReadiness.export_ready && <p className="error-message">Coverexport blockiert: Schrift fehlt ({coverFontReadiness.missing_families.join(", ")}). Der Entwurf bleibt speicherbar.</p>}{selectedCoverId && <p className="hint">Vorlage ausgewählt und im Entwurf gespeichert. Textsatz und finale Vorschau folgen im nächsten Schritt.</p>}{coverError && <p className="error-message">{coverError}</p>}</div>}
    {message && <p className="hint">{message}</p>}</section>;
}
