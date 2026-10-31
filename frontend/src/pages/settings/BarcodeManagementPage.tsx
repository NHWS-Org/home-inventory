import { useCallback, useEffect, useState, lazy, Suspense } from 'react';
import {
  clearAdminBarcodeCache,
  correctAdminBarcode,
  debugAdminBarcode,
  deleteAdminBarcodeCache,
  getAdminBarcodeCache,
  getAdminBarcodes,
  type AdminBarcodeCacheEntry,
  type AdminBarcodeDebugResult,
  type AdminBarcodeRecord,
} from '../../api';
const BarcodeScanner = lazy(() => import('../../components/BarcodeScanner'));

const formats = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'itf', 'qr_code', 'data_matrix'];

function errorText(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'Operazione non riuscita';
}

function dateText(value: string): string {
  return new Date(value).toLocaleString();
}

export default function BarcodeManagementPage() {
  const [query, setQuery] = useState('');
  const [barcodes, setBarcodes] = useState<AdminBarcodeRecord[]>([]);
  const [cache, setCache] = useState<AdminBarcodeCacheEntry[]>([]);
  const [code, setCode] = useState('');
  const [format, setFormat] = useState('');
  const [debugResult, setDebugResult] = useState<AdminBarcodeDebugResult | null>(null);
  const [selectedBarcode, setSelectedBarcode] = useState<AdminBarcodeRecord | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [debugging, setDebugging] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [registered, cached] = await Promise.all([getAdminBarcodes(query), getAdminBarcodeCache(query)]);
      setBarcodes(registered);
      setCache(cached);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => { void loadData(); }, [loadData]);

  const runDebug = async (forceRefresh = false) => {
    if (!code.trim()) return;
    setDebugging(true);
    setError('');
    setMessage('');
    try {
      const result = await debugAdminBarcode(code, format || null, forceRefresh);
      setDebugResult(result);
      setMessage(forceRefresh ? 'Cache aggiornata e controllo API completato.' : 'Controllo del codice completato.');
      if (forceRefresh) await loadData();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setDebugging(false);
    }
  };

  const removeCacheEntry = async (entry: AdminBarcodeCacheEntry) => {
    try {
      await deleteAdminBarcodeCache(entry.code);
      setCache((current) => current.filter((row) => row.code !== entry.code));
      setMessage(`Voce cache ${entry.code} eliminata.`);
    } catch (err) {
      setError(errorText(err));
    }
  };

  const applyCorrection = async () => {
    if (!selectedBarcode || !debugResult) return;
    if (!window.confirm(`Sostituire il codice associato a "${selectedBarcode.item_name}" con ${debugResult.normalized_code}?`)) return;
    try {
      await correctAdminBarcode(selectedBarcode.id, debugResult.normalized_code, format || selectedBarcode.format);
      setMessage(`Codice aggiornato per "${selectedBarcode.item_name}" e modifica registrata nella cronologia.`);
      setSelectedBarcode(null);
      await loadData();
    } catch (err) {
      setError(errorText(err));
    }
  };

  const clearCache = async () => {
    if (!window.confirm('Eliminare tutte le voci della cache barcode? I codici associati agli item non verranno modificati.')) return;
    try {
      const deleted = await clearAdminBarcodeCache();
      setCache([]);
      setMessage(`Eliminate ${deleted} voci dalla cache.`);
    } catch (err) {
      setError(errorText(err));
    }
  };

  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold">Gestione barcode</h2>
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
          Controlla i codici acquisiti, verifica la normalizzazione e interroga di nuovo le anagrafiche esterne.
        </p>
      </div>

      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{error}</p>}
      {message && <p role="status" className="rounded-lg bg-green-50 p-3 text-sm text-green-700 dark:bg-green-950/40 dark:text-green-300">{message}</p>}

      <section className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
        <h3 className="font-semibold">Debug e correzione lettura</h3>
        <p className="mb-3 mt-1 text-sm text-gray-600 dark:text-gray-300">
          Inserisci il valore letto oppure correggilo manualmente. La correzione viene usata solo per questo controllo e non cambia gli item.
        </p>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_auto]">
          <label className="block text-sm font-medium">
            Codice acquisito o corretto
            <input value={code} onChange={(event) => { setCode(event.target.value); setDebugResult(null); }} onKeyDown={(event) => { if (event.key === 'Enter') void runDebug(); }} className="mt-1 min-h-11 w-full rounded-lg border px-3 font-mono font-normal dark:border-gray-600 dark:bg-gray-800" placeholder="EAN, ISBN, Code 128, QR…" />
          </label>
          <label className="block text-sm font-medium">
            Formato acquisito
            <select value={format} onChange={(event) => { setFormat(event.target.value); setDebugResult(null); }} className="mt-1 min-h-11 w-full rounded-lg border px-3 font-normal dark:border-gray-600 dark:bg-gray-800">
              <option value="">Non indicato</option>
              {formats.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <button type="button" onClick={() => setScannerOpen(true)} className="min-h-11 self-end rounded-lg bg-purple-600 px-4 font-medium text-white hover:bg-purple-700">📷 Acquisisci</button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" disabled={!code.trim() || debugging} onClick={() => void runDebug()} className="min-h-11 rounded-lg bg-blue-600 px-4 font-medium text-white hover:bg-blue-700 disabled:opacity-50">Analizza codice</button>
          <button type="button" disabled={!code.trim() || debugging} onClick={() => void runDebug(true)} className="min-h-11 rounded-lg bg-emerald-600 px-4 font-medium text-white hover:bg-emerald-700 disabled:opacity-50">{debugging ? 'Controllo…' : 'Forza nuovo controllo API'}</button>
        </div>

        {debugResult && (
          <div className="mt-4 space-y-3 rounded-lg bg-gray-50 p-4 text-sm dark:bg-gray-800/70">
            <div className="grid gap-2 sm:grid-cols-2">
              <p><strong>Valore acquisito:</strong> <code className="break-all">{debugResult.raw_code}</code></p>
              <p><strong>Valore normalizzato:</strong> <code className="break-all">{debugResult.normalized_code}</code></p>
              <p><strong>Formato:</strong> {debugResult.format || 'non disponibile'}</p>
              <p><strong>GTIN valido:</strong> {debugResult.is_valid_gtin ? 'Sì' : 'No'}</p>
              <p><strong>ISBN-13:</strong> {debugResult.is_isbn ? 'Sì' : 'No'}</p>
              <p><strong>Lookup esterno attivo:</strong> {debugResult.lookup_enabled ? 'Sì' : 'No'}</p>
              <p><strong>Controllato:</strong> {dateText(debugResult.checked_at)}</p>
            </div>
            <div>
              <strong>Item associati ({debugResult.matches.length})</strong>
              {debugResult.matches.length ? <ul className="mt-1 list-inside list-disc">{debugResult.matches.map((match) => <li key={match.barcode_id}>{match.item_name} · {match.inventory_name}</li>)}</ul> : <p className="mt-1 text-gray-600 dark:text-gray-300">Nessun item associato a questo codice.</p>}
            </div>
            <div>
              <strong>Risposta catalogo esterno</strong>
              {debugResult.product ? <p className="mt-1">{debugResult.product.name || 'Senza titolo'}{debugResult.product.brand ? ` · ${debugResult.product.brand}` : ''}{debugResult.product.quantity_label ? ` · ${debugResult.product.quantity_label}` : ''} · fonte: {debugResult.product.source || 'sconosciuta'}</p> : <p className="mt-1 text-gray-600 dark:text-gray-300">Nessun prodotto restituito. {debugResult.cache ? `Cache: ${debugResult.cache.found ? 'trovato' : 'non trovato'}, ${debugResult.cache.source || 'nessuna fonte'}, ${dateText(debugResult.cache.fetched_at)}.` : 'Nessun risultato salvato in cache.'}</p>}
              {debugResult.source_checks.length > 0 && <ul className="mt-1 list-inside list-disc">{debugResult.source_checks.map((check) => <li key={check.source}>{check.source}: {check.outcome === 'found' ? 'trovato' : check.outcome === 'missing' ? 'nessuna corrispondenza' : `errore (${check.detail || 'causa non specificata'})`}</li>)}</ul>}
              {!debugResult.lookup_enabled && <p className="mt-1 text-amber-700 dark:text-amber-300">La ricerca esterna è disattivata da BARCODE_LOOKUP_ENABLED.</p>}
            </div>
            {selectedBarcode && <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 dark:border-gray-700">
              <p>Associazione selezionata: <strong>{selectedBarcode.item_name}</strong> · {selectedBarcode.inventory_name}</p>
              <button type="button" onClick={() => void applyCorrection()} className="min-h-11 rounded-lg bg-amber-600 px-4 font-medium text-white hover:bg-amber-700">Applica codice corretto all’associazione</button>
            </div>}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold">Cache anagrafica</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Esiti positivi e negativi del lookup esterno.</p>
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => void loadData()} disabled={loading} className="min-h-10 rounded-lg border px-3 dark:border-gray-600">Aggiorna</button>
            <button type="button" onClick={() => void clearCache()} disabled={cache.length === 0} className="min-h-10 rounded-lg bg-red-600 px-3 text-white hover:bg-red-700 disabled:opacity-50">Svuota cache</button>
          </div>
        </div>
        {cache.length === 0 ? <p className="text-sm text-gray-500">{loading ? 'Caricamento…' : 'Nessuna voce in cache.'}</p> : (
          <ul className="space-y-2">
            {cache.map((entry) => (
              <li key={entry.code} className="flex flex-col gap-2 rounded-lg border p-3 dark:border-gray-700 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 text-sm">
                  <p className="break-all font-mono font-semibold">{entry.code} <span className={`ml-1 rounded px-2 py-0.5 font-sans text-xs ${entry.found ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200'}`}>{entry.found ? 'Trovato' : 'Non trovato'}</span></p>
                  <p className="truncate">{entry.name || 'Nessun nome'}{entry.brand ? ` · ${entry.brand}` : ''}</p>
                  <p className="text-gray-500">{entry.source || 'Nessuna fonte'} · {dateText(entry.fetched_at)}</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={() => { setCode(entry.code); setFormat(''); setSelectedBarcode(null); setDebugResult(null); }} className="min-h-10 rounded-lg border px-3 dark:border-gray-600">Usa per debug</button>
                  <button type="button" onClick={() => void removeCacheEntry(entry)} className="min-h-10 rounded-lg bg-red-600 px-3 text-white hover:bg-red-700">Elimina</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 className="font-semibold">Codici associati agli item</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">Seleziona un codice per analizzarlo o provarne una correzione.</p>
          </div>
          <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void loadData(); }}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} className="min-h-10 min-w-0 rounded-lg border px-3 dark:border-gray-600 dark:bg-gray-800" placeholder="Cerca codice, item o inventario" />
            <button type="submit" className="min-h-10 rounded-lg bg-gray-700 px-3 text-white">Cerca</button>
          </form>
        </div>
        {barcodes.length === 0 ? <p className="text-sm text-gray-500">{loading ? 'Caricamento…' : 'Nessun codice associato trovato.'}</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead><tr className="border-b dark:border-gray-700"><th className="p-2">Codice</th><th className="p-2">Formato</th><th className="p-2">Item</th><th className="p-2">Inventario / lista</th><th className="p-2">Ultima modifica</th><th className="p-2">Debug</th></tr></thead>
              <tbody>{barcodes.map((entry) => (
                <tr key={entry.id} className="border-b last:border-0 dark:border-gray-700">
                  <td className="break-all p-2 font-mono">{entry.code}</td><td className="p-2">{entry.format || '—'}</td><td className="p-2">{entry.item_name}</td><td className="p-2">{entry.inventory_name}</td><td className="p-2">{dateText(entry.data_mod)}</td>
                  <td className="p-2"><button type="button" onClick={() => { setCode(entry.code); setFormat(entry.format || ''); setSelectedBarcode(entry); setDebugResult(null); window.scrollTo({ top: 0, behavior: 'smooth' }); }} className="rounded-lg bg-blue-600 px-3 py-2 text-white">Usa</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      {scannerOpen && (
        <Suspense fallback={null}>
          <BarcodeScanner open={scannerOpen} onClose={() => setScannerOpen(false)} onDetected={(value, scannedFormat) => { setCode(value); setFormat(scannedFormat || ''); setDebugResult(null); setScannerOpen(false); }} />
        </Suspense>
      )}
    </section>
  );
}
