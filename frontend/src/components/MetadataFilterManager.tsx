import { useEffect, useMemo, useRef, useState } from 'react';
import { Dialog } from '@headlessui/react';
import { useBottomSheetDrag } from './useBottomSheetDrag';

import {
  createFilterTemplate,
  deleteFilterTemplate,
  getFilterTemplate,
  getFilterTemplates,
  getFilterTemplateScopePreview,
  updateFilterTemplate,
} from '../api';
import {
  FilterTemplate,
  FilterTemplateListItem,
  FilterTemplateScopePreview,
  MetadataDefinition,
  MetadataFilterOperator,
} from '../types';

type MatchMode = 'all' | 'any';
type CriterionKind = 'NUMBER' | 'DATE' | 'BOOLEAN' | 'TEXT' | 'LIST';

type CriterionRow = {
  id: string;
  kind: CriterionKind;
  definitionId: number | null;
  operator: MetadataFilterOperator;
  valueText: string;
  rangeFrom: string;
  rangeTo: string;
  boolValue: boolean | '';
};

function newId() {
  return Math.random().toString(36).slice(2, 10);
}

function emptyRow(kind: CriterionKind = 'NUMBER'): CriterionRow {
  return {
    id: newId(),
    kind,
    definitionId: null,
    operator: 'equals',
    valueText: '',
    rangeFrom: '',
    rangeTo: '',
    boolValue: '',
  };
}

function isBetween(op: MetadataFilterOperator) {
  return op === 'between';
}

function isDynamicTodayToken(value: string) {
  const normalized = value.trim().toLowerCase();
  return normalized === 'today' || normalized === 'oggi';
}

const numericOperators: Array<{ value: MetadataFilterOperator; label: string }> = [
  { value: 'equals', label: '=' },
  { value: 'not_equals', label: '!=' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '>=' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '<=' },
  { value: 'between', label: 'between' },
  { value: 'is_null', label: 'Non impostato' },
  { value: 'is_not_null', label: 'Impostato' },
];

const dateOperators: Array<{ value: MetadataFilterOperator; label: string }> = [
  { value: 'equals', label: '=' },
  { value: 'not_equals', label: '!=' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '>=' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '<=' },
  { value: 'between', label: 'between' },
  { value: 'is_null', label: 'Non impostato' },
  { value: 'is_not_null', label: 'Impostato' },
];

const booleanOperators: Array<{ value: MetadataFilterOperator; label: string }> = [
  { value: 'equals', label: '=' },
  { value: 'not_equals', label: '!=' },
  { value: 'is_null', label: 'Non impostato' },
  { value: 'is_not_null', label: 'Impostato' },
];

const textOperators: Array<{ value: MetadataFilterOperator; label: string }> = [
  { value: 'equals', label: '=' },
  { value: 'not_equals', label: '!=' },
  { value: 'contains', label: 'contiene' },
  { value: 'not_contains', label: 'non contiene' },
  { value: 'is_null', label: 'Non impostato' },
  { value: 'is_not_null', label: 'Impostato' },
];

const listOperators: Array<{ value: MetadataFilterOperator; label: string }> = [
  { value: 'equals', label: '=' },
  { value: 'not_equals', label: '!=' },
  { value: 'is_null', label: 'Non impostato' },
  { value: 'is_not_null', label: 'Impostato' },
];

function parseTemplate(template: FilterTemplate): { matchMode: MatchMode; rows: CriterionRow[] } {
  const root = template.criteria as Record<string, unknown>;
  const rowsRaw = Array.isArray(root?.criteria) ? (root.criteria as Array<Record<string, unknown>>) : [];

  const rows = rowsRaw.map((entry) => {
    const kind = (entry.field_type as CriterionKind)
      ?? (entry.value_boolean != null ? 'BOOLEAN' : entry.value_date != null ? 'DATE' : entry.value_text != null ? 'TEXT' : 'NUMBER');
    const rawDefinitionId = entry.definition_id;
    const definitionId = typeof rawDefinitionId === 'number'
      ? rawDefinitionId
      : typeof rawDefinitionId === 'string' && rawDefinitionId.trim() !== ''
        ? Number(rawDefinitionId)
        : null;

    return {
      id: newId(),
      kind,
      definitionId,
      operator: (entry.operator as MetadataFilterOperator) ?? 'equals',
      valueText:
        kind === 'NUMBER'
          ? (entry.value_number != null ? String(entry.value_number) : '')
          : kind === 'DATE'
            ? (entry.value_date != null ? String(entry.value_date) : '')
            : (entry.value_text != null ? String(entry.value_text) : ''),
      rangeFrom: entry.range_from != null ? String(entry.range_from) : '',
      rangeTo: entry.range_to != null ? String(entry.range_to) : '',
      boolValue: typeof entry.value_boolean === 'boolean' ? entry.value_boolean : '',
    } as CriterionRow;
  }).filter((r) => r.definitionId !== null);

  return {
    matchMode: root?.match_mode === 'any' ? 'any' : 'all',
    rows: rows.length > 0 ? rows : [emptyRow()],
  };
}

