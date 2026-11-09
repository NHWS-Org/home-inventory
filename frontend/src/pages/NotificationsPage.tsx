import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiBox, FiCheckSquare, FiArrowRight, FiCheck, FiTrash2 } from "react-icons/fi";
import {
  changeNotifications, deleteNotification, getInbox, markNotificationRead, notificationAction, notificationDate,
  notificationIndicator, notificationItemName, notificationLink, notifyInboxChanged, type InboxNotification,
} from "../notificationsApi";

export function NotificationOpenLink({ row }: { row: InboxNotification }) {
  const kind = row.inventory_type === "CHECKLIST" ? "lista" : "inventario";
  return <Link to={notificationLink(row)} aria-label={`Apri ${kind} ${row.inventory_name}`} title={`Apri ${kind}`} className="inline-flex h-11 w-11 items-center justify-center rounded border text-blue-700 dark:text-blue-300"><FiArrowRight aria-hidden="true" /></Link>;
}

export function NotificationSummary({ row }: { row: InboxNotification }) {
  const indicator = notificationIndicator(row);
  const name = notificationItemName(row);
  const action = notificationAction(row);
  return <p title={[indicator.label, name, action].filter(Boolean).join(" · ")} className="line-clamp-2 break-words text-sm [overflow-wrap:anywhere]">
    <span role="img" aria-label={indicator.label} className="mr-1 whitespace-nowrap">{indicator.symbol}</span>
    {name && <span className="font-medium">{name}</span>}
    {name && action && " · "}{action}
  </p>;
}

