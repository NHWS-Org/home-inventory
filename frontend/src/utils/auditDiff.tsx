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

const isEmptyValue = (value: unknown): boolean =>
  value === null || value === undefined || value === '' ||
  (Array.isArray(value) && value.length === 0);

export const formatValue = (value: unknown): string => {
  if (isEmptyValue(value)) return 'vuoto';
  if (typeof value === 'boolean') return value ? 'si' : 'no';
  return String(value);
};

function sameValue(from: unknown, to: unknown): boolean {
  if (from === to || (isEmptyValue(from) && isEmptyValue(to))) return true;
  return Array.isArray(from) && Array.isArray(to) &&
    from.length === to.length && from.every((value, index) => value === to[index]);
}

function normalizedDecimal(value: unknown): string | null {
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(String(value));
  if (!match || (!match[2] && !match[3])) return null;

  // Compare decimal values without losing precision through Number conversion.
  const fractional = match[3] ?? '';
  const digits = `${match[2]}${fractional}`.replace(/^0+/, '');
  if (!digits) return '0';
  const significant = digits.replace(/0+$/, '');
  const exponent = BigInt(match[4] ?? '0') - BigInt(fractional.length) +
    BigInt(digits.length - significant.length);
  return `${match[1] === '-' ? '-' : ''}${significant}e${exponent}`;
}

function sameMetadataValue(from: unknown, to: unknown): boolean {
  if (sameValue(from, to)) return true;
  if (!from || !to || typeof from !== 'object' || typeof to !== 'object') return false;

  const before = from as Record<string, unknown>;
  const after = to as Record<string, unknown>;
  const beforeKeys = Object.keys(before).filter((key) => before[key] !== null && before[key] !== undefined);
  const afterKeys = Object.keys(after).filter((key) => after[key] !== null && after[key] !== undefined);
  if (beforeKeys.length !== 1 || afterKeys.length !== 1 || beforeKeys[0] !== afterKeys[0]) return false;

  const key = beforeKeys[0];
  if (key === 'value_number') {
    const beforeNumber = normalizedDecimal(before[key]);
    const afterNumber = normalizedDecimal(after[key]);
    return beforeNumber !== null && beforeNumber === afterNumber;
  }
  return sameValue(before[key], after[key]);
}

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
          if (sameMetadataValue(c.from, c.to)) continue;
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
        if (sameValue(v?.from, v?.to)) continue;
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
  } catch (error) {
    console.error('Errore nella lettura delle modifiche audit', error);
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
