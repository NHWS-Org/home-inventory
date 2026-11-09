import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiBox, FiCheckSquare, FiArrowRight, FiCheck } from "react-icons/fi";
import {
  getInbox, markAllNotificationsRead, markNotificationRead, notificationAction, notificationDate,
  notificationItemName, notificationLink, notifyInboxChanged, type InboxNotification,
} from "../notificationsApi";

export function NotificationOpenLink({ row }: { row: InboxNotification }) {
  const kind = row.inventory_type === "CHECKLIST" ? "lista" : "inventario";
  return <Link to={notificationLink(row)} aria-label={`Apri ${kind} ${row.inventory_name}`} title={`Apri ${kind}`} className="inline-flex h-11 w-11 items-center justify-center rounded border text-blue-700 dark:text-blue-300"><FiArrowRight aria-hidden="true" /></Link>;
}

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
      <h1 id="notifications-heading" className="sr-only text-2xl font-bold md:not-sr-only">Centro notifiche</h1>
      <p className="text-sm">La lettura riguarda l'inbox. Non indica la consegna di una notifica push.</p>
      <div className="flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => void load()} className="min-h-11 rounded border px-3">Aggiorna</button>
        <button disabled={busy || !rows.length} onClick={() => void read()} className="min-h-11 rounded border px-3">Segna tutte come lette</button>
        <Link to="/profile" className="inline-flex min-h-11 items-center text-blue-700 underline dark:text-blue-300">Preferenze notifiche</Link>
      </div>
      {error && <p role="alert">{error}</p>}
      {busy && <p role="status">Caricamento...</p>}
      {!busy && !error && !rows.length && <p role="status">Nessuna notifica disponibile.</p>}
      <ul aria-label="Notifiche ricevute" className="space-y-2">
        {rows.map(row => (
          <li key={row.id} className={`flex items-start gap-2 rounded border p-2 ${!row.read_at ? "border-blue-500" : "border-gray-300 dark:border-gray-700"}`}>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="flex items-center gap-1.5 text-sm font-semibold">
                {row.inventory_type === "CHECKLIST" ? <FiCheckSquare className="shrink-0" aria-label="Lista" /> : <FiBox className="shrink-0" aria-label="Inventario" />}
                <span className="break-words">{row.inventory_name}</span>
              </p>
              <p title={notificationAction(row)} className="line-clamp-2 break-words text-sm [overflow-wrap:anywhere]">{notificationItemName(row) && <><span className="font-medium">{notificationItemName(row)}</span> · </>}{notificationAction(row)}</p>
              <p className="text-xs text-gray-600 dark:text-gray-400">
                <time dateTime={row.action_at ?? row.created_at}>{notificationDate(row).toLocaleString([], { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}</time>
                <span> · {row.read_at ? "Letta" : "Da leggere"}</span>
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <NotificationOpenLink row={row} />
              <button disabled={busy || !!row.read_at} aria-label={row.read_at ? "Già letta" : "Segna come letta"} title={row.read_at ? "Già letta" : "Segna come letta"} onClick={() => void read(row.id)} className={`inline-flex h-11 w-11 items-center justify-center rounded border ${row.read_at ? "cursor-default border-gray-300 bg-gray-100 text-gray-400 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-500" : ""}`}><FiCheck aria-hidden="true" /></button>
            </div>
          </li>
        ))}
      </ul>
      {more && <button disabled={busy} onClick={() => void load(offset)} className="min-h-11 rounded border px-3">Carica altre</button>}
    </section>
  );
}
