import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getInbox, markAllNotificationsRead, markNotificationRead, notificationLabels,
  notificationLink, notifyInboxChanged, type InboxNotification,
} from "../notificationsApi";

export default function NotificationsPage() {
  const [rows, setRows] = useState<InboxNotification[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async (nextOffset = 0) => {
    setBusy(true);
    setError("");
    try {
      const next = await getInbox(nextOffset);
      setRows(previous => nextOffset ? [...previous, ...next.filter(row => !previous.some(p => p.id === row.id))] : next);
      setOffset(nextOffset + next.length);
      setMore(next.length === 50);
      notifyInboxChanged();
    } catch {
      setError("Impossibile caricare le notifiche. Riprova.");
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function read(id?: number) {
    setBusy(true);
    setError("");
    try {
      if (id === undefined) await markAllNotificationsRead();
      else await markNotificationRead(id);
      notifyInboxChanged();
      // Reload authorized data: access may have changed since the page was opened.
      const next = await getInbox();
      setRows(next);
      setOffset(next.length);
      setMore(next.length === 50);
    } catch {
      setError("Lettura non aggiornata o accesso revocato. Aggiorna l'elenco e riprova.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-labelledby="notifications-heading" aria-busy={busy} className="space-y-4 p-4">
      <h1 id="notifications-heading" className="text-2xl font-bold">Centro notifiche</h1>
      <p className="text-sm">La lettura riguarda l'inbox. Non indica la consegna di una notifica push.</p>
      <div className="flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => void load()} className="min-h-11 rounded border px-3">Aggiorna</button>
        <button disabled={busy || !rows.length} onClick={() => void read()} className="min-h-11 rounded border px-3">Segna tutte come lette</button>
        <Link to="/profile" className="inline-flex min-h-11 items-center text-blue-700 underline dark:text-blue-300">Preferenze notifiche</Link>
      </div>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">Caricamento...</p>}
      {!busy && !error && !rows.length && <p role="status">Nessuna notifica disponibile.</p>}
      <ul aria-label="Notifiche ricevute" className="space-y-3">
        {rows.map(row => (
          <li key={row.id} className={`space-y-2 rounded border p-3 ${!row.read_at ? "border-blue-500" : "border-gray-300 dark:border-gray-700"}`}>
            <p className="font-semibold">{notificationLabels[row.event.event_type]} — {row.inventory_name}</p>
            <p>{row.read_at ? "Letta" : "Da leggere"} · {new Date(row.created_at + (row.created_at.endsWith("Z") ? "" : "Z")).toLocaleString()}</p>
            {row.event.event_type === "item_quantity_changed" && <p>Quantità: {row.event.previous_quantity} → {row.event.quantity}</p>}
            <div className="flex flex-wrap items-center gap-3">
              <Link to={notificationLink(row)} className="inline-flex min-h-11 items-center text-blue-700 underline dark:text-blue-300">Apri contenitore</Link>
              {!row.read_at && <button disabled={busy} onClick={() => void read(row.id)} className="min-h-11 rounded border px-3">Segna come letta</button>}
            </div>
          </li>
        ))}
      </ul>
      {more && <button disabled={busy} onClick={() => void load(offset)} className="min-h-11 rounded border px-3">Carica altre</button>}
    </section>
  );
}