export default function NotificationsPage() {
  const [rows, setRows] = useState<InboxNotification[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [allSelected, setAllSelected] = useState(false);
  const [message, setMessage] = useState("");
  const hasSelection = allSelected || selected.size > 0;
  const visibleSelected = rows.filter(row => selected.has(row.id)).length;
  const load = useCallback(async (nextOffset = 0) => {
    setBusy(true);
    setError("");
    try {
      const next = await getInbox(nextOffset);
      setRows(previous => nextOffset ? [...previous, ...next.filter(row => !previous.some(p => p.id === row.id))] : next);
      setOffset(nextOffset + next.length);
      setMore(next.length === 50);
      if (!nextOffset) {
        setSelected(new Set());
        setAllSelected(false);
      }
      notifyInboxChanged();
    } catch {
      setError("Impossibile caricare le notifiche. Riprova.");
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  function toggle(id: number) {
    const next = allSelected ? new Set(rows.map(row => row.id)) : new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setAllSelected(false);
    setSelected(next);
  }

  async function act(action: "read" | "delete", target?: number | "all") {
    const all = target === "all" || (target === undefined && allSelected);
    if (action === "delete" && !window.confirm(
      all ? "Eliminare definitivamente tutte le tue notifiche, anche quelle non caricate?"
        : target !== undefined ? "Eliminare definitivamente questa notifica?"
          : `Eliminare definitivamente le ${selected.size} notifiche selezionate?`,
    )) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (typeof target === "number") {
        if (action === "read") await markNotificationRead(target);
        else await deleteNotification(target);
        setMessage(action === "read" ? "Notifica segnata come letta." : "Notifica eliminata.");
      } else {
        const updated = await changeNotifications(action, all ? { all: true } : { ids: [...selected] });
        setMessage(action === "read" ? `${updated} notifiche segnate come lette.` : `${updated} notifiche eliminate.`);
      }
      setSelected(new Set());
      setAllSelected(false);
      notifyInboxChanged();
      // Reload authorized data: access may have changed since the page was opened.
      const next = await getInbox();
      setRows(next);
      setOffset(next.length);
      setMore(next.length === 50);
    } catch {
      setError("Operazione non completata o elenco non aggiornato. Aggiorna l'elenco e riprova.");
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
        <button disabled={busy || !rows.length} onClick={() => void act("read", "all")} className="min-h-11 rounded border px-3">Segna tutte come lette</button>
        <Link to="/profile" className="inline-flex min-h-11 items-center text-blue-700 underline dark:text-blue-300">Preferenze notifiche</Link>
      </div>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Selezione notifiche">
        <label className="inline-flex min-h-11 items-center gap-2 rounded border px-3">
          <input type="checkbox" disabled={busy || !rows.length}
            checked={rows.length > 0 && (allSelected || visibleSelected === rows.length)}
            ref={input => { if (input) input.indeterminate = !allSelected && visibleSelected > 0 && visibleSelected < rows.length; }}
            onChange={event => {
              setAllSelected(false);
              setSelected(event.target.checked ? new Set(rows.map(row => row.id)) : new Set());
            }} />Seleziona visibili
        </label>
        <button disabled={busy || !rows.length} onClick={() => { setAllSelected(true); setSelected(new Set()); }} className="min-h-11 rounded border px-3">Seleziona tutte (anche non caricate)</button>
        {hasSelection && <button disabled={busy} onClick={() => { setSelected(new Set()); setAllSelected(false); }} className="min-h-11 rounded border px-3">Annulla selezione</button>}
        <span role="status" className="text-sm">{allSelected ? "Tutte le notifiche selezionate" : `${selected.size} selezionate`}</span>
        <button disabled={busy || !hasSelection} onClick={() => void act("read")} className="min-h-11 rounded border px-3">Segna selezionate come lette</button>
        <button disabled={busy || !hasSelection} onClick={() => void act("delete")} className="min-h-11 rounded border border-red-600 px-3 text-red-700 dark:text-red-300">Elimina selezionate</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {busy && <p role="status">Caricamento...</p>}
      {!busy && !error && !rows.length && <p role="status">Nessuna notifica disponibile.</p>}
      <ul aria-label="Notifiche ricevute" className="space-y-2">
        {rows.map(row => (
          <li key={row.id} className={`flex items-start gap-2 rounded border p-2 ${!row.read_at ? "border-blue-500" : "border-gray-300 dark:border-gray-700"}`}>
            <label className="inline-flex h-11 min-w-8 items-center justify-center">
              <input type="checkbox" disabled={busy} checked={allSelected || selected.has(row.id)}
                onChange={() => toggle(row.id)} aria-label={`Seleziona notifica: ${notificationItemName(row) ?? row.inventory_name}, ${notificationIndicator(row).label}`} />
            </label>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="flex items-center gap-1.5 text-sm font-semibold">
                {row.inventory_type === "CHECKLIST" ? <FiCheckSquare className="shrink-0" aria-label="Lista" /> : <FiBox className="shrink-0" aria-label="Inventario" />}
                <span className="break-words">{row.inventory_name}</span>
              </p>
              <NotificationSummary row={row} />
              <p className="text-xs text-gray-600 dark:text-gray-400">
                <time dateTime={row.action_at ?? row.created_at}>{notificationDate(row).toLocaleString([], { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}</time>
                <span> · {row.read_at ? "Letta" : "Da leggere"}</span>
              </p>
            </div>
            <div className="grid shrink-0 grid-cols-2 gap-1 sm:grid-cols-3">
              <NotificationOpenLink row={row} />
              <button disabled={busy || !!row.read_at} aria-label={row.read_at ? "Già letta" : "Segna come letta"} title={row.read_at ? "Già letta" : "Segna come letta"} onClick={() => void act("read", row.id)} className={`inline-flex h-11 w-11 items-center justify-center rounded border ${row.read_at ? "cursor-default border-gray-300 bg-gray-100 text-gray-400 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-500" : ""}`}><FiCheck aria-hidden="true" /></button>
              <button disabled={busy} aria-label="Elimina notifica" title="Elimina notifica" onClick={() => void act("delete", row.id)} className="inline-flex h-11 w-11 items-center justify-center rounded border text-red-700 dark:text-red-300"><FiTrash2 aria-hidden="true" /></button>
            </div>
          </li>
        ))}
      </ul>
      {more && <button disabled={busy} onClick={() => void load(offset)} className="min-h-11 rounded border px-3">Carica altre</button>}
    </section>
  );
}
