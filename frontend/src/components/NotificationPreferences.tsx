import { useEffect, useRef, useState } from "react";
import { getNotificationPreferences, notificationLabels, notifyInboxChanged, saveNotificationPreference, type NotificationPreference } from "../notificationsApi";

export default function NotificationPreferences() {
  const [rows, setRows] = useState<NotificationPreference[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const saving = useRef(false);
  async function load() {
    setLoading(true);
    setError("");
    setNotice("");
    try { setRows(await getNotificationPreferences()); }
    catch { setError("Impossibile caricare le preferenze notifiche."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function changeMode(row: NotificationPreference, mode: string) {
    if (saving.current) return;
    saving.current = true;
    const next = { ...row, in_app_enabled: mode !== "off", push_enabled: mode === "inbox_push" };
    setRows(previous => previous.map(p => p.event_type === row.event_type ? next : p));
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await saveNotificationPreference(next);
      notifyInboxChanged();
      setNotice(`Preferenze salvate: ${notificationLabels[row.event_type]}.`);
    } catch {
      setRows(previous => previous.map(p => p.event_type === row.event_type ? row : p));
      setError("Salvataggio non riuscito: ripristinato il valore precedente. Seleziona di nuovo per riprovare.");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <section aria-labelledby="notification-preferences-heading" className="space-y-2">
      <p className="text-sm">Scegli Disattivate, Solo Inbox oppure Inbox + Push per ogni evento: si salva automaticamente. Il push richiede anche il consenso browser nel pannello dedicato.</p>
      <p className="text-sm">Solo per modifiche di altri utenti a inventari e liste che puoi modificare. Quantità e spunte sono notificate dopo 45 secondi dall'ultima modifica; i dettagli includono nome, descrizione, barcode e metadati.</p>
      {loading && <p role="status">Caricamento...</p>}
      {error && <p role="alert">{error}</p>}
      {error && <button type="button" disabled={busy || loading} onClick={() => void load()} className="min-h-11 rounded border px-3">Ricarica preferenze</button>}
      {rows.map(row => (
        <fieldset key={row.event_type} disabled={busy || loading} className="rounded border px-2 pb-2">
          <legend className="font-semibold">{notificationLabels[row.event_type]}</legend>
          <label className="block">
            <span className="sr-only">Ricezione notifiche: {notificationLabels[row.event_type]}</span>
            <select
              value={row.push_enabled ? "inbox_push" : row.in_app_enabled ? "inbox" : "off"}
              onChange={event => void changeMode(row, event.currentTarget.value)}
              className="min-h-11 w-full rounded border border-gray-300 bg-white px-3 text-sm disabled:opacity-60 dark:border-gray-700 dark:bg-gray-900"
            >
              <option value="off">Disattivate</option>
              <option value="inbox">Solo Inbox</option>
              <option value="inbox_push">Inbox + Push</option>
            </select>
          </label>
        </fieldset>
      ))}
      <p role="status" className="text-sm">{busy ? "Salvataggio..." : notice}</p>
    </section>
  );
}
