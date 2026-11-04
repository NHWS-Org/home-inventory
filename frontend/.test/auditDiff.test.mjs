import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom',
  configFile: false,
  logLevel: 'error',
  server: { middlewareMode: true },
});
after(() => server.close());
const { parseDiffEntries } = await server.ssrLoadModule('/src/utils/auditDiff.tsx');

test('omits empty and unchanged fields in historical diffs', () => {
  const entries = parseDiffEntries(JSON.stringify({
    description: { from: null, to: '' },
    name: { from: 'Articolo', to: 'Articolo' },
    barcodes: { from: ['123'], to: ['123'] },
    quantity: { from: 1, to: 2 },
  }));

  assert.deepEqual(entries.map(({ field }) => field), ['quantity']);
  assert.equal(entries[0].formattedChange, '1 -> 2');
  assert.deepEqual(parseDiffEntries(JSON.stringify({
    description: { from: '', to: null },
  })), []);
});

test('retains real changes involving empty, zero, false and barcode values', () => {
  const entries = parseDiffEntries(JSON.stringify({
    description: { from: '', to: 'nota' },
    quantity: { from: 0, to: 1 },
    enabled: { from: false, to: null },
    barcodes: { from: [], to: ['123'] },
  }));

  assert.deepEqual(entries.map(({ field }) => field), ['description', 'quantity', 'enabled', 'barcodes']);
  assert.deepEqual(entries.map(({ formattedChange }) => formattedChange), [
    'vuoto -> nota',
    '0 -> 1',
    'no -> vuoto',
    'vuoto -> 123',
  ]);
});

test('omits equivalent metadata while preserving genuinely different values', () => {
  const entries = parseDiffEntries(JSON.stringify({
    metadata: [
      { definition_id: 1, from: { value_number: '1.0000' }, to: { value_number: '1' } },
      { definition_id: 2, from: { value_number: '1000.0000' }, to: { value_number: '1e3' } },
      { definition_id: 3, from: { value_number: '-0.0000' }, to: { value_number: '0' } },
      { definition_id: 4, from: { value_boolean: false }, to: { value_boolean: false } },
      { definition_id: 5, from: { value_boolean: false }, to: { value_boolean: true } },
      {
        definition_id: 6,
        from: { value_number: '9007199254740992' },
        to: { value_number: '9007199254740993' },
      },
      { definition_id: 7, from: { value_number: '-1.2300' }, to: { value_number: '-1.23' } },
      { definition_id: 8, from: { value_number: '.1000' }, to: { value_number: '1e-1' } },
      { definition_id: 9, from: null, to: { value_number: '0' } },
      { definition_id: 10, from: { value_boolean: false }, to: null },
    ],
  }));

  assert.deepEqual(entries.map(({ field }) => field), ['meta-5', 'meta-6', 'meta-9', 'meta-10']);
  assert.equal(entries[0].formattedChange, 'no -> sì');
  assert.equal(entries[1].formattedChange, '9007199254740992 -> 9007199254740993');
  assert.equal(entries[2].formattedChange, 'vuoto -> 0');
  assert.equal(entries[3].formattedChange, 'no -> vuoto');
});

test('retains checklist status changes and omits unchanged ones', () => {
  const entries = parseDiffEntries(JSON.stringify({
    description: { from: null, to: '' },
    quantity: { from: 0, to: 1 },
  }), true);

  assert.equal(entries.length, 1);
  assert.equal(entries[0].field, 'quantity');
  assert.equal(entries[0].label, 'Status');
  assert.ok(entries[0].formattedChange);
  assert.deepEqual(parseDiffEntries(JSON.stringify({
    quantity: { from: 0, to: 0 },
  }), true), []);
});