function serializeRows(rows: CriterionRow[]): Array<Record<string, unknown>> {
  return rows
    .filter((r) => r.definitionId !== null)
    .filter((r) => {
      if (r.operator === 'is_null' || r.operator === 'is_not_null') return true;
      if (r.kind === 'BOOLEAN') return r.boolValue !== '';
      if (isBetween(r.operator)) return r.rangeFrom !== '' && r.rangeTo !== '';
      return r.valueText !== '';
    })
    .map((r) => {
      const base: Record<string, unknown> = {
        definition_id: r.definitionId as number,
        field_type: r.kind,
        operator: r.operator,
      };

      if (r.operator === 'is_null' || r.operator === 'is_not_null') {
        return base;
      }

      if (r.kind === 'BOOLEAN') {
        return { ...base, value_boolean: r.boolValue === true };
      }
      if (r.kind === 'DATE') {
        if (isBetween(r.operator)) return { ...base, range_from: r.rangeFrom, range_to: r.rangeTo };
        return { ...base, value_date: r.valueText };
      }
      if (r.kind === 'TEXT' || r.kind === 'LIST') {
        return { ...base, value_text: r.valueText };
      }
      if (isBetween(r.operator)) return { ...base, range_from: r.rangeFrom, range_to: r.rangeTo };
      return { ...base, value_number: r.valueText };
    });
}

function deduceFilterType(rows: CriterionRow[]): 'numeric' | 'date' | 'boolean' | 'text' | 'composite' {
  const kinds = new Set(rows.filter((r) => r.definitionId !== null).map((r) => r.kind));
  if (kinds.size === 1) {
    const only = Array.from(kinds)[0];
    if (only === 'NUMBER') return 'numeric';
    if (only === 'DATE') return 'date';
    if (only === 'BOOLEAN') return 'boolean';
    if (only === 'TEXT' || only === 'LIST') return 'text';
  }
  if (Array.from(kinds).every((kind) => kind === 'TEXT' || kind === 'LIST')) {
    return 'text';
  }
  return 'composite';
}

