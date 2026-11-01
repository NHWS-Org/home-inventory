import React, { ReactNode } from 'react';

export const fieldLabel = (field: string): string => {
  const labels: Record<string, string> = {
    name: 'Nome',
    description: 'Descrizione',
    quantity: 'Quantita',
    inventory_id: 'Inventario',
    owner_id: 'Proprietario',
    type: 'Tipo',
  };
  return labels[field] || field;
};

export const formatValue = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return 'vuoto';
  if (typeof value === 'boolean') return value ? 'si' : 'no';
  return String(value);
};

export const formatTypedMetadataValue = (typed: unknown): string => {
  if (typed === null || typed === undefined) return 'vuoto';
  if (typeof typed !== 'object') return String(typed);
  const t = typed as Record<string, unknown>;
  if (t.value_text !== undefined && t.value_text !== null) return String(t.value_text);
  if (t.value_number !== undefined && t.value_number !== null) return String(t.value_number);
  if (t.value_boolean !== undefined && t.value_boolean !== null) return t.value_boolean ? 'sì' : 'no';
  if (t.value_date !== undefined && t.value_date !== null) return String(t.value_date);
  return 'vuoto';
};

export const isChecklistChecked = (value: unknown): boolean => {
  const numeric = Number(value);
  return !Number.isNaN(numeric) && numeric > 0;
};

export const renderChecklistStatus = (value: unknown): ReactNode => (
  <span
    className="inline-flex h-6 w-6 items-center justify-center rounded border border-gray-400 bg-gray-100 text-gray-700 dark:border-gray-500 dark:bg-gray-700 dark:text-gray-200"
    style={{
      fontSize: '16px',
      lineHeight: '1',
      fontWeight: '600',
    }}
    aria-hidden="true"
    title={isChecklistChecked(value) ? 'check' : 'uncheck'}
  >
    {isChecklistChecked(value) ? '✓' : ''}
  </span>
);

export interface ParsedDiffEntry {
  field: string;
  label: string;
  from: unknown;
  to: unknown;
  formattedChange: ReactNode;
}

export function parseDiffEntries(
  diff: string | null | undefined,
  isChecklist = false
): ParsedDiffEntry[] {
  if (!diff) return [];
  try {
    const parsed = JSON.parse(diff) as Record<string, unknown>;
    const entries = Object.entries(parsed);
    const result: ParsedDiffEntry[] = [];

    for (const [field, values] of entries) {
      if (field === 'metadata' && Array.isArray(values)) {
        for (const change of values) {
          const c = change as Record<string, unknown>;
          const label =
            (c.definition_label as string | undefined) ??
            (c.definition_key as string | undefined) ??
            'Metadato';
          result.push({
            field: `meta-${String(c.definition_id)}`,
            label,
            from: c.from,
            to: c.to,
            formattedChange: `${formatTypedMetadataValue(c.from)} -> ${formatTypedMetadataValue(c.to)}`,
          });
        }
      } else {
        const v = values as { from: unknown; to: unknown } | null | undefined;
        const isStatusField = field === 'quantity' && isChecklist;
        result.push({
          field,
          label: isStatusField ? 'Status' : fieldLabel(field),
          from: v?.from,
          to: v?.to,
          formattedChange: isStatusField ? (
            <React.Fragment key={field}>
              {renderChecklistStatus(v?.from)}
              <span>{' -> '}</span>
              {renderChecklistStatus(v?.to)}
            </React.Fragment>
          ) : (
            `${formatValue(v?.from)} -> ${formatValue(v?.to)}`
          ),
        });
      }
    }
    return result;
  } catch {
    return [];
  }
}

export const getInventoryTypeIcon = (inventoryType?: string | null): string =>
  inventoryType === 'CHECKLIST' ? '📝' : '📦';

export const getInventoryPath = (
  inventoryType: string | null | undefined,
  inventoryId: number
): string | null => {
  if (inventoryType === 'CHECKLIST') return `/checklists/${inventoryId}`;
  if (inventoryType === 'INVENTORY') return `/inventories/${inventoryId}`;
  return null;
};

