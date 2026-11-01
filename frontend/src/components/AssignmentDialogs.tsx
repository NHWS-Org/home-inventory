import { useEffect, useMemo, useState } from 'react';
import { Dialog } from '@headlessui/react';
import { useBottomSheetDrag } from './useBottomSheetDrag';
import {
  createAssignment, createItem, deleteAssignment, deleteItem, getAssignmentsBySource,
  getChecklists, getInventories, getInventoryItems, updateAssignment,
} from '../api';
import type { Assignment, AssignmentSummary, InventoryItem, Item } from '../types';

export const ASSIGNMENTS_CHANGED_EVENT = 'barcode-items-changed';
const notifyChanged = () => window.dispatchEvent(new Event(ASSIGNMENTS_CHANGED_EVENT));

type Named = { id: number; name: string };

function errorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : 'Operazione non riuscita';
}

function Shell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const sheetDrag = useBottomSheetDrag(onClose);

  return (
    <Dialog open onClose={onClose} className="relative z-[70]">
      <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
      <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
        <Dialog.Panel
          style={{ transform: `translateY(${sheetDrag.offset}px)`, transition: sheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
          className="max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] shadow-2xl dark:bg-gray-800 dark:text-gray-100 sm:max-w-md sm:rounded-2xl sm:p-6"
        >
          <button type="button" aria-label="Chiudi o trascina verso il basso" {...sheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
            <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
          </button>
          <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
          {children}
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}

function QtyStepper({ value, onChange, max }: { value: number; onChange: (v: number) => void; max?: number }) {
  return (
    <div className="grid w-full grid-cols-3 gap-2">
      <button type="button" aria-label="Diminuisci quantità" className="min-h-12 w-full rounded bg-gray-300 text-xl text-gray-900 dark:bg-gray-600 dark:text-gray-100"
        onClick={() => onChange(Math.max(1, value - 1))}>−</button>
      <span className="flex min-h-12 items-center justify-center rounded border border-gray-300 text-xl font-semibold dark:border-gray-600">{value}</span>
      <button type="button" aria-label="Aumenta quantità" className="min-h-12 w-full rounded bg-gray-300 text-xl text-gray-900 disabled:opacity-40 dark:bg-gray-600 dark:text-gray-100"
        disabled={max != null && value >= max}
        onClick={() => onChange(max != null ? Math.min(max, value + 1) : value + 1)}>+</button>
    </div>
  );
}

function Actions({ onClose, onConfirm, label, busy, disabled }: {
  onClose: () => void; onConfirm?: () => void; label?: string; busy?: boolean; disabled?: boolean;
}) {
  return (
    <div className={`grid w-full gap-2 pt-1 ${onConfirm ? 'grid-cols-2' : 'grid-cols-1'}`}>
      <button type="button" onClick={onClose} className="min-h-12 w-full rounded-xl bg-gray-300 px-3 font-medium text-gray-900 dark:bg-gray-600 dark:text-gray-100">
        {onConfirm ? 'Annulla' : 'Chiudi'}
      </button>
      {onConfirm && (
        <button type="button" onClick={onConfirm} disabled={busy || disabled}
          className="min-h-12 w-full rounded-xl bg-blue-600 px-3 font-medium text-white disabled:opacity-50">
          {busy ? '...' : label}
        </button>
      )}
    </div>
  );
}

/** Dall'inventario: scegli lista e quantita', crea la riga e il collegamento. */
export function AssignToListDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  const [lists, setLists] = useState<Named[]>([]);
  const [listId, setListId] = useState<number | null>(null);
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const available = Math.max(0, item.net_qty ?? item.quantity);

  useEffect(() => {
    getChecklists().then((data) => {
      setLists(data);
      if (data.length === 1) setListId(data[0].id);
    }).catch((err) => setError(errorMessage(err)));
  }, []);

  const submit = async () => {
    if (listId == null) return;
    setBusy(true);
    setError(null);
    try {
      const row = await createItem({ name: item.name, description: item.description, quantity: 0, inventory_id: listId });
      try {
        await createAssignment(row.id, item.id, qty);
      } catch (err) {
        try {
          await deleteItem(row.id);
        } catch (cleanupError) {
          throw new Error(`${errorMessage(err)}. La riga creata non e' stata rimossa: ${errorMessage(cleanupError)}`);
        }
        throw err;
      }
      notifyChanged();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Shell title={`Assegna "${item.name}" a una lista`} onClose={onClose}>
      <select value={listId ?? ''} onChange={(e) => setListId(e.target.value ? Number(e.target.value) : null)}
        className="w-full rounded border border-gray-300 bg-white p-3 text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100">
        <option value="">Scegli la lista…</option>
        {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
      {lists.length === 0 && <p className="text-sm text-gray-500 dark:text-gray-400">Non hai ancora nessuna lista.</p>}
      <p className="text-sm text-gray-500 dark:text-gray-400">Disponibile dopo le altre assegnazioni: {available}</p>
      <QtyStepper value={qty} onChange={setQty} max={Math.max(1, available)} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <Actions onClose={onClose} onConfirm={submit} label="Assegna" busy={busy} disabled={listId == null || available < 1} />
    </Shell>
  );
}

/** Scegli un item di inventario e la quantita' da prelevare (max = stock). */
export function InventoryPickerDialog({ onClose, onPick }: {
  onClose: () => void;
  onPick: (item: InventoryItem, qty: number) => Promise<void>;
}) {
  const [inventories, setInventories] = useState<Named[]>([]);
  const [inventoryId, setInventoryId] = useState<number | null>(null);
  const [itemsByInventory, setItemsByInventory] = useState<Map<number, InventoryItem[]>>(new Map());
  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState<InventoryItem | null>(null);
  const [pickedInventoryName, setPickedInventoryName] = useState('');
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getInventories().then((data) => {
      setInventories(data);
      return Promise.all(data.map(async (inventory) => ({
        id: inventory.id,
        items: await getInventoryItems(inventory.id),
      })));
    }).then((results) => {
      setItemsByInventory(new Map(results.map(({ id, items }) => [id, items])));
    }).catch((err) => setError(errorMessage(err))).finally(() => setLoading(false));
  }, []);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return inventories
      .filter((inventory) => inventoryId == null || inventory.id === inventoryId)
      .flatMap((inventory) => (itemsByInventory.get(inventory.id) ?? [])
        .filter((item) => !needle || item.name.toLowerCase().includes(needle)
          || (item.barcodes ?? []).some((barcode) => barcode.code.includes(needle)))
        .map((item) => ({ item, inventoryName: inventory.name })));
  }, [inventories, inventoryId, itemsByInventory, search]);

  const submit = async () => {
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      await onPick(picked, qty);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  if (picked) {
    const available = Math.max(0, picked.net_qty ?? picked.quantity);
    return (
      <Shell title={picked.name} onClose={onClose}>
        <p className="text-sm text-gray-500 dark:text-gray-400">{pickedInventoryName}</p>
        <p className="text-sm text-gray-500 dark:text-gray-400">Disponibile dopo le altre assegnazioni: {available}</p>
        <QtyStepper value={qty} onChange={setQty} max={Math.max(1, available)} />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="grid w-full grid-cols-2 gap-2">
          <button type="button" className="min-h-12 w-full rounded-xl bg-gray-300 px-3 font-medium text-gray-900 dark:bg-gray-600 dark:text-gray-100" onClick={() => setPicked(null)}>Indietro</button>
          <button type="button" className="min-h-12 w-full rounded-xl bg-blue-600 px-3 font-medium text-white disabled:opacity-50" onClick={submit} disabled={busy || available < 1}>
            {busy ? '...' : 'Conferma'}
          </button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell title="Scegli da inventario" onClose={onClose}>
      <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cerca item in tutti gli inventari…"
        className="w-full rounded border border-gray-300 bg-white p-3 text-gray-900 placeholder:text-gray-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder:text-gray-400" />
      <select value={inventoryId ?? ''} onChange={(e) => setInventoryId(e.target.value ? Number(e.target.value) : null)}
        className="w-full rounded border border-gray-300 bg-white p-3 text-gray-900 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100">
        <option value="">Tutti gli inventari</option>
        {inventories.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
      </select>
      <ul className="max-h-[45vh] overflow-y-auto divide-y dark:divide-gray-700">
        {visible.map(({ item, inventoryName }) => (
          <li key={item.id}>
            <button type="button" onClick={() => { setPicked(item); setPickedInventoryName(inventoryName); setQty(1); }}
              className="w-full flex justify-between items-center gap-2 py-3 text-left">
              <span className="min-w-0">
                <span className="block truncate">{item.name}</span>
                <span className="block truncate text-xs text-gray-500 dark:text-gray-400">{inventoryName}</span>
              </span>
              <span className="whitespace-nowrap text-sm text-gray-600 dark:text-gray-300">{item.net_qty ?? item.quantity}</span>
            </button>
          </li>
        ))}
        {!loading && visible.length === 0 && (
          <li className="py-3 text-sm text-gray-500 dark:text-gray-400">
            {inventories.length === 0 ? 'Nessun inventario disponibile' : 'Nessun item trovato'}
          </li>
        )}
        {loading && <li className="py-3 text-sm text-gray-500 dark:text-gray-400">Caricamento inventari e item…</li>}
      </ul>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <Actions onClose={onClose} />
    </Shell>
  );
}

/** Dalla lista: crea una nuova riga collegata a un item di inventario. */
export function AddFromInventoryDialog({ listId, onClose }: { listId: number; onClose: () => void }) {
  return (
    <InventoryPickerDialog
      onClose={onClose}
      onPick={async (picked, qty) => {
        const row = await createItem({ name: picked.name, description: picked.description, quantity: 0, inventory_id: listId });
        try {
          await createAssignment(row.id, picked.id, qty);
        } catch (err) {
          try {
            await deleteItem(row.id);
          } catch (cleanupError) {
            throw new Error(`${errorMessage(err)}. La riga creata non e' stata rimossa: ${errorMessage(cleanupError)}`);
          }
          throw err;
        }
        notifyChanged();
        onClose();
      }}
    />
  );
}

/** Collega una riga già presente in lista a un item di inventario. */
export function AssignExistingListItemDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  return (
    <InventoryPickerDialog
      onClose={onClose}
      onPick={async (source, qty) => {
        await createAssignment(item.id, source.id, qty);
        notifyChanged();
        onClose();
      }}
    />
  );
}

/** Nel form di creazione/modifica di una riga di lista: collega (o scollega) un item di inventario. */
export function ListLinkField({ current, onPick, onClear, onClearAndDelete }: {
  current: { name: string; inventoryName?: string | null; qty: number } | null;
  onPick: (item: InventoryItem, qty: number) => Promise<void>;
  onClear: () => Promise<void> | void;
  onClearAndDelete?: () => Promise<void> | void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<void> | void) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="mb-4 rounded border border-gray-200 dark:border-gray-700 p-3 space-y-2">
      <div className="text-sm font-medium">Preleva da inventario</div>
      {current ? (
        <>
          <div className="text-sm">
            📦 ×{current.qty} · {current.name}{current.inventoryName ? ` (${current.inventoryName})` : ''}
          </div>
          <div className={`grid w-full gap-2 ${onClearAndDelete ? 'grid-cols-2' : 'grid-cols-1'}`}>
            <button type="button" disabled={busy} onClick={() => run(onClear)}
              className="min-h-12 w-full rounded-xl border border-gray-400 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-500 dark:text-gray-100 dark:hover:bg-gray-700">
              Scollega, mantieni nella lista
            </button>
            {onClearAndDelete && (
              <button type="button" disabled={busy} onClick={() => run(onClearAndDelete)}
                className="min-h-12 w-full rounded-xl border border-red-500 px-3 py-2 text-sm font-medium text-red-600 disabled:opacity-50">
                Scollega e cancella dalla lista
              </button>
            )}
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </>
      ) : (
        <button type="button" onClick={() => setOpen(true)} className="min-h-12 w-full rounded-xl bg-gray-200 px-3 py-2 font-medium text-gray-900 dark:bg-gray-700 dark:text-gray-100">
          📥 Collega a un item di inventario
        </button>
      )}
      {open && (
        <InventoryPickerDialog
          onClose={() => setOpen(false)}
          onPick={async (item, qty) => { await onPick(item, qty); setOpen(false); }}
        />
      )}
    </div>
  );
}

/** Dalla riga di lista: cambia quantita' o scollega. */
export function EditAssignmentDialog({ assignment, listItemId, onClose }: { assignment: AssignmentSummary; listItemId: number; onClose: () => void }) {
  const [qty, setQty] = useState(assignment.qty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      notifyChanged();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Shell title={assignment.source_name ?? 'Assegnazione'} onClose={onClose}>
      <p className="text-sm text-gray-500 dark:text-gray-400">
        📦 {assignment.source_inventory_name} · stock {assignment.source_stock ?? '?'}
        {assignment.source_net_qty != null && ` · netto ${assignment.source_net_qty}`}
      </p>
      {(assignment.source_net_qty ?? 0) < 0 && (
        <p className="rounded bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200 p-2 text-sm">
          ⚠️ Le assegnazioni in essere superano lo stock di {Math.abs(assignment.source_net_qty ?? 0)}.
        </p>
      )}
      <QtyStepper
        value={qty}
        onChange={setQty}
        max={assignment.list_checked
          ? Math.max(assignment.qty, assignment.source_net_qty ?? assignment.qty)
          : assignment.qty + Math.max(0, assignment.source_net_qty ?? 0)}
      />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <button type="button" disabled={busy}
        onClick={() => { if (window.confirm('Scollegare la riga dall\'inventario?')) run(() => deleteAssignment(assignment.id)); }}
        className="w-full rounded border border-red-500 text-red-600 py-2">
        Scollega dall'inventario
      </button>
      <button type="button" disabled={busy}
        onClick={() => {
          if (window.confirm('Scollegare e cancellare questo item dalla lista?')) {
            run(() => deleteItem(listItemId));
          }
        }}
        className="w-full rounded border border-red-700 text-red-700 py-2">
        Scollega e cancella item dalla lista
      </button>
      <Actions onClose={onClose} onConfirm={() => run(() => updateAssignment(assignment.id, qty))}
        label="Salva" busy={busy} disabled={qty === assignment.qty} />
    </Shell>
  );
}

/** Dall'inventario: lordo/netto e assegnazioni in essere, modificabili. */
export function SourceAssignmentsDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  const [rows, setRows] = useState<Assignment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getAssignmentsBySource(item.id).then(setRows).catch(() => setRows([]));
  }, [item.id]);

  const assigned = rows?.[0]?.source_net_qty == null
    ? (rows ?? []).reduce((sum, r) => sum + r.qty, 0)
    : item.quantity - rows[0].source_net_qty;
  const net = item.quantity - assigned;

  const change = async (row: Assignment, qty: number) => {
    setError(null);
    try {
      const updated = await updateAssignment(row.id, qty);
      setRows((cur) => (cur ?? []).map((r) => ({
        ...r,
        qty: r.id === row.id ? qty : r.qty,
        source_net_qty: updated.source_net_qty,
      })));
      notifyChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async (row: Assignment) => {
    if (!window.confirm(`Rimuovere l'assegnazione da "${row.list_name}"?`)) return;
    setError(null);
    try {
      await deleteAssignment(row.id);
      setRows(await getAssignmentsBySource(item.id));
      notifyChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const deleteListItem = async (row: Assignment) => {
    if (!window.confirm(`Cancellare "${row.list_item_name ?? row.list_name}" dalla lista?`)) return;
    setError(null);
    try {
      await deleteItem(row.list_item_id);
      setRows(await getAssignmentsBySource(item.id));
      notifyChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <Shell title={item.name} onClose={onClose}>
      <div className="grid grid-cols-3 text-center text-sm">
        <div><div className="text-xl font-semibold">{item.quantity}</div>lordo</div>
        <div><div className="text-xl font-semibold">−{assigned}</div>assegnato</div>
        <div><div className={`text-xl font-semibold ${net < 0 ? 'text-red-600' : ''}`}>{net}</div>netto</div>
      </div>
      {net < 0 && (
        <p className="rounded bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200 p-2 text-sm">
          ⚠️ Assegnato oltre lo stock di {Math.abs(net)}.
        </p>
      )}
      <ul className="divide-y dark:divide-gray-700">
        {(rows ?? []).map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <span className="min-w-0 flex-1">
              <span className="block truncate">{r.list_name ?? 'Lista'}</span>
              <span className="block truncate text-xs text-gray-500 dark:text-gray-400">{r.list_item_name ?? r.source_name}</span>
              {r.list_checked && (
                <span className="block text-xs text-emerald-700 dark:text-emerald-400">Spuntata · già scaricata</span>
              )}
            </span>
            <span className="flex items-center gap-2">
              <button type="button" className="h-9 w-9 rounded bg-gray-300 text-gray-900 disabled:opacity-40 dark:bg-gray-600 dark:text-gray-100"
                disabled={r.qty <= 1} onClick={() => change(r, r.qty - 1)}>−</button>
              <span className="min-w-[1.5rem] text-center font-semibold">{r.qty}</span>
              <button type="button" className="h-9 w-9 rounded bg-gray-300 text-gray-900 disabled:opacity-40 dark:bg-gray-600 dark:text-gray-100"
                disabled={r.qty >= r.qty + Math.max(0, r.source_net_qty ?? 0)}
                onClick={() => change(r, r.qty + 1)}>+</button>
              <button type="button" className="h-9 rounded border border-gray-400 px-2 text-xs text-gray-800 hover:bg-gray-100 dark:border-gray-500 dark:text-gray-100 dark:hover:bg-gray-700" onClick={() => remove(r)} title="Scollega">Scollega</button>
              <button type="button" className="h-9 px-2 rounded bg-red-600 text-white text-xs" onClick={() => deleteListItem(r)} title="Cancella item dalla lista">🗑️</button>
            </span>
          </li>
        ))}
        {rows && rows.length === 0 && <li className="py-2 text-sm text-gray-500 dark:text-gray-400">Nessuna assegnazione in essere</li>}
      </ul>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <Actions onClose={onClose} />
    </Shell>
  );
}
