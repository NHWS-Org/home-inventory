import { Dialog } from "@headlessui/react";
import { isAxiosError } from "axios";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { FiBell, FiBox, FiCheckSquare, FiClock, FiFilter, FiInfo, FiPlay, FiPlus, FiSearch, FiTrash2, FiX } from "react-icons/fi";
import {
  createFilter, createTrigger, deleteFilter, deleteTrigger, FILTER_WEEKDAYS, formatWeekdays,
  getFilter, getFilterFields, getFilters, getTrigger, getTriggers, previewFilter, previewTrigger, updateFilter, updateTrigger,
  validateFilterInput,
  type FilterCondition, type FilterEvaluation, type FilterField, type FilterInput,
  type FilterOperator, type FilterResponse, type FilterValue, type TriggerInput, type TriggerResponse,
} from "../filtersApi";
import { useBottomSheetDrag } from "../components/useBottomSheetDrag";
import { useAuth } from "../useAuth";

type Section = "filters" | "triggers";
type DateDraft = { mode: "date" | "today" | "relative"; date: string; days: string };
type ConditionDraft = {
  source: "item" | "metadata";
  field: string;
  definition_id?: number;
  operator: FilterOperator;
  value: string | boolean | DateDraft;
  range_from: DateDraft;
  range_to: DateDraft;
};

const defaultTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Rome";
const textControl = "mt-1 min-h-11 w-full min-w-0 rounded-xl border border-gray-300 bg-white px-3 text-base dark:border-gray-600 dark:bg-gray-800";
const button = "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-xl border border-gray-300 px-3 text-sm font-medium hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-600 dark:hover:bg-gray-800";
const primary = "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50";

function apiErrorMessage(error: unknown, fallback: string): string {
  if (isAxiosError<{ detail?: unknown }>(error) && typeof error.response?.data?.detail === "string") {
    return error.response.data.detail;
  }
  return fallback;
}

function defaultCondition(field?: FilterField): ConditionDraft {
  return {
    source: field?.source ?? "item",
    field: field?.field ?? "name",
    definition_id: field?.definition_id,
    operator: field?.operators[0] ?? "contains",
    value: field?.field_type === "BOOLEAN" ? false : field?.field_type === "DATE" ? { mode: "today", date: "", days: "0" } : "",
    range_from: { mode: "today", date: "", days: "0" },
    range_to: { mode: "today", date: "", days: "0" },
  };
}

function conditionFromApi(condition: FilterCondition, fields: FilterField[]): ConditionDraft {
  const field = fields.find(item => item.source === condition.source && item.field === condition.field
    && (item.definition_id ?? null) === (condition.definition_id ?? null));
  const dateDraft = (value: FilterValue | undefined): DateDraft => {
    if (typeof value === "object" && value !== null && "relative_days" in value) {
      return value.relative_days === 0
        ? { mode: "today", date: "", days: "0" }
        : { mode: "relative", date: "", days: String(value.relative_days) };
    }
    return { mode: "date", date: typeof value === "string" ? value : "", days: "0" };
  };
  const value = field?.field_type === "DATE"
    ? dateDraft(condition.value)
    : typeof condition.value === "boolean" || typeof condition.value === "string"
      ? condition.value
      : condition.value == null ? "" : String(condition.value);
  return {
    source: condition.source,
    field: condition.field,
    definition_id: condition.definition_id,
    operator: condition.operator,
    value,
    range_from: dateDraft(condition.range_from),
    range_to: dateDraft(condition.range_to),
  };
}

function serializeDate(value: DateDraft): FilterValue {
  if (value.mode === "date") return value.date;
  if (value.mode === "today") return { relative_days: 0 };
  return { relative_days: Number(value.days) };
}

function serializeCondition(row: ConditionDraft, field: FilterField): FilterCondition {
  const base: FilterCondition = {
    source: row.source,
    field: row.field,
    ...(row.definition_id ? { definition_id: row.definition_id } : {}),
    operator: row.operator,
  };
  if (row.operator === "is_null" || row.operator === "is_not_null") return base;
  if (row.operator === "between") {
    if (field.field_type === "DATE") return { ...base, range_from: serializeDate(row.range_from), range_to: serializeDate(row.range_to) };
    return { ...base, range_from: Number(row.range_from.date), range_to: Number(row.range_to.date) };
  }
  if (field.field_type === "DATE") return { ...base, value: serializeDate(row.value as DateDraft) };
  if (field.field_type === "BOOLEAN") return { ...base, value: row.value === true };
  if (field.field_type === "NUMBER") return { ...base, value: Number(row.value) };
  return { ...base, value: String(row.value) };
}

function dateControl(value: DateDraft, onChange: (value: DateDraft) => void, label: string) {
  return <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
    <select aria-label={`${label}: riferimento`} className={textControl} value={value.mode} onChange={event => onChange({ ...value, mode: event.target.value as DateDraft["mode"] })}>
      <option value="today">Oggi</option>
      <option value="relative">Oggi ± giorni</option>
      <option value="date">Data specifica</option>
    </select>
    {value.mode === "date"
      ? <input aria-label={`${label}: data`} type="date" className={textControl} value={value.date} onChange={event => onChange({ ...value, date: event.target.value })} />
      : value.mode === "relative"
        ? <input aria-label={`${label}: giorni`} type="number" step="1" className={textControl} placeholder="es. -3 o 7" value={value.days} onChange={event => onChange({ ...value, days: event.target.value })} />
        : <p className="flex min-h-11 items-center rounded-xl bg-gray-50 px-3 text-sm text-gray-600 dark:bg-gray-800 dark:text-gray-300">Data calcolata in base al fuso orario scelto</p>}
  </div>;
}

