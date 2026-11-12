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
const { MemoryRouter, Routes, Route, useLocation } = await import('react-router-dom');
const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
const { default: GenericListPage } = await server.ssrLoadModule('/src/pages/GenericListPage.tsx');
const { default: GenericDetailPage, SwipeableItemRow } = await server.ssrLoadModule('/src/pages/GenericDetailPage.tsx');
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

test('back to top scrolls the page container to zero, including filters, on mobile and desktop', async () => {
  const width = window.innerWidth;
  const windowScroll = window.scrollTo;
  window.scrollTo = () => assert.fail('The document is not the page scroll container');
  try {
    for (const viewport of [390, 1024]) {
      window.innerWidth = viewport;
      for (const path of ['inventories', 'checklists']) {
        for (const detail of [false, true]) {
          for (const role of detail ? ['admin'] : ['admin', 'viewer']) {
            const container = {
              id: 1, name: 'Dispensa', version_num: 1, owner: { username: 'admin' },
              item_count: 0, data_mod: '2026-11-03T19:09:30',
            };
            api.defaults.adapter = async config => ({
              config, status: 200, statusText: 'OK', headers: {},
              data: config.url === '/inventory/' || config.url === '/checklist/'
                ? [container]
                : config.url === '/inventory/1' || config.url === '/checklist/1'
                  ? container : [],
            });
            await act(async () => root.render(createElement(MemoryRouter, {
              key: `${viewport}-${path}-${detail}-${role}`,
              initialEntries: [`/${path}${detail ? '/1' : ''}`],
            }, createElement(AuthContext.Provider, { value: { user: { role: { name: role } } } },
              createElement('div', { 'data-page-scroll': true },
                createElement(Routes, null, createElement(Route, {
                  path: `/${path}${detail ? '/:id' : ''}`,
                  element: createElement(detail ? GenericDetailPage : GenericListPage),
                })))))));
            const scroller = document.querySelector('[data-page-scroll]');
            scroller.scrollTop = 900;
            const calls = [];
            scroller.scrollTo = options => { calls.push(options); scroller.scrollTop = options.top; };
            const button = scroller.querySelector('button[aria-label="Torna in cima alla pagina"]');
            assert.ok(button, `${viewport} ${path} ${detail} ${role}`);
            assert.ok(scroller.querySelector('input[placeholder*="Filtra"]'));
            await act(async () => button.click());
            assert.deepEqual(calls, [{ top: 0, behavior: 'smooth' }]);
            assert.equal(scroller.scrollTop, 0);
          }
        }
      }
    }
  } finally {
    window.innerWidth = width;
    window.scrollTo = windowScroll;
  }
});

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

test('compact inventory controls preserve quantity updates and editing without selecting the row', async () => {
  const updates = [];
  const edited = [];
  let selections = 0;
  let item = {
    id: 2, inventory_id: 1, name: 'Hamburger pollo/tacchino x2', description: 'Fileni',
    quantity: 1, version_num: 4, username_mod: 'angela', data_mod: '2026-11-03T19:09:30',
  };
  const render = async (isEditMode = false) => act(async () => root.render(createElement(SwipeableItemRow, {
    key: 'compact-inventory', item, isMobile: true, isChecklist: false, isInventory: true,
    user: { role: { name: 'admin' } }, isEditMode, selectedItems: [],
    setSelectedItems() { selections++; },
    setItemBeingEdited(value) { edited.push(value); },
    async updateItem(id, value) { updates.push({ id, quantity: value.quantity }); return value; },
    setItems(updater) { [item] = updater([item]); },
    deleteItem() {}, setIsCloning() {},
  })));
  const click = async label => act(async () => document.querySelector(`button[aria-label="${label}"]`).click());
  await render();
  await click('Aumenta quantità');
  await render();
  assert.equal(item.quantity, 2);
  await click('Diminuisci quantità');
  await render(true);
  assert.equal(item.quantity, 1);
  await click('Diminuisci quantità');
  await render(true);
  assert.equal(item.quantity, 0);
  assert.equal(document.querySelector('button[aria-label="Diminuisci quantità"]').disabled, true);
  await click('Diminuisci quantità');
  assert.deepEqual(updates, [{ id: 2, quantity: 2 }, { id: 2, quantity: 1 }, { id: 2, quantity: 0 }]);
  await click('Modifica item');
  await click('Clona item');
  assert.equal(edited[0].name, item.name);
  assert.equal(edited[1].name, `${item.name} (copia)`);
  assert.equal(selections, 0);
});

test('compact checklist keeps completion usable and exposes assignment only to editors', async () => {
  let item = {
    id: 3, inventory_id: 1, name: 'Riso', quantity: 0,
    version_num: 1, data_mod: '2026-11-03T19:09:30',
  };
  const quantities = [];
  const render = async role => act(async () => root.render(createElement(SwipeableItemRow, {
    key: 'compact-checklist', item, isMobile: true, isChecklist: true, isInventory: false,
    user: { role: { name: role } }, isEditMode: false, selectedItems: [],
    setSelectedItems() {}, setItemBeingEdited() {}, deleteItem() {}, setIsCloning() {},
    async updateItem(id, value) { quantities.push(value.quantity); return value; },
    setItems(updater) { [item] = updater([item]); },
  })));
  await render('admin');
  assert.ok(document.querySelector('button[aria-label="Assegna da inventario"]'));
  assert.ok(document.querySelector('button[aria-label="Visualizza cronologia item"]'));
  await act(async () => document.querySelector('input[aria-label="Completato"]').click());
  await render('admin');
  assert.equal(document.querySelector('input').checked, true);
  await act(async () => document.querySelector('input').click());
  assert.deepEqual(quantities, [1, 0]);
  await render('viewer');
  assert.equal(document.querySelector('input').disabled, true);
  assert.equal(document.querySelector('button[aria-label="Assegna da inventario"]'), null);
});
