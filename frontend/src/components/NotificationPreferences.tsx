import { useEffect, useRef, useState } from "react";
import { getNotificationPreferences, notificationLabels, saveNotificationPreference, type NotificationPreference } from "../notificationsApi";

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
  async function toggle(row: NotificationPreference, field: "in_app_enabled" | "push_enabled" | "include_own_actions") {
    if (saving.current) return;
    saving.current = true;
    const next = { ...row, [field]: !row[field] };
    setRows(previous => previous.map(p => p.event_type === row.event_type ? next : p));
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await saveNotificationPreference(next);
      setNotice(`Preferenze salvate: ${notificationLabels[row.event_type]}.`);
    } catch {
      setRows(previous => previous.map(p => p.event_type === row.event_type ? row : p));
      setError("Salvataggio non riuscito: ripristinato il valore precedente. Tocca di nuovo per riprovare.");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <section aria-labelledby="notification-preferences-heading" className="space-y-2">
      <p className="text-sm">Tocca un parametro per attivarlo o disattivarlo: si salva automaticamente. Il push richiede anche il consenso browser nel pannello dedicato.</p>
      <p className="text-sm">Solo per inventari e liste che puoi modificare. Quantità e spunte sono notificate dopo 45 secondi dall'ultima modifica; i dettagli includono nome, descrizione, barcode e metadati. Le tue azioni sono escluse salvo scelta di "Mie azioni".</p>
      {loading && <p role="status">Caricamento...</p>}
      {error && <p role="alert">{error}</p>}
      {error && <button type="button" disabled={busy || loading} onClick={() => void load()} className="min-h-11 rounded border px-3">Ricarica preferenze</button>}
      {rows.map(row => (
        <fieldset key={row.event_type} disabled={busy || loading} className="rounded border px-2 pb-2">
          <legend className="font-semibold">{notificationLabels[row.event_type]}</legend>
          <div className="flex flex-wrap gap-2">
          {([
            ["in_app_enabled", "Inbox"],
            ["push_enabled", "Push"],
            ["include_own_actions", "Mie azioni"],
          ] as const).map(([field, label]) => (
            <label key={field} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded border px-3 text-sm ${row[field] ? "border-blue-500 bg-blue-50 dark:bg-blue-950" : "border-gray-300 dark:border-gray-700"} ${busy || loading ? "cursor-wait opacity-60" : ""}`}>
              <input type="checkbox" checked={row[field]} onChange={() => void toggle(row, field)} />
              {label}
            </label>
          ))}
          </div>
        </fieldset>
      ))}
      <p role="status" className="text-sm">{busy ? "Salvataggio..." : notice}</p>
    </section>
  );
}
