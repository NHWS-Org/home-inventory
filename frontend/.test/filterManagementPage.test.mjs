import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example/filters' });
const originals = new Map();
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  Event: dom.window.Event, HTMLElement: dom.window.HTMLElement, MouseEvent: dom.window.MouseEvent,
  localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
})) {
  originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { act, createElement } = await import('react');
const { createRoot } = await import('react-dom/client');
const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(async () => {
  await act(async () => root.unmount());
  await server.close();
  dom.window.close();
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});

const { FilterEditor, TriggerEditor } = await server.ssrLoadModule('/src/pages/FilterManagementPage.tsx');
const root = createRoot(document.getElementById('root'));

const scope = { scope_type: 'all_inventories', summary: 'Tutti gli inventari', inventories: [{ id: 2, name: 'Dispensa', type: 'INVENTORY' }] };
const filter = {
  id: 13, name: 'Scadenze', description: '', is_shared: true, container_type: 'INVENTORY',
  match_mode: 'all', can_manage: true, conditions: [{
    source: 'metadata', field: 'expires_on', definition_id: 8, operator: 'between',
    range_from: { relative_days: -2 }, range_to: { relative_days: 4 },
  }],
  scope_preview: scope, trigger_count: 0,
};
const fields = [{
  source: 'metadata', field: 'expires_on', definition_id: 8, label: 'Scadenza',
  field_type: 'DATE', operators: ['between'], container_types: ['INVENTORY'],
}];

test('filter editor renders typed date-range controls with signed Oggi + X day inputs at both ends', async () => {
  await act(async () => root.render(createElement(FilterEditor, {
    filter, fields, onClose() {}, onSaved() {},
  })));
  assert.ok(document.querySelector('[aria-label="Campo della condizione"]'));
  assert.ok(document.querySelector('[aria-label="Operatore"]'));
  assert.equal(document.querySelector('[aria-label="Data iniziale: giorni"]')?.value, '-2');
  assert.equal(document.querySelector('[aria-label="Data finale: giorni"]')?.value, '4');
  assert.ok(document.querySelector('[aria-label="Data iniziale: riferimento"]')?.textContent?.includes('Oggi ± giorni'));
  assert.ok(document.querySelector('[aria-label="Data finale: riferimento"]'));
  await act(async () => root.render(null));
});

test('filter editor rejects an empty typed value instead of reporting a false save', async () => {
  const numericFields = [{
    source: 'item', field: 'quantity', label: 'Quantità', field_type: 'NUMBER',
    operators: ['equals'], container_types: ['INVENTORY', 'CHECKLIST'],
  }];
  await act(async () => root.render(createElement(FilterEditor, {
    filter: null, fields: numericFields, onClose() {}, onSaved() {},
  })));
  const name = document.querySelector('input[placeholder="Es. Scorte da riordinare"]');
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value').set.call(name, 'Filtro di test');
    name.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  });
  await act(async () => document.querySelector('button[type="submit"]').click());
  assert.match(document.querySelector('[role="alert"]').textContent, /Inserisci un valore/);
  await act(async () => root.render(null));
});

test('invalid legacy filters display the server error and require deliberate rebuilding before save', async () => {
  await act(async () => root.render(createElement(FilterEditor, {
    filter: { ...filter, conditions: [], validation_error: 'Definizione del metadato non più disponibile.' },
    fields, onClose() {}, onSaved() {},
  })));
  assert.match(document.querySelector('[role="alert"]').textContent, /Definizione del metadato non più disponibile/);
  assert.equal(document.querySelector('button[type="submit"]').disabled, true);
  assert.equal(document.querySelector('[aria-label="Campo della condizione"]'), null);
  assert.equal(document.querySelector('[aria-label="Elimina filtro"]').disabled, false);
  const rebuild = [...document.querySelectorAll('button')].find(button => button.textContent === 'Ricostruisci filtro');
  await act(async () => rebuild.click());
  assert.equal(document.querySelector('button[type="submit"]').disabled, false);
  assert.ok(document.querySelector('[aria-label="Campo della condizione"]'));
  assert.match(document.body.textContent, /salvataggio sostituirà le condizioni originali/);
  await act(async () => root.render(null));
});

test('trigger editor exposes ISO weekday selections, timezone, and result-change choices', async () => {
  await act(async () => root.render(createElement(TriggerEditor, {
    trigger: null, filters: [filter], defaultFilterId: 13, onClose() {}, onSaved() {},
  })));
  for (const [day, value] of [['Lun', 1], ['Mar', 2], ['Mer', 3], ['Gio', 4], ['Ven', 5], ['Sab', 6], ['Dom', 7]]) {
    const button = document.querySelector(`[data-weekday="${value}"]`);
    assert.ok(button);
    assert.equal(button.textContent, day);
  }
  assert.ok(document.body.textContent.includes('Solo se i risultati cambiano'));
  assert.ok(document.body.textContent.includes('Fuso orario'));
  assert.ok(document.body.textContent.includes('Tutti i contenitori compatibili'));
  await act(async () => document.querySelector('[data-weekday="7"]').click());
  assert.equal(document.querySelector('[data-weekday="7"]').getAttribute('aria-pressed'), 'false');
  await act(async () => root.render(null));
});
