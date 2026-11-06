import { useEffect, useState } from "react";
import { getNotificationPreferences, notificationLabels, saveNotificationPreference, type NotificationPreference } from "../notificationsApi";

export default function NotificationPreferences() {
  const [rows, setRows] = useState<NotificationPreference[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function load() {
    setLoading(true);
    setError("");
    setNotice("");
    try { setRows(await getNotificationPreferences()); }
    catch { setError("Impossibile caricare le preferenze notifiche."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  async function save(row: NotificationPreference) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await saveNotificationPreference(row);
      setNotice(`Preferenze salvate: ${notificationLabels[row.event_type]}.`);
    } catch { setError("Salvataggio non riuscito. Le modifiche non sono confermate; riprova."); }
    finally { setBusy(false); }
  }
  return (
    <section aria-labelledby="notification-preferences-heading" className="space-y-3">
      <h2 id="notification-preferences-heading" className="text-xl font-bold">Preferenze notifiche</h2>
      <p className="text-sm">Inbox attiva di default, push solo su consenso. Abilitare un evento push non concede il permesso al browser: usa il pannello dedicato.</p>
      {loading && <p role="status">Caricamento...</p>}
      {error && <p role="alert">{error}</p>}
      <button disabled={busy || loading} onClick={() => void load()} className="min-h-11 rounded border px-3">Ricarica preferenze</button>
      {rows.map(row => (
        <fieldset key={row.event_type} disabled={busy || loading} className="space-y-2 rounded border p-3">
          <legend className="font-semibold">{notificationLabels[row.event_type]}</legend>
          {([
            ["in_app_enabled", "Centro notifiche"],
            ["push_enabled", "Push sui browser abilitati"],
            ["include_own_actions", "Includi le mie azioni"],
          ] as const).map(([field, label]) => (
            <label key={field} className="flex min-h-11 items-center gap-2">
              <input type="checkbox" checked={row[field]} onChange={event => setRows(previous => previous.map(p => p.event_type === row.event_type ? { ...p, [field]: event.target.checked } : p))} />
              {label}
            </label>
          ))}
          <button onClick={() => void save(row)} className="min-h-11 rounded border px-3">Salva {notificationLabels[row.event_type]}</button>
        </fieldset>
      ))}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
