import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { FiArrowRight, FiBell, FiBox, FiCheck, FiCheckSquare, FiLayers, FiMoreHorizontal, FiRefreshCw, FiSettings, FiTrash2, FiX } from "react-icons/fi";
import {
  changeNotifications, deleteNotification, getInbox, getUnreadCount, markNotificationRead, notificationAction, notificationDate,
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


const GROUP_KEY = "notifications.groupByContainer";
const iconButtonBase = "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border transition-colors disabled:opacity-40";
const iconButton = `${iconButtonBase} border-gray-200 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200 dark:hover:bg-gray-800`;
const iconButtonActive = `${iconButtonBase} border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-300 dark:hover:bg-blue-900`;
const selectionButtonBase = `${iconButtonBase} border-slate-500 bg-slate-700 hover:border-slate-300 hover:bg-slate-600 disabled:hover:border-slate-500 disabled:hover:bg-slate-700`;
const selectionButton = `${selectionButtonBase} text-white`;
const selectionDangerButton = `${selectionButtonBase} text-red-300 hover:text-red-200`;
const rowAction = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40 dark:border-gray-700 dark:bg-gray-900 dark:hover:bg-gray-800";

function shortDate(row: InboxNotification): string {
  const date = notificationDate(row);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return date.toDateString() === new Date().toDateString()
    ? time : `${date.toLocaleDateString([], { day: "2-digit", month: "2-digit" })} ${time}`;
}

function containerLink(row: InboxNotification): string {
  return `/${row.inventory_type === "CHECKLIST" ? "checklists" : "inventories"}/${row.event.inventory_id}`;
}

function ContainerIcon({ row }: { row: InboxNotification }) {
  const Icon = row.event.event_type === "filter_trigger_matched" ? FiBell : row.inventory_type === "CHECKLIST" ? FiCheckSquare : FiBox;
  const label = row.event.event_type === "filter_trigger_matched" ? "Avviso da trigger" : row.inventory_type === "CHECKLIST" ? "Lista" : "Inventario";
  return <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"><Icon role="img" aria-label={label} /></span>;
}

function MoreMenu({ label, children }: { label: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => { if (!ref.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  return <div ref={ref} className="relative">
    <button type="button" aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(value => !value)} className={iconButton}><FiMoreHorizontal aria-hidden="true" /></button>
    {open && <div role="menu" aria-label={label} className="absolute right-0 top-11 z-30 w-64 rounded-xl border border-gray-200 bg-white p-1.5 text-sm shadow-xl dark:border-gray-700 dark:bg-gray-900">{children(() => setOpen(false))}</div>}
  </div>;
}
const menuItem = "flex min-h-11 w-full items-center gap-3 rounded-lg px-3 text-left hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-gray-800";

interface RowProps {
  row: InboxNotification;
  compact?: boolean;
  busy: boolean;
  selecting: boolean;
  checked: boolean;
  onToggle: () => void;
  onLongPress: () => void;
  onRead: () => void;
  onDelete: () => void;
}

function NotificationRow({ row, compact, busy, selecting, checked, onToggle, onLongPress, onRead, onDelete }: RowProps) {
  const [dx, setDx] = useState(0);
  const touch = useRef<{ x: number; y: number; axis?: "h" | "v"; timer: number } | null>(null);
  const suppressClick = useRef(false);
  const unread = !row.read_at;
  const name = notificationItemName(row) ?? row.inventory_name;
  const end = () => {
    if (touch.current) window.clearTimeout(touch.current.timer);
    touch.current = null;
    if (dx <= -80) onDelete();
    else if (dx >= 80 && unread) onRead();
    if (Math.abs(dx) > 8) suppressClick.current = true;
    setDx(0);
  };
  return (
    <li className="group relative overflow-hidden border-b border-gray-100 dark:border-gray-800">
      {dx !== 0 && <div aria-hidden="true" className={`absolute inset-0 flex items-center px-5 text-sm font-semibold text-white ${dx < 0 ? "justify-end bg-red-600" : "justify-start bg-green-600"}`}>
        {dx < 0 ? <><FiTrash2 className="mr-2" />Elimina</> : <><FiCheck className="mr-2" />Letta</>}
      </div>}
      <div
        style={{ transform: dx ? `translateX(${dx}px)` : undefined, touchAction: "pan-y" }}
        className={`relative flex items-start gap-2.5 ${compact ? "py-2 pl-5 pr-3" : "p-3"} ${unread ? "bg-blue-50 dark:bg-blue-950/40" : "bg-white dark:bg-gray-900"} ${dx ? "" : "transition-transform"}`}
        onTouchStart={event => {
          if (selecting || busy) return;
          const point = event.touches[0];
          touch.current = { x: point.clientX, y: point.clientY, timer: window.setTimeout(() => {
            suppressClick.current = true;
            touch.current = null;
            onLongPress();
          }, 550) };
        }}
        onTouchMove={event => {
          const start = touch.current;
          if (!start) return;
          const point = event.touches[0];
          const mx = point.clientX - start.x;
          const my = point.clientY - start.y;
          if (!start.axis && Math.max(Math.abs(mx), Math.abs(my)) > 8) {
            window.clearTimeout(start.timer);
            start.axis = Math.abs(mx) > Math.abs(my) ? "h" : "v";
          }
          if (start.axis === "h") setDx(Math.max(-120, Math.min(unread ? 120 : 0, mx)));
        }}
        onTouchEnd={end}
        onTouchCancel={() => { if (touch.current) window.clearTimeout(touch.current.timer); touch.current = null; setDx(0); }}
      >
        <label className={`${selecting ? "inline-flex" : "hidden md:inline-flex"} h-9 w-6 shrink-0 items-center justify-center`}>
          <input type="checkbox" disabled={busy} checked={checked} onChange={onToggle}
            aria-label={`Seleziona notifica: ${name}, ${notificationIndicator(row).label}`} className="h-4 w-4" />
        </label>
        <span aria-hidden="true" className={`mt-3.5 h-2 w-2 shrink-0 rounded-full ${unread ? "bg-blue-600" : "bg-transparent"}`} />
        <Link
          to={notificationLink(row)}
          aria-label={`${unread ? "Da leggere: " : ""}${row.inventory_name} · ${name} · ${notificationAction(row)}`}
          onClick={event => {
            if (suppressClick.current) { suppressClick.current = false; event.preventDefault(); return; }
            if (selecting) { event.preventDefault(); onToggle(); }
          }}
          className="flex min-w-0 flex-1 items-start gap-3 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
        >
          {!compact && <ContainerIcon row={row} />}
          <span className="min-w-0 flex-1">
            {!compact && <span className="block truncate text-xs font-semibold text-gray-600 dark:text-gray-300">{row.inventory_name}</span>}
            <NotificationSummary row={row} />
          </span>
          <time dateTime={row.action_at ?? row.created_at} className="shrink-0 pt-0.5 text-xs text-gray-500 dark:text-gray-400">{shortDate(row)}</time>
        </Link>
        <div className="sr-only flex gap-1 focus-within:not-sr-only md:not-sr-only md:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100">
          {unread && <button type="button" disabled={busy} aria-label="Segna come letta" title="Segna come letta" onClick={onRead} className={rowAction}><FiCheck aria-hidden="true" /></button>}
          <button type="button" disabled={busy} aria-label="Elimina notifica" title="Elimina notifica" onClick={onDelete} className={`${rowAction} text-red-700 dark:text-red-300`}><FiTrash2 aria-hidden="true" /></button>
        </div>
      </div>
    </li>
  );
}

export default function NotificationsPage() {
  const [rows, setRows] = useState<InboxNotification[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [allSelected, setAllSelected] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [message, setMessage] = useState("");
  const [view, setView] = useState<"unread" | "all">("unread");
  const [unreadCount, setUnreadCount] = useState<number | null>(null);
  const [grouped, setGrouped] = useState(() => localStorage.getItem(GROUP_KEY) === "1");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const unreadOnly = view === "unread";
  const hasSelection = allSelected || selected.size > 0;
  const selecting = selectMode || hasSelection;
  const visibleSelected = rows.filter(row => allSelected || selected.has(row.id)).length;

  const groups = useMemo(() => {
    const map = new Map<number, InboxNotification[]>();
    for (const row of rows) map.set(row.event.inventory_id, [...(map.get(row.event.inventory_id) ?? []), row]);
    return [...map.values()];
  }, [rows]);

  const refreshCount = useCallback(async () => {
    try { setUnreadCount(await getUnreadCount()); } catch { setUnreadCount(null); }
  }, []);

  const replaceRows = useCallback(async (onlyUnread: boolean) => {
    const next = await getInbox(0, onlyUnread);
    setRows(next);
    setOffset(next.length);
    setMore(next.length === 50);
  }, []);

  const load = useCallback(async (nextOffset = 0) => {
    setBusy(true);
    setError("");
    try {
      if (nextOffset) {
        const next = await getInbox(nextOffset, unreadOnly);
        setRows(previous => [...previous, ...next.filter(row => !previous.some(p => p.id === row.id))]);
        setOffset(nextOffset + next.length);
        setMore(next.length === 50);
      } else {
        await replaceRows(unreadOnly);
        setSelected(new Set());
        setAllSelected(false);
        setSelectMode(false);
      }
      void refreshCount();
      notifyInboxChanged();
    } catch {
      setError("Impossibile caricare le notifiche. Riprova.");
    } finally {
      setBusy(false);
    }
  }, [unreadOnly, replaceRows, refreshCount]);
  useEffect(() => { void load(); }, [load]);

  function toggleGrouped() {
    const next = !grouped;
    localStorage.setItem(GROUP_KEY, next ? "1" : "0");
    setGrouped(next);
  }

  function setChecked(ids: number[], checked: boolean) {
    const next = allSelected ? new Set(rows.map(row => row.id)) : new Set(selected);
    for (const id of ids) {
      if (checked) next.add(id);
      else next.delete(id);
    }
    setAllSelected(false);
    setSelected(next);
  }

  function clearSelection() {
    setSelected(new Set());
    setAllSelected(false);
    setSelectMode(false);
  }

  async function act(action: "read" | "delete", target?: number | number[] | "all", label?: string) {
    const all = target === "all" || (target === undefined && allSelected);
    const ids = Array.isArray(target) ? target : typeof target === "number" ? [target] : [...selected];
    const scope = unreadOnly && target === undefined ? " da leggere" : "";
    if (action === "delete" && !window.confirm(
      all ? `Eliminare definitivamente tutte le tue notifiche${scope}, anche quelle non caricate?`
        : typeof target === "number" ? "Eliminare definitivamente questa notifica?"
          : label ? `Eliminare definitivamente le ${ids.length} notifiche di ${label}?`
            : `Eliminare definitivamente le ${ids.length} notifiche selezionate?`,
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
        const updated = await changeNotifications(action, all
          ? { all: true, ...(unreadOnly && target === undefined ? { unread_only: true } : {}) }
          : { ids });
        setMessage(action === "read" ? `${updated} notifiche segnate come lette.` : `${updated} notifiche eliminate.`);
      }
      clearSelection();
      notifyInboxChanged();
      // Reload authorized data: access may have changed since the page was opened.
      await replaceRows(unreadOnly);
      void refreshCount();
    } catch {
      setError("Operazione non completata o elenco non aggiornato. Aggiorna l'elenco e riprova.");
    } finally {
      setBusy(false);
    }
  }

  const visibleCheckbox = (className: string) => (
    <label className={className} title="Seleziona visibili">
      <input type="checkbox" disabled={busy || !rows.length} aria-label="Seleziona visibili" className="h-4 w-4"
        checked={rows.length > 0 && visibleSelected === rows.length}
        ref={input => { if (input) input.indeterminate = !allSelected && visibleSelected > 0 && visibleSelected < rows.length; }}
        onChange={event => {
          setAllSelected(false);
          setSelectMode(true);
          setSelected(event.target.checked ? new Set(rows.map(row => row.id)) : new Set());
        }} />
    </label>
  );

  const rowProps = (row: InboxNotification, compact = false): RowProps => ({
    row, compact, busy, selecting,
    checked: allSelected || selected.has(row.id),
    onToggle: () => setChecked([row.id], !(allSelected || selected.has(row.id))),
    onLongPress: () => { setSelectMode(true); setChecked([row.id], true); },
    onRead: () => void act("read", row.id),
    onDelete: () => void act("delete", row.id),
  });

  return (
    <section aria-labelledby="notifications-heading" aria-busy={busy} className="pb-4">
      {selecting ? (
        <div className="sticky top-0 z-20 bg-slate-800 text-white shadow md:rounded-b-xl" role="group" aria-label="Selezione notifiche">
          <div className="flex items-center gap-2 px-3 py-2">
            <button type="button" disabled={busy} aria-label="Annulla selezione" title="Annulla selezione" onClick={clearSelection} className={selectionButton}><FiX aria-hidden="true" /></button>
            {visibleCheckbox("inline-flex h-10 w-8 items-center justify-center")}
            <span role="status" className="min-w-0 flex-1 truncate font-semibold">{allSelected ? "Tutte selezionate" : `${selected.size} selezionate`}</span>
            <button type="button" disabled={busy || !hasSelection} aria-label="Segna selezionate come lette" title="Segna selezionate come lette" onClick={() => void act("read")} className={selectionButton}><FiCheck aria-hidden="true" /></button>
            <button type="button" disabled={busy || !hasSelection} aria-label="Elimina selezionate" title="Elimina selezionate" onClick={() => void act("delete")} className={selectionDangerButton}><FiTrash2 aria-hidden="true" /></button>
          </div>
          <p className="flex flex-wrap items-center gap-x-2 bg-slate-700/60 px-3 py-1.5 text-xs">
            <span>{allSelected ? `Tutte le notifiche${unreadOnly ? " da leggere" : ""}, anche non caricate` : `${visibleSelected} di ${rows.length} caricate`}</span>
            {!allSelected && <button type="button" disabled={busy || !rows.length} onClick={() => { setAllSelected(true); setSelected(new Set()); }} className="min-h-8 underline">Seleziona tutte (anche non caricate)</button>}
          </p>
        </div>
      ) : (
        <div className="sticky top-0 z-20 flex items-center gap-2 border-b border-gray-200 bg-white/95 px-3 py-2 backdrop-blur dark:border-gray-800 dark:bg-gray-900/95">
          {visibleCheckbox("hidden h-10 w-6 items-center justify-center md:inline-flex")}
          <h1 id="notifications-heading" className="sr-only md:not-sr-only md:mr-2 md:whitespace-nowrap md:text-xl md:font-bold">Notifiche</h1>
          <div role="group" aria-label="Notifiche da mostrare" className="flex flex-1 rounded-lg bg-gray-100 p-0.5 text-sm md:flex-none dark:bg-gray-800">
            {(["unread", "all"] as const).map(value => (
              <button key={value} type="button" aria-pressed={view === value} disabled={busy && view === value} onClick={() => setView(value)}
                className={`min-h-9 flex-1 whitespace-nowrap rounded-md px-3 ${view === value ? "bg-white font-semibold shadow-sm dark:bg-gray-950" : "text-gray-600 dark:text-gray-300"}`}>
                {value === "unread" ? `Da leggere${unreadCount ? ` · ${unreadCount > 99 ? "99+" : unreadCount}` : ""}` : "Tutte"}
              </button>
            ))}
          </div>
          <span className="hidden flex-1 md:block" />
          <button type="button" aria-label="Raggruppa per contenitore" title="Raggruppa per contenitore" aria-pressed={grouped} onClick={toggleGrouped}
            className={grouped ? iconButtonActive : iconButton}><FiLayers aria-hidden="true" /></button>
          <button type="button" aria-label="Seleziona notifiche" title="Seleziona notifiche" disabled={busy || !rows.length} onClick={() => setSelectMode(true)} className={`${iconButton} md:hidden`}><FiCheckSquare aria-hidden="true" /></button>
          <span className="hidden gap-2 md:flex">
            <button type="button" disabled={busy} aria-label="Aggiorna" title="Aggiorna" onClick={() => void load()} className={iconButton}><FiRefreshCw aria-hidden="true" /></button>
            <button type="button" disabled={busy || !unreadCount} aria-label="Segna tutte come lette" title="Segna tutte come lette" onClick={() => void act("read", "all")} className={iconButton}><FiCheck aria-hidden="true" /></button>
            <Link to="/profile" aria-label="Preferenze notifiche" title="Preferenze notifiche" className={iconButton}><FiSettings aria-hidden="true" /></Link>
          </span>
          <div className="md:hidden">
            <MoreMenu label="Altre azioni notifiche">{close => <>
              <button type="button" role="menuitem" disabled={busy || !unreadCount} onClick={() => { close(); void act("read", "all"); }} className={menuItem}><FiCheck aria-hidden="true" />Segna tutte come lette</button>
              <button type="button" role="menuitem" disabled={busy} onClick={() => { close(); void load(); }} className={menuItem}><FiRefreshCw aria-hidden="true" />Aggiorna</button>
              <button type="button" role="menuitemcheckbox" aria-checked={grouped} onClick={toggleGrouped} className={menuItem}>
                <FiLayers aria-hidden="true" /><span className="flex-1">Raggruppa per contenitore</span>
                <span aria-hidden="true" className={`relative h-5 w-9 rounded-full ${grouped ? "bg-blue-600" : "bg-gray-300 dark:bg-gray-600"}`}><span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${grouped ? "left-[18px]" : "left-0.5"}`} /></span>
              </button>
              <hr className="my-1 border-gray-200 dark:border-gray-700" />
              <Link to="/profile" role="menuitem" onClick={close} className={menuItem}><FiSettings aria-hidden="true" />Preferenze notifiche</Link>
            </>}</MoreMenu>
          </div>
        </div>
      )}

      <div className="space-y-2 px-3 pt-2" aria-live="polite">
        {error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{error}</p>}
        {message && <p role="status" className="text-sm text-gray-600 dark:text-gray-300">{message}</p>}
        {busy && <p role="status" className="text-sm text-gray-500">Caricamento...</p>}
        {!busy && !error && !rows.length && <p role="status" className="py-10 text-center text-gray-500 dark:text-gray-400">{unreadOnly ? "Nessuna notifica da leggere." : "Nessuna notifica disponibile."}</p>}
      </div>

      {grouped ? (
        <ul aria-label="Notifiche ricevute per contenitore" className="mt-1 md:mx-3 md:space-y-3">
          {groups.map(groupRows => {
            const first = groupRows[0];
            const id = first.event.inventory_id;
            const ids = groupRows.map(row => row.id);
            const unread = groupRows.filter(row => !row.read_at).map(row => row.id);
            const checkedCount = groupRows.filter(row => allSelected || selected.has(row.id)).length;
            const open = expanded.has(id);
            const shown = open ? groupRows : groupRows.slice(0, 3);
            const kind = first.inventory_type === "CHECKLIST" ? "lista" : "inventario";
            return (
              <li key={id} className="overflow-hidden border-y border-gray-200 md:rounded-xl md:border dark:border-gray-800">
                <div className="flex items-center gap-2.5 bg-gray-50 px-3 py-2 dark:bg-gray-800/60">
                  <label className={`${selecting ? "inline-flex" : "hidden md:inline-flex"} h-9 w-6 shrink-0 items-center justify-center`}>
                    <input type="checkbox" disabled={busy} aria-label={`Seleziona notifiche di ${first.inventory_name}`} className="h-4 w-4"
                      checked={checkedCount === ids.length}
                      ref={input => { if (input) input.indeterminate = checkedCount > 0 && checkedCount < ids.length; }}
                      onChange={event => setChecked(ids, event.target.checked)} />
                  </label>
                  <ContainerIcon row={first} />
                  <h2 className="min-w-0 flex-1 truncate font-semibold">{first.inventory_name}</h2>
                  <span title={unread.length ? `${unread.length} da leggere` : `${ids.length} notifiche`}
                    className={`rounded-full px-2 text-xs font-bold ${unread.length ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200"}`}>{unread.length || ids.length}</span>
                  <span className="hidden gap-1 md:flex">
                    <Link to={containerLink(first)} aria-label={`Apri ${kind} ${first.inventory_name}`} title={`Apri ${kind}`} className={`${rowAction} text-blue-700 dark:text-blue-300`}><FiArrowRight aria-hidden="true" /></Link>
                    <button type="button" disabled={busy || !unread.length} aria-label={`Segna come lette le notifiche di ${first.inventory_name}`} title="Segna gruppo come letto" onClick={() => void act("read", unread)} className={rowAction}><FiCheck aria-hidden="true" /></button>
                    <button type="button" disabled={busy} aria-label={`Elimina le notifiche di ${first.inventory_name}`} title="Elimina notifiche del gruppo" onClick={() => void act("delete", ids, first.inventory_name)} className={`${rowAction} text-red-700 dark:text-red-300`}><FiTrash2 aria-hidden="true" /></button>
                  </span>
                  <div className="md:hidden">
                    <MoreMenu label={`Azioni per ${first.inventory_name}`}>{close => <>
                      <Link to={containerLink(first)} role="menuitem" onClick={close} className={menuItem}><FiArrowRight aria-hidden="true" />Apri {kind}</Link>
                      <button type="button" role="menuitem" disabled={busy || !unread.length} onClick={() => { close(); void act("read", unread); }} className={menuItem}><FiCheck aria-hidden="true" />Segna gruppo come letto</button>
                      <button type="button" role="menuitem" disabled={busy} onClick={() => { close(); void act("delete", ids, first.inventory_name); }} className={`${menuItem} text-red-700 dark:text-red-300`}><FiTrash2 aria-hidden="true" />Elimina notifiche del gruppo</button>
                    </>}</MoreMenu>
                  </div>
                </div>
                <ul aria-label={`Notifiche di ${first.inventory_name}`}>
                  {shown.map(row => <NotificationRow key={row.id} {...rowProps(row, true)} />)}
                </ul>
                {groupRows.length > 3 && (
                  <button type="button" onClick={() => setExpanded(previous => {
                    const next = new Set(previous);
                    if (open) next.delete(id);
                    else next.add(id);
                    return next;
                  })} className="min-h-10 w-full px-5 text-left text-sm text-blue-700 hover:bg-gray-50 dark:text-blue-300 dark:hover:bg-gray-800">
                    {open ? "Mostra meno" : `Mostra altre ${groupRows.length - 3}`}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <ul aria-label="Notifiche ricevute" className="mt-1 md:mx-3 md:overflow-hidden md:rounded-xl md:border md:border-gray-200 md:dark:border-gray-800">
          {rows.map(row => <NotificationRow key={row.id} {...rowProps(row)} />)}
        </ul>
      )}
      {more && <div className="px-3 pt-3"><button type="button" disabled={busy} onClick={() => void load(offset)} className="min-h-11 w-full rounded-lg border border-gray-200 px-3 md:w-auto dark:border-gray-700">Carica altre</button></div>}
    </section>
  );
}
