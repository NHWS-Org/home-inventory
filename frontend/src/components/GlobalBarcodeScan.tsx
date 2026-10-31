import { useCallback, useEffect, useMemo, useState, lazy, Suspense } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Dialog } from '@headlessui/react';
import {
  addItemBarcode,
  createItem,
  getChecklistItems,
  getChecklists,
  getInventories,
  getInventoryItems,
  lookupBarcode,
  updateItem,
} from '../api';
import type { BarcodeLookupResult, BarcodeMatch } from '../types';
const BarcodeScanner = lazy(() => import('./BarcodeScanner'));
import { useAuth } from '../useAuth';
import { useKeyboardScanner } from '../useKeyboardScanner';
import { useBottomSheetDrag } from './useBottomSheetDrag';

export const ITEMS_CHANGED_EVENT = 'barcode-items-changed';

type Kind = 'inventories' | 'checklists';
type Target = { id: number; name: string; kind: Kind };
type ListItem = { id: number; name: string; description?: string | null; quantity: number; inventory_id: number; barcodes?: unknown[] };
type Scan = { code: string; format: string | null; lookup: BarcodeLookupResult };
type Mode = 'menu' | 'create' | 'associate';

const kindOf = (m: BarcodeMatch): Kind => (m.inventory_type === 'CHECKLIST' ? 'checklists' : 'inventories');
const targetKey = (t: Target) => `${t.kind}:${t.id}`;

function errorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return err instanceof Error && err.message ? err.message : 'Operazione non riuscita';
}

const fetchItems = (kind: Kind, id: number): Promise<ListItem[]> =>
  (kind === 'checklists' ? getChecklistItems(id) : getInventoryItems(id)) as Promise<ListItem[]>;

