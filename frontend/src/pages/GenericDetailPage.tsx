import { useParams, useLocation, Link } from "react-router-dom";
import { useRef, useEffect, useState, useCallback } from 'react';
import {
  getInventoryById, getInventoryItems,
  getChecklistById, getChecklistItems,
  createItem, updateItem, deleteItem,
  getMetadataDefinitions, listAllMetadataDefinitions, getItemMetadataValues,
  getFilterTemplates, getFilterTemplate,
  filterItemsByTextMetadata, filterItemsByNumericMetadata, filterItemsByDateMetadata, filterItemsByBooleanMetadata,
  bulkUpsertItemMetadataValues, deleteItemMetadataValue, createAssignment, deleteAssignment } from "../api";
import { Inventory, InventoryItem, Item, User, MetadataDefinition, ItemMetadataValue, ItemMetadataValueUpsert, FilterTemplate, FilterTemplateListItem } from "../types";
import { Dialog } from "@headlessui/react";
import { FiArrowLeft, FiClock } from 'react-icons/fi';
import { createPortal } from 'react-dom';
import { useContext } from "react";
import { AuthContext } from "../auth-context";
import { useSwipeable } from 'react-swipeable';
import { HistoryModal } from "../components/HistoryModal";
import MetadataFilterManager from "../components/MetadataFilterManager";
import { ITEMS_CHANGED_EVENT } from "../components/GlobalBarcodeScan";
import ItemBarcodesEditor from "../components/ItemBarcodesEditor";
import { useBottomSheetDrag } from "../components/useBottomSheetDrag";
import { AddFromInventoryDialog, AssignExistingListItemDialog, AssignToListDialog, EditAssignmentDialog, ListLinkField, SourceAssignmentsDialog } from "../components/AssignmentDialogs";
import { isAxiosError } from "axios";

interface Props {
  item: Item;
  isMobile: boolean;
  isChecklist: boolean;
  isInventory: boolean;
  user: User | null;
  isEditMode: boolean;
  selectedItems: number[];
  setSelectedItems: React.Dispatch<React.SetStateAction<number[]>>;
  setItemBeingEdited: (item: Item) => void;
  updateItem: (id: number, item: Partial<Item>, onInsufficient?: 'zero') => Promise<Item | null>;
  deleteItem: (id: number) => Promise<void>;
  setIsCloning: React.Dispatch<React.SetStateAction<boolean>>;
  setItems: React.Dispatch<React.SetStateAction<Item[]>>;
}

type MetadataDraftMap = Record<number, ItemMetadataValueUpsert>;

async function createItemWithFeedback(data: Parameters<typeof createItem>[0]) {
  try {
    return await createItem(data);
  } catch (error) {
    const detail = isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail : undefined;
    window.alert(typeof detail === "string" ? `Creazione non riuscita: ${detail}` : "Creazione non riuscita. Riprova.");
    return null;
  }
}

const ITEM_PRIORITY_OPTIONS = [
  { value: 2, label: "🔥🔥 Molto alta" },
  { value: 1, label: "🔥 Alta" },
  { value: 0, label: "● Media" },
  { value: -1, label: "▼ Bassa" },
  { value: -2, label: "▼▼ Molto bassa" },
];

const ITEM_PRIORITY_LABELS: Record<number, string> = {
  [-2]: "Molto bassa",
  [-1]: "Bassa",
  0: "Media",
  1: "Alta",
  2: "Molto alta",
};

function getPriorityIndicator(priority: number) {
  return {
    label: ITEM_PRIORITY_LABELS[priority] ?? ITEM_PRIORITY_LABELS[0],
    symbol: priority > 0 ? "▲".repeat(priority) : priority < 0 ? "▼".repeat(-priority) : "●",
    className: priority === 2
      ? "text-red-600 dark:text-red-400"
      : priority === 1
        ? "text-orange-500 dark:text-orange-400"
        : priority === -2
          ? "text-blue-700 dark:text-blue-300"
          : priority === -1
            ? "text-sky-500 dark:text-sky-400"
            : "text-gray-500 dark:text-gray-400",
  };
}

function createEmptyMetadataDraft(fieldType: MetadataDefinition['field_type']): ItemMetadataValueUpsert {
  if (fieldType === 'TEXT' || fieldType === 'LIST') {
    return { definition_id: 0, value_text: null };
  }
  if (fieldType === 'NUMBER') {
    return { definition_id: 0, value_number: null };
  }
  if (fieldType === 'BOOLEAN') {
    return { definition_id: 0, value_boolean: null };
  }
  return { definition_id: 0, value_date: null };
}

function getTypedValueForDefinition(
  definition: MetadataDefinition,
  value?: ItemMetadataValue | ItemMetadataValueUpsert,
): string {
  if (!value) {
    return '';
  }
  if (definition.field_type === 'TEXT' || definition.field_type === 'LIST') {
    return value.value_text ?? '';
  }
  if (definition.field_type === 'NUMBER') {
    return value.value_number != null ? String(value.value_number) : '';
  }
  if (definition.field_type === 'BOOLEAN') {
    if (value.value_boolean === true) return 'true';
    if (value.value_boolean === false) return 'false';
    return '';
  }
  return value.value_date ?? '';
}

function normalizeMetadataDraft(
  definition: MetadataDefinition,
  draft?: ItemMetadataValueUpsert,
): ItemMetadataValueUpsert | null {
  if (!draft) {
    return null;
  }

  if (definition.field_type === 'TEXT' || definition.field_type === 'LIST') {
    const nextValue = draft.value_text?.trim() ?? '';
    return nextValue ? { definition_id: definition.id, value_text: nextValue } : null;
  }

  if (definition.field_type === 'NUMBER') {
    if (draft.value_number === null || draft.value_number === undefined || draft.value_number === '') {
      return null;
    }
    return { definition_id: definition.id, value_number: draft.value_number };
  }

  if (definition.field_type === 'BOOLEAN') {
    if (draft.value_boolean === null || draft.value_boolean === undefined) {
      return null;
    }
    return { definition_id: definition.id, value_boolean: draft.value_boolean };
  }

  return draft.value_date ? { definition_id: definition.id, value_date: draft.value_date } : null;
}

function buildMetadataDraftMap(values: ItemMetadataValue[]): MetadataDraftMap {
  return values.reduce<MetadataDraftMap>((accumulator, value) => {
    accumulator[value.definition_id] = {
      definition_id: value.definition_id,
      value_text: value.value_text ?? null,
      value_number: value.value_number ?? null,
      value_boolean: value.value_boolean ?? null,
      value_date: value.value_date ?? null,
    };
    return accumulator;
  }, {});
}

function formatItemMetadataValue(value: ItemMetadataValue): string {
  if (value.display_value) {
    return value.display_value;
  }
  if (value.field_type === 'BOOLEAN') {
    return value.value_boolean ? 'Sì' : 'No';
  }
  if (value.field_type === 'NUMBER') {
    return value.value_number != null ? String(value.value_number) : '';
  }
  if (value.field_type === 'DATE') {
    return value.value_date ? value.value_date : '';
  }
  return value.value_text ?? '';
}

