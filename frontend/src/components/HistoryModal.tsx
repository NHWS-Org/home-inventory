import { useState, useEffect, useContext, useMemo, ReactNode, useCallback } from 'react';
import { Dialog } from '@headlessui/react';
import { useBottomSheetDrag } from './useBottomSheetDrag';
import { ItemVersion, InventoryVersion } from '../types';
import {
  getItemHistory,
  rollbackItem,
  getInventoryHistory,
  rollbackInventory,
  getChecklistHistory,
  rollbackChecklist,
  deleteItemHistoryVersion,
  deleteItemHistoryVersions,
  deleteInventoryHistoryVersion,
  deleteInventoryHistoryVersions,
  deleteChecklistHistoryVersion,
  deleteChecklistHistoryVersions,
} from '../api';
import { AuthContext } from '../auth-context-instance';
import { parseDiffEntries } from '../utils/auditDiff';

interface HistoryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRollback?: () => void;
  entityType: 'item' | 'inventory' | 'checklist';
  itemContainerType?: 'INVENTORY' | 'CHECKLIST';
  entityId: number;
  entityName: string;
}

export function HistoryModal({
  isOpen,
  onClose,
  onRollback,
  entityType,
  itemContainerType,
  entityId,
  entityName,
}: HistoryModalProps) {
  const authContext = useContext(AuthContext);
  const user = authContext?.user;
  const isAdmin = user?.role?.name === 'admin';
  const canRollback = Boolean(user?.role?.name && user.role.name !== 'viewer');
  const [versions, setVersions] = useState<(ItemVersion | InventoryVersion)[]>([]);
    const displayedVersions = useMemo(
      () => [...versions].sort((a, b) => b.version_num - a.version_num),
      [versions]
    );

    const latestVersionNum = useMemo(
      () => (versions.length > 0 ? Math.max(...versions.map((v) => v.version_num)) : null),
      [versions]
    );

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedVersionNums, setSelectedVersionNums] = useState<number[]>([]);
  const sheetDrag = useBottomSheetDrag(onClose);

  const describeVersion = (version: ItemVersion | InventoryVersion): { label: string; content: ReactNode }[] => {
    if (version.operation === 'CREATE') {
      return [{ label: 'Azione', content: 'Record creato' }];
    }
    if (version.operation === 'DELETE') {
      return [{ label: 'Azione', content: 'Record eliminato' }];
    }

    if (!version.diff) {
      return [{ label: 'Modifiche', content: 'Nessuna modifica dettagliata disponibile' }];
    }

    const isChecklistQuantity =
      version.operation === 'UPDATE' &&
      entityType === 'item' &&
      itemContainerType === 'CHECKLIST';

    const entries = parseDiffEntries(version.diff, isChecklistQuantity);
    if (entries.length === 0) {
      return [{ label: 'Modifiche', content: 'Nessuna modifica rilevata' }];
    }

    return entries.map((entry) => ({
      label: entry.label,
      content: entry.formattedChange,
    }));
  };

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let data;
      if (entityType === 'item') {
        data = await getItemHistory(entityId);
      } else if (entityType === 'inventory') {
        data = await getInventoryHistory(entityId);
      } else {
        data = await getChecklistHistory(entityId);
      }
      setVersions(data);
      setSelectedVersionNums([]);
    } catch (err) {
      setError('Errore nel caricamento della cronologia');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [entityId, entityType]);

  useEffect(() => {
    if (!isOpen) return;
    fetchHistory();
  }, [isOpen, fetchHistory]);

  const handleRollback = async (versionNum: number) => {
    if (!window.confirm(`Vuoi ripristinare la versione ${versionNum}?`)) return;
    
    try {
      if (entityType === 'item') {
        await rollbackItem(entityId, versionNum);
      } else if (entityType === 'inventory') {
        await rollbackInventory(entityId, versionNum);
      } else {
        await rollbackChecklist(entityId, versionNum);
      }
      
      if (onRollback) onRollback();
      onClose();
    } catch (err) {
      setError('Errore nel ripristino della versione');
      console.error(err);
    }
  };

  const toggleVersionSelection = (versionNum: number) => {
    setSelectedVersionNums((prev) =>
      prev.includes(versionNum)
        ? prev.filter((v) => v !== versionNum)
        : [...prev, versionNum]
    );
  };

  const handleDeleteSingle = async (versionNum: number) => {
    if (!window.confirm(`Vuoi eliminare la versione v${versionNum}?`)) return;
    try {
      if (entityType === 'item') {
        await deleteItemHistoryVersion(entityId, versionNum);
      } else if (entityType === 'inventory') {
        await deleteInventoryHistoryVersion(entityId, versionNum);
      } else {
        await deleteChecklistHistoryVersion(entityId, versionNum);
      }
      await fetchHistory();
      if (onRollback) onRollback();
    } catch (err) {
      setError('Errore durante la cancellazione della versione');
      console.error(err);
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedVersionNums.length === 0) return;
    if (!window.confirm(`Vuoi eliminare ${selectedVersionNums.length} versioni selezionate?`)) return;

    try {
      if (entityType === 'item') {
        await deleteItemHistoryVersions(entityId, selectedVersionNums);
      } else if (entityType === 'inventory') {
        await deleteInventoryHistoryVersions(entityId, selectedVersionNums);
      } else {
        await deleteChecklistHistoryVersions(entityId, selectedVersionNums);
      }
      await fetchHistory();
      if (onRollback) onRollback();
    } catch (err) {
      setError('Errore durante la cancellazione massiva');
      console.error(err);
    }
  };

  const operationBadge = (op: string) => {
    const colors: { [key: string]: string } = {
      'CREATE': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
      'UPDATE': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      'DELETE': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    };
    return colors[op] || '';
  };

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
      <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
        <Dialog.Panel
          style={{ transform: `translateY(${sheetDrag.offset}px)`, transition: sheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
          className="flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl bg-white pb-[calc(env(safe-area-inset-bottom)+0.75rem)] shadow-2xl dark:bg-gray-900 sm:rounded-2xl sm:pb-0"
        >
          <div className="shrink-0 border-b border-gray-200 px-4 pb-3 pt-2 dark:border-gray-700 sm:p-6 sm:pb-4">
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...sheetDrag.gripProps} className="mx-auto mb-2 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <div className="flex items-center justify-between gap-3">
              <Dialog.Title className="min-w-0 text-lg font-bold dark:text-white sm:text-xl">
                Cronologia: {entityName}
              </Dialog.Title>
              <button type="button" onClick={onClose} aria-label="Chiudi cronologia" className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-2xl text-gray-500 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800">×</button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
            {loading && <div className="text-center text-gray-500">Caricamento...</div>}
            {error && <div className="text-center text-red-500 mb-4">{error}</div>}

            {!loading && versions.length > 0 && (
              <div className="space-y-3">
                {isAdmin && (
                      <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:justify-end">
                    <button
                      onClick={() => setSelectedVersionNums(displayedVersions.map((v) => v.version_num))}
                      className="min-h-11 w-full rounded-xl bg-gray-200 px-2 text-sm hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 sm:min-h-0 sm:w-auto sm:rounded sm:px-3 sm:py-1"
                    >
                      Seleziona tutte
                    </button>
                    <button
                      onClick={() => setSelectedVersionNums([])}
                      className="min-h-11 w-full rounded-xl bg-gray-200 px-2 text-sm hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 sm:min-h-0 sm:w-auto sm:rounded sm:px-3 sm:py-1"
                    >
                      Deseleziona
                    </button>
                    <button
                      onClick={handleDeleteSelected}
                      disabled={selectedVersionNums.length === 0}
                      className="col-span-2 min-h-11 w-full rounded-xl bg-red-600 px-2 text-sm text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed sm:col-span-1 sm:min-h-0 sm:w-auto sm:rounded sm:px-3 sm:py-1"
                    >
                      Elimina selezionate ({selectedVersionNums.length})
                    </button>
                  </div>
                )}

                {displayedVersions.map((version) => (
                  <div
                    key={version.version_num}
                    className="border rounded-lg p-4 dark:border-gray-700 dark:bg-gray-800"
                  >
                    <div className="flex items-start justify-between gap-2 flex-wrap">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          {isAdmin && (
                            <input
                              type="checkbox"
                              checked={selectedVersionNums.includes(version.version_num)}
                              onChange={() => toggleVersionSelection(version.version_num)}
                              className="w-4 h-4"
                              title={`Seleziona versione v${version.version_num}`}
                            />
                          )}
                          <span className={`px-2 py-1 rounded text-sm font-semibold ${operationBadge(version.operation)}`}>
                            {version.operation}
                          </span>
                          <span className="text-sm font-mono bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded">
                            v{version.version_num}
                          </span>
                        </div>
                        <div className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                          <p>
                            da <strong>{version.changed_by_username || 'Sconosciuto'}</strong> il{' '}
                            <time>{new Date(version.changed_at).toLocaleString()}</time>
                          </p>
                        </div>

                        <div className="text-xs bg-gray-50 dark:bg-gray-700/40 rounded p-3 space-y-1">
                          {describeVersion(version).map((entry, entryIdx) => (
                            <p key={entryIdx} className="text-gray-700 dark:text-gray-200">
                              <span className="font-semibold">{entry.label}:</span> {entry.content}
                            </p>
                          ))}
                        </div>
                      </div>

                      <div className="flex w-full gap-2 sm:w-auto sm:items-center">
                        {canRollback && version.operation !== 'DELETE' && version.version_num !== latestVersionNum && (
                          <button
                            onClick={() => handleRollback(version.version_num)}
                            className="min-h-11 flex-1 rounded-xl bg-blue-500 px-3 text-sm text-white hover:bg-blue-600 sm:min-h-0 sm:flex-none sm:rounded sm:py-1 sm:whitespace-nowrap"
                          >
                            Ripristina
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            onClick={() => handleDeleteSingle(version.version_num)}
                            className="min-h-11 flex-1 rounded-xl bg-red-600 px-3 text-sm text-white hover:bg-red-700 sm:min-h-0 sm:flex-none sm:rounded sm:py-1 sm:whitespace-nowrap"
                          >
                            Elimina
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!loading && versions.length === 0 && (
              <div className="text-center text-gray-500">Nessuna cronologia disponibile</div>
            )}
          </div>

          <div className="shrink-0 border-t border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
            <button
              onClick={onClose}
              className="min-h-12 w-full rounded-xl bg-gray-300 px-4 font-medium text-black hover:bg-gray-400 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
            >
              Chiudi
            </button>
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
