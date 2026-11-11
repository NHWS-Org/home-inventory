import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example' });
const originals = new Map();
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  Event: dom.window.Event, localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
})) {
  originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
const { MemoryRouter, useLocation } = await import('react-router-dom');
const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
const { default: GenericListPage } = await server.ssrLoadModule('/src/pages/GenericListPage.tsx');
const { SwipeableItemRow } = await server.ssrLoadModule('/src/pages/GenericDetailPage.tsx');
const { AuthContext } = await server.ssrLoadModule('/src/auth-context.tsx');
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

function Location() {
  return createElement('output', { 'aria-label': 'Destinazione' }, useLocation().pathname);
}

for (const path of ['inventories', 'checklists']) {
  test(`${path} cards keep QR at the top without a reserved bottom strip`, async () => {
    const name = 'Garage - Regali per bambini';
    const requests = [];
    api.defaults.adapter = async config => {
      requests.push(config.url);
      return { config, status: 200, statusText: 'OK', headers: {}, data: [{
        id: 1, name, version_num: 3, owner: { username: 'angela' }, item_count: 13,
        data_ins: '2026-11-03T19:09:30', data_mod: '2026-11-03T19:09:30',
        matching_items: [{ id: 2, name: 'Gioco', quantity: 1 }],
      }] };
    };
    await act(async () => root.render(createElement(MemoryRouter, { key: path, initialEntries: [`/${path}`] },
      createElement(AuthContext.Provider, { value: { user: { role: { name: 'admin' } } } },
        createElement(GenericListPage), createElement(Location)))));
    assert.ok(requests.includes(path === 'inventories' ? '/inventory/' : '/checklist/'));
    const heading = document.querySelector('h2');
    const card = heading.closest('li');
    const qr = card.querySelector(`button[aria-label="Mostra QR code per ${name}"]`);
    assert.ok(qr);
    assert.equal(qr.parentElement.firstElementChild, qr);
    assert.match(qr.className, /float-right/);
    assert.match(qr.className, /h-11 w-11/);
    assert.doesNotMatch(card.className, /pb-16/);
    assert.doesNotMatch(qr.className, /absolute|bottom-/);
    assert.equal(heading.textContent, name);
    assert.match(card.querySelector('p').textContent, /Ultima modifica: .* · v3$/);
    assert.match(card.textContent, /Creatore: angela \| Oggetti: 13/);
    assert.match(card.textContent, /Corrispondenze trovate:Gioco|Corrispondenze trovate:1x Gioco/);
    await act(async () => card.click());
    assert.equal(document.querySelector('output').textContent, `/${path}/1`);
    const edit = [...document.querySelectorAll('button')].find(button => button.textContent === '✏️Modifica');
    await act(async () => edit.click());
    const editHeading = document.querySelector('h2');
    assert.equal(editHeading.textContent, name);
    assert.match(editHeading.closest('li').querySelector('p').textContent, /Ultima modifica: .* · v3$/);
  });
}

test('inventory and checklist item versions appear with modification details, not the name', async () => {
  for (const isChecklist of [false, true]) {
    for (const isEditMode of [false, true]) {
      await act(async () => root.render(createElement(SwipeableItemRow, {
        item: {
          id: 2, inventory_id: 1, name: 'Riso', quantity: 1, version_num: 123,
          data_mod: '2026-11-03T19:09:30', username_mod: 'angela',
        },
        isMobile: true, isChecklist, isInventory: !isChecklist,
        user: { role: { name: 'viewer' } }, isEditMode, selectedItems: [],
        setSelectedItems() {}, setItemBeingEdited() {}, updateItem() {}, deleteItem() {},
        setItems() {}, setIsCloning() {},
      })));
      const name = [...document.querySelectorAll('span')].find(node => node.textContent === 'Riso');
      assert.ok(name);
      assert.doesNotMatch(name.parentElement.textContent, /v123/);
      const details = [...document.querySelectorAll('li div')].find(node => node.textContent.startsWith('Ultima modifica:'));
      assert.match(details.textContent, /^Ultima modifica: angela - .* · v123$/);
      assert.equal(document.querySelector('li').textContent.match(/v123/g)?.length, 1);
    }
  }
});