export default function GlobalBarcodeScan() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { user } = useAuth();
  const canEdit = Boolean(user?.role?.name && user.role.name !== 'viewer');

  const [scannerOpen, setScannerOpen] = useState(false);
  const [scan, setScan] = useState<Scan | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('menu');

  const [targets, setTargets] = useState<Target[]>([]);
  const [targetKeySel, setTargetKeySel] = useState('');
  const [targetItems, setTargetItems] = useState<ListItem[]>([]);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newQuantity, setNewQuantity] = useState(1);
  const [search, setSearch] = useState('');
  const [selectedItemId, setSelectedItemId] = useState<number | null>(null);
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [matchQty, setMatchQty] = useState<Record<number, number>>({});

  const currentTarget = useMemo(() => {
    const m = pathname.match(/^\/(inventories|checklists)\/(\d+)/);
    return m ? { kind: m[1] as Kind, id: Number(m[2]) } : null;
  }, [pathname]);

  const target = targets.find((t) => targetKey(t) === targetKeySel) ?? null;

  const loadTargets = useCallback(async () => {
    const [inv, chk] = await Promise.all([getInventories(), getChecklists()]);
    const all: Target[] = [
      ...inv.map((i) => ({ id: i.id, name: i.name, kind: 'inventories' as Kind })),
      ...chk.map((c) => ({ id: c.id, name: c.name, kind: 'checklists' as Kind })),
    ];
    setTargets(all);
    return all;
  }, []);

  const handleCode = useCallback(
    async (rawCode: string, format: string | null) => {
      setScannerOpen(false);
      setError(null);
      setDone(null);
      // I QR stampati per un inventario/lista contengono il suo link diretto.
      // Gli altri QR e i barcode continuano nel normale flusso di lookup item.
      try {
        const scannedUrl = new URL(rawCode, window.location.origin);
        const inventoryPath = scannedUrl.pathname.match(/^\/(inventories|checklists)\/([1-9]\d*)\/?$/);
        if (scannedUrl.origin === window.location.origin && inventoryPath) {
          setScan(null);
          setLoading(false);
          navigate(`${scannedUrl.pathname}${scannedUrl.search}${scannedUrl.hash}`);
          return;
        }
      } catch {
        // Un valore che non è un URL resta un normale codice barcode.
      }
      setLoading(true);
      try {
        const lookup = await lookupBarcode(rawCode, true);
        const product = lookup.product;
        setNewName(product?.name ?? lookup.matches[0]?.name ?? '');
        setNewDescription([product?.brand, product?.quantity_label].filter(Boolean).join(' - '));
        setNewQuantity(1);
        setSearch('');
        setSelectedItemId(null);
        setQuantities({});
        setMatchQty(Object.fromEntries(lookup.matches.map((m) => [m.item_id, m.quantity ?? 0])));
        setMode(lookup.matches.length > 0 ? 'menu' : canEdit ? 'create' : 'menu');
        setScan({ code: lookup.code, format, lookup });

        if (canEdit && lookup.matches.length === 0) {
          const all = await loadTargets();
          const preferred =
            all.find((t) => currentTarget && t.kind === currentTarget.kind && t.id === currentTarget.id) ?? all[0];
          setTargetKeySel(preferred ? targetKey(preferred) : '');
        }
      } catch (err) {
        setScan(null);
        setError(errorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [canEdit, currentTarget, loadTargets, navigate],
  );

  useKeyboardScanner(!!user?.username && !scannerOpen && scan === null && !loading, (code) => void handleCode(code, null));

  // Elenco item dell'inventario/lista selezionato come destinazione (per l'associazione)
  useEffect(() => {
    if (!target || mode !== 'associate') return;
    let cancelled = false;
    fetchItems(target.kind, target.id)
      .then((list) => !cancelled && setTargetItems(list))
      .catch(() => !cancelled && setTargetItems([]));
    return () => {
      cancelled = true;
    };
  }, [target, mode]);

  const candidates = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return targetItems
      .filter((i) => !needle || i.name.toLowerCase().includes(needle) || (i.description ?? '').toLowerCase().includes(needle))
      .sort((a, b) => a.name.localeCompare(b.name))
      .slice(0, 50);
  }, [targetItems, search]);

  const closeAll = () => {
    setScan(null);
    setError(null);
    setDone(null);
    setMode('menu');
  };

  const notifyChanged = () => window.dispatchEvent(new Event(ITEMS_CHANGED_EVENT));

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    setError(null);
    try {
      const message = await action();
      notifyChanged();
      setDone(message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openMatch = (m: BarcodeMatch) => {
    closeAll();
    navigate(`/${kindOf(m)}/${m.inventory_id}?item=${m.item_id}`, { state: { scanAt: Date.now() } });
  };

  const setQuantity = async (m: BarcodeMatch, quantity: number) => {
    setBusy(true);
    setError(null);
    try {
      const list = await fetchItems(kindOf(m), m.inventory_id);
      const item = list.find((i) => i.id === m.item_id);
      if (!item) throw new Error('Oggetto non trovato');
      const value = Math.max(0, Math.floor(quantity));
      await updateItem(item.id, {
        name: item.name,
        description: item.description ?? '',
        quantity: value,
        inventory_id: item.inventory_id,
      });
      setMatchQty((prev) => ({ ...prev, [m.item_id]: value }));
      setQuantities((prev) => ({ ...prev, [m.item_id]: '' }));
      notifyChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitCreate = () =>
    run(async () => {
      if (!scan || !target) throw new Error('Seleziona inventario o lista');
      const name = newName.trim();
      if (!name) throw new Error('Nome obbligatorio');
      await createItem({
        name,
        description: newDescription.trim() || undefined,
        quantity: target.kind === 'checklists' ? 0 : newQuantity,
        inventory_id: target.id,
        barcodes: [{ code: scan.code, format: scan.format }],
      });
      return `Creato "${name}" in ${target.name} con codice ${scan.code}`;
    });

  const submitAssociate = () =>
    run(async () => {
      if (!scan || selectedItemId === null) throw new Error('Seleziona un oggetto');
      const item = targetItems.find((i) => i.id === selectedItemId);
      await addItemBarcode(selectedItemId, scan.code, scan.format);
      return `Codice ${scan.code} associato a "${item?.name ?? ''}"`;
    });

  const rescan = () => {
    closeAll();
    setScannerOpen(true);
  };

  const scanSheetDrag = useBottomSheetDrag(closeAll);

  if (!user?.username) return null;

  const product = scan?.lookup.product ?? null;
  const matches = scan?.lookup.matches ?? [];
  const isChecklistMatch = (m: BarcodeMatch) => m.inventory_type === 'CHECKLIST';

  const targetSelect = (
    <div className="mb-2">
      <label className="block text-sm font-medium">Inventario / lista</label>
      <select
        className="w-full border rounded p-1 dark:bg-gray-800"
        value={targetKeySel}
        onChange={(e) => {
          setTargetKeySel(e.target.value);
          setSelectedItemId(null);
        }}
      >
        {targets.map((t) => (
          <option key={targetKey(t)} value={targetKey(t)}>
            {t.kind === 'checklists' ? '☑️' : '📦'} {t.name}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <>
      {/* Il lettore barcode resta nell'angolo alto destro su mobile. */}
      <button
        onClick={() => setScannerOpen(true)}
        title="Scansiona barcode / QR code"
        aria-label="Scansiona barcode / QR code"
        className="fixed right-4 top-4 z-[45] flex h-12 w-12 items-center justify-center rounded-xl bg-purple-600 text-xl text-white shadow-lg hover:bg-purple-700 md:bottom-4 md:top-auto md:z-30 md:h-14 md:w-14"
      >
        📷
      </button>

      {scannerOpen && (
        <Suspense fallback={null}>
          <BarcodeScanner open={scannerOpen} onClose={() => setScannerOpen(false)} onDetected={(c, f) => void handleCode(c, f)} />
        </Suspense>
      )}

      <Dialog open={loading || scan !== null || error !== null} onClose={() => !busy && !loading && closeAll()} className="relative z-50">
        <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel
            style={{ transform: `translateY(${scanSheetDrag.offset}px)`, transition: scanSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl dark:bg-gray-900 dark:text-white sm:rounded-2xl"
          >
            <div className="shrink-0 px-5 pb-3 pt-3 sm:px-6 sm:pt-5">
              <button type="button" aria-label="Chiudi o trascina verso il basso" {...scanSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
                <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
              </button>
              <div className="flex items-center justify-between gap-3">
                {loading ? (
                  <Dialog.Title className="text-lg font-semibold">Ricerca codice…</Dialog.Title>
                ) : scan ? (
                  <div>
                    <Dialog.Title className="text-lg font-semibold">
                      {matches.length > 0 ? (matches.length > 1 ? 'Prodotti trovati' : 'Prodotto trovato') : 'Nuovo codice'}
                    </Dialog.Title>
                    <p className="mt-1 break-all font-mono text-xs text-gray-500 dark:text-gray-400">{scan.code}</p>
                  </div>
                ) : (
                  <Dialog.Title className="text-lg font-semibold">Scansione non riuscita</Dialog.Title>
                )}
                {!loading && <button type="button" onClick={closeAll} aria-label="Chiudi" className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-2xl text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800">×</button>}
              </div>
            </div>
            <div className="overflow-y-auto px-5 pb-5 sm:px-6">
              {loading && <p className="py-2 text-sm text-gray-600 dark:text-gray-300">Attendi mentre cerco il codice…</p>}
              {!loading && !scan && error && <p className="rounded-xl bg-red-50 p-4 text-red-700 dark:bg-red-950/40 dark:text-red-300" role="alert">{error}</p>}
              {!loading && scan && (
                <>
                {done ? (
                  <>
                    <div className="rounded-2xl bg-green-50 p-4 text-green-800 dark:bg-green-950/40 dark:text-green-300" role="status">✅ {done}</div>
                    <div className="mt-4 grid grid-cols-2 gap-2">
                      <button onClick={closeAll} className="min-h-12 rounded-xl border border-gray-300 px-4 font-medium dark:border-gray-700">Chiudi</button>
                      <button onClick={rescan} className="min-h-12 rounded-xl bg-purple-600 px-4 font-medium text-white hover:bg-purple-700">Scansiona altro</button>
                    </div>
                  </>
                ) : mode === 'menu' ? (
                  <>
                    {matches.length === 0 && (
                      <p className="mb-3 rounded-xl bg-gray-100 p-3 text-sm dark:bg-gray-800">Nessun oggetto ha questo codice.</p>
                    )}
                    <ul className="space-y-3">
                      {matches.map((m) => {
                        const qty = matchQty[m.item_id] ?? m.quantity ?? 0;
                        return (
                          <li key={m.item_id} className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
                            <div className="mb-3 flex items-start gap-3">
                              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-blue-50 text-xl dark:bg-blue-950/50">{isChecklistMatch(m) ? '☑️' : '📦'}</span>
                              <div className="min-w-0 flex-1">
                                <div className="font-semibold">{m.name}</div>
                                <div className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                                {isChecklistMatch(m) ? 'Lista' : 'Inventario'}: {m.inventory_name ?? m.inventory_id}
                              {' · '}
                              {isChecklistMatch(m) ? (qty ? 'Completato' : 'Da fare') : `Quantità: ${qty}`}
                                </div>
                              </div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                              {canEdit && isChecklistMatch(m) && (
                                <button disabled={busy} onClick={() => void setQuantity(m, qty ? 0 : 1)} className="col-span-2 min-h-12 rounded-xl bg-green-600 px-3 font-medium text-white hover:bg-green-700 disabled:opacity-50">
                                  {qty ? 'Segna da fare' : 'Segna completato'}
                                </button>
                              )}
                              {canEdit && !isChecklistMatch(m) && (
                                <>
                                  <button disabled={busy} onClick={() => void setQuantity(m, qty + 1)} className="min-h-12 rounded-xl bg-green-600 px-3 font-medium text-white hover:bg-green-700 disabled:opacity-50">+1 pezzo</button>
                                  <button disabled={busy || !qty} onClick={() => void setQuantity(m, qty - 1)} className="min-h-12 rounded-xl bg-orange-500 px-3 font-medium text-white hover:bg-orange-600 disabled:opacity-50">−1 pezzo</button>
                                  <input
                                    type="number"
                                    min="0"
                                    aria-label={`Quantità per ${m.name}`}
                                    placeholder="Quantità"
                                    className="min-h-12 min-w-0 rounded-xl border border-gray-300 px-3 text-center dark:border-gray-700 dark:bg-gray-800"
                                    value={quantities[m.item_id] ?? ''}
                                    onChange={(e) => setQuantities((prev) => ({ ...prev, [m.item_id]: e.target.value }))}
                                  />
                                  <button
                                    disabled={busy || !(quantities[m.item_id] ?? '').trim()}
                                    onClick={() => void setQuantity(m, Number(quantities[m.item_id]))}
                                    className="min-h-12 rounded-xl border border-blue-600 px-3 font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50 dark:text-blue-300 dark:hover:bg-blue-950/40"
                                  >
                                    Imposta quantità
                                  </button>
                                </>
                              )}
                              <button onClick={() => openMatch(m)} className="col-span-2 flex min-h-12 items-center justify-center gap-2 rounded-xl bg-purple-600 px-3 font-medium text-white hover:bg-purple-700">
                                Apri prodotto <span aria-hidden="true">→</span>
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                    {error && <p className="mb-2 mt-3 text-sm text-red-600" role="alert">{error}</p>}
                    <button onClick={rescan} className="mt-3 min-h-12 w-full rounded-xl border border-gray-300 px-4 font-medium dark:border-gray-700">Scansiona un altro codice</button>
                  </>
                ) : (
                  <>
                    {product && (
                      <div className="mb-4 flex items-center gap-3 rounded-2xl bg-blue-50 p-4 dark:bg-gray-800">
                        {product.image_url ? (
                          <img src={product.image_url} alt="" className="h-14 w-14 shrink-0 rounded-xl bg-white object-contain" />
                        ) : (
                          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-white text-2xl dark:bg-gray-700" aria-hidden="true">📦</span>
                        )}
                        <div className="min-w-0 text-sm">
                          <div className="font-semibold">{product.name ?? 'Prodotto senza nome'}</div>
                          {[product.brand, product.quantity_label].filter(Boolean).length > 0 && <div className="mt-1 text-gray-600 dark:text-gray-300">{[product.brand, product.quantity_label].filter(Boolean).join(' · ')}</div>}
                          <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">Fonte: {product.source}</div>
                        </div>
                      </div>
                    )}
                    <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl bg-gray-100 p-1 dark:bg-gray-800">
                      <button
                        type="button"
                        onClick={() => setMode('create')}
                        aria-pressed={mode === 'create'}
                        className={`min-h-11 rounded-lg px-3 font-medium ${mode === 'create' ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-white' : 'text-gray-600 dark:text-gray-300'}`}
                      >
                        Crea prodotto
                      </button>
                      <button
                        type="button"
                        onClick={() => setMode('associate')}
                        aria-pressed={mode === 'associate'}
                        className={`min-h-11 rounded-lg px-3 font-medium ${mode === 'associate' ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-white' : 'text-gray-600 dark:text-gray-300'}`}
                      >
                        Collega esistente
                      </button>
                    </div>

                    {targetSelect}

                    {mode === 'create' ? (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          void submitCreate();
                        }}
                      >
                        <div className="mb-3">
                          <label htmlFor="barcode-new-name" className="mb-1 block text-sm font-medium">Nome</label>
                          <input id="barcode-new-name" autoFocus className="min-h-12 w-full rounded-xl border border-gray-300 px-3 dark:border-gray-700 dark:bg-gray-800" value={newName} onChange={(e) => setNewName(e.target.value)} />
                        </div>
                        <div className="mb-3">
                          <label htmlFor="barcode-new-description" className="mb-1 block text-sm font-medium">Descrizione</label>
                          <input id="barcode-new-description" className="min-h-12 w-full rounded-xl border border-gray-300 px-3 dark:border-gray-700 dark:bg-gray-800" value={newDescription} onChange={(e) => setNewDescription(e.target.value)} />
                        </div>
                        {target?.kind !== 'checklists' && (
                          <div className="mb-4">
                            <label htmlFor="barcode-new-quantity" className="mb-1 block text-sm font-medium">Quantità iniziale</label>
                            <input
                              id="barcode-new-quantity"
                              type="number"
                              min="0"
                              className="min-h-12 w-28 rounded-xl border border-gray-300 px-3 text-center dark:border-gray-700 dark:bg-gray-800"
                              value={newQuantity}
                              onChange={(e) => setNewQuantity(Math.max(0, Number(e.target.value)))}
                            />
                          </div>
                        )}
                        {error && <p className="mb-3 text-sm text-red-600" role="alert">{error}</p>}
                        <div className="grid grid-cols-2 gap-2 pt-1">
                          <button type="button" onClick={closeAll} className="min-h-12 rounded-xl border border-gray-300 px-4 font-medium dark:border-gray-700">Annulla</button>
                          <button type="submit" disabled={busy || !newName.trim() || !target} className="min-h-12 rounded-xl bg-purple-600 px-4 font-medium text-white hover:bg-purple-700 disabled:opacity-50">Crea prodotto</button>
                        </div>
                      </form>
                    ) : (
                      <div>
                        <input
                          aria-label="Cerca prodotto da collegare"
                          className="mb-2 min-h-12 w-full rounded-xl border border-gray-300 px-3 dark:border-gray-700 dark:bg-gray-800"
                          placeholder="Cerca oggetto..."
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                        <ul className="mb-3 max-h-56 overflow-y-auto rounded-xl border border-gray-200 dark:border-gray-700">
                          {candidates.length === 0 && <li className="p-3 text-sm text-gray-500">Nessun prodotto trovato.</li>}
                          {candidates.map((item) => (
                            <li key={item.id}>
                              <button
                                type="button"
                                onClick={() => setSelectedItemId(item.id)}
                                className={`min-h-12 w-full px-3 text-left ${selectedItemId === item.id ? 'bg-blue-600 text-white' : 'hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                              >
                                {item.name}
                                {(item.barcodes?.length ?? 0) > 0 && <span className="ml-2 text-xs opacity-70">🏷️ {item.barcodes?.length}</span>}
                              </button>
                            </li>
                          ))}
                        </ul>
                        {selectedItemId !== null && <p className="mb-3 text-sm text-gray-600 dark:text-gray-300" aria-live="polite">Prodotto selezionato: {targetItems.find((item) => item.id === selectedItemId)?.name}</p>}
                        {error && <p className="mb-3 text-sm text-red-600" role="alert">{error}</p>}
                        <div className="grid grid-cols-2 gap-2 pt-1">
                          <button type="button" onClick={closeAll} className="min-h-12 rounded-xl border border-gray-300 px-4 font-medium dark:border-gray-700">Annulla</button>
                          <button
                            type="button"
                            disabled={busy || selectedItemId === null}
                            onClick={() => void submitAssociate()}
                            className="min-h-12 rounded-xl bg-purple-600 px-5 font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                          >
                            Associa
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}
                </>
              )}
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </>
  );
}
