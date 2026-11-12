import { useState, type ReactNode } from 'react';
import { Dialog } from '@headlessui/react';
import { FiSearch, FiSliders, FiX } from 'react-icons/fi';
import { useBottomSheetDrag } from './useBottomSheetDrag';
import type { FilterTemplateListItem } from '../types';

interface Props<Sort extends string> {
  search: string;
  onSearch: (value: string) => void;
  sortBy: Sort;
  sortOptions: ReadonlyArray<{ value: Sort; label: string }>;
  onSortBy: (value: Sort) => void;
  sortOrder: 'asc' | 'desc';
  onSortOrder: (value: 'asc' | 'desc') => void;
  checklist?: boolean;
  priorityOrder?: 'asc' | 'desc';
  onPriorityOrder?: (value: 'asc' | 'desc') => void;
  barcode?: 'all' | 'with' | 'without';
  onBarcode?: (value: 'all' | 'with' | 'without') => void;
  templateId?: number | '';
  templates?: FilterTemplateListItem[];
  onTemplate?: (value: number | '') => void;
  metadataSummary?: string | null;
  onClearMetadata?: () => void;
  onReset: () => void;
  metadataEditor?: ReactNode;
  placeholder?: string;
  selectionActions?: ReactNode;
}

export default function MobileItemFilters<Sort extends string>(props: Props<Sort>) {
  const [open, setOpen] = useState(false);
  const drag = useBottomSheetDrag(() => setOpen(false));
  const hasBarcode = props.barcode !== undefined && props.barcode !== 'all';
  const hasMetadata = props.metadataSummary != null || (props.templateId !== undefined && props.templateId !== '');
  const activeCount = Number(hasBarcode) + Number(hasMetadata);
  const control = 'min-h-11 w-full rounded-xl border border-gray-300 bg-white px-3 text-base md:text-sm dark:border-gray-600 dark:bg-gray-800';
  const segment = (selected: boolean) => `min-h-11 min-w-0 flex-1 rounded-lg px-2 text-sm ${selected ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100' : 'text-gray-700 dark:text-gray-200'}`;
  const ascending = props.sortBy === 'name' ? 'A → Z' : 'Crescente';
  const descending = props.sortBy === 'name' ? 'Z → A' : 'Decrescente';

  return (
    <>
      <div className="mb-2">
        <div className="flex items-center gap-2 py-1">
          <div className="relative min-w-0 flex-1">
            <FiSearch aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="search"
              aria-label="Ricerca libera"
              placeholder={props.placeholder ?? 'Cerca nella lista…'}
              value={props.search}
              onChange={(event) => props.onSearch(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Escape') props.onSearch(''); }}
              className={`${control} pl-9 pr-11 [&::-webkit-search-cancel-button]:appearance-none`}
            />
            {props.search && (
              <button type="button" onClick={() => props.onSearch('')} aria-label="Cancella ricerca" className="absolute right-0 top-0 grid h-11 w-11 place-items-center">
                <FiX aria-hidden="true" />
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label={`Filtri e ordinamento${activeCount ? ` (${activeCount} filtri attivi)` : ''}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            className="relative grid h-11 w-11 shrink-0 place-items-center rounded-xl border border-gray-300 dark:border-gray-600"
          >
            <FiSliders aria-hidden="true" />
            {activeCount > 0 && <span aria-hidden="true" className="absolute -right-1 -top-1 rounded-full bg-blue-600 px-1.5 text-xs text-white">{activeCount}</span>}
          </button>
        </div>
        {activeCount > 0 && (
          <div className="flex flex-wrap gap-1">
            {hasBarcode && (
              <button type="button" onClick={() => props.onBarcode?.('all')} className="min-h-9 rounded-full bg-blue-50 px-3 text-xs text-blue-800 dark:bg-blue-950 dark:text-blue-100">
                {props.barcode === 'with' ? 'Con barcode' : 'Senza barcode'} <span aria-hidden="true">×</span>
              </button>
            )}
            {hasMetadata && (
              <button type="button" onClick={props.onClearMetadata} className="min-h-9 max-w-full break-words rounded-full bg-blue-50 px-3 text-left text-xs text-blue-800 dark:bg-blue-950 dark:text-blue-100">
                {props.templates?.find(template => template.id === props.templateId)?.name ?? props.metadataSummary ?? 'Filtro metadati'} <span aria-hidden="true">×</span>
              </button>
            )}
          </div>
        )}
      </div>
      <Dialog open={open} onClose={setOpen} className="relative z-50">
        <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end md:items-center md:justify-center md:p-6">
          <Dialog.Panel
            style={{ transform: `translateY(${drag.offset}px)`, transition: drag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="max-h-[90dvh] w-full overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white md:max-w-lg md:rounded-2xl"
          >
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...drag.gripProps} className="mx-auto flex h-8 w-16 touch-none items-center justify-center"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" /></button>
            <div className="mb-4 flex items-center justify-between">
              <Dialog.Title className="text-lg font-bold">Filtri e ordinamento</Dialog.Title>
              <button type="button" onClick={() => setOpen(false)} aria-label="Chiudi filtri" className="grid h-11 w-11 place-items-center rounded-xl"><FiX aria-hidden="true" /></button>
            </div>
            <div className="space-y-4">
              <label className="block text-sm font-medium">
                Ordina per
                <select value={props.sortBy} onChange={(event) => {
                  const option = props.sortOptions.find(option => option.value === event.target.value);
                  if (option) props.onSortBy(option.value);
                }} className={`${control} mt-1`}>
                  {props.sortOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <fieldset>
                <legend className="mb-1 text-sm font-medium">Direzione</legend>
                <div className="flex rounded-xl border border-gray-300 p-1 dark:border-gray-600">
                  {(['asc', 'desc'] as const).map(value => <button key={value} type="button" aria-pressed={props.sortOrder === value} onClick={() => props.onSortOrder(value)} className={segment(props.sortOrder === value)}>{value === 'asc' ? ascending : descending}</button>)}
                </div>
              </fieldset>
              {props.checklist && (
                <fieldset>
                  <legend className="mb-1 text-sm font-medium">Priorità</legend>
                  <div className="flex rounded-xl border border-gray-300 p-1 dark:border-gray-600">
                    {(['desc', 'asc'] as const).map(value => <button key={value} type="button" aria-pressed={props.priorityOrder === value} onClick={() => props.onPriorityOrder?.(value)} className={segment(props.priorityOrder === value)}>{value === 'desc' ? 'Prima alta' : 'Prima bassa'}</button>)}
                  </div>
                </fieldset>
              )}
              {props.onBarcode && <fieldset>
                <legend className="mb-1 text-sm font-medium">Barcode</legend>
                <div className="flex rounded-xl border border-gray-300 p-1 dark:border-gray-600">
                  {(['all', 'with', 'without'] as const).map(value => <button key={value} type="button" aria-pressed={props.barcode === value} onClick={() => props.onBarcode?.(value)} className={segment(props.barcode === value)}>{value === 'all' ? 'Tutti' : value === 'with' ? 'Con barcode' : 'Senza barcode'}</button>)}
                </div>
              </fieldset>}
              {props.metadataEditor && (
                <>
                  <label className="block text-sm font-medium">
                    Template filtro
                    <select value={props.templateId} onChange={(event) => props.onTemplate?.(event.target.value ? Number(event.target.value) : '')} className={`${control} mt-1`}>
                      <option value="">Nessuno</option>
                      {props.templates?.map(template => <option key={template.id} value={template.id}>{template.name}</option>)}
                    </select>
                  </label>
                  {props.metadataEditor}
                </>
              )}
              {props.selectionActions}
              <button type="button" onClick={props.onReset} className="min-h-11 w-full rounded-xl border border-red-300 px-3 text-sm text-red-700 dark:text-red-300">Azzera filtri</button>
              <button type="button" onClick={() => setOpen(false)} className="min-h-11 w-full rounded-xl bg-blue-600 px-3 text-sm font-medium text-white">Chiudi</button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </>
  );
}
