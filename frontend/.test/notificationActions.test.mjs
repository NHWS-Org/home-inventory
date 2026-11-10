import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example/notifications' });
const originals = new Map();
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  Event: dom.window.Event,
  localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
})) {
  originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
const { MemoryRouter } = await import('react-router-dom');
const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
const { default: NotificationsPage } = await server.ssrLoadModule('/src/pages/NotificationsPage.tsx');
const { api } = await server.ssrLoadModule('/src/api.ts');
const root = createRoot(document.getElementById('root'));
after(async () => {
  await act(async () => root.unmount());
  await server.close();
  dom.window.close();
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});

test('notification selection handles pages, all, read, permanent deletion, cancellation and errors', async () => {
  let rows = Array.from({ length: 55 }, (_, i) => ({
    id: i + 1, created_at: '2026-11-09T16:30:00Z', read_at: null,
    inventory_type: 'INVENTORY', inventory_name: 'Dispensa', item_name: `Riso ${i + 1}`,
    event: { event_type: 'item_quantity_changed', inventory_id: 1, previous_quantity: 2, quantity: 1 },
  }));
  const requests = [];
  let failMutation = false;
  let confirmed = true;
  dom.window.confirm = () => confirmed;
  api.defaults.adapter = async config => {
    const data = config.data ? JSON.parse(config.data) : undefined;
    requests.push({ method: config.method, url: config.url, data });
    if (config.method !== 'get' && failMutation) throw new Error('Access revoked');
    let response;
    if (config.method === 'get') {
      const offset = config.params?.offset ?? 0;
      response = rows.slice(offset, offset + 50).map(row => ({ ...row }));
    } else {
      const ids = data?.all ? rows.map(row => row.id) : data?.ids ?? [Number(config.url.split('/')[2])];
      if (data?.action === 'delete' || config.method === 'delete') rows = rows.filter(row => !ids.includes(row.id));
      else rows = rows.map(row => ids.includes(row.id) ? { ...row, read_at: '2026-11-09T16:40:00Z' } : row);
      response = { updated: ids.length };
    }
    return { config, data: response, status: 200, statusText: 'OK', headers: {} };
  };
  const button = text => [...document.querySelectorAll('button')].find(node => node.textContent === text);
  const checkboxes = () => [...document.querySelectorAll('li input[type="checkbox"]')];
  const click = async node => {
    assert.ok(node && !node.disabled);
    await act(async () => node.click());
  };
  await act(async () => root.render(createElement(MemoryRouter, null, createElement(NotificationsPage))));
  assert.equal(checkboxes().length, 50);
  assert.match(document.body.textContent, /🟡↓/);
  assert.ok(button('Elimina selezionate').disabled);
  await click(checkboxes()[0]);
  await click(checkboxes()[1]);
  await click(button('Segna selezionate come lette'));
  assert.deepEqual(requests.find(r => r.method === 'post').data, { action: 'read', ids: [1, 2] });
  assert.equal(rows.filter(row => row.read_at).length, 2);
  await click(document.querySelector('input[type="checkbox"]'));
  assert.equal(checkboxes().filter(node => node.checked).length, 50);
  await click(button('Carica altre'));
  assert.equal(checkboxes().length, 55);
  assert.equal(checkboxes().filter(node => node.checked).length, 50);
  await click(button('Seleziona tutte (anche non caricate)'));
  assert.equal(checkboxes().filter(node => node.checked).length, 55);
  await click(checkboxes()[0]);
  assert.equal(checkboxes().filter(node => node.checked).length, 54);
  await click(button('Annulla selezione'));
  await click(checkboxes()[0]);
  failMutation = true;
  await click(button('Elimina selezionate'));
  assert.match(document.querySelector('[role="alert"]').textContent, /Operazione non completata/);
  assert.equal(checkboxes().filter(node => node.checked).length, 1);
  assert.equal(rows.length, 55);
  failMutation = false;
  confirmed = false;
  const before = requests.length;
  await click(button('Elimina selezionate'));
  assert.equal(requests.length, before);
  confirmed = true;
  await click(document.querySelector('button[aria-label="Elimina notifica"]'));
  assert.equal(rows.length, 54);
  assert.ok(!rows.some(row => row.id === 1));
  await click(button('Seleziona tutte (anche non caricate)'));
  await click(button('Elimina selezionate'));
  assert.deepEqual(requests.filter(r => r.method === 'post').at(-1).data, { action: 'delete', all: true });
  assert.equal(rows.length, 0);
  assert.equal(checkboxes().length, 0, JSON.stringify({
    requests: requests.slice(-4), alert: document.querySelector('[role="alert"]')?.textContent,
    busy: document.querySelector('section')?.getAttribute('aria-busy'),
  }));
  assert.match(document.body.textContent, /Nessuna notifica disponibile/);
  assert.ok(button('Elimina selezionate').disabled);
});