export default function MetadataFilterManager({
  inventoryId,
  currentContainerType,
  definitions,
  allDefinitions,
  onTemplatesChanged,
  triggerLabel,
  triggerClassName = '',
  onDialogClose,
}: {
  inventoryId: number;
  currentContainerType: 'INVENTORY' | 'CHECKLIST';
  definitions: MetadataDefinition[];
  allDefinitions?: MetadataDefinition[];
  onTemplatesChanged?: (templates: FilterTemplateListItem[]) => void;
  triggerLabel?: string;
  triggerClassName?: string;
  onDialogClose?: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [templates, setTemplates] = useState<FilterTemplateListItem[]>([]);
  const [matchMode, setMatchMode] = useState<MatchMode>('all');
  const [rows, setRows] = useState<CriterionRow[]>([emptyRow()]);
  const [templateName, setTemplateName] = useState('');
  const [templateDescription, setTemplateDescription] = useState('');
  const [editingTemplateId, setEditingTemplateId] = useState<number | null>(null);
  const [useAllDefs, setUseAllDefs] = useState(true);
  const [scopePreview, setScopePreview] = useState<FilterTemplateScopePreview | null>(null);
  const [scopePreviewLoading, setScopePreviewLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'success' | 'error' | ''>('');
  const timerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const dialogPanelRef = useRef<HTMLDivElement>(null);

  const allDefs = allDefinitions ?? definitions;
  const defsByKind = useMemo(() => ({
    NUMBER: definitions.filter((d) => d.is_active && d.field_type === 'NUMBER'),
    DATE: definitions.filter((d) => d.is_active && d.field_type === 'DATE'),
    BOOLEAN: definitions.filter((d) => d.is_active && d.field_type === 'BOOLEAN'),
    TEXT: definitions.filter((d) => d.is_active && d.field_type === 'TEXT'),
    LIST: definitions.filter((d) => d.is_active && d.field_type === 'LIST'),
  }), [definitions]);
  const allDefsByKind = useMemo(() => ({
    NUMBER: allDefs.filter((d) => d.is_active && d.field_type === 'NUMBER'),
    DATE: allDefs.filter((d) => d.is_active && d.field_type === 'DATE'),
    BOOLEAN: allDefs.filter((d) => d.is_active && d.field_type === 'BOOLEAN'),
    TEXT: allDefs.filter((d) => d.is_active && d.field_type === 'TEXT'),
    LIST: allDefs.filter((d) => d.is_active && d.field_type === 'LIST'),
  }), [allDefs]);

  function defsFor(kind: CriterionKind) {
    return useAllDefs ? allDefsByKind[kind] : defsByKind[kind];
  }

  function showMessage(text: string, type: 'success' | 'error') {
    setMessage(text);
    setMessageType(type);
    window.setTimeout(() => {
      setMessage('');
      setMessageType('');
    }, type === 'success' ? 3000 : 5000);
  }

  function resetCreate() {
    setEditingTemplateId(null);
    setTemplateName('');
    setTemplateDescription('');
    setMatchMode('all');
    setRows([emptyRow()]);
  }

  function closeAndReset() {
    setIsOpen(false);
    resetCreate();
    onDialogClose?.();
  }

  const sheetDrag = useBottomSheetDrag(closeAndReset);

  useEffect(() => {
    if (isOpen && dialogPanelRef.current) dialogPanelRef.current.scrollTop = 0;
  }, [isOpen]);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await getFilterTemplates(inventoryId, true, true);
        setTemplates(data);
        onTemplatesChanged?.(data);
      } catch {
        setTemplates([]);
        onTemplatesChanged?.([]);
      }
    };
    void load();
  }, [inventoryId, onTemplatesChanged]);

  useEffect(() => {
    const ids = Array.from(new Set(rows.map((r) => r.definitionId).filter((id): id is number => id !== null)));
    if (timerRef.current) window.clearTimeout(timerRef.current);
    if (ids.length === 0) {
      setScopePreview(null);
      return;
    }
    timerRef.current = window.setTimeout(async () => {
      setScopePreviewLoading(true);
      try {
        const preview = await getFilterTemplateScopePreview(ids);
        setScopePreview(preview);
      } catch {
        setScopePreview(null);
      } finally {
        setScopePreviewLoading(false);
      }
    }, 500);
  }, [rows]);

  async function saveTemplate() {
    if (!templateName.trim()) {
      showMessage('Inserisci un nome template.', 'error');
      return;
    }

    const criteria = serializeRows(rows);
    if (criteria.length === 0) {
      showMessage('Aggiungi almeno un criterio valido.', 'error');
      return;
    }

    const filterType = deduceFilterType(rows);

    setBusy(true);
    try {
      if (editingTemplateId) {
        await updateFilterTemplate(editingTemplateId, {
          name: templateName.trim(),
          description: templateDescription.trim() || null,
          filter_type: filterType,
          criteria: {
            filter_type: filterType,
            match_mode: matchMode,
            criteria,
          },
        });
      } else {
        await createFilterTemplate({
          name: templateName.trim(),
          description: templateDescription.trim() || null,
          filter_type: filterType,
          criteria: {
            filter_type: filterType,
            match_mode: matchMode,
            criteria,
          },
          is_shared: false,
        });
      }

      const data = await getFilterTemplates(inventoryId, true, true);
      setTemplates(data);
      onTemplatesChanged?.(data);
      showMessage(editingTemplateId ? 'Template aggiornato.' : 'Template salvato.', 'success');
      resetCreate();
    } catch {
      showMessage(editingTemplateId ? 'Aggiornamento template non riuscito.' : 'Salvataggio template non riuscito.', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function editTemplate(templateId: number) {
    setBusy(true);
    try {
      const template = await getFilterTemplate(templateId);
      const parsed = parseTemplate(template);
      setMatchMode(parsed.matchMode);
      setRows(parsed.rows);
      setTemplateName(template.name ?? '');
      setTemplateDescription(template.description ?? '');
      setEditingTemplateId(template.id);
      setIsOpen(true);
    } catch {
      showMessage('Impossibile aprire il template in modifica.', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function removeTemplate(templateId: number) {
    if (!window.confirm('Eliminare il template selezionato?')) return;
    setBusy(true);
    try {
      await deleteFilterTemplate(templateId);
      const next = templates.filter((t) => t.id !== templateId);
      setTemplates(next);
      onTemplatesChanged?.(next);
      if (editingTemplateId === templateId) resetCreate();
      showMessage('Template eliminato.', 'success');
    } catch {
      showMessage('Errore durante l\'eliminazione del template.', 'error');
    } finally {
      setBusy(false);
    }
  }

  function isTemplateCompatible(template: FilterTemplateListItem): boolean {
    const preview = template.scope_preview;
    if (!preview) return true;
    if (preview.scope_type === 'global') return true;
    if (preview.scope_type === 'all_inventories') return currentContainerType === 'INVENTORY';
    if (preview.scope_type === 'all_checklists') return currentContainerType === 'CHECKLIST';
    if (preview.scope_type === 'none') return false;
    return preview.inventories.some((inv) => inv.id === inventoryId);
  }

  return (
    <>
      <button
        onClick={(event) => {
          // The mobile trigger is inside the expandable actions menu. Keep that
          // menu mounted while the dialog opens so its state is not discarded.
          event.stopPropagation();
          resetCreate();
          setIsOpen(true);
        }}
        className={`py-2 px-4 bg-indigo-600 text-white rounded-full shadow-lg hover:bg-indigo-700 ${triggerClassName}`}
      >
        {triggerLabel ?? <>
          <span className="inline md:hidden">🧩</span>
          <span className="hidden md:inline">Filtri metadata</span>
        </>}
      </button>

      <Dialog open={isOpen} onClose={closeAndReset} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel
            ref={dialogPanelRef}
            style={{ transform: `translateY(${sheetDrag.offset}px)`, transition: sheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="max-h-[92dvh] w-full overflow-y-auto rounded-t-3xl bg-white p-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white sm:max-w-6xl sm:rounded-xl sm:p-6 sm:pb-6 xl:overflow-hidden"
          >
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...sheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <div className="mb-3 flex items-center justify-between gap-3">
              <Dialog.Title className="text-lg font-semibold">
                {editingTemplateId ? 'Modifica template filtri metadati' : 'Builder filtri metadati'}
              </Dialog.Title>
              <button type="button" onClick={closeAndReset} aria-label="Chiudi filtri metadati" className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gray-100 text-3xl leading-none text-gray-600 hover:bg-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700">×</button>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px] xl:h-[78vh]">
              <div className="space-y-4 xl:min-h-0 flex flex-col">
                <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                  <div>
                    <label className="mb-1 block text-sm font-medium">Match mode</label>
                    <select
                      value={matchMode}
                      onChange={(event) => setMatchMode(event.target.value as MatchMode)}
                      className="w-full rounded border px-3 py-2 dark:bg-gray-800"
                    >
                      <option value="all">Tutti i criteri</option>
                      <option value="any">Almeno un criterio</option>
                    </select>
                  </div>
                  {allDefinitions && allDefinitions.length > 0 && (
                    <div className="flex flex-col justify-end">
                      <label className="mb-1 block text-sm font-medium">Campi disponibili</label>
                      <button
                        type="button"
                        onClick={() => setUseAllDefs((v) => !v)}
                        className={`rounded border px-3 py-2 text-sm whitespace-nowrap transition-colors ${
                          useAllDefs
                            ? 'border-indigo-600 bg-indigo-600 text-white'
                            : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200'
                        }`}
                      >
                        {useAllDefs ? '🌍 Tutti i metadati' : '📦 Solo questo contenitore'}
                      </button>
                    </div>
                  )}
                </div>

                <div className="rounded border border-gray-200 p-3 dark:border-gray-700 xl:flex-1 xl:min-h-0 xl:overflow-y-auto space-y-3">
                  {rows.map((row, index) => {
                    const options = defsFor(row.kind);
                    const selectedDefinition = options.find((definition) => definition.id === row.definitionId);
                    const operators = row.kind === 'NUMBER'
                      ? numericOperators
                      : row.kind === 'DATE'
                        ? dateOperators
                        : row.kind === 'BOOLEAN'
                          ? booleanOperators
                          : row.kind === 'TEXT'
                            ? textOperators
                            : listOperators;
                    const isNullOp = row.operator === 'is_null' || row.operator === 'is_not_null';

                    return (
                      <div key={row.id} className="rounded border p-3 dark:border-gray-700">
                        <div className="mb-2 flex items-center justify-between">
                          <span className="text-sm font-medium">Criterio {index + 1}</span>
                          {rows.length > 1 && (
                            <button
                              className="text-sm text-red-600 hover:underline"
                              onClick={() => setRows((current) => current.filter((r) => r.id !== row.id))}
                              type="button"
                            >
                              Rimuovi
                            </button>
                          )}
                        </div>

                        <div className="grid gap-3 md:grid-cols-[140px_minmax(0,1fr)_170px_minmax(0,1fr)]">
                          <select
                            value={row.kind}
                            onChange={(event) => {
                              const nextKind = event.target.value as CriterionKind;
                              setRows((current) => current.map((r) =>
                                r.id === row.id ? { ...emptyRow(nextKind), id: row.id } : r,
                              ));
                            }}
                            className="rounded border px-3 py-2 dark:bg-gray-800"
                          >
                            <option value="NUMBER">Numerico</option>
                            <option value="DATE">Data</option>
                            <option value="BOOLEAN">Booleano</option>
                            <option value="TEXT">Testo</option>
                            <option value="LIST">Lista</option>
                          </select>

                          <select
                            value={row.definitionId ?? ''}
                            onChange={(event) => setRows((current) => current.map((r) =>
                              r.id === row.id
                                ? { ...r, definitionId: event.target.value ? Number(event.target.value) : null }
                                : r,
                            ))}
                            className="rounded border px-3 py-2 dark:bg-gray-800"
                          >
                            <option value="">Seleziona metadato</option>
                            {options.map((definition) => (
                              <option key={definition.id} value={definition.id}>{definition.label}</option>
                            ))}
                          </select>

                          <select
                            value={row.operator}
                            onChange={(event) => setRows((current) => current.map((r) =>
                              r.id === row.id
                                ? { ...r, operator: event.target.value as MetadataFilterOperator }
                                : r,
                            ))}
                            className="rounded border px-3 py-2 dark:bg-gray-800"
                          >
                            {operators.map((operator) => (
                              <option key={operator.value} value={operator.value}>{operator.label}</option>
                            ))}
                          </select>

                          {row.kind === 'BOOLEAN' ? (
                            <select
                              value={row.boolValue === '' ? '' : row.boolValue ? 'true' : 'false'}
                              onChange={(event) => setRows((current) => current.map((r) =>
                                r.id === row.id
                                  ? { ...r, boolValue: event.target.value === '' ? '' : event.target.value === 'true' }
                                  : r,
                              ))}
                              className="rounded border px-3 py-2 dark:bg-gray-800"
                              disabled={isNullOp}
                            >
                              <option value="">Seleziona valore</option>
                              <option value="true">Sì</option>
                              <option value="false">No</option>
                            </select>
                          ) : row.kind === 'LIST' ? (
                            <select
                              value={row.valueText}
                              onChange={(event) => setRows((current) => current.map((r) =>
                                r.id === row.id ? { ...r, valueText: event.target.value } : r,
                              ))}
                              className="rounded border px-3 py-2 dark:bg-gray-800"
                              disabled={isNullOp || !selectedDefinition}
                            >
                              <option value="">[Vuoto]</option>
                              {(selectedDefinition?.list_options ?? []).map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          ) : row.kind === 'DATE' && !isBetween(row.operator) ? (
                            <div className="space-y-2">
                              <div className="flex gap-2">
                                <button
                                  type="button"
                                  className={`rounded border px-2 py-1 text-xs ${
                                    isDynamicTodayToken(row.valueText)
                                      ? 'border-gray-300 bg-white text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200'
                                      : 'border-indigo-600 bg-indigo-600 text-white'
                                  }`}
                                  onClick={() => setRows((current) => current.map((r) =>
                                    r.id === row.id ? { ...r, valueText: '' } : r,
                                  ))}
                                  disabled={isNullOp}
                                >
                                  Data fissa
                                </button>
                                <button
                                  type="button"
                                  className={`rounded border px-2 py-1 text-xs ${
                                    isDynamicTodayToken(row.valueText)
                                      ? 'border-indigo-600 bg-indigo-600 text-white'
                                      : 'border-gray-300 bg-white text-gray-700 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200'
                                  }`}
                                  onClick={() => setRows((current) => current.map((r) =>
                                    r.id === row.id ? { ...r, valueText: 'today' } : r,
                                  ))}
                                  disabled={isNullOp}
                                >
                                  Oggi (dinamico)
                                </button>
                              </div>

                              {isDynamicTodayToken(row.valueText) ? (
                                <div className="rounded border border-indigo-300 bg-indigo-50 px-3 py-2 text-sm text-indigo-900 dark:border-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-200">
                                  Valore dinamico selezionato: <strong>oggi</strong>
                                </div>
                              ) : (
                                <input
                                  type="date"
                                  value={row.valueText}
                                  onChange={(event) => setRows((current) => current.map((r) =>
                                    r.id === row.id ? { ...r, valueText: event.target.value } : r,
                                  ))}
                                  className="rounded border px-3 py-2 dark:bg-gray-800 w-full"
                                  placeholder="Valore"
                                  disabled={isNullOp}
                                />
                              )}
                            </div>
                          ) : isBetween(row.operator) ? (
                            <div className="grid gap-2 sm:grid-cols-2">
                              <input
                                type={row.kind === 'NUMBER' ? 'number' : 'date'}
                                value={row.rangeFrom}
                                onChange={(event) => setRows((current) => current.map((r) =>
                                  r.id === row.id ? { ...r, rangeFrom: event.target.value } : r,
                                ))}
                                className="rounded border px-3 py-2 dark:bg-gray-800"
                                placeholder="Da"
                                disabled={isNullOp}
                              />
                              <input
                                type={row.kind === 'NUMBER' ? 'number' : 'date'}
                                value={row.rangeTo}
                                onChange={(event) => setRows((current) => current.map((r) =>
                                  r.id === row.id ? { ...r, rangeTo: event.target.value } : r,
                                ))}
                                className="rounded border px-3 py-2 dark:bg-gray-800"
                                placeholder="A"
                                disabled={isNullOp}
                              />
                            </div>
                          ) : row.kind === 'TEXT' ? (
                            <input
                              type="text"
                              value={row.valueText}
                              onChange={(event) => setRows((current) => current.map((r) =>
                                r.id === row.id ? { ...r, valueText: event.target.value } : r,
                              ))}
                              className="rounded border px-3 py-2 dark:bg-gray-800"
                              placeholder="Valore"
                              disabled={isNullOp}
                            />
                          ) : (
                            <input
                              type={row.kind === 'NUMBER' ? 'number' : 'date'}
                              value={row.valueText}
                              onChange={(event) => setRows((current) => current.map((r) =>
                                r.id === row.id ? { ...r, valueText: event.target.value } : r,
                              ))}
                              className="rounded border px-3 py-2 dark:bg-gray-800"
                              placeholder="Valore"
                              disabled={isNullOp}
                            />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="flex justify-start">
                  <button
                    type="button"
                    onClick={() => setRows((current) => [...current, emptyRow()])}
                    className="rounded bg-gray-200 px-3 py-2 text-sm hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600"
                  >
                    Aggiungi criterio
                  </button>
                </div>

                <div className="rounded border border-amber-200 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-900/20">
                  <label className="mb-1 block text-sm font-semibold text-amber-800 dark:text-amber-200">Chi vedrà questo template</label>
                  {scopePreviewLoading ? (
                    <div className="text-sm text-amber-700 dark:text-amber-300">Calcolo visibilità in corso...</div>
                  ) : scopePreview ? (
                    <>
                      <div className="text-sm text-amber-800 dark:text-amber-200">{scopePreview.summary}</div>
                      {scopePreview.inventories.length > 0 && (
                        <div className="mt-2 max-h-28 overflow-auto rounded bg-white/70 p-2 text-xs text-amber-900 dark:bg-gray-800 dark:text-amber-100">
                          {scopePreview.inventories.map((inv) => (
                            <div key={inv.id}>• [{inv.type}] {inv.name}</div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-sm text-amber-700 dark:text-amber-300">Seleziona almeno un campo per vedere la visibilità.</div>
                  )}
                </div>

                <div className="rounded border border-gray-200 p-3 dark:border-gray-700">
                  <label className="mb-2 block text-sm font-medium">
                    {editingTemplateId ? 'Modifica template' : 'Salva come template'}
                  </label>
                  <div className="space-y-2">
                    <input
                      className="w-full rounded border px-3 py-2 dark:bg-gray-800"
                      placeholder="Nome template"
                      value={templateName}
                      onChange={(event) => setTemplateName(event.target.value)}
                    />
                    <textarea
                      className="w-full rounded border px-3 py-2 dark:bg-gray-800"
                      placeholder="Descrizione (opzionale)"
                      value={templateDescription}
                      onChange={(event) => setTemplateDescription(event.target.value)}
                      rows={2}
                    />
                    <div className="flex justify-end gap-2">
                      {editingTemplateId && (
                        <button
                          className="rounded bg-gray-300 px-4 py-2 hover:bg-gray-400 dark:bg-gray-700 dark:hover:bg-gray-600"
                          onClick={resetCreate}
                          type="button"
                        >
                          Annulla modifica
                        </button>
                      )}
                      <button
                        className="rounded bg-emerald-600 px-4 py-2 text-white hover:bg-emerald-700 disabled:bg-emerald-300"
                        disabled={busy}
                        onClick={saveTemplate}
                        type="button"
                      >
                        {editingTemplateId ? 'Salva modifiche' : 'Salva'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={closeAndReset}
                    className="rounded bg-gray-300 px-4 py-2 hover:bg-gray-400 dark:bg-gray-700 dark:hover:bg-gray-600"
                  >
                    Chiudi
                  </button>
                </div>
              </div>

              <aside className="rounded border border-gray-200 p-4 dark:border-gray-700 xl:overflow-y-auto">
                <h3 className="mb-3 font-semibold">Template salvati</h3>
                <div className="space-y-2 xl:max-h-[520px] xl:overflow-auto pr-1">
                  {templates.length === 0 ? (
                    <div className="text-sm text-gray-500 dark:text-gray-300">Nessun template disponibile.</div>
                  ) : (
                    templates.map((template) => (
                      <div key={template.id} className="rounded border p-3 dark:border-gray-700">
                        <div className="flex items-center justify-between gap-2">
                          <div className="font-medium">{template.name}</div>
                          {isTemplateCompatible(template) ? (
                            <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">
                              Compatibile
                            </span>
                          ) : (
                            <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900 dark:text-red-200">
                              Non compatibile
                            </span>
                          )}
                        </div>
                        {template.description && (
                          <div className="text-xs text-gray-500 dark:text-gray-300">{template.description}</div>
                        )}
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-300">Tipo: {template.filter_type}</div>
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-300">Criteri: {template.criteria_count ?? 0}</div>
                        {template.scope_preview?.summary && (
                          <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                            Visibilità: {template.scope_preview.summary}
                          </div>
                        )}
                        <div className="mt-3 flex gap-2">
                          <button
                            className="rounded bg-amber-600 px-3 py-1 text-sm text-white hover:bg-amber-700"
                            onClick={() => void editTemplate(template.id)}
                            type="button"
                          >
                            Modifica
                          </button>
                          <button
                            className="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
                            onClick={() => void removeTemplate(template.id)}
                            type="button"
                          >
                            Elimina
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </aside>
            </div>

            {message && (
              <div className={`rounded px-3 py-2 text-white ${messageType === 'success' ? 'bg-green-600' : 'bg-red-600'}`}>
                {message}
              </div>
            )}
          </Dialog.Panel>
        </div>
      </Dialog>
    </>
  );
}