export function FilterEditor({ filter, fields, onClose, onSaved }: {
  filter: FilterResponse | null;
  fields: FilterField[];
  onClose: () => void;
  onSaved: (filter: FilterResponse | null, deletedId?: number) => void;
}) {
  const drag = useBottomSheetDrag(onClose);
  const invalidFilter = Boolean(filter && (filter.validation_error || filter.conditions.length === 0));
  const [rebuilding, setRebuilding] = useState(false);
  const [name, setName] = useState(filter?.name ?? "");
  const [description, setDescription] = useState(filter?.description ?? "");
  const [shared, setShared] = useState(filter?.is_shared ?? false);
  const [containerType, setContainerType] = useState<FilterInput["container_type"]>(filter?.container_type ?? null);
  const [matchMode, setMatchMode] = useState<"all" | "any">(filter?.match_mode ?? "all");
  const [rows, setRows] = useState<ConditionDraft[]>(filter?.conditions.length
    ? filter.conditions.map(condition => conditionFromApi(condition, fields))
    : invalidFilter ? [] : [defaultCondition(fields.find(field => field.container_types.length === 2) ?? fields[0])]);
  const [preview, setPreview] = useState<FilterEvaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const usableFields = useMemo(() => fields.filter(field =>
    containerType ? field.container_types.includes(containerType) : field.container_types.length === 2,
  ), [containerType, fields]);

  const selectedFields = rows.map(row => usableFields.find(field => field.source === row.source
    && field.field === row.field && (field.definition_id ?? null) === (row.definition_id ?? null)));

  function chooseField(index: number, field: FilterField) {
    setRows(previous => previous.map((row, rowIndex) => rowIndex === index
      ? defaultCondition(field)
      : row));
  }

  function updateRow(index: number, change: Partial<ConditionDraft>) {
    setRows(previous => previous.map((row, rowIndex) => rowIndex === index ? { ...row, ...change } : row));
  }

  function buildInput(): FilterInput {
    if (invalidFilter && !rebuilding) throw new Error("Ricostruisci esplicitamente il filtro prima di salvarlo.");
    const conditions = rows.map((row, index) => {
      const field = selectedFields[index];
      if (!field) throw new Error("Seleziona un campo disponibile per ogni condizione.");
      if (row.operator === "between") {
        if (field.field_type === "DATE") {
          const validEndpoint = (date: DateDraft) => date.mode === "date" ? !!date.date
            : date.mode === "today" || (date.days.trim() !== "" && Number.isSafeInteger(Number(date.days)));
          if (!validEndpoint(row.range_from) || !validEndpoint(row.range_to)) throw new Error("Completa entrambi gli estremi dell'intervallo.");
        } else if (row.range_from.date === "" || row.range_to.date === "") {
          throw new Error("Completa entrambi gli estremi dell'intervallo.");
        } else if (field.field_type === "NUMBER"
          && (!Number.isFinite(Number(row.range_from.date)) || !Number.isFinite(Number(row.range_to.date))
            || Number(row.range_from.date) > Number(row.range_to.date))) {
          throw new Error("Inserisci un intervallo numerico valido.");
        }
      } else if (row.operator !== "is_null" && row.operator !== "is_not_null") {
        if (field.field_type === "DATE") {
          const date = row.value as DateDraft;
          if (date.mode === "date" && !date.date) throw new Error("Inserisci la data di confronto.");
          if (date.mode === "relative" && (date.days.trim() === "" || !Number.isSafeInteger(Number(date.days)))) throw new Error("Inserisci un numero intero di giorni relativo a oggi.");
        } else if (row.value === "") {
          throw new Error("Inserisci un valore per ogni condizione.");
        } else if (field.field_type === "NUMBER" && !Number.isFinite(Number(row.value))) {
          throw new Error("Inserisci un numero valido.");
        }
      }
      if (field.field_type === "DATE" && row.operator === "between") {
        const from = row.range_from, to = row.range_to;
        if (from.mode === "date" && to.mode === "date" && from.date > to.date) throw new Error("La data iniziale deve precedere quella finale.");
      }
      return serializeCondition(row, field);
    });
    const input: FilterInput = {
      name: name.trim(),
      description: description.trim() || undefined,
      is_shared: shared,
      container_type: containerType,
      match_mode: matchMode,
      conditions,
    };
    validateFilterInput(input);
    return input;
  }

  async function testFilter() {
    setError("");
    setNotice("");
    try {
      const result = await previewFilter({ ...buildInput(), timezone: defaultTimezone });
      setPreview(result);
      setNotice("Anteprima aggiornata.");
    } catch (reason) {
      setError(reason instanceof Error && !isAxiosError(reason) ? reason.message : apiErrorMessage(reason, "Impossibile calcolare l'anteprima."));
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const input = buildInput();
      const saved = filter ? await updateFilter(filter.id, input) : await createFilter(input);
      onSaved(saved);
    } catch (reason) {
      setError(reason instanceof Error && !isAxiosError(reason) ? reason.message : apiErrorMessage(reason, "Salvataggio non riuscito."));
    } finally {
      setBusy(false);
    }
  }

  async function removeFilter() {
    if (!filter) return;
    setBusy(true);
    try {
      await deleteFilter(filter.id);
      onClose();
      onSaved(null, filter.id);
    } catch {
      setError("Eliminazione non riuscita. Il filtro e i trigger collegati non sono stati modificati.");
      setConfirmDelete(false);
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open onClose={onClose} className="relative z-[80]">
    <div className="fixed inset-0 bg-slate-950/45 backdrop-blur-[1px]" aria-hidden="true" />
    <div className="fixed inset-0 flex items-end justify-center md:items-stretch md:justify-end">
      <Dialog.Panel
        style={{ transform: `translateY(${drag.offset}px)`, transition: drag.isDragging ? "none" : "transform 220ms ease-out" }}
        className="flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-3xl bg-white text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white md:h-full md:max-h-none md:max-w-[600px] md:rounded-none md:rounded-l-2xl"
      >
        <button type="button" aria-label="Chiudi o trascina verso il basso" {...drag.gripProps} className="mx-auto mt-3 flex h-11 w-16 shrink-0 touch-none items-center justify-center md:hidden"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" /></button>
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-gray-200 px-5 py-4 dark:border-gray-700 md:px-7">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{filter ? "Filtro salvato" : "Nuovo filtro"}</p>
            <Dialog.Title className="mt-1 truncate text-xl font-bold">{filter?.name || "Definisci un filtro"}</Dialog.Title>
          </div>
          <button type="button" className="grid h-11 w-11 shrink-0 place-items-center rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800" onClick={onClose} aria-label="Chiudi editor"><FiX /></button>
        </header>
        <form onSubmit={save} className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 md:p-7">
            {error && <p role="alert" className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">{error}</p>}
            {notice && <p role="status" className="rounded-xl bg-blue-50 p-3 text-sm text-blue-800 dark:bg-blue-950 dark:text-blue-200">{notice}</p>}
            {invalidFilter && <div className="space-y-2 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100">
              <p role="alert">{filter?.validation_error || "Questo filtro legacy non contiene condizioni valide e non può essere valutato."}</p>
              <p>{rebuilding ? "Ricostruzione avviata. Il salvataggio sostituirà le condizioni originali." : "Il filtro originale rimane invariato. Puoi eliminarlo oppure avviare una ricostruzione esplicita."}</p>
              {!rebuilding && filter?.can_manage && <button type="button" className={button} onClick={() => {
                setRebuilding(true);
                setRows([defaultCondition(usableFields[0])]);
              }}>Ricostruisci filtro</button>}
            </div>}
            <fieldset disabled={(invalidFilter && !rebuilding) || (filter !== null && !filter.can_manage)} className="min-w-0 space-y-5 disabled:opacity-60">
            <label className="block text-sm font-semibold">Nome del filtro<input autoFocus className={textControl} value={name} onChange={event => setName(event.target.value)} maxLength={120} required placeholder="Es. Scorte da riordinare" /></label>
            <label className="block text-sm font-semibold">Descrizione (facoltativa)<input className={textControl} value={description} onChange={event => setDescription(event.target.value)} maxLength={500} /></label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm font-semibold">Tipo contenitore<select className={textControl} value={containerType ?? "ALL"} onChange={event => {
                const next = event.target.value === "ALL" ? null : event.target.value as FilterInput["container_type"];
                setContainerType(next);
                setNotice("Tipo aggiornato. Le condizioni non compatibili sono state azzerate: verifica i campi e i valori prima di salvare.");
                setRows(previous => previous.map(row => {
                  const compatible = fields.find(field => field.source === row.source && field.field === row.field && (field.definition_id ?? null) === (row.definition_id ?? null)
                    && (next ? field.container_types.includes(next) : field.container_types.length === 2));
                  return compatible ? row : defaultCondition(fields.find(field => next ? field.container_types.includes(next) : field.container_types.length === 2));
                }));
              }}><option value="ALL">Inventari e liste</option><option value="INVENTORY">Inventari</option><option value="CHECKLIST">Liste</option></select></label>
              <label className="block text-sm font-semibold">Visibilità<select className={textControl} value={shared ? "shared" : "private"} onChange={event => setShared(event.target.value === "shared")}><option value="private">Privato</option><option value="shared">Condiviso</option></select></label>
            </div>
            <section className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-bold">Condizioni</h3>
                <div className="flex rounded-xl bg-gray-100 p-1 dark:bg-gray-800" role="group" aria-label="Logica condizioni">
                  {(["all", "any"] as const).map(mode => <button key={mode} type="button" aria-pressed={matchMode === mode} onClick={() => setMatchMode(mode)} className={`min-h-11 rounded-lg px-3 text-xs ${matchMode === mode ? "bg-white font-semibold shadow dark:bg-gray-700" : ""}`}>{mode === "all" ? "Tutte (E)" : "Almeno una (O)"}</button>)}
                </div>
              </div>
              <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">Le condizioni combinano campi item e metadati in un’unica valutazione.</p>
              <p className="mb-2 text-xs text-gray-500 dark:text-gray-400">Quantità è disponibile solo per gli inventari; Completato e Priorità solo per le liste. “Inventari e liste” mostra soltanto i campi compatibili con entrambi.</p>
              <div className="space-y-3">
                {rows.map((row, index) => {
                  const field = selectedFields[index];
                  const operators = field?.operators ?? [];
                  const isNullOp = row.operator === "is_null" || row.operator === "is_not_null";
                  const selectField = (event: React.ChangeEvent<HTMLSelectElement>) => {
                    const selected = usableFields[Number(event.target.value)];
                    if (selected) chooseField(index, selected);
                  };
                  const dateValue = row.value as DateDraft;
                  return <div key={index} className="relative rounded-xl border border-gray-200 bg-gray-50/70 p-3 dark:border-gray-700 dark:bg-gray-800/50">
                    <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,.8fr)_44px]">
                      <label className="block min-w-0 text-xs font-semibold text-gray-600 dark:text-gray-300">Campo · {field?.source === "metadata" ? "Metadato" : "Item"}
                        <select aria-label="Campo della condizione" className={textControl} value={field ? usableFields.indexOf(field) : ""} onChange={selectField} disabled={!usableFields.length}>
                            {!usableFields.length && <option value="">Nessun campo disponibile</option>}
                          <optgroup label="Campi item">{usableFields.map((candidate, candidateIndex) => candidate.source === "item" ? <option key={`${candidate.source}:${candidate.field}`} value={candidateIndex}>{candidate.label}</option> : null)}</optgroup>
                          <optgroup label="Metadati">{usableFields.map((candidate, candidateIndex) => candidate.source === "metadata" ? <option key={`${candidate.source}:${candidate.definition_id}`} value={candidateIndex}>{candidate.label}</option> : null)}</optgroup>
                        </select>
                      </label>
                      <label className="block min-w-0 text-xs font-semibold text-gray-600 dark:text-gray-300">Operatore<select aria-label="Operatore" className={textControl} value={row.operator} onChange={event => updateRow(index, { operator: event.target.value as FilterOperator })}>
                        {operators.map(operator => <option key={operator} value={operator}>{operatorLabel(operator)}</option>)}
                      </select></label>
                      <button type="button" disabled={rows.length <= 1} aria-label="Rimuovi condizione" title="Rimuovi condizione" onClick={() => setRows(previous => previous.filter((_, rowIndex) => rowIndex !== index))} className="mt-5 grid h-11 w-11 place-items-center rounded-xl text-gray-500 hover:bg-gray-200 disabled:opacity-40 dark:hover:bg-gray-700"><FiX /></button>
                    </div>
                    {!isNullOp && field && row.operator === "between" && <div className="mt-3 grid gap-3">
                      {field.field_type === "DATE"
                        ? <>
                          <label className="block text-xs font-semibold">Da {dateControl(row.range_from, value => updateRow(index, { range_from: value }), "Data iniziale")}</label>
                          <label className="block text-xs font-semibold">A {dateControl(row.range_to, value => updateRow(index, { range_to: value }), "Data finale")}</label>
                        </>
                        : <div className="grid gap-3 sm:grid-cols-2">
                          <label className="text-xs font-semibold">Da<input type="number" className={textControl} value={row.range_from.date} onChange={event => updateRow(index, { range_from: { ...row.range_from, date: event.target.value } })} /></label>
                          <label className="text-xs font-semibold">A<input type="number" className={textControl} value={row.range_to.date} onChange={event => updateRow(index, { range_to: { ...row.range_to, date: event.target.value } })} /></label>
                        </div>}
                    </div>}
                    {!isNullOp && field && row.operator !== "between" && <label className="mt-3 block text-xs font-semibold text-gray-600 dark:text-gray-300">Valore
                      {field.field_type === "DATE"
                        ? dateControl(dateValue, value => updateRow(index, { value }), "Data di confronto")
                        : field.field_type === "BOOLEAN"
                          ? <select className={textControl} value={String(row.value)} onChange={event => updateRow(index, { value: event.target.value === "true" })}><option value="false">No</option><option value="true">Sì</option></select>
                          : field.field_type === "LIST"
                            ? <select className={textControl} value={String(row.value)} onChange={event => updateRow(index, { value: event.target.value })}><option value="">Seleziona…</option>{field.list_options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
                            : <input type={field.field_type === "NUMBER" ? "number" : "text"} step={field.field_type === "NUMBER" ? "any" : undefined} className={textControl} value={String(row.value)} onChange={event => updateRow(index, { value: event.target.value })} />}
                    </label>}
                  </div>;
                })}
              </div>
              <button type="button" onClick={() => setRows(previous => [...previous, defaultCondition(usableFields[0])])} disabled={!usableFields.length} className={`${button} mt-3 w-full border-dashed`}><FiPlus /> Aggiungi condizione</button>
            </section>
            <section className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div><h3 className="font-bold">{filter ? "Ambito del filtro salvato" : "Ambito calcolato"}</h3><p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{filter?.scope_preview.summary ?? "L’ambito disponibile verrà calcolato dal server."}</p></div>
                <span className="rounded-lg bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-800 dark:bg-blue-950 dark:text-blue-200">{filter?.scope_preview.inventories.length ?? "—"} contenitori</span>
              </div>
              {filter?.trigger_count ? <p className="mt-2 text-xs text-gray-600 dark:text-gray-300">{filter.trigger_count} trigger associati</p> : null}
            </section>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-bold">Anteprima risultati</h3>
              <button type="button" disabled={busy} onClick={() => void testFilter()} className={button}><FiPlay /> Prova filtro</button>
            </div>
            {preview && <section aria-live="polite" className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
              <p className="font-semibold">{preview.total_count} risultati in {preview.containers.length} contenitori</p>
              {preview.containers.length === 0 ? <p className="mt-2 text-sm text-gray-500">Nessun risultato.</p> : <ul className="mt-2 divide-y divide-gray-200 dark:divide-gray-700">{preview.containers.map(container => <li key={`${container.type}-${container.id}`} className="flex justify-between gap-3 py-2 text-sm"><span>{container.name}</span><b>{container.count} righe</b></li>)}</ul>}
            </section>}
            <p className="flex gap-2 rounded-xl bg-blue-50 p-3 text-xs leading-5 text-blue-900 dark:bg-blue-950 dark:text-blue-100"><FiInfo className="mt-0.5 shrink-0" /> I filtri non inviano notifiche. Per una valutazione automatica crea un trigger collegato.</p>
            </fieldset>
          </div>
          <footer className="flex shrink-0 items-center gap-2 border-t border-gray-200 bg-white px-4 py-3 pb-[calc(env(safe-area-inset-bottom)+.75rem)] dark:border-gray-700 dark:bg-gray-900 md:px-7">
            {filter?.can_manage && <button type="button" disabled={busy} onClick={() => setConfirmDelete(true)} className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-red-700 hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-950" aria-label="Elimina filtro"><FiTrash2 /></button>}
            <span className="mr-auto hidden text-xs text-gray-500 md:block">La ricerca applica una valutazione unica lato server.</span>
            <button type="button" disabled={busy} className={button} onClick={onClose}>Annulla</button>
            <button type="submit" disabled={busy || (filter !== null && !filter.can_manage) || (invalidFilter && !rebuilding)} className={primary}>{busy ? "Salvataggio…" : "Salva filtro"}</button>
          </footer>
        </form>
        {confirmDelete && <div className="absolute inset-0 z-10 grid place-items-center bg-black/40 p-4" role="alertdialog" aria-modal="true" aria-labelledby="delete-filter-title">
          <div className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl dark:bg-gray-800">
            <h3 id="delete-filter-title" className="font-bold">Eliminare questo filtro?</h3>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">I trigger collegati resteranno salvati ma non potranno più valutare questo filtro.</p>
            <div className="mt-4 flex justify-end gap-2"><button type="button" className={button} onClick={() => setConfirmDelete(false)}>Annulla</button><button type="button" className="min-h-11 rounded-xl bg-red-600 px-4 font-semibold text-white" disabled={busy} onClick={() => void removeFilter()}>Elimina</button></div>
          </div>
        </div>}
      </Dialog.Panel>
    </div>
  </Dialog>;
}

function operatorLabel(operator: FilterOperator): string {
  const labels: Record<FilterOperator, string> = {
    equals: "Uguale a", not_equals: "Diverso da", contains: "Contiene", not_contains: "Non contiene",
    gt: "Maggiore di", gte: "Maggiore o uguale", lt: "Minore di", lte: "Minore o uguale",
    between: "Tra", is_null: "Non impostato", is_not_null: "Impostato",
  };
  return labels[operator];
}

export function TriggerEditor({ trigger, filters, defaultFilterId, onClose, onSaved }: {
  trigger: TriggerResponse | null;
  filters: FilterResponse[];
  defaultFilterId?: number;
  onClose: () => void;
  onSaved: (trigger: TriggerResponse | null, deletedId?: number) => void;
}) {
  const drag = useBottomSheetDrag(onClose);
  const [name, setName] = useState(trigger?.name ?? "");
  const [filterId, setFilterId] = useState<number | "">(trigger?.filter_id ?? defaultFilterId ?? "");
  const [enabled, setEnabled] = useState(trigger?.enabled ?? true);
  const [time, setTime] = useState(trigger?.time ?? "08:00");
  const [timezone, setTimezone] = useState(trigger?.timezone ?? defaultTimezone);
  const [weekdays, setWeekdays] = useState<number[]>(trigger?.weekdays ?? [1, 2, 3, 4, 5, 6, 7]);
  const [scopeAll, setScopeAll] = useState(trigger?.inventory_ids == null);
  const [inventoryIds, setInventoryIds] = useState<number[]>(trigger?.inventory_ids ?? []);
  const [notifyMode, setNotifyMode] = useState<TriggerInput["notify_mode"]>(trigger?.notify_mode ?? "always");
  const [preview, setPreview] = useState<FilterEvaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedFilter = filters.find(filter => filter.id === filterId);
  const availableContainers = selectedFilter?.scope_preview.inventories ?? [];

  function buildInput(): TriggerInput {
    if (!name.trim()) throw new Error("Inserisci il nome del trigger.");
    if (filterId === "") throw new Error("Seleziona un filtro salvato.");
    if (!weekdays.length) throw new Error("Seleziona almeno un giorno della settimana.");
    if (!scopeAll && !inventoryIds.length) throw new Error("Seleziona almeno un contenitore o scegli tutti.");
    if (selectedFilter && !selectedFilter.can_manage) throw new Error("Non puoi collegare un filtro che non puoi gestire.");
    if (selectedFilter && (selectedFilter.validation_error || !selectedFilter.conditions.length)) throw new Error("Il filtro collegato non contiene condizioni valide.");
    return {
      name: name.trim(), filter_id: filterId, enabled, time, timezone, weekdays: [...weekdays].sort((a, b) => a - b),
      inventory_ids: scopeAll ? null : inventoryIds, notify_mode: notifyMode,
    };
  }

  async function testTrigger() {
    if (!trigger) {
      setError("Salva il trigger prima di provare l’anteprima.");
      return;
    }
    setBusy(true);
    setError("");
    try { setPreview(await previewTrigger(trigger.id)); }
    catch (reason) { setError(apiErrorMessage(reason, "Anteprima non disponibile. Verifica accesso al filtro e riprova.")); }
    finally { setBusy(false); }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const input = buildInput();
      onSaved(trigger ? await updateTrigger(trigger.id, input) : await createTrigger(input));
    } catch (reason) {
      setError(reason instanceof Error && !isAxiosError(reason) ? reason.message : apiErrorMessage(reason, "Salvataggio non riuscito."));
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!trigger) return;
    setBusy(true);
    setError("");
    try { await deleteTrigger(trigger.id); onClose(); onSaved(null, trigger.id); }
    catch { setError("Eliminazione non riuscita. Il trigger è rimasto invariato."); }
    finally { setBusy(false); }
  }

  return <Dialog open onClose={onClose} className="relative z-[80]">
    <div className="fixed inset-0 bg-slate-950/45 backdrop-blur-[1px]" aria-hidden="true" />
    <div className="fixed inset-0 flex items-end justify-center md:items-stretch md:justify-end">
      <Dialog.Panel style={{ transform: `translateY(${drag.offset}px)`, transition: drag.isDragging ? "none" : "transform 220ms ease-out" }} className="flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-3xl bg-white text-gray-900 shadow-2xl dark:bg-gray-900 dark:text-white md:h-full md:max-h-none md:max-w-[600px] md:rounded-none md:rounded-l-2xl">
        <button type="button" aria-label="Chiudi o trascina verso il basso" {...drag.gripProps} className="mx-auto mt-3 flex h-11 w-16 shrink-0 touch-none items-center justify-center md:hidden"><span className="h-1 w-10 rounded-full bg-gray-300 dark:bg-gray-600" /></button>
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-gray-200 px-5 py-4 dark:border-gray-700 md:px-7">
          <div><p className="text-xs font-semibold uppercase tracking-wider text-gray-500">{trigger ? "Pianificazione salvata" : "Nuovo trigger"}</p><Dialog.Title className="mt-1 text-xl font-bold">{trigger?.name || "Definisci un trigger"}</Dialog.Title></div>
          <button type="button" className="grid h-11 w-11 place-items-center rounded-xl hover:bg-gray-100 dark:hover:bg-gray-800" onClick={onClose} aria-label="Chiudi editor"><FiX /></button>
        </header>
        <form onSubmit={save} className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5 md:p-7">
            {error && <p role="alert" className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200">{error}</p>}
            <label className="block text-sm font-semibold">Nome del trigger<input autoFocus className={textControl} value={name} onChange={event => setName(event.target.value)} maxLength={120} required placeholder="Es. Controllo scadenze" /></label>
            <label className="block text-sm font-semibold">Filtro collegato<select className={textControl} value={filterId} onChange={event => { setFilterId(event.target.value ? Number(event.target.value) : ""); setInventoryIds([]); setScopeAll(true); }} required>
              <option value="">Seleziona un filtro…</option>{filters.map(filter => <option key={filter.id} value={filter.id} disabled={!filter.can_manage || Boolean(filter.validation_error) || !filter.conditions.length}>{filter.name}{filter.validation_error || !filter.conditions.length ? " (non valido)" : filter.can_manage ? "" : " (sola lettura)"}</option>)}
            </select></label>
            {selectedFilter && <div className="rounded-xl bg-blue-50 p-3 text-sm text-blue-900 dark:bg-blue-950 dark:text-blue-100"><FiFilter className="mr-2 inline" />{selectedFilter.scope_preview.summary}</div>}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm font-semibold">Orario<input type="time" className={textControl} value={time} onChange={event => setTime(event.target.value)} required /></label>
              <label className="block text-sm font-semibold">Fuso orario<select className={textControl} value={timezone} onChange={event => setTimezone(event.target.value)}>
                {[...new Set([timezone, defaultTimezone, "Europe/Rome", "UTC", "Europe/London", "America/New_York"])].map(zone => <option key={zone}>{zone}</option>)}
              </select></label>
            </div>
            <fieldset>
              <legend className="mb-2 text-sm font-semibold">Giorni di esecuzione</legend>
              <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">{FILTER_WEEKDAYS.map(day => <button key={day.value} type="button" data-weekday={day.value} aria-label={`${day.label}, giorno ${day.value}`} aria-pressed={weekdays.includes(day.value)} onClick={() => setWeekdays(previous => previous.includes(day.value) ? previous.filter(value => value !== day.value) : [...previous, day.value])} className={`min-h-11 rounded-xl border text-sm ${weekdays.includes(day.value) ? "border-blue-600 bg-blue-50 font-semibold text-blue-800 dark:bg-blue-950 dark:text-blue-100" : "border-gray-300 dark:border-gray-600"}`}>{day.label}</button>)}</div>
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-sm font-semibold">Ambito</legend>
              <label className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-gray-200 px-3 dark:border-gray-700"><input type="radio" checked={scopeAll} onChange={() => setScopeAll(true)} />Tutti i contenitori compatibili del filtro</label>
              <label className="mt-2 flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-gray-200 px-3 dark:border-gray-700"><input type="radio" checked={!scopeAll} onChange={() => setScopeAll(false)} disabled={!availableContainers.length} />Solo contenitori selezionati</label>
              {!scopeAll && <div className="mt-2 max-h-44 space-y-1 overflow-y-auto rounded-xl border border-gray-200 p-2 dark:border-gray-700">
                {availableContainers.map(container => <label key={container.id} className="flex min-h-11 items-center gap-3 px-2 text-sm"><input type="checkbox" checked={inventoryIds.includes(container.id)} onChange={event => setInventoryIds(previous => event.target.checked ? [...previous, container.id] : previous.filter(id => id !== container.id))} /><span className="flex min-w-0 items-center gap-2">{container.type === "CHECKLIST" ? <FiCheckSquare /> : <FiBox />}{container.name}</span></label>)}
                {!availableContainers.length && <p className="p-2 text-sm text-gray-500">Il filtro non ha contenitori selezionabili.</p>}
              </div>}
            </fieldset>
            <fieldset>
              <legend className="mb-2 text-sm font-semibold">Quando inviare</legend>
              <label className="flex cursor-pointer gap-3 rounded-xl border border-gray-200 p-3 dark:border-gray-700"><input type="radio" checked={notifyMode === "always"} onChange={() => setNotifyMode("always")} /><span><b className="block text-sm">Ogni esecuzione con risultati</b><span className="text-xs text-gray-600 dark:text-gray-300">Invia un avviso ogni volta che il filtro trova corrispondenze.</span></span></label>
              <label className="mt-2 flex cursor-pointer gap-3 rounded-xl border border-gray-200 p-3 dark:border-gray-700"><input type="radio" checked={notifyMode === "changed"} onChange={() => setNotifyMode("changed")} /><span><b className="block text-sm">Solo se i risultati cambiano</b><span className="text-xs text-gray-600 dark:text-gray-300">Riduce gli avvisi ripetuti quando l’elenco non varia.</span></span></label>
            </fieldset>
            <label className="flex min-h-12 items-center justify-between gap-3 rounded-xl border border-gray-200 px-3 dark:border-gray-700"><span className="text-sm font-semibold">{enabled ? "Trigger attivo" : "Trigger in pausa"}</span><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} className="h-5 w-5 accent-blue-600" /></label>
            {trigger && <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-semibold">Anteprima trigger salvato · {formatWeekdays(trigger.weekdays)} · {trigger.timezone}</span><button type="button" disabled={busy} onClick={() => void testTrigger()} className={button}><FiPlay /> Prova</button><p className="w-full text-xs text-gray-500">Salva le modifiche per provarle. L’anteprima usa la pianificazione e l’ambito già salvati.</p></div>}
            {preview && <section aria-live="polite" className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700"><p className="font-semibold">{preview.total_count} risultati in {preview.containers.length} contenitori</p>{preview.containers.map(container => <p key={container.id} className="mt-2 flex justify-between text-sm"><span>{container.name}</span><b>{container.count} righe</b></p>)}</section>}
            <p className="flex gap-2 rounded-xl bg-blue-50 p-3 text-xs leading-5 text-blue-900 dark:bg-blue-950 dark:text-blue-100"><FiBell className="mt-0.5 shrink-0" /> Nessun messaggio viene inviato durante l’anteprima. Gli avvisi effettivi rispettano iscrizioni, preferenze e accessi.</p>
            {trigger?.last_error && <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">Ultima esecuzione: {trigger.last_error}</p>}
          </div>
          <footer className="flex shrink-0 items-center gap-2 border-t border-gray-200 bg-white px-4 py-3 pb-[calc(env(safe-area-inset-bottom)+.75rem)] dark:border-gray-700 dark:bg-gray-900 md:px-7">
            {trigger?.can_manage && <button type="button" disabled={busy} onClick={() => { if (window.confirm("Eliminare questo trigger?")) void remove(); }} className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-red-700 hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-950" aria-label="Elimina trigger"><FiTrash2 /></button>}
            {trigger && !trigger.can_manage && <span className="mr-auto hidden text-xs text-gray-500 md:block">Sola lettura</span>}
            {(!trigger || trigger.can_manage) && <span className="mr-auto hidden text-xs text-gray-500 md:block">Prossima esecuzione: {trigger?.next_run_at ? new Date(trigger.next_run_at).toLocaleString() : "dopo il salvataggio"}</span>}
            <button type="button" className={button} onClick={onClose}>Annulla</button><button type="submit" disabled={busy || (trigger !== null && !trigger.can_manage)} className={primary}>{busy ? "Salvataggio…" : "Salva trigger"}</button>
          </footer>
        </form>
      </Dialog.Panel>
    </div>
  </Dialog>;
}

export default function FilterManagementPage() {
  const location = useLocation();
  const { user } = useAuth();
  const section: Section = location.pathname === "/triggers" ? "triggers" : "filters";
  const [filters, setFilters] = useState<FilterResponse[]>([]);
  const [triggers, setTriggers] = useState<TriggerResponse[]>([]);
  const [fields, setFields] = useState<FilterField[]>([]);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editFilter, setEditFilter] = useState<FilterResponse | null | undefined>();
  const [editTrigger, setEditTrigger] = useState<TriggerResponse | null | undefined>();
  const [newTriggerFilterId, setNewTriggerFilterId] = useState<number | undefined>();
  const canManage = Boolean(user?.role?.name && user.role.name !== "viewer");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextFilters, nextFields, nextTriggers] = await Promise.all([getFilters(), getFilterFields(), getTriggers()]);
      setFilters(nextFilters);
      setFields(nextFields);
      setTriggers(nextTriggers);
    } catch {
      setError("Impossibile caricare filtri e trigger. Verifica l’accesso e riprova.");
    } finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  const matchingFilters = useMemo(() => filters.filter(filter => {
    const matchesText = `${filter.name} ${filter.description ?? ""} ${filter.scope_preview.summary}`.toLocaleLowerCase("it").includes(query.toLocaleLowerCase("it"));
    const matchesScope = scope === "all" || (scope === "INVENTORY"
      ? filter.container_type === "INVENTORY" || (filter.container_type === null && filter.scope_preview.inventories.some(item => item.type === "INVENTORY"))
      : filter.container_type === "CHECKLIST" || (filter.container_type === null && filter.scope_preview.inventories.some(item => item.type === "CHECKLIST")));
    return matchesText && matchesScope;
  }), [filters, query, scope]);
  const matchingTriggers = useMemo(() => triggers.filter(trigger => {
    const matchesText = `${trigger.name} ${trigger.filter_name}`.toLocaleLowerCase("it").includes(query.toLocaleLowerCase("it"));
    const matchesScope = scope === "all" || (scope === "active" ? trigger.enabled : !trigger.enabled);
    return matchesText && matchesScope;
  }), [triggers, query, scope]);

  async function openFilter(filterId: number) {
    try { setEditFilter(await getFilter(filterId)); }
    catch { setError("Impossibile aprire il filtro: i permessi potrebbero essere cambiati."); }
  }
  async function openTrigger(triggerId: number) {
    try { setEditTrigger(await getTrigger(triggerId)); }
    catch { setError("Impossibile aprire il trigger: i permessi potrebbero essere cambiati."); }
  }
  function onFilterSaved(saved: FilterResponse | null, deletedId?: number) {
    if (saved) setFilters(previous => [saved, ...previous.filter(filter => filter.id !== saved.id)]);
    else if (deletedId) setFilters(previous => previous.filter(filter => filter.id !== deletedId));
    setEditFilter(undefined);
    setNotice(saved ? "Filtro salvato." : "Filtro eliminato.");
    if (!saved) void load();
  }
  function onTriggerSaved(saved: TriggerResponse | null, deletedId?: number) {
    if (saved) setTriggers(previous => [saved, ...previous.filter(trigger => trigger.id !== saved.id)]);
    else if (deletedId) setTriggers(previous => previous.filter(trigger => trigger.id !== deletedId));
    setEditTrigger(undefined);
    setNotice(saved ? "Trigger salvato." : "Trigger eliminato.");
    void load();
  }

  const title = section === "filters" ? "Gestione filtri" : "Gestione trigger";
  return <main className="mx-auto max-w-6xl space-y-5 px-1 pb-5 md:px-2" aria-busy={loading}>
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="mb-1 text-xs font-semibold uppercase tracking-wider text-gray-500">Organizzazione</p><h1 className="text-2xl font-bold md:text-3xl">{title}</h1><p className="mt-2 max-w-2xl text-sm text-gray-600 dark:text-gray-300">{section === "filters" ? "Combina campi degli elementi e metadati in un’unica ricerca riutilizzabile." : "Pianifica i filtri per ricevere avvisi solo nei giorni e negli ambiti scelti."}</p></div>
      {canManage && <button type="button" className={primary} onClick={() => {
        if (section === "filters") setEditFilter(null);
        else { setNewTriggerFilterId(undefined); setEditTrigger(null); }
      }}><FiPlus />{section === "filters" ? "Nuovo filtro" : "Nuovo trigger"}</button>}
    </header>
    <nav aria-label="Organizzazione" className="flex w-fit max-w-full rounded-xl bg-gray-100 p-1 dark:bg-gray-800">
      <Link aria-current={section === "filters" ? "page" : undefined} to="/filters" className={`flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm ${section === "filters" ? "bg-white font-semibold shadow dark:bg-gray-700" : "text-gray-600 dark:text-gray-300"}`}><FiFilter />Filtri <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-600">{filters.length}</span></Link>
      <Link aria-current={section === "triggers" ? "page" : undefined} to="/triggers" className={`flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm ${section === "triggers" ? "bg-white font-semibold shadow dark:bg-gray-700" : "text-gray-600 dark:text-gray-300"}`}><FiClock />Trigger <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs dark:bg-gray-600">{triggers.length}</span></Link>
    </nav>
    <div className="flex flex-wrap gap-2">
      <label className="relative min-w-[min(100%,16rem)] flex-1"><span className="sr-only">Cerca {section === "filters" ? "filtri" : "trigger"}</span><FiSearch aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={section === "filters" ? "Cerca un filtro…" : "Cerca un trigger…"} className={`${textControl} mt-0 pl-10`} /></label>
      <label><span className="sr-only">Restringi elenco</span><select value={scope} onChange={event => setScope(event.target.value)} className={`${textControl} mt-0 w-44`}>{section === "filters" ? <><option value="all">Tutti i contenitori</option><option value="INVENTORY">Inventari</option><option value="CHECKLIST">Liste</option></> : <><option value="all">Tutti gli stati</option><option value="active">Attivi</option><option value="paused">In pausa</option></>}</select></label>
    </div>
    {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"><span>{error}</span><button type="button" className={button} onClick={() => void load()}>Riprova</button></div>}
    {notice && <p role="status" className="rounded-xl bg-green-50 p-3 text-sm text-green-800 dark:bg-green-950 dark:text-green-200">{notice}</p>}
    <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
      <div className={`hidden gap-4 border-b border-gray-200 bg-gray-50 px-5 py-3 text-xs font-semibold text-gray-500 dark:border-gray-700 dark:bg-gray-800 xl:grid ${section === "filters" ? "grid-cols-[minmax(0,1fr)_180px_170px_52px]" : "grid-cols-[minmax(0,1fr)_170px_170px_105px]"}`}>
        <span>{section === "filters" ? "Filtro / condizioni" : "Trigger / filtro"}</span><span>{section === "filters" ? "Applicabile a" : "Pianificazione"}</span><span>{section === "filters" ? "Trigger associati" : "Ultimo controllo"}</span><span>{section === "filters" ? "" : "Stato"}</span>
      </div>
      {loading && <p role="status" className="p-6 text-center text-sm text-gray-500">Caricamento…</p>}
      {!loading && section === "filters" && (matchingFilters.length ? matchingFilters.map(filter => <article key={filter.id} className="grid gap-3 border-b border-gray-200 p-4 last:border-0 dark:border-gray-700 xl:grid-cols-[minmax(0,1fr)_180px_170px_52px] xl:items-center xl:gap-4 xl:px-5">
        <div className="min-w-0"><button type="button" onClick={() => void openFilter(filter.id)} className="min-h-11 max-w-full break-words text-left font-semibold text-blue-700 hover:underline dark:text-blue-300">{filter.name}</button><p className="break-words text-sm text-gray-600 dark:text-gray-300">{filter.description || summarizeConditions(filter.conditions, fields)}</p><div className="mt-2 flex flex-wrap gap-1.5"><span className="rounded-md bg-gray-100 px-2 py-1 text-xs dark:bg-gray-800">{filter.conditions.length} {filter.conditions.length === 1 ? "condizione" : "condizioni"} · {filter.match_mode === "all" ? "Tutte" : "Almeno una"}</span><span className={`rounded-md px-2 py-1 text-xs ${filter.is_shared ? "bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-100" : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"}`}>{filter.is_shared ? "Condiviso" : "Privato"}</span></div></div>
        <div className="space-y-2"><p className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300"><FiBox aria-hidden="true" className="shrink-0" />{filter.scope_preview.summary}</p>{filter.validation_error && <p role="alert" className="break-words text-sm text-amber-800 dark:text-amber-200">Filtro non valido: {filter.validation_error}</p>}</div>
        <div className="flex flex-wrap items-center gap-1 text-sm">{filter.trigger_count ? <span>{filter.trigger_count} trigger associati</span> : <span className="text-gray-500">Nessun trigger</span>}{canManage && !filter.validation_error && filter.conditions.length > 0 && <button type="button" onClick={() => { setNewTriggerFilterId(filter.id); setEditTrigger(null); }} className="min-h-11 rounded-lg px-2 text-blue-700 hover:bg-blue-50 dark:text-blue-300 dark:hover:bg-blue-950">+ Associa</button>}</div>
        <button type="button" onClick={() => void openFilter(filter.id)} disabled={!filter.can_manage} className={`${button} justify-self-end`} aria-label={`Modifica filtro ${filter.name}`} title={filter.can_manage ? "Modifica filtro" : "Sola lettura"}><FiInfo /></button>
      </article>) : <p className="p-8 text-center text-sm text-gray-500">Nessun filtro corrispondente.</p>)}
      {!loading && section === "triggers" && (matchingTriggers.length ? matchingTriggers.map(trigger => <article key={trigger.id} className="grid gap-3 border-b border-gray-200 p-4 last:border-0 dark:border-gray-700 xl:grid-cols-[minmax(0,1fr)_170px_170px_105px] xl:items-center xl:gap-4 xl:px-5">
        <div className="min-w-0"><button type="button" disabled={!trigger.can_manage} onClick={() => void openTrigger(trigger.id)} className="min-h-11 max-w-full break-words text-left font-semibold text-blue-700 hover:underline disabled:cursor-default disabled:no-underline dark:text-blue-300">{trigger.name}</button><p className="text-sm text-gray-600 dark:text-gray-300"><FiFilter className="mr-1 inline" />{trigger.filter_name}</p><div className="mt-2 flex flex-wrap gap-1.5"><span className={`rounded-md px-2 py-1 text-xs ${trigger.enabled ? "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-200" : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"}`}>{trigger.enabled ? "Attivo" : "In pausa"}</span><span className="rounded-md bg-gray-100 px-2 py-1 text-xs dark:bg-gray-800">Temporale</span></div></div>
        <div><p className="font-semibold">{trigger.time}</p><p className="text-xs text-gray-500">{formatWeekdays(trigger.weekdays)} · {trigger.timezone}</p></div>
        <div className="text-xs text-gray-600 dark:text-gray-300">{trigger.last_error ? <span className="text-red-700 dark:text-red-300">{trigger.last_error}</span> : trigger.last_run_at ? <><p>{new Date(trigger.last_run_at).toLocaleString()}</p><b>{trigger.last_container_count ?? 0} contenitori · {trigger.last_result_count ?? 0} righe</b></> : "Nessuna esecuzione"}</div>
        <div className="flex items-center justify-end gap-1"><button type="button" role="switch" aria-checked={trigger.enabled} disabled={!trigger.can_manage} aria-label={`${trigger.enabled ? "Disattiva" : "Attiva"} ${trigger.name}`} onClick={async () => {
          try { const updated = await updateTrigger(trigger.id, { name: trigger.name, filter_id: trigger.filter_id, enabled: !trigger.enabled, time: trigger.time, timezone: trigger.timezone, weekdays: trigger.weekdays, inventory_ids: trigger.inventory_ids, notify_mode: trigger.notify_mode }); setTriggers(previous => previous.map(row => row.id === updated.id ? updated : row)); setNotice(updated.enabled ? "Trigger attivato." : "Trigger messo in pausa."); }
          catch { setError("Impossibile cambiare lo stato del trigger."); }
        }} className={`relative h-11 w-14 rounded-full transition-colors ${trigger.enabled ? "bg-blue-600" : "bg-gray-300 dark:bg-gray-600"}`}><span className={`absolute top-[14px] h-5 w-5 rounded-full bg-white shadow transition-transform ${trigger.enabled ? "left-[30px]" : "left-1.5"}`} /></button><button type="button" disabled={!trigger.can_manage} onClick={() => void openTrigger(trigger.id)} className="grid h-11 w-11 place-items-center rounded-xl hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-gray-800" aria-label={`Modifica trigger ${trigger.name}`}>⋯</button></div>
      </article>) : <p className="p-8 text-center text-sm text-gray-500">Nessun trigger corrispondente.</p>)}
    </section>
    <p className="flex gap-2 rounded-xl bg-blue-50 p-3 text-xs leading-5 text-blue-900 dark:bg-blue-950 dark:text-blue-100"><FiInfo className="mt-0.5 shrink-0" /> I filtri salvati sono applicabili nella ricerca di inventari e liste. I trigger inviano avvisi solo agli utenti iscritti che hanno accesso al filtro e ai contenitori.</p>
    {editFilter !== undefined && <FilterEditor filter={editFilter} fields={fields} onClose={() => setEditFilter(undefined)} onSaved={onFilterSaved} />}
    {editTrigger !== undefined && <TriggerEditor trigger={editTrigger} filters={filters} defaultFilterId={newTriggerFilterId} onClose={() => { setEditTrigger(undefined); setNewTriggerFilterId(undefined); }} onSaved={onTriggerSaved} />}
  </main>;
}

function summarizeConditions(conditions: FilterCondition[], fields: FilterField[]): string {
  if (!conditions.length) return "Filtro legacy non valido: aggiorna le condizioni.";
  return conditions.map(condition => {
    const field = fields.find(item => item.field === condition.field && item.source === condition.source && item.definition_id === condition.definition_id);
    const value = condition.operator === "is_null" ? "non impostato"
      : condition.operator === "is_not_null" ? "impostato"
        : condition.operator === "between"
          ? `${formatValue(condition.range_from)} – ${formatValue(condition.range_to)}`
          : formatValue(condition.value);
    return `${field?.label ?? condition.field} ${operatorLabel(condition.operator).toLowerCase()} ${value}`.trim();
  }).join(conditions.length > 1 ? " · " : "");
}

function formatValue(value: FilterValue | undefined): string {
  if (value == null) return "";
  if (typeof value === "object" && "relative_days" in value) {
    const days = value.relative_days;
    return days === 0 ? "Oggi" : `Oggi ${days > 0 ? "+" : "−"} ${Math.abs(days)} giorni`;
  }
  if (typeof value === "boolean") return value ? "Sì" : "No";
  return String(value);
}
