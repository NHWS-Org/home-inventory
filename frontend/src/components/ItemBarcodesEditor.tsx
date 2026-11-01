import { useState, lazy, Suspense } from 'react';
import { addItemBarcode, deleteItemBarcode } from '../api';
import { ItemBarcode } from '../types';
const BarcodeScanner = lazy(() => import('./BarcodeScanner'));

interface Props {
  itemId: number;
  barcodes: ItemBarcode[];
  onChange: (barcodes: ItemBarcode[]) => void;
}

function errorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : 'Operazione non riuscita';
}

export default function ItemBarcodesEditor({ itemId, barcodes, onChange }: Props) {
  const [scannerOpen, setScannerOpen] = useState(false);
  const [manualCode, setManualCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const add = async (code: string, format: string | null) => {
    const trimmed = code.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const created = await addItemBarcode(itemId, trimmed, format);
      onChange([...barcodes, created]);
      setManualCode('');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const confirmRemove = (barcode: ItemBarcode) => {
    if (window.confirm(`Rimuovere il codice ${barcode.code} da questo item?`)) void remove(barcode);
  };

  const remove = async (barcode: ItemBarcode) => {
    setBusy(true);
    setError(null);
    try {
      await deleteItemBarcode(itemId, barcode.id);
      onChange(barcodes.filter((b) => b.id !== barcode.id));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-4">
      {barcodes.length === 0 && <p className="text-sm text-gray-500 mb-1">Nessun codice associato</p>}
      <ul className="mb-2 space-y-1">
        {barcodes.map((barcode) => (
          <li key={barcode.id} className="flex items-center gap-2 text-sm">
            <span className="font-mono break-all flex-1">{barcode.code}</span>
            {barcode.format && <span className="text-xs text-gray-500">{barcode.format}</span>}
            <button type="button" disabled={busy} onClick={() => confirmRemove(barcode)} className="px-2 py-1 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50" title="Rimuovi" aria-label="Rimuovi codice">🗑️</button>
          </li>
        ))}
      </ul>
      <div className="grid grid-cols-2 gap-2">
        <input
          className="col-span-2 min-h-12 w-full border rounded px-3"
          placeholder="Digita o incolla un codice"
          value={manualCode}
          onChange={(e) => setManualCode(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void add(manualCode, null);
            }
          }}
        />
        <button type="button" disabled={busy || !manualCode.trim()} onClick={() => void add(manualCode, null)} className="min-h-12 w-full bg-blue-500 text-white rounded-xl font-medium hover:bg-blue-600 disabled:opacity-50">
          Aggiungi
        </button>
        <button type="button" disabled={busy} onClick={() => setScannerOpen(true)} className="min-h-12 w-full bg-purple-600 text-white rounded-xl font-medium hover:bg-purple-700" title="Scansiona">
          📷 Scansiona
        </button>
      </div>
      {error && <p className="text-red-600 text-sm mt-1">{error}</p>}
      {scannerOpen && (
        <Suspense fallback={null}>
          <BarcodeScanner
            open={scannerOpen}
            onClose={() => setScannerOpen(false)}
            onDetected={(code, format) => {
              setScannerOpen(false);
              void add(code, format);
            }}
          />
        </Suspense>
      )}
    </div>
  );
}
