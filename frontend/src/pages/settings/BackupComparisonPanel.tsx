import { useEffect, useState } from "react";
import { isAxiosError } from "axios";
import { compareBackups } from "../../api";
import type { BackupComparison } from "../../api";

interface Props {
  beforeFilename: string;
  afterFilename: string | null;
  onClose: () => void;
}

const kindLabels = { added: "Aggiunto", removed: "Rimosso", modified: "Modificato" };

function displayValue(value: unknown, present: boolean): string {
  if (!present) return "(assente)";
  if (value === null) return "null";
  if (typeof value === "string") return value === "" ? '""' : value;
  return JSON.stringify(value);
}

export default function BackupComparisonPanel({ beforeFilename, afterFilename, onClose }: Props) {
  const [reversed, setReversed] = useState(false);
  const [table, setTable] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const before = reversed && afterFilename ? afterFilename : beforeFilename;
  const after = reversed ? beforeFilename : afterFilename;
  const requestKey = JSON.stringify([before, after, table, offset]);
  const [response, setResponse] = useState<{
    key: string;
    result: BackupComparison | null;
    error: string;
  } | null>(null);
  const loading = response?.key !== requestKey;
  const result = response?.key === requestKey ? response.result : null;
  const error = response?.key === requestKey ? response.error : "";

  useEffect(() => {
    const controller = new AbortController();
    compareBackups(before, after, table, offset, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) setResponse({ key: requestKey, result: data, error: "" });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        console.error("Errore nel confronto backup:", err);
        setResponse({
          key: requestKey,
          result: null,
          error: isAxiosError<{ detail?: string }>(err) && typeof err.response?.data.detail === "string"
            ? err.response.data.detail : "Errore nel confronto dei backup.",
        });
      });
    return () => controller.abort();
  }, [before, after, table, offset, requestKey]);

  return (
    <section aria-labelledby="backup-comparison-title" aria-busy={loading} className="min-w-0 space-y-3 rounded border border-gray-300 p-3 dark:border-gray-600">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="backup-comparison-title" className="font-semibold">Confronto backup (sola lettura)</h3>
        <button type="button" onClick={onClose} className="rounded border px-3 py-1">Chiudi confronto</button>
      </div>
      <p className="break-all text-sm"><strong>Prima:</strong> {before} → <strong>Dopo:</strong> {after ?? "DB corrente"}</p>
      <p className="text-sm text-gray-600 dark:text-gray-300">
        Record associati per chiave primaria: usare backup della stessa installazione.
        Password, hash, segreti riconosciuti e valori delle impostazioni sono oscurati, ma le loro modifiche sono conteggiate.
        Nessun dato viene ripristinato.
        {!afterFilename && " Il DB corrente viene riletto a ogni cambio pagina o filtro."}
      </p>
      {afterFilename && (
        <button type="button" disabled={loading} onClick={() => { setReversed(value => !value); setOffset(0); }}
          className="rounded border px-3 py-1 disabled:opacity-50">Inverti prima/dopo</button>
      )}
      {loading && <p role="status">Confronto in corso...</p>}
      {error && <p role="alert" className="text-red-700 dark:text-red-400">{error}</p>}
      {result && (
        <>
          <p className="text-sm">Revisione prima: {result.before.db_alembic_version ?? "n/d"} · Revisione dopo: {result.after.db_alembic_version ?? "n/d"}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Riepilogo delle differenze per tabella</caption>
              <thead><tr>{["Tabella", "Prima", "Dopo", "Aggiunti", "Rimossi", "Modificati", "Invariati"].map(label => <th key={label} scope="col" className="p-2">{label}</th>)}</tr></thead>
              <tbody>
                {result.tables.map(summary => (
                  <tr key={summary.table} className="border-t dark:border-gray-700">
                    <th scope="row" className="p-2 font-normal">{summary.table}
                      {!summary.before_present && " (assente prima)"}
                      {!summary.after_present && " (assente dopo)"}
                    </th>
                    <td className="p-2">{summary.before_count}</td><td className="p-2">{summary.after_count}</td>
                    <td className="p-2">{summary.added}</td><td className="p-2">{summary.removed}</td>
                    <td className="p-2">{summary.modified}</td><td className="p-2">{summary.unchanged}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <label className="block text-sm">
            Dettagli tabella:
            <select value={table ?? ""} onChange={event => { setTable(event.target.value || null); setOffset(0); }}
              className="ml-2 max-w-full rounded border p-1 dark:bg-gray-800">
              <option value="">Tutte</option>
              {result.tables.map(summary => <option key={summary.table} value={summary.table}>{summary.table}</option>)}
            </select>
          </label>
          <p role="status">{result.total_changes === 0 ? "Nessuna differenza nei record." : `${result.total_changes} record differenti${table ? ` in ${table}` : ""}.`}</p>
          {result.changes.map(change => (
            <details key={`${change.table}-${JSON.stringify(change.key)}`} className="min-w-0 rounded border p-2 dark:border-gray-700">
              <summary className="cursor-pointer break-all">{kindLabels[change.kind]} · {change.table} · {JSON.stringify(change.key)}</summary>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead><tr><th scope="col" className="p-2">Campo</th><th scope="col" className="p-2">Prima</th><th scope="col" className="p-2">Dopo</th></tr></thead>
                  <tbody>{change.fields.map(field => (
                    <tr key={field.field} className="border-t dark:border-gray-700">
                      <th scope="row" className="p-2 font-normal">{field.field}</th>
                      <td className="max-w-sm whitespace-pre-wrap break-all p-2">{displayValue(field.before, field.before_present)}</td>
                      <td className="max-w-sm whitespace-pre-wrap break-all p-2">{displayValue(field.after, field.after_present)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </details>
          ))}
          {(result.total_changes > result.limit || offset > 0) && (
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - result.limit))}
                className="rounded border px-3 py-1 disabled:opacity-50">Precedenti</button>
              <span>{result.changes.length > 0
                ? `${offset + 1}–${offset + result.changes.length} di ${result.total_changes}`
                : `Nessun record in questa pagina (${result.total_changes} totali)`}</span>
              {offset >= result.total_changes && (
                <button type="button" onClick={() => setOffset(0)} className="rounded border px-3 py-1">Torna alla prima pagina</button>
              )}
              <button type="button" disabled={offset + result.limit >= result.total_changes} onClick={() => setOffset(value => value + result.limit)}
                className="rounded border px-3 py-1 disabled:opacity-50">Successivi</button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