function MetadataFieldsSection({
  definitions,
  drafts,
  onChange,
}: {
  definitions: MetadataDefinition[];
  drafts: MetadataDraftMap;
  onChange: (definition: MetadataDefinition, value: string) => void;
}) {
  if (definitions.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 rounded border border-gray-200 p-3 dark:border-gray-700">
      <div className="space-y-3">
        {definitions.map((definition) => {
          const currentValue = getTypedValueForDefinition(definition, drafts[definition.id]);

          return (
            <div key={definition.id}>
              <label className="mb-1 block text-sm font-medium">
                {definition.label}
                {definition.is_required ? ' *' : ''}
              </label>
              {definition.description && (
                <div className="mb-1 text-xs text-gray-500 dark:text-gray-400">
                  {definition.description}
                </div>
              )}
              {definition.field_type === 'TEXT' && (
                <input
                  type="text"
                  className="w-full border rounded p-1 dark:bg-gray-800"
                  value={currentValue}
                  onChange={(event) => onChange(definition, event.target.value)}
                />
              )}
              {definition.field_type === 'LIST' && (
                <select
                  className="w-full border rounded p-1 dark:bg-gray-800"
                  value={currentValue}
                  onChange={(event) => onChange(definition, event.target.value)}
                >
                  <option value="">[Vuoto]</option>
                  {(definition.list_options ?? []).map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              )}
              {definition.field_type === 'NUMBER' && (
                <input
                  type="number"
                  step="0.0001"
                  className="w-full border rounded p-1 dark:bg-gray-800"
                  value={currentValue}
                  onChange={(event) => onChange(definition, event.target.value)}
                />
              )}
              {definition.field_type === 'DATE' && (
                <div className="space-y-2">
                  <div className="space-y-2">
                    <input
                      type="date"
                      className="w-full border rounded p-1 dark:bg-gray-800"
                      value={currentValue}
                      onChange={(event) => onChange(definition, event.target.value)}
                    />
                    {currentValue && (
                      <button
                        type="button"
                        className="min-h-11 w-full rounded border px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-700"
                        onClick={() => onChange(definition, '')}
                      >
                        Svuota
                      </button>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {currentValue ? `Valore impostato: ${currentValue}` : 'Non impostata'}
                  </div>
                </div>
              )}
              {definition.field_type === 'BOOLEAN' && (
                <select
                  className="w-full border rounded p-1 dark:bg-gray-800"
                  value={currentValue}
                  onChange={(event) => onChange(definition, event.target.value)}
                >
                  <option value="">Non impostato</option>
                  <option value="true">Sì</option>
                  <option value="false">No</option>
                </select>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SwipeableItemRow({
  item, isMobile, isChecklist, isInventory, user,
  isEditMode, selectedItems, setSelectedItems, setItemBeingEdited,
  updateItem, deleteItem, setItems, setIsCloning, 
}: Props) {
  const [action, setAction] = useState<'left' | 'right' | null>(null);
  const [isItemHistoryOpen, setIsItemHistoryOpen] = useState(false);
  const [isPriorityMenuOpen, setIsPriorityMenuOpen] = useState(false);
  const [assignDialog, setAssignDialog] = useState<'assign' | 'link' | 'sources' | 'edit' | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const priorityMenuRef = useRef<HTMLSpanElement>(null);

  // Gestione click fuori per chiudere i pulsanti swipe
  useEffect(() => {
    if (!action) return;

    function handleClickOutside(e: MouseEvent) {
      // Se il target ha la classe "swipe-button", ignora
      if ((e.target as HTMLElement).classList.contains("swipe-button")) {
        return;
      }
      setAction(null);
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [action]);

  const swipeHandlers = useSwipeable({
    onSwipedLeft: () => setAction('left'),
    onSwipedRight: () => setAction('right'),
    //onTap: () => setAction(null),
    trackMouse: false,
    delta: 40,
  });

  const isViewer = user?.role?.name === 'viewer';
  const priority = item.priority ?? 0;
  const priorityIndicator = getPriorityIndicator(priority);

  // Chiudi il menu priorità al click fuori
  useEffect(() => {
    if (!isPriorityMenuOpen) return;

    function handleClickOutside(e: MouseEvent) {
      if (priorityMenuRef.current && !priorityMenuRef.current.contains(e.target as Node)) {
        setIsPriorityMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isPriorityMenuOpen]);

  const changePriority = async (value: number) => {
    setIsPriorityMenuOpen(false);
    if (value === priority) return;
    try {
      const updated = await updateItem(item.id, { ...item, priority: value });
      if (updated) setItems(prev => prev.map(i => i.id === updated.id ? updated : i));
    } catch {
      alert('Aggiornamento priorità non riuscito');
    }
  };

  const cloneItem = () => {
    const cloned = {
      ...item,
      name: `${item.name} (copia)`
    };
    setItemBeingEdited(cloned);
    setIsCloning(true);
  };

  // Combine refs for swipeHandlers and rowRef to avoid duplicate ref assignment
  const combinedRef = (el: HTMLDivElement | null) => {
    rowRef.current = el;
    if (isMobile && swipeHandlers.ref) {
      swipeHandlers.ref(el);
    }
  };

  const handleClone = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    //console.log("Clona premuto", item);
    cloneItem();
    setAction(null);
  };

  const handleEdit = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    //console.log("Modifica premuto", item);
    setItemBeingEdited(item);
    setIsCloning(false);
    setAction(null);
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    //console.log("Elimina premuto", item);
    if (confirm("Vuoi eliminare questo elemento?")) {
      deleteItem(item.id).then(() => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
      });
    }
    setAction(null);
  };

  const applyUpdate = (upd: Item | null) => {
    if (upd) setItems(prev => prev.map(i => i.id === upd.id ? upd : i));
  };

  const toggleChecked = async (checked: boolean) => {
    const updated = { ...item, quantity: checked ? 1 : 0 };
    try {
      applyUpdate(await updateItem(item.id, updated));
    } catch (err) {
      const detail = (err as { response?: { status?: number; data?: { detail?: { code?: string; available?: number; requested?: number; source_name?: string } } } })?.response;
      if (detail?.status === 409 && detail.data?.detail?.code === 'insufficient_stock') {
        const d = detail.data.detail;
        if (window.confirm(`Stock insufficiente per "${d.source_name}": disponibili ${d.available}, richiesti ${d.requested}.\n\nOK = azzera lo stock e spunta\nAnnulla = non spuntare`)) {
          try {
            applyUpdate(await updateItem(item.id, updated, 'zero'));
          } catch {
            alert('Operazione non riuscita');
          }
        }
        return;
      }
      alert('Operazione non riuscita');
    }
  };

  const actionGridColumns = isEditMode && !isViewer
    ? (isInventory ? 'grid-cols-6' : 'grid-cols-4')
    : isInventory && !isViewer
      ? 'grid-cols-5'
      : 'grid-cols-2';

  return (
    <div
      ref={combinedRef}
      className="relative mb-2"
    >
      {/* Action buttons */}
      {(action === 'left') && !isViewer && (
        <>
          <button
            type="button"
            aria-label="Clona item"
            title="Clona item"
            className="swipe-button absolute transition-transform duration-300 ease-in-out transform translate-x-0 right-1/4 top-0 h-full w-1/4 bg-yellow-500 text-white font-bold z-20"
            onClick={handleClone}
          >
            📄
          </button>
          <button
            type="button"
            aria-label="Modifica item"
            title="Modifica item"
            className="swipe-button absolute transition-transform duration-300 ease-in-out transform translate-x-0 right-0 top-0 h-full w-1/4 bg-blue-600 text-white font-bold z-20"
            onClick={handleEdit}
          >
            ✏️
          </button>
        </>
      )}
      {(action === 'right') && !isViewer && (
        <button
          type="button"
          aria-label="Elimina item"
          title="Elimina item"
          className="swipe-button absolute transition-transform duration-300 ease-in-out transform translate-x-0 left-0 top-0 h-full w-1/4 bg-red-600 text-white font-bold z-20"
          onClick={handleDelete}
        >
          🗑️
        </button>
      )}

      {/* Actual list item */}
      <li
        className={`relative border p-2 rounded shadow-sm flex flex-col md:flex-row md:justify-between md:items-center
    ${isEditMode && selectedItems.includes(item.id) ? "bg-blue-100 dark:bg-blue-900" : "bg-white dark:bg-gray-800"}
    md:hover:bg-gray-100 dark:md:hover:bg-gray-700
    ${(isChecklist && item.quantity > 0) || (isInventory && item.quantity === 0) ? "text-gray-400" : ""}`}
        onClick={() => {
          if (isEditMode) {
            setSelectedItems(prev =>
              prev.includes(item.id) ? prev.filter(id => id !== item.id) : [...prev, item.id]
            );
          } else {
            setAction(null);
          }
        }}
      >
        <div className="flex w-full flex-row items-start gap-2 md:w-auto md:items-center">
          {isEditMode && (
            <div className="flex shrink-0 items-center md:mr-1">
              <span className="text-base">
                {selectedItems.includes(item.id) ? '☑️' : '⬜️'}
              </span>
            </div>
          )}
          <div className="flex flex-col">
            <div className="font-semibold flex items-center gap-2">
              <span>{item.name}</span>
              {isChecklist && (
                <span ref={priorityMenuRef} className="relative inline-flex">
                  <button
                    type="button"
                    disabled={isViewer}
                    aria-label={`Priorità ${priorityIndicator.label.toLowerCase()}${isViewer ? '' : ' - tocca per modificare'}`}
                    title={`Priorità ${priorityIndicator.label}${isViewer ? '' : ' - tocca per modificare'}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!isViewer) setIsPriorityMenuOpen((open) => !open);
                    }}
                    className={`flex min-h-10 min-w-10 items-center justify-center rounded-lg border border-gray-300 bg-gray-100 px-2 text-sm leading-none dark:border-gray-600 dark:bg-gray-700 md:min-h-7 md:min-w-7 ${
                      isViewer ? '' : 'hover:bg-gray-200 dark:hover:bg-gray-600 cursor-pointer'
                    } ${priorityIndicator.className}`}
                  >
                    {priorityIndicator.symbol}
                  </button>
                  {isPriorityMenuOpen && (
                    <div
                      className="absolute left-0 top-full z-30 mt-1 w-48 overflow-hidden rounded-lg border border-gray-300 bg-white shadow-lg dark:border-gray-600 dark:bg-gray-800"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {ITEM_PRIORITY_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void changePriority(option.value);
                          }}
                          className={`block min-h-11 w-full px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${
                            option.value === priority ? 'bg-blue-50 font-semibold dark:bg-blue-900' : ''
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  )}
                </span>
              )}
              {(item.barcodes?.length ?? 0) > 0 && (
                <span
                  className="text-xs bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200 px-2 py-1 rounded whitespace-nowrap"
                  title={item.barcodes?.map((b) => b.code).join('\n')}
                >
                  🏷️ {item.barcodes?.length}
                </span>
              )}
            </div>
            {item.description && (
              <div className="text-sm text-gray-500 dark:text-gray-200">{item.description}</div>
            )}
            {isChecklist && item.assignment && (
              <button
                type="button"
                disabled={isViewer}
                onClick={(e) => { e.stopPropagation(); setAssignDialog('edit'); }}
                className={`mt-1 min-h-11 max-w-full self-start rounded-xl px-3 py-2 text-sm ${
                  item.quantity === 0 && ((item.assignment.source_stock ?? 0) < item.assignment.qty || (item.assignment.source_net_qty ?? 0) < 0)
                    ? 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200'
                    : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200'
                }`}
              >
                📦 ×{item.assignment.qty} · {item.assignment.source_inventory_name} · stock {item.assignment.source_stock ?? '?'}
                {item.quantity === 0 && (item.assignment.source_net_qty ?? 0) < 0 ? ` · netto ${item.assignment.source_net_qty}` : ''}
                {item.quantity === 0 && ((item.assignment.source_stock ?? 0) < item.assignment.qty || (item.assignment.source_net_qty ?? 0) < 0) ? ' ⚠️' : ''}
              </button>
            )}
            {isChecklist && !item.assignment && !isViewer && !isEditMode && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setAssignDialog('link'); }}
                className="mt-1 min-h-11 self-start rounded-xl bg-blue-100 px-3 py-2 text-sm text-blue-800 dark:bg-blue-900 dark:text-blue-200"
              >
                📥 Assegna
              </button>
            )}
            {isInventory && ((item.assignment_count ?? 0) > 0 || (item.assigned_qty ?? 0) > 0) && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setAssignDialog('sources'); }}
                className={`mt-1 min-h-11 max-w-full self-start rounded-xl px-3 py-2 text-sm ${
                  (item.net_qty ?? 0) < 0
                    ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                    : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200'
                }`}
                title="Quantità assegnate a liste"
              >
                📋 {item.assigned_qty ?? 0} assegnati → {item.net_qty ?? item.quantity} netti
                {(item.assignment_count ?? 0) > (item.assigned_qty ?? 0) && ` · ${item.assignment_count} collegamenti`}
              </button>
            )}
            {item.metadata_values && item.metadata_values.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {item.metadata_values
                  .filter((value) => value.definition_label && formatItemMetadataValue(value))
                  .map((value) => (
                    <span
                      key={value.id}
                      className="rounded-full bg-slate-100 px-2 py-0.5 text-sm text-slate-700 dark:bg-slate-700 dark:text-slate-100"
                    >
                      {value.definition_label}: {formatItemMetadataValue(value)}
                    </span>
                  ))}
              </div>
            )}
            <div className="mt-1 text-xs text-gray-400">
              Ultima modifica: {item.username_mod} - {new Date(item.data_mod).toLocaleString()}{" "}
              <span className="whitespace-nowrap">· v{item.version_num}</span>
            </div>
          </div>
        </div>
        <div className={`mt-2 grid w-full ${actionGridColumns} gap-1.5 md:mt-0 md:flex md:w-auto md:items-center md:justify-end`}>
          <button
            type="button"
            className="col-span-1 min-h-11 w-full rounded-lg bg-gray-200 px-1 text-base text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600 md:min-h-0 md:w-auto md:rounded md:px-3 md:py-1 md:text-sm md:whitespace-nowrap"
            onClick={(e) => {
              e.stopPropagation();
              setIsItemHistoryOpen(true);
            }}
            title="Visualizza cronologia item"
            aria-label="Visualizza cronologia item"
          >
            <span className="inline md:hidden">🕓</span>
            <span className="hidden md:inline">Cronologia</span>
          </button>
          {isInventory && !isViewer && !isEditMode && (
            <button
              type="button"
            className="col-span-1 min-h-11 w-full rounded-lg bg-gray-200 px-1 text-base text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600 md:min-h-0 md:w-auto md:rounded md:px-3 md:py-1 md:text-sm md:whitespace-nowrap"
              onClick={(e) => { e.stopPropagation(); setAssignDialog('assign'); }}
              title="Assegna a una lista"
              aria-label="Assegna a una lista"
            >
              <span className="inline md:hidden">📋</span>
              <span className="hidden md:inline">📋 Assegna</span>
            </button>
          )}
          {isEditMode && !isViewer && (
            <>
              <button
                type="button"
                className="col-span-1 min-h-11 w-full rounded-lg bg-yellow-500 px-1 text-lg text-white md:min-h-0 md:w-auto md:rounded md:px-2 md:py-1 md:text-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  cloneItem();
                }}
                aria-label="Clona item"
              >
                <span className="inline md:hidden">📄</span>
                <span className="hidden md:inline">📄 Clona</span>
              </button>
              <button
                type="button"
                className="col-span-1 min-h-11 w-full rounded-lg bg-blue-500 px-1 text-lg text-white md:min-h-0 md:w-auto md:rounded md:px-2 md:py-1 md:text-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  setItemBeingEdited(item);
                }}
                aria-label="Modifica item"
              >
                <span className="inline md:hidden">✏️</span>
                <span className="hidden md:inline">✏️ Modifica</span>
              </button>
            </>
          )}
          {isChecklist ? (
            <div className="col-span-1 flex min-h-11 w-full items-center justify-center md:h-full">
              <input
                type="checkbox"
                checked={item.quantity > 0}
                disabled={isViewer}
                onChange={(e) => {
                  if (isViewer) return;
                  toggleChecked(e.target.checked);
                }}
                className="h-10 w-10 accent-blue-600 focus:ring-2 rounded shadow-sm border-2 border-gray-400 dark:border-gray-600"
                style={{ minWidth: '2.5rem', minHeight: '2.5rem' }}
                aria-label="Completato"
              />
            </div>
          ) : isInventory && !isViewer ? (
            <div className="col-span-3 grid w-full grid-cols-3 gap-1.5 md:col-span-1 md:flex md:w-auto md:items-center">
              <button
                type="button"
                aria-label="Diminuisci quantità"
                disabled={item.quantity <= 0}
                className="min-h-11 w-full rounded-lg bg-gray-400 text-lg hover:bg-gray-600 disabled:opacity-40 md:min-h-0 md:w-auto md:rounded md:px-3 md:py-1 md:text-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  const updated = { ...item, quantity: Math.max(0, item.quantity - 1) };
                  updateItem(item.id, updated).then((upd) => {
                    if (upd) {
                      setItems(prev => prev.map(i => i.id === upd.id ? upd : i));
                      window.dispatchEvent(new Event(ITEMS_CHANGED_EVENT));
                    }
                  });
                }}
              >
                -
              </button>
              <span className="flex min-h-11 items-center justify-center rounded-lg border border-gray-200 text-base font-semibold dark:border-gray-700 md:min-h-0 md:min-w-[24px] md:rounded-none md:border-0 md:text-base md:font-normal">{item.quantity}</span>
              <button
                type="button"
                aria-label="Aumenta quantità"
                className="min-h-11 w-full rounded-lg bg-gray-400 text-lg hover:bg-gray-600 md:min-h-0 md:w-auto md:rounded md:px-3 md:py-1 md:text-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  const updated = { ...item, quantity: item.quantity + 1 };
                  updateItem(item.id, updated).then((upd) => {
                    if (upd) {
                      setItems(prev => prev.map(i => i.id === upd.id ? upd : i));
                      window.dispatchEvent(new Event(ITEMS_CHANGED_EVENT));
                    }
                  });
                }}
              >
                +
              </button>
            </div>
          ) : (
            <span className="min-w-[24px] text-center">{item.quantity}</span>
          )}
        </div>
      </li>

      {assignDialog === 'assign' && <AssignToListDialog item={item} onClose={() => setAssignDialog(null)} />}
      {assignDialog === 'sources' && <SourceAssignmentsDialog item={item} onClose={() => setAssignDialog(null)} />}
      {assignDialog === 'link' && (
        <AssignExistingListItemDialog item={item} onClose={() => setAssignDialog(null)} />
      )}
      {assignDialog === 'edit' && item.assignment && (
        <EditAssignmentDialog assignment={item.assignment} listItemId={item.id} onClose={() => setAssignDialog(null)} />
      )}

      <HistoryModal
        isOpen={isItemHistoryOpen}
        onClose={() => setIsItemHistoryOpen(false)}
        onRollback={async () => {
          const getItems = isInventory ? getInventoryItems : getChecklistItems;
          const refreshed = await getItems(item.inventory_id);
          if (refreshed) setItems(refreshed as Item[]);
        }}
        entityType="item"
        itemContainerType={isChecklist ? 'CHECKLIST' : 'INVENTORY'}
        entityId={item.id}
        entityName={item.name}
      />
    </div>
  );
}

export default function InventoryDetailPage() {
  const isMobile = window.innerWidth < 768;
  const authContext = useContext(AuthContext);
  const user = authContext?.user ?? null;
  const isAdmin = user?.role?.name === 'admin';
  const isViewer = user?.role?.name === 'viewer';
  const canEdit = Boolean(user?.role?.name && user.role.name !== 'viewer');
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const importExportSheetDrag = useBottomSheetDrag(() => setIsShareModalOpen(false));
  const [csvTextarea, setCsvTextarea] = useState('');
  const [importMode, setImportMode] = useState<'merge' | 'replace'>('merge');
  const { id } = useParams();
  const location = useLocation();
  const [filterText, setFilterText] = useState(() => new URLSearchParams(location.search).get('filtro') || "");
  const [isAddFromInventoryOpen, setIsAddFromInventoryOpen] = useState(false);
  const [barcodeFilter, setBarcodeFilter] = useState<'all' | 'with' | 'without'>('all');
  const basePath = location.pathname.split("/")[1] as "inventories" | "checklists";
  const isInventory = basePath === "inventories";
  const isChecklist = basePath === "checklists";
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [isInsertMode, setisInsertMode] = useState(false);
  const [newItemLink, setNewItemLink] = useState<{ item: InventoryItem; qty: number } | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [newItemName, setNewItemName] = useState("");
  const [newItemDescription, setNewItemDescription] = useState("");
  const [newItemQuantity, setNewItemQuantity] = useState(isChecklist ? 0 : 1);
  const [newItemPriority, setNewItemPriority] = useState(0);
  const [isEditMode, setIsEditMode] = useState(false);
  const [isMoreActionsOpen, setIsMoreActionsOpen] = useState(false);
  const [selectedItems, setSelectedItems] = useState<number[]>([]);
  const [sortBy, setSortBy] = useState<'name' | 'date' | 'quantity'>(() => {
    const stored = localStorage.getItem('item_sortBy');
    // Migrazione: se era "date" (vecchio default), "priority" o non impostato, passa a "name"
    if (stored === 'name' || stored === 'quantity') {
      return stored;
    }
    localStorage.setItem('item_sortBy', 'name');
    return 'name';
  });
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => {
    const stored = localStorage.getItem('item_sortOrder');
    if (stored === 'asc' || stored === 'desc') return stored;
    return 'asc';
  });
  // Ordinamento per priorità: separato e prioritario rispetto agli altri criteri (solo checklist)
  const [prioritySortOrder, setPrioritySortOrder] = useState<'asc' | 'desc'>(() => {
    const stored = localStorage.getItem('item_prioritySortOrder');
    if (stored === 'asc' || stored === 'desc') return stored;
    return 'desc';
  });
  const [itemBeingEdited, setItemBeingEdited] = useState<Item | null>(null);
  const detailTopRef = useRef<HTMLDivElement>(null);
  const filtroParam = filterText;
  const [isCloning, setIsCloning] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [metadataDefinitions, setMetadataDefinitions] = useState<MetadataDefinition[]>([]);
  const [allMetadataDefinitions, setAllMetadataDefinitions] = useState<MetadataDefinition[]>([]);
  const [newItemMetadataDrafts, setNewItemMetadataDrafts] = useState<MetadataDraftMap>({});
  const [editingMetadataDrafts, setEditingMetadataDrafts] = useState<MetadataDraftMap>({});
  const [editingMetadataValues, setEditingMetadataValues] = useState<ItemMetadataValue[]>([]);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [metadataFilteredItemIds, setMetadataFilteredItemIds] = useState<number[] | null>(null);
  const [metadataFilterSummary, setMetadataFilterSummary] = useState<string | null>(null);
  const [filterTemplates, setFilterTemplates] = useState<FilterTemplateListItem[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('');

  const editingMetadataRecap = metadataDefinitions
    .filter((definition) => definition.is_active)
    .flatMap((definition) => {
      const rawValue = getTypedValueForDefinition(definition, editingMetadataDrafts[definition.id]).trim();
      if (!rawValue) return [];
      const value = definition.field_type === 'BOOLEAN'
        ? (rawValue === 'true' ? 'Sì' : 'No')
        : definition.field_type === 'LIST'
          ? (definition.list_options?.find((option) => option.value === rawValue)?.label ?? rawValue)
          : rawValue;
      return [{ id: definition.id, label: definition.label, value }];
    });

useEffect(() => {
  const fetchData = async () => {
    if (!id) return;

    const getById  = isInventory ? getInventoryById  : getChecklistById;
    const getItems = isInventory ? getInventoryItems : getChecklistItems;

    const inventoryData = await getById(Number(id));
    if (inventoryData) setInventory(inventoryData as Inventory);

    const definitionsData = await getMetadataDefinitions(Number(id), true);
    setMetadataDefinitions(definitionsData);
    const allDefsData = await listAllMetadataDefinitions(true);
    setAllMetadataDefinitions(allDefsData);
    const templatesData = await getFilterTemplates(Number(id), true);
    setFilterTemplates(templatesData);

    const itemsData = await getItems(Number(id));
    if (Array.isArray(itemsData)) setItems(itemsData as Item[]);
  };
  fetchData();
}, [id, isInventory]);

  useEffect(() => {
    const refresh = async () => {
      if (!id) return;
      const getItems = isInventory ? getInventoryItems : getChecklistItems;
      const refreshed = await getItems(Number(id));
      if (Array.isArray(refreshed)) setItems(refreshed as Item[]);
    };
    window.addEventListener(ITEMS_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(ITEMS_CHANGED_EVENT, refresh);
  }, [id, isInventory]);

  const openedItemParam = useRef<string | null>(null);
  useEffect(() => {
    const itemParam = new URLSearchParams(location.search).get('item');
    if (!itemParam) {
      openedItemParam.current = null;
      return;
    }
    const key = `${id}:${itemParam}:${location.key}`;
    if (openedItemParam.current === key) return;
    const target = items.find((i) => i.id === Number(itemParam));
    if (!target) return;
    openedItemParam.current = key;
    queueMicrotask(() => {
      if (isViewer) setFilterText(target.name);
      else setItemBeingEdited(target);
    });
  }, [items, location.search, location.key, id, isViewer]);

  useEffect(() => {
    if (!itemBeingEdited) {
      setEditingMetadataValues([]);
      setEditingMetadataDrafts({});
      return;
    }

    const loadItemMetadata = async () => {
      setMetadataLoading(true);
      try {
        const values = await getItemMetadataValues(itemBeingEdited.id);
        setEditingMetadataValues(values);
        setEditingMetadataDrafts(buildMetadataDraftMap(values));
      } catch {
        setEditingMetadataValues([]);
        setEditingMetadataDrafts({});
      } finally {
        setMetadataLoading(false);
      }
    };

    void loadItemMetadata();
  }, [itemBeingEdited]);

  useEffect(() => {
    setNewItemMetadataDrafts({});
  }, [inventory?.id]);

  useEffect(() => {
    if (selectedTemplateId === '') return;
    const exists = filterTemplates.some((template) => template.id === selectedTemplateId);
    if (!exists) {
      setSelectedTemplateId('');
    }
  }, [filterTemplates, selectedTemplateId]);

  useEffect(() => {
    localStorage.setItem("item_sortBy", sortBy);
    localStorage.setItem("item_sortOrder", sortOrder);
    localStorage.setItem("item_prioritySortOrder", prioritySortOrder);
  }, [sortBy, sortOrder, prioritySortOrder]);

  const sortedItems = [...items]
    .filter((item) => {
      const matchesMetadata = metadataFilteredItemIds === null || metadataFilteredItemIds.includes(item.id);
      const normalizedFilter = filterText.toLowerCase();
      const metadataValues = item.metadata_values ?? [];
      const matchesTextMetadata = metadataValues.some((value) => {
        if (value.field_type !== 'TEXT' && value.field_type !== 'LIST') {
          return false;
        }

        return [
          value.display_value,
          value.value_text,
          formatItemMetadataValue(value),
        ].some((candidate) => candidate?.toLowerCase().includes(normalizedFilter));
      });
      const matchesText =
        item.name.toLowerCase().includes(normalizedFilter) ||
        item.description?.toLowerCase().includes(normalizedFilter) ||
        (item.barcodes ?? []).some((barcode) => barcode.code.toLowerCase().includes(normalizedFilter)) ||
        matchesTextMetadata;

      const hasBarcodes = (item.barcodes?.length ?? 0) > 0;
      const matchesBarcodeFilter =
        barcodeFilter === 'all' || (barcodeFilter === 'with' ? hasBarcodes : !hasBarcodes);

      return matchesMetadata && matchesText && matchesBarcodeFilter;
    })
    .sort((a, b) => {
      // 1) Completato/non completato (checklist) o quantità zero in fondo (inventario)
      if (isChecklist) {
        const aDone = a.quantity > 0;
        const bDone = b.quantity > 0;
        if (aDone !== bDone) return aDone ? 1 : -1;
        // 2) Priorità: criterio prioritario e separato (default: alta prima)
        const priorityDiff = (b.priority ?? 0) - (a.priority ?? 0);
        if (priorityDiff !== 0) return prioritySortOrder === "desc" ? priorityDiff : -priorityDiff;
      } else {
        if (a.quantity === 0 && b.quantity > 0) return 1;
        if (a.quantity > 0 && b.quantity === 0) return -1;
      }
      // 3) Criterio di ordinamento selezionato
      let result = 0;
      const activeSortBy = isChecklist && sortBy === "quantity" ? "name" : sortBy;
      if (activeSortBy === "name") result = a.name.localeCompare(b.name);
      else if (activeSortBy === "quantity") result = a.quantity - b.quantity;
      else result = new Date(a.data_mod).getTime() - new Date(b.data_mod).getTime();
      return sortOrder === "asc" ? result : -result;
    });

    const handleCSVImport = async (csvText: string) => {
        if (!inventory) return;
      
        const rows = csvText.trim().split('\n');
        const [header, ...lines] = rows;
        //const columns = header.split(',').map(c => c.trim().replace(/"/g, ''));
        const separator = header.includes(';') ? ';' : ',';
        const columns = header.split(separator).map(c => c.trim().replace(/"/g, ''));
        const nameIndex = columns.indexOf('name');
        const descIndex = columns.indexOf('description');
        const qtyIndex = columns.indexOf('quantity');
      
        if (nameIndex === -1) {
          alert('Il CSV deve contenere almeno la colonna "name".');
          return;
        }
      
        const parsedItems = lines.map(line => {
          //const parts = line.split(',').map(p => p.replace(/^"|"$/g, '').replace(/""/g, '"'));
          const parts = line.split(separator).map(p => p.replace(/^"|"$/g, '').replace(/""/g, '"'));
          return {
            name: parts[nameIndex],
            description: parts[descIndex] || '',
            quantity: qtyIndex >= 0 ? Number(parts[qtyIndex]) || 0 : (isChecklist ? 0 : 1),
            inventory_id: inventory.id
          };
        });
      
        // const merge = window.confirm("Vuoi unire (merge) con gli elementi esistenti per nome?\nPremi Annulla per eliminare tutto e reinserire da zero.");
        const merge = importMode === 'merge';
        if (!merge) {
          await Promise.all(items.map(item => deleteItem(item.id)));
          const inserted = await Promise.all(parsedItems.map(createItem));
          setItems(inserted.filter(Boolean));
        } else {
          const updated = [...items];
          for (const newItem of parsedItems) {
          const existing = updated.find(i => i.name.toLowerCase() === newItem.name.toLowerCase());
            if (existing) {
              const merged = { ...existing, ...newItem };
              const result = await updateItem(existing.id, merged);
              if (result) {
                const idx = updated.findIndex(i => i.id === existing.id);
                updated[idx] = result;
              }
            } else {
              const created = await createItem(newItem);
              if (created) updated.push(created);
            }
          }
          setItems(updated);
        }
      };

    const applyTemplateToList = useCallback(async (templateId: number) => {
      try {
        const template: FilterTemplate = await getFilterTemplate(templateId);
        const root = template.criteria as Record<string, unknown>;
        const filterType = (root?.filter_type as string) || template.filter_type;
        const matchMode = (root?.match_mode as 'all' | 'any') || 'all';
        const criteria = Array.isArray(root?.criteria) ? root.criteria : [];

        if (!criteria.length) {
          alert('Il template non contiene criteri validi.');
          return;
        }

        const asSet = (ids: number[]) => new Set(ids);
        const intersect = (a: Set<number>, b: Set<number>) => new Set([...a].filter((x) => b.has(x)));
        const union = (a: Set<number>, b: Set<number>) => new Set([...a, ...b]);

        const byType = {
          text: criteria.filter((c) => {
            const raw = c as Record<string, unknown>;
            return raw.field_type === 'TEXT' || raw.field_type === 'LIST' || raw.value_text != null || filterType === 'text';
          }),
          numeric: criteria.filter((c) => {
            const raw = c as Record<string, unknown>;
            return raw.field_type === 'NUMBER' || raw.value_number != null || filterType === 'numeric';
          }),
          date: criteria.filter((c) => {
            const raw = c as Record<string, unknown>;
            return raw.field_type === 'DATE' || raw.value_date != null || filterType === 'date';
          }),
          boolean: criteria.filter((c) => {
            const raw = c as Record<string, unknown>;
            return raw.field_type === 'BOOLEAN' || raw.value_boolean != null || filterType === 'boolean';
          }),
        };

        const resultSets: Set<number>[] = [];

        if (byType.text.length > 0) {
          const response = await filterItemsByTextMetadata({
            inventory_id: Number(id),
            match_mode: matchMode,
            criteria: byType.text as never,
          });
          resultSets.push(asSet(response.item_ids));
        }

        if (byType.numeric.length > 0) {
          const response = await filterItemsByNumericMetadata({
            inventory_id: Number(id),
            match_mode: matchMode,
            criteria: byType.numeric as never,
          });
          resultSets.push(asSet(response.item_ids));
        }

        if (byType.date.length > 0) {
          const response = await filterItemsByDateMetadata({
            inventory_id: Number(id),
            match_mode: matchMode,
            criteria: byType.date as never,
          });
          resultSets.push(asSet(response.item_ids));
        }

        if (byType.boolean.length > 0) {
          const response = await filterItemsByBooleanMetadata({
            inventory_id: Number(id),
            match_mode: matchMode,
            criteria: byType.boolean as never,
          });
          resultSets.push(asSet(response.item_ids));
        }

        if (resultSets.length === 0) {
          alert('Tipo template non supportato.');
          return;
        }

        let finalSet = resultSets[0];
        for (let i = 1; i < resultSets.length; i += 1) {
          finalSet = matchMode === 'all' ? intersect(finalSet, resultSets[i]) : union(finalSet, resultSets[i]);
        }

        const itemIds = Array.from(finalSet.values()).sort((a, b) => a - b);
        setMetadataFilteredItemIds(itemIds);
        setMetadataFilterSummary(`Template "${template.name}" applicato (${itemIds.length} risultati)`);
        return;

      } catch {
        alert('Errore durante l\'applicazione del template.');
      }
    }, [id]);

  useEffect(() => {
    if (selectedTemplateId === '' || !inventory) {
      return;
    }

    void applyTemplateToList(selectedTemplateId);
  }, [selectedTemplateId, inventory, items, applyTemplateToList]);

  const addItemSheetDrag = useBottomSheetDrag(() => setisInsertMode(false));
  const editItemSheetDrag = useBottomSheetDrag(() => setItemBeingEdited(null));

  return (
    <div ref={detailTopRef} className="relative p-3 sm:p-4">
      {inventory && (
        <div className="fixed inset-x-4 top-20 z-50 md:hidden">
          <div className="grid grid-cols-[2.75rem_minmax(0,1fr)_2.75rem] items-center gap-2">
            <Link
              to={`/${basePath}${filtroParam ? `?filtro=${encodeURIComponent(filtroParam)}` : ""}`}
              aria-label={`Torna all'elenco ${isChecklist ? 'delle liste' : 'degli inventari'}`}
              className="grid h-11 w-12 place-items-center rounded-xl bg-gray-100 text-xl text-blue-700 dark:bg-gray-800 dark:text-blue-300"
            ><FiArrowLeft aria-hidden="true" /></Link>
            <h1 className="truncate text-center text-lg font-bold" title={inventory.name}>{inventory.name}</h1>
            <button type="button" onClick={() => setIsHistoryOpen(true)} aria-label="Apri log modifiche" title="Log modifiche" className="grid h-11 w-12 place-items-center rounded-xl bg-gray-100 text-lg text-gray-700 dark:bg-gray-800 dark:text-gray-200">
              <FiClock aria-hidden="true" />
            </button>
          </div>
          <p className="mt-1 truncate px-1 text-xs leading-tight text-gray-600 dark:text-gray-300">
            Creato da: {inventory.owner.username ? `${inventory.owner.username}` : "Sconosciuto"} | Data modifica: {new Date(inventory.data_mod).toLocaleString()}
          </p>
        </div>
      )}
      <div className="relative z-10 bg-white pb-1 dark:bg-gray-900 md:sticky md:top-0">
        <Link
          to={`/${basePath}${filtroParam ? `?filtro=${encodeURIComponent(filtroParam)}` : ""}`}
          className="mb-1 hidden text-sm text-blue-500 hover:underline md:inline-block"
        >
          ← Torna all'elenco {isChecklist ? "delle liste" : "degli inventari"}
        </Link>
        {inventory && (
          <>
            <div className="mb-1 hidden flex-wrap items-center justify-between gap-2 md:flex">
              <h2 className="flex items-center gap-1.5 text-lg font-bold sm:gap-2 sm:text-xl">
                {isChecklist ? "Lista: " : "Inventario: "}
                {inventory.name}
                <span className="rounded bg-blue-100 px-1.5 py-0.5 font-mono text-xs text-blue-800 dark:bg-blue-900 dark:text-blue-200 sm:px-2 sm:py-1 sm:text-sm">
                  v{inventory.version_num}
                </span>
              </h2>
              <button
                onClick={() => setIsHistoryOpen(true)}
                className="h-10 w-10 shrink-0 rounded-lg bg-gray-200 px-1 text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600 sm:h-auto sm:w-auto sm:rounded sm:px-3 sm:py-1 sm:text-sm sm:whitespace-nowrap"
                title="Visualizza cronologia modifiche"
              >
                <span className="inline md:hidden">📋</span>
                <span className="hidden md:inline">Cronologia</span>
              </button>
            </div>
            <p className="mb-1 hidden text-xs text-gray-600 dark:text-gray-400 sm:mb-2 sm:text-sm md:block">
              Creato da: {inventory.owner.username ? `${inventory.owner.username}` : "Sconosciuto"} | Data modifica:{" "}
              {new Date(inventory.data_mod).toLocaleString()}
            </p>
            <hr className="mb-1 hidden sm:mb-2 md:block" />
          </>
        )}
      </div>

      {inventory ? (
        <div>
          <div className="z-10 mb-2 flex flex-wrap items-center gap-1.5 border-b bg-white px-1 py-1.5 dark:bg-gray-900 sm:sticky sm:top-16 sm:mb-3 sm:gap-2 sm:py-2">
            <label htmlFor="sort-by-select" className="hidden sm:inline text-sm font-medium">Ordina per:</label>
            {isChecklist && (
              <button
                type="button"
                onClick={() => {
                  const next = prioritySortOrder === 'desc' ? 'asc' : 'desc';
                  localStorage.setItem('item_prioritySortOrder', next);
                  setPrioritySortOrder(next);
                }}
                className="min-h-10 rounded border px-2 sm:min-h-0 sm:py-1 whitespace-nowrap"
                aria-label={prioritySortOrder === 'desc'
                  ? 'Priorità: prima alta (tocca per invertire)'
                  : 'Priorità: prima bassa (tocca per invertire)'}
                title={prioritySortOrder === 'desc'
                  ? 'Priorità: prima alta (tocca per invertire)'
                  : 'Priorità: prima bassa (tocca per invertire)'}
              >
                🔥<span className="hidden sm:inline"> Priorità</span> {prioritySortOrder === 'desc' ? '⬇️' : '⬆️'}
              </button>
            )}
            <select
              id="sort-by-select"
              aria-label="Ordina per"
              value={isChecklist && sortBy === "quantity" ? "name" : sortBy}
              onChange={(e) => {
                const value = e.target.value as 'name' | 'date' | 'quantity';
                localStorage.setItem('item_sortBy', value);
                setSortBy(value);
              }}
              className="min-h-10 min-w-0 flex-1 rounded border px-2 py-1 sm:min-h-0 sm:flex-none"
            >
              <option value="date">Data modifica</option>
              <option value="name">Nome</option>
              {!isChecklist && <option value="quantity">Quantità</option>}
            </select>
            <button
              type="button"
              onClick={() => {
                const newOrder = sortOrder === 'asc' ? 'desc' : 'asc';
                localStorage.setItem('item_sortOrder', newOrder);
                setSortOrder(newOrder);
              }}
              className="min-h-10 min-w-10 rounded border px-2 sm:min-h-0 sm:min-w-0 sm:py-1"
              aria-label={sortOrder === 'asc' ? 'Inverti ordine: passa a decrescente' : 'Inverti ordine: passa a crescente'}
              title={`Ordina in ordine ${sortOrder === 'asc' ? 'decrescente' : 'crescente'}`}
            >
              <span aria-hidden="true">{sortOrder === 'asc' ? '⬆️' : '⬇️'}</span>
            </button>
            <div className="w-full sm:w-auto">
              <div className="flex items-center gap-1.5 sm:gap-2">
                <input
                  type="text"
                  placeholder="Filtra la lista..."
                  value={filterText}
                  onChange={(e) => setFilterText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                      setFilterText('');
                    }
                  }}
                  className="min-h-10 min-w-0 flex-1 rounded border px-2 py-1 sm:min-h-0 sm:flex-none sm:w-auto"
                />
                <select
                  value={barcodeFilter}
                  onChange={(e) => setBarcodeFilter(e.target.value as 'all' | 'with' | 'without')}
                  className="min-h-10 w-28 rounded border px-1.5 py-1 sm:min-h-0 sm:w-auto"
                  title="Filtra per barcode"
                >
                  <option value="all">🏷️ Tutti</option>
                  <option value="with">🏷️ Con barcode</option>
                  <option value="without">🏷️ Senza barcode</option>
                </select>
                <button
                  type="button"
                  onClick={() => {
                    setFilterText('');
                    setBarcodeFilter('all');
                    window.history.replaceState(null, '', location.pathname);
                  }}
                  aria-label="Cancella filtro"
                  className="min-h-10 min-w-10 rounded bg-gray-300 px-2 py-1 text-gray-700 dark:bg-gray-700 dark:text-gray-300 sm:min-w-0 sm:px-4 sm:py-2"
                >
                  <span className="inline sm:hidden" aria-hidden="true">❌</span>
                  <span className="hidden sm:inline">Cancella filtro</span>
                </button>
              </div>
            </div>
            {(isInventory || isChecklist) && canEdit && (
              <div className="flex w-full items-center gap-1.5 sm:w-auto sm:gap-2">
                <label className="hidden sm:inline text-sm font-medium whitespace-nowrap">Template filtro:</label>
                <select
                  value={selectedTemplateId}
                  onChange={async (e) => {
                    const value = e.target.value;
                    if (!value) {
                      setSelectedTemplateId('');
                      setMetadataFilteredItemIds(null);
                      setMetadataFilterSummary(null);
                      return;
                    }
                    const templateId = Number(value);
                    setSelectedTemplateId(templateId);
                    await applyTemplateToList(templateId);
                  }}
                  className="min-h-10 min-w-0 flex-1 rounded border px-2 py-1 sm:min-h-0 sm:flex-none sm:min-w-[220px]"
                >
                  <option value="">Template filtro: nessuno</option>
                  {filterTemplates.map((template) => (
                    <option key={template.id} value={template.id}>{template.name}</option>
                  ))}
                </select>
              </div>
            )}
            {isEditMode && (
                <div className="mb-1 grid w-full grid-cols-2 gap-2 sm:ml-auto sm:w-auto">
                <button
                    onClick={() => setSelectedItems(sortedItems.map(item => item.id))}
                    className="min-h-10 w-full rounded bg-blue-500 px-2 py-1 text-sm text-white"
                >
                    Seleziona tutti
                </button>
                <button
                    onClick={() => setSelectedItems([])}
                    className="min-h-10 w-full rounded bg-gray-500 px-2 py-1 text-sm text-white"
                >
                    Deseleziona tutti
                </button>
                </div>
            )}
          </div>
          {metadataFilterSummary && (
            <div className="mb-3 flex items-center gap-2 rounded border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-100">
              <span>{metadataFilterSummary}</span>
              <button
                className="ml-auto rounded bg-indigo-600 px-3 py-1 text-white hover:bg-indigo-700"
                onClick={() => {
                  setMetadataFilteredItemIds(null);
                  setMetadataFilterSummary(null);
                  setSelectedTemplateId('');
                }}
                type="button"
              >
                Rimuovi filtro
              </button>
            </div>
          )}
          <ul className="mb-20">
            {sortedItems.map((item) => (
              <SwipeableItemRow
                key={item.id}
                item={item}
                isMobile={isMobile}
                isChecklist={isChecklist}
                isInventory={isInventory}
                user={user}
                isEditMode={isEditMode}
                selectedItems={selectedItems}
                setSelectedItems={setSelectedItems}
                setItemBeingEdited={setItemBeingEdited}
                updateItem={async (id, itemArg, onInsufficient) =>
                  await updateItem(id, {
                    name: itemArg.name ?? "",
                    description: itemArg.description,
                    quantity: itemArg.quantity ?? 0,
                    priority: isChecklist ? itemArg.priority ?? 0 : 0,
                    inventory_id: itemArg.inventory_id ?? inventory?.id ?? 0,
                  }, onInsufficient)
                }
                deleteItem={deleteItem}
                setItems={setItems}
                setIsCloning={setIsCloning}
              />
            ))}
          </ul>
        </div>
      ) : (
        <p>Caricamento {isChecklist ? "checklist" : "inventaro"}...</p>
      )}

      {!isMobile && <div className="fixed right-4 top-4 z-40 flex flex-wrap justify-end gap-2">
        <button type="button" onClick={() => detailTopRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-gray-700 px-3 py-2 text-white shadow-lg hover:bg-gray-800" title="Torna in cima alla lista">
          ↑ In cima
        </button>
        {isEditMode && selectedItems.length > 0 && (
          <button
            onClick={async () => {
              if (!window.confirm("Sei sicuro di voler eliminare gli oggetti selezionati?")) return;
              for (const id of selectedItems) {
                await deleteItem(id);
              }
              setSelectedItems([]);
              setIsEditMode(false);
              const getItems = isInventory ? getInventoryItems : getChecklistItems;
              const refreshed = inventory && await getItems(inventory.id);
              if (refreshed) setItems(refreshed);
            }}
            className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-red-600 px-3 py-2 text-white shadow-lg hover:bg-red-700"
          >
            <span className="inline md:hidden">🗑️ {( selectedItems.length )}</span>
            <span className="hidden md:inline">Elimina {( selectedItems.length )}</span>
          </button>
        )}
        {isChecklist && canEdit && (
          <button
            onClick={() => setIsAddFromInventoryOpen(true)}
            className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-emerald-600 px-3 py-2 text-white shadow-lg hover:bg-emerald-700"
            title="Aggiungi da inventario"
          >
            <span className="inline md:hidden">📥</span>
            <span className="hidden md:inline">📥 Da inventario</span>
          </button>
        )}
        {(isInventory || isChecklist) && canEdit && (
          <MetadataFilterManager
            inventoryId={inventory?.id ?? Number(id)}
            currentContainerType={isChecklist ? 'CHECKLIST' : 'INVENTORY'}
            definitions={metadataDefinitions}
            allDefinitions={allMetadataDefinitions}
            onTemplatesChanged={setFilterTemplates}
            triggerClassName="!flex !h-10 !min-h-10 !min-w-12 !items-center !justify-center !rounded-xl !px-3 !py-2"
          />
        )}
        {(isInventory || isChecklist) && canEdit && (
          <button
            onClick={() => {
              const now = new Date();
              const header = `${inventory?.name} (${now.toLocaleString()})`;
              const withQty = items.filter(i => i.quantity > 0).sort((a, b) => a.name.localeCompare(b.name));
              const zeroQty = items.filter(i => i.quantity === 0).sort((a, b) => a.name.localeCompare(b.name));
              const lines = [...withQty, ...zeroQty].map(i =>
                `- ${i.quantity}x ${i.name}${i.description ? ` (${i.description})` : ''}`
              );
              const text = encodeURIComponent([header, ...lines].join('\n'));
              //window.location.href = `https://wa.me/?text=${text}`;
              window.open(`https://wa.me/?text=${text}`, '_blank');
            }}
            className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-green-700 px-3 py-2 text-white shadow-lg hover:bg-green-800"
          >
            <span className="inline md:hidden">📲</span>
            <span className="hidden md:inline">📲 WhatsApp</span>
          </button>
        )}
        {(isInventory || isChecklist) && isAdmin && (
          <button
            onClick={() => setIsShareModalOpen(true)}
            className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-green-600 px-3 py-2 text-white shadow-lg hover:bg-green-700"
          >
            <span className="inline md:hidden">📤</span>
            <span className="hidden md:inline">Import/Export</span>
          </button>
        )}
        {(isInventory || isChecklist) && canEdit && (
          <>
            <button
              onClick={() => {
                setIsEditMode((prev) => !prev);
                setSelectedItems([]);
              }}
              className={`flex h-10 min-w-12 items-center justify-center rounded-xl px-3 py-2 text-white shadow-lg ${
                isEditMode ? "bg-yellow-700" : "bg-yellow-500 hover:bg-yellow-600"
              }`}
            >
              <span className="inline md:hidden">{isEditMode ? "✖️" : "✏️"}</span>
              <span className="hidden md:inline">{isEditMode ? "Chiudi" : "Modifica"}</span>
            </button>
            <button
              onClick={() => setisInsertMode(true)}
              className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-blue-500 px-3 py-2 text-white shadow-lg hover:bg-blue-600"
            >
              <span className="inline md:hidden">➕</span>
              <span className="hidden md:inline">Nuovo</span>
            </button>
          </>
        )}
      </div>}

      {isMobile && canEdit && (isInventory || isChecklist) && (
        <div className="fixed bottom-[calc(env(safe-area-inset-bottom)+4.5rem)] left-1/2 z-40 flex -translate-x-1/2 flex-col items-center">
          {isMoreActionsOpen && (
            <>
              <div className="relative z-40 mb-2 flex w-56 flex-col gap-2 rounded-2xl border border-gray-200 bg-white p-2 shadow-xl dark:border-gray-700 dark:bg-gray-800">
                {isEditMode && selectedItems.length > 0 && (
                  <button
                    type="button"
                    onClick={async () => {
                      if (!window.confirm('Sei sicuro di voler eliminare gli oggetti selezionati?')) return;
                      for (const selectedId of selectedItems) await deleteItem(selectedId);
                      setSelectedItems([]);
                      setIsEditMode(false);
                      const getItems = isInventory ? getInventoryItems : getChecklistItems;
                      const refreshed = inventory && await getItems(inventory.id);
                      if (refreshed) setItems(refreshed);
                      setIsMoreActionsOpen(false);
                    }}
                    className="min-h-11 w-full rounded-xl bg-red-600 px-3 text-left text-sm font-medium text-white"
                  >🗑️ Elimina selezionati ({selectedItems.length})</button>
                )}
                {isChecklist && (
                  <button type="button" onClick={() => { setIsMoreActionsOpen(false); setIsAddFromInventoryOpen(true); }} className="min-h-11 w-full rounded-xl bg-emerald-600 px-3 text-left text-sm font-medium text-white">
                    📥 Aggiungi da inventario
                  </button>
                )}
                <MetadataFilterManager
                  inventoryId={inventory?.id ?? Number(id)}
                  currentContainerType={isChecklist ? 'CHECKLIST' : 'INVENTORY'}
                  definitions={metadataDefinitions}
                  allDefinitions={allMetadataDefinitions}
                  onTemplatesChanged={setFilterTemplates}
                  triggerLabel="🧩 Filtri metadati"
                  triggerClassName="!min-h-11 !w-full !rounded-xl !px-3 !py-2 !text-left !text-sm !font-medium !shadow-none"
                  onDialogClose={() => setIsMoreActionsOpen(false)}
                />
                <button
                  type="button"
                  onClick={() => {
                    setIsMoreActionsOpen(false);
                    const now = new Date();
                    const header = `${inventory?.name} (${now.toLocaleString()})`;
                    const withQty = items.filter((item) => item.quantity > 0).sort((a, b) => a.name.localeCompare(b.name));
                    const zeroQty = items.filter((item) => item.quantity === 0).sort((a, b) => a.name.localeCompare(b.name));
                    const lines = [...withQty, ...zeroQty].map((item) => `- ${item.quantity}x ${item.name}${item.description ? ` (${item.description})` : ''}`);
                    window.open(`https://wa.me/?text=${encodeURIComponent([header, ...lines].join('\n'))}`, '_blank');
                  }}
                  className="min-h-11 w-full rounded-xl bg-green-700 px-3 text-left text-sm font-medium text-white"
                >📲 Condividi su WhatsApp</button>
                {isAdmin && (
                  <button type="button" onClick={() => { setIsMoreActionsOpen(false); setIsShareModalOpen(true); }} className="min-h-11 w-full rounded-xl bg-green-600 px-3 text-left text-sm font-medium text-white">
                    📤 Importa / esporta
                  </button>
                )}
              </div>
            </>
          )}
          <div className="relative z-40 flex gap-1 rounded-2xl bg-white/90 p-1 shadow-lg backdrop-blur dark:bg-gray-900/90">
            <button
              type="button"
              onClick={() => setisInsertMode(true)}
              aria-label="Aggiungi item"
              title="Aggiungi item"
              className="flex h-10 min-w-12 items-center justify-center rounded-xl bg-blue-500 px-3 py-2 text-lg text-white shadow-lg hover:bg-blue-600"
            >➕</button>
            <button
              type="button"
              onClick={() => { setIsEditMode((current) => !current); setSelectedItems([]); }}
              aria-label={isEditMode ? 'Esci dalla modifica' : 'Modifica item'}
              title={isEditMode ? 'Esci dalla modifica' : 'Modifica item'}
              className={`flex h-10 w-12 items-center justify-center rounded-xl text-lg text-white shadow-lg ${isEditMode ? 'bg-yellow-700' : 'bg-yellow-500'}`}
            >{isEditMode ? '✖️' : '✏️'}</button>
            <button
              type="button"
              onClick={() => detailTopRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
              aria-label="Torna in cima alla lista"
              title="Torna in cima alla lista"
              className="flex h-10 w-12 items-center justify-center rounded-xl bg-gray-600 text-lg text-white shadow-lg"
            >↑</button>
            <button
              type="button"
              onClick={() => setIsMoreActionsOpen((open) => !open)}
              aria-label={isMoreActionsOpen ? 'Chiudi altre azioni' : 'Altre azioni'}
              aria-expanded={isMoreActionsOpen}
              title="Altre azioni"
              className="flex h-10 w-12 items-center justify-center rounded-xl bg-gray-700 text-lg text-white shadow-lg dark:bg-gray-600"
            >⋯</button>
          </div>
        </div>
      )}

      {isMobile && isMoreActionsOpen && createPortal(
        <button type="button" aria-label="Chiudi altre azioni" onClick={() => setIsMoreActionsOpen(false)} className="fixed inset-0 z-[39]" />,
        document.body,
      )}

      <Dialog open={isInsertMode} onClose={() => setisInsertMode(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel
            style={{ transform: `translateY(${addItemSheetDrag.offset}px)`, transition: addItemSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="max-h-[92dvh] w-full max-w-2xl overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1.25rem)] shadow-2xl dark:bg-gray-900 dark:text-white sm:rounded-2xl sm:p-6"
          >
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...addItemSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <Dialog.Title className="mb-4 text-lg font-semibold">Nuovo oggetto</Dialog.Title>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (!inventory) return;
                const metadataValues = metadataDefinitions
                  .map((definition) => normalizeMetadataDraft(definition, newItemMetadataDrafts[definition.id]))
                  .filter((value): value is ItemMetadataValueUpsert => value !== null);
                const newItem = await createItemWithFeedback({
                  name: newItemName,
                  description: newItemDescription,
                  quantity: newItemQuantity,
                  priority: isChecklist ? newItemPriority : 0,
                  inventory_id: inventory.id,
                  metadata_values: metadataValues,
                });
                if (newItem) {
                  if (isChecklist && newItemLink) {
                    try {
                      await createAssignment(newItem.id, newItemLink.item.id, newItemLink.qty);
                    } catch (err) {
                      window.alert(err instanceof Error ? err.message : "Collegamento non riuscito");
                    }
                  }
                  const getItems = isInventory ? getInventoryItems : getChecklistItems;
                  const refreshed = inventory && await getItems(inventory.id);
                  if (refreshed) setItems(refreshed);
                  setNewItemName("");
                  setNewItemDescription("");
                  setNewItemQuantity(isChecklist ? 0 : 1);
                  setNewItemPriority(0);
                  setNewItemMetadataDrafts({});
                  setNewItemLink(null);
                  setisInsertMode(false);
                }
              }}
            >
              <div className="mb-2">
                <label className="block text-sm font-medium">Nome</label>
                <input type="text" className="min-h-12 w-full border rounded p-3" value={newItemName} onChange={(e) => setNewItemName(e.target.value)} />
              </div>
              <div className="mb-2">
                <label className="block text-sm font-medium">Descrizione</label>
                <input type="text" className="min-h-12 w-full border rounded p-3" value={newItemDescription} onChange={(e) => setNewItemDescription(e.target.value)} />
              </div>
              {isChecklist && canEdit && (
                <ListLinkField
                  current={newItemLink ? { name: newItemLink.item.name, qty: newItemLink.qty } : null}
                  onPick={async (picked, qty) => {
                    setNewItemLink({ item: picked, qty });
                    if (!newItemName.trim()) setNewItemName(picked.name);
                  }}
                  onClear={() => setNewItemLink(null)}
                />
              )}
              {isInventory && (
                <div className="mb-4">
                  <label className="block text-sm font-medium">Quantità</label>
                  <div className="grid grid-cols-3 gap-2">
                    <button
                      type="button"
                      onClick={() => setNewItemQuantity((prev) => Math.max(0, prev - 1))}
                      aria-label="Diminuisci quantità"
                      className="min-h-12 w-full bg-gray-400 rounded hover:bg-gray-600 text-xl leading-none"
                    >
                      −
                    </button>
                    <input
                      type="number"
                      min="0"
                      className="min-h-12 w-full border rounded p-2 text-center"
                      value={newItemQuantity}
                      onChange={(e) => setNewItemQuantity(Math.max(0, Number(e.target.value)))}
                    />
                    <button
                      type="button"
                      onClick={() => setNewItemQuantity((prev) => prev + 1)}
                      aria-label="Aumenta quantità"
                      className="min-h-12 w-full bg-gray-400 rounded hover:bg-gray-600 text-xl leading-none"
                    >
                      +
                    </button>
                  </div>
                </div>
              )}
              {isChecklist && (
                <div className="mb-4">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={newItemQuantity > 0}
                      onChange={(e) => setNewItemQuantity(e.target.checked ? 1 : 0)}
                    />
                    Elemento completato
                  </label>
                </div>
              )}
              {isChecklist && (
                <div className="mb-4">
                  <label htmlFor="new-item-priority" className="mb-1 block text-sm font-medium">Priorità</label>
                  <select
                    id="new-item-priority"
                    value={newItemPriority}
                    onChange={(event) => setNewItemPriority(Number(event.target.value))}
                    className="min-h-12 w-full rounded border p-3 dark:bg-gray-800"
                  >
                    {ITEM_PRIORITY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </div>
              )}
              <MetadataFieldsSection
                definitions={metadataDefinitions.filter((definition) => definition.is_active)}
                drafts={newItemMetadataDrafts}
                onChange={(definition, value) => {
                  setNewItemMetadataDrafts((current) => {
                    const nextDraft = createEmptyMetadataDraft(definition.field_type);
                    nextDraft.definition_id = definition.id;

                    if (definition.field_type === 'TEXT' || definition.field_type === 'LIST') {
                      nextDraft.value_text = value || null;
                    } else if (definition.field_type === 'NUMBER') {
                      nextDraft.value_number = value === '' ? null : value;
                    } else if (definition.field_type === 'BOOLEAN') {
                      nextDraft.value_boolean = value === '' ? null : value === 'true';
                    } else {
                      nextDraft.value_date = value || null;
                    }

                    return {
                      ...current,
                      [definition.id]: nextDraft,
                    };
                  });
                }}
              />
              <div className="grid w-full grid-cols-2 gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setisInsertMode(false);
                    setNewItemMetadataDrafts({});
                  }}
                  className="min-h-12 w-full rounded-xl bg-gray-400 px-4 font-medium hover:bg-gray-600"
                >
                  Chiudi
                </button>
                <button type="submit" className="min-h-12 w-full rounded-xl bg-blue-500 px-4 font-medium text-white hover:bg-blue-600">
                  Aggiungi
                </button>
              </div>
            </form>
          </Dialog.Panel>
        </div>
      </Dialog>

      <Dialog open={!!itemBeingEdited} onClose={() => setItemBeingEdited(null)} className="relative z-50">
        <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel
            style={{ transform: `translateY(${editItemSheetDrag.offset}px)`, transition: editItemSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="max-h-[92dvh] w-full max-w-2xl overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1.25rem)] shadow-2xl dark:bg-gray-900 dark:text-white sm:rounded-2xl sm:p-6"
          >
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...editItemSheetDrag.gripProps} className="mx-auto mb-3 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <Dialog.Title className="mb-4 text-lg font-semibold">{isCloning ? "Clona oggetto" : "Modifica oggetto"}</Dialog.Title>
            {itemBeingEdited && (
              <form
              onSubmit={async (e) => {
                e.preventDefault();
                if (isCloning) {
                  if (!inventory) return;
                  const metadataValues = metadataDefinitions
                    .map((definition) => normalizeMetadataDraft(definition, editingMetadataDrafts[definition.id]))
                    .filter((value): value is ItemMetadataValueUpsert => value !== null);
                  const newItem = await createItemWithFeedback({
                    name: itemBeingEdited.name,
                    description: itemBeingEdited.description ?? "",
                    quantity: itemBeingEdited.quantity,
                    priority: isChecklist ? itemBeingEdited.priority ?? 0 : 0,
                    inventory_id: inventory.id,
                    metadata_values: metadataValues,
                  });
                  if (newItem) {
                    const getItems = isInventory ? getInventoryItems : getChecklistItems;
                    const refreshed = inventory && await getItems(inventory.id);
                    if (refreshed) setItems(refreshed);
                    setItemBeingEdited(null);
                    setIsCloning(false);
                  }
                } else {
                  const updated = await updateItem(itemBeingEdited.id, {
                    name: itemBeingEdited.name,
                    description: itemBeingEdited.description ?? "",
                    quantity: itemBeingEdited.quantity,
                    priority: isChecklist ? itemBeingEdited.priority ?? 0 : 0,
                    inventory_id: itemBeingEdited.inventory_id,
                  });
                  if (updated) {
                    const existingValuesByDefinitionId = new Map(
                      editingMetadataValues.map((value) => [value.definition_id, value]),
                    );

                    const metadataValuesToUpsert = metadataDefinitions
                      .map((definition) => normalizeMetadataDraft(definition, editingMetadataDrafts[definition.id]))
                      .filter((value): value is ItemMetadataValueUpsert => value !== null);

                    const metadataValueIdsToDelete = metadataDefinitions
                      .filter((definition) => !normalizeMetadataDraft(definition, editingMetadataDrafts[definition.id]))
                      .map((definition) => existingValuesByDefinitionId.get(definition.id)?.id)
                      .filter((valueId): valueId is number => valueId !== undefined);

                    if (metadataValueIdsToDelete.length > 0) {
                      await Promise.all(metadataValueIdsToDelete.map((valueId) => deleteItemMetadataValue(valueId)));
                    }

                    if (metadataValuesToUpsert.length > 0) {
                      await bulkUpsertItemMetadataValues({
                        item_id: updated.id,
                        values: metadataValuesToUpsert,
                      });
                    }

                    // Refresh the full list so metadata badges are up to date
                    const getItemsFn = isInventory ? getInventoryItems : getChecklistItems;
                    const refreshed = inventory && await getItemsFn(inventory.id);
                    if (refreshed) setItems(refreshed as Item[]);
                    setItemBeingEdited(null);
                  }
                }
              }}
              >
                <div className="mb-2">
                  <label className="block text-sm font-medium">Nome</label>
                  <input
                    type="text"
                    className="min-h-12 w-full border rounded p-3"
                    value={itemBeingEdited.name}
                    onChange={(e) =>
                      setItemBeingEdited({ ...itemBeingEdited, name: e.target.value })
                    }
                  />
                </div>
                <div className="mb-2">
                  <label className="block text-sm font-medium">Descrizione</label>
                  <input
                    type="text"
                    className="min-h-12 w-full border rounded p-3"
                    value={itemBeingEdited.description || ""}
                    onChange={(e) =>
                      setItemBeingEdited({ ...itemBeingEdited, description: e.target.value })
                    }
                  />
                </div>
                {isInventory && (
                  <div className="mb-4">
                    <label className="block text-sm font-medium">Quantità</label>
                    <div className="grid grid-cols-3 gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setItemBeingEdited((prev) =>
                            prev ? { ...prev, quantity: Math.max(0, prev.quantity - 1) } : prev
                          )
                        }
                        aria-label="Diminuisci quantità"
                        className="min-h-12 w-full bg-gray-400 rounded hover:bg-gray-600 text-xl leading-none"
                      >
                        −
                      </button>
                      <input
                        type="number"
                        min="0"
                        className="min-h-12 w-full border rounded p-2 text-center"
                        value={itemBeingEdited.quantity}
                        onChange={(e) =>
                          setItemBeingEdited({
                            ...itemBeingEdited,
                            quantity: Math.max(0, Number(e.target.value)),
                          })
                        }
                      />
                      <button
                        type="button"
                        onClick={() =>
                          setItemBeingEdited((prev) =>
                            prev ? { ...prev, quantity: prev.quantity + 1 } : prev
                          )
                        }
                        aria-label="Aumenta quantità"
                        className="min-h-12 w-full bg-gray-400 rounded hover:bg-gray-600 text-xl leading-none"
                      >
                        +
                      </button>
                    </div>
                  </div>
                )}
                {isChecklist && (
                  <div className="mb-4">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={itemBeingEdited.quantity > 0}
                        onChange={(e) =>
                          setItemBeingEdited({
                            ...itemBeingEdited,
                            quantity: e.target.checked ? 1 : 0,
                          })
                        }
                      />
                      Elemento completato
                    </label>
                  </div>
                )}
                {isChecklist && (
                  <div className="mb-4">
                    <label htmlFor="edit-item-priority" className="mb-1 block text-sm font-medium">Priorità</label>
                    <select
                      id="edit-item-priority"
                      value={itemBeingEdited.priority ?? 0}
                      onChange={(event) =>
                        setItemBeingEdited({ ...itemBeingEdited, priority: Number(event.target.value) })
                      }
                      className="min-h-12 w-full rounded border p-3 dark:bg-gray-800"
                    >
                      {ITEM_PRIORITY_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </div>
                )}
                {isChecklist && !isCloning && canEdit && (
                  <ListLinkField
                    current={itemBeingEdited.assignment
                      ? { name: itemBeingEdited.assignment.source_name ?? "", inventoryName: itemBeingEdited.assignment.source_inventory_name, qty: itemBeingEdited.assignment.qty }
                      : null}
                    onPick={async (picked, qty) => {
                      const created = await createAssignment(itemBeingEdited.id, picked.id, qty);
                      setItemBeingEdited((prev) => (prev ? { ...prev, assignment: created } : prev));
                      setItems((current) => current.map((it) => (it.id === itemBeingEdited.id ? { ...it, assignment: created } : it)));
                    }}
                    onClear={async () => {
                      if (!itemBeingEdited.assignment) return;
                      await deleteAssignment(itemBeingEdited.assignment.id);
                      setItemBeingEdited((prev) => (prev ? { ...prev, assignment: null } : prev));
                      setItems((current) => current.map((it) => (it.id === itemBeingEdited.id ? { ...it, assignment: null } : it)));
                      window.dispatchEvent(new Event(ITEMS_CHANGED_EVENT));
                    }}
                    onClearAndDelete={async () => {
                      await deleteItem(itemBeingEdited.id);
                      setItems((current) => current.filter((it) => it.id !== itemBeingEdited.id));
                      setItemBeingEdited(null);
                      window.dispatchEvent(new Event(ITEMS_CHANGED_EVENT));
                    }}
                  />
                )}
                {!isCloning && (
                  <details className="mb-3 rounded-xl border border-gray-200 dark:border-gray-700">
                    <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800">
                      <span className="min-w-0">
                        <span className="block font-medium">Codici a barre / QR</span>
                        <span className="block break-all text-sm text-gray-500 dark:text-gray-400">
                          {(itemBeingEdited.barcodes?.length ?? 0) === 1
                            ? '1 codice assegnato'
                            : `${itemBeingEdited.barcodes?.length ?? 0} codici assegnati`}
                          {(itemBeingEdited.barcodes?.length ?? 0) > 0 && ` · ${itemBeingEdited.barcodes?.map((barcode) => barcode.code).join(', ')}`}
                        </span>
                      </span>
                      <span className="shrink-0 text-gray-500" aria-hidden="true">⌄</span>
                    </summary>
                    <div className="border-t border-gray-200 px-4 pt-3 dark:border-gray-700">
                      <ItemBarcodesEditor
                        itemId={itemBeingEdited.id}
                        barcodes={itemBeingEdited.barcodes ?? []}
                        onChange={(barcodes) => {
                          setItemBeingEdited((prev) => (prev ? { ...prev, barcodes } : prev));
                          setItems((current) =>
                            current.map((item) => (item.id === itemBeingEdited.id ? { ...item, barcodes } : item)),
                          );
                        }}
                      />
                    </div>
                  </details>
                )}
                {metadataDefinitions.some((definition) => definition.is_active) && (
                  <details className="mb-4 rounded-xl border border-gray-200 dark:border-gray-700">
                    <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800">
                      <span className="min-w-0">
                        <span className="block font-medium">Metadati</span>
                        {metadataLoading ? (
                          <span className="block text-sm text-gray-500 dark:text-gray-400">Caricamento valori…</span>
                        ) : editingMetadataRecap.length > 0 ? (
                          <span className="block text-sm text-gray-600 dark:text-gray-300">
                            {editingMetadataRecap.map((metadata) => `${metadata.label}: ${metadata.value}`).join(' · ')}
                          </span>
                        ) : (
                          <span className="block text-sm text-gray-500 dark:text-gray-400">Nessun metadato valorizzato</span>
                        )}
                      </span>
                      <span className="shrink-0 text-gray-500" aria-hidden="true">⌄</span>
                    </summary>
                    <div className="border-t border-gray-200 px-4 pt-1 dark:border-gray-700">
                      {metadataLoading ? (
                        <div className="py-3 text-sm text-gray-500 dark:text-gray-300">Caricamento metadati…</div>
                      ) : (
                        <MetadataFieldsSection
                          definitions={metadataDefinitions.filter((definition) => definition.is_active)}
                          drafts={editingMetadataDrafts}
                          onChange={(definition, value) => {
                            setEditingMetadataDrafts((current) => {
                              const nextDraft = createEmptyMetadataDraft(definition.field_type);
                              nextDraft.definition_id = definition.id;

                              if (definition.field_type === 'TEXT' || definition.field_type === 'LIST') {
                                nextDraft.value_text = value || null;
                              } else if (definition.field_type === 'NUMBER') {
                                nextDraft.value_number = value === '' ? null : value;
                              } else if (definition.field_type === 'BOOLEAN') {
                                nextDraft.value_boolean = value === '' ? null : value === 'true';
                              } else {
                                nextDraft.value_date = value || null;
                              }

                              return {
                                ...current,
                                [definition.id]: nextDraft,
                              };
                            });
                          }}
                        />
                      )}
                    </div>
                  </details>
                )}
                <div className="grid w-full grid-cols-2 gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setItemBeingEdited(null);
                      setIsCloning(false);
                      setEditingMetadataDrafts({});
                      setEditingMetadataValues([]);
                    }}
                    className="min-h-12 w-full rounded-xl bg-gray-400 px-4 font-medium hover:bg-gray-600"
                  >
                    Chiudi
                  </button>
                  <button
                    type="submit"
                    className={`min-h-12 w-full rounded-xl px-4 font-medium text-white hover:opacity-90 ${isCloning ? "bg-yellow-500 hover:bg-yellow-600" : "bg-green-600 hover:bg-green-700"}`}
                  >
                    {isCloning ? "Clona" : "Salva modifiche"}
                  </button>
                </div>
              </form>
            )}
          </Dialog.Panel>
        </div>
      </Dialog>
      <Dialog open={isShareModalOpen} onClose={() => setIsShareModalOpen(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-end justify-center sm:items-center sm:p-4">
          <Dialog.Panel
            style={{ transform: `translateY(${importExportSheetDrag.offset}px)`, transition: importExportSheetDrag.isDragging ? 'none' : 'transform 220ms ease-out' }}
            className="max-h-[92dvh] w-full space-y-4 overflow-y-auto rounded-t-3xl bg-white p-5 pb-[calc(env(safe-area-inset-bottom)+1rem)] text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white sm:max-w-lg sm:rounded-xl sm:p-6 sm:pb-6"
          >
            <button type="button" aria-label="Chiudi o trascina verso il basso" {...importExportSheetDrag.gripProps} className="mx-auto mb-2 flex h-8 w-16 touch-none items-center justify-center sm:hidden">
              <span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" aria-hidden="true" />
            </button>
            <Dialog.Title className="text-lg font-semibold mb-2">Importa / Esporta CSV</Dialog.Title>
            <button
              onClick={() => {
                const csvContent = [
                  ['name', 'description', 'quantity'],
                  ...items.map(item => [item.name, item.description ?? '', item.quantity.toString()])
                ]
                  .map(e => e.map(v => `"${v.replace(/"/g, '""')}"`).join(','))
                  .join('\n');
                const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a");
                link.setAttribute("href", url);
                link.setAttribute("download", `${inventory?.name || 'inventory'}.csv`);
                link.click();
              }}
              className="w-full px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700"
            >
              Esporta in CSV
            </button>

            <div className="flex items-center gap-4">
              <label className="text-sm font-medium">Modalità importazione:</label>
              <select
                value={importMode}
                onChange={(e) => setImportMode(e.target.value as 'merge' | 'replace')}
                className="border rounded p-1"
              >
                <option value="merge">Unisci per nome</option>
                <option value="replace">Sostituisci completamente</option>
              </select>
            </div>
            <input
              type="file"
              accept=".csv"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const text = await file.text();
                handleCSVImport(text);
                setIsShareModalOpen(false);
              }}
              className="w-full border rounded p-2"
            />

            <div>
              <textarea
                placeholder="Incolla qui il CSV"
                rows={4}
                className="w-full border rounded p-2"
                value={csvTextarea}
                onChange={(e) => setCsvTextarea(e.target.value)}
              />
              <button
                onClick={() => {
                  handleCSVImport(csvTextarea);
                  setCsvTextarea('');
                  setIsShareModalOpen(false);
                }}
                className="mt-2 px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
              >
                Importa da testo
              </button>
            </div>

            <div className="flex justify-end">
              <button
                onClick={() => setIsShareModalOpen(false)}
                className="px-3 py-1 bg-gray-400 rounded hover:bg-gray-600"
              >
                Chiudi
              </button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>

      <HistoryModal
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        onRollback={async () => {
          // Refresh inventory and items after rollback
          if (!inventory) return;
          const getById = isInventory ? getInventoryById : getChecklistById;
          const getItems = isInventory ? getInventoryItems : getChecklistItems;
          const updated = await getById(inventory.id);
          if (updated) setInventory(updated);
          const refreshed = await getItems(inventory.id);
          if (refreshed) setItems(refreshed);
        }}
        entityType={isInventory ? "inventory" : "checklist"}
        entityId={inventory?.id || 0}
        entityName={inventory?.name || ""}
      />
      {isAddFromInventoryOpen && inventory && (
        <AddFromInventoryDialog listId={inventory.id} onClose={() => setIsAddFromInventoryOpen(false)} />
      )}
    </div>
  );
}
