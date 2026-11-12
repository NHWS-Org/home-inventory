import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { act, createElement, useState } from 'react';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example', pretendToBeVisual: true });
const originals = new Map();
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  Event: dom.window.Event, localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
  HTMLElement: dom.window.HTMLElement, Element: dom.window.Element, Node: dom.window.Node,
  MutationObserver: dom.window.MutationObserver,
  requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
  cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
  getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
})) {
  originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
const { MemoryRouter, Routes, Route, useLocation } = await import('react-router-dom');
const layoutListeners = new Set();
window.matchMedia = query => ({
  get matches() {
    const minWidth = query.match(/min-width:\s*(\d+)px/);
    return minWidth ? window.innerWidth >= Number(minWidth[1]) : false;
  },
  addEventListener(event, listener) { layoutListeners.add(listener); },
  removeEventListener(event, listener) { layoutListeners.delete(listener); },
});
const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
const { default: GenericListPage } = await server.ssrLoadModule('/src/pages/GenericListPage.tsx');
const { default: GenericDetailPage, SwipeableItemRow } = await server.ssrLoadModule('/src/pages/GenericDetailPage.tsx');
const { default: MobileItemFilters } = await server.ssrLoadModule('/src/components/MobileItemFilters.tsx');
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

test('mobile filter sheet preserves search independence, sort state and removable filters', async () => {
  function Harness({ checklist }) {
    const [search, onSearch] = useState('Riso');
    const [barcode, onBarcode] = useState('all');
    const [sortBy, onSortBy] = useState('name');
    const [sortOrder, onSortOrder] = useState('asc');
    const [priorityOrder, onPriorityOrder] = useState('desc');
    const [templateId, onTemplate] = useState('');
    return createElement(MobileItemFilters, {
      search, onSearch, barcode, onBarcode, sortBy, onSortBy, sortOrder, onSortOrder,
      sortOptions: [{ value: 'name', label: 'Nome' }, { value: 'date', label: 'Data modifica' }],
      checklist, priorityOrder, onPriorityOrder, templateId, onTemplate,
      templates: [{ id: 1, name: 'Alimenti' }], metadataSummary: null,
      onClearMetadata() { onTemplate(''); },
      onReset() { onSearch(''); onBarcode('all'); onTemplate(''); },
      metadataEditor: createElement('button', { type: 'button' }, 'Filtri metadati'),
    });
  }
  const click = async text => {
    const node = [...document.querySelectorAll('button')].find(button => button.textContent === text);
    assert.ok(node, text);
    await act(async () => node.click());
  };
  await act(async () => root.render(createElement(Harness, { checklist: false })));
  assert.equal(document.querySelectorAll('select').length, 0);
  await act(async () => document.querySelector('button[aria-haspopup="dialog"]').click());
  assert.ok(document.querySelector('[role="dialog"]'));
  assert.equal(document.querySelectorAll('select').length, 2);
  assert.equal(document.querySelector('[role="dialog"]').textContent.includes('Priorità'), false);
  await click('Senza barcode');
  await click('Z → A');
  await click('Chiudi');
  assert.equal(document.querySelector('input').value, 'Riso');
  assert.ok(document.querySelector('button[aria-label="Filtri e ordinamento (1 filtri attivi)"]'));
  await act(async () => document.querySelector('button[aria-label="Cancella ricerca"]').click());
  assert.equal(document.querySelector('input').value, '');
  assert.ok([...document.querySelectorAll('button')].some(button => button.textContent.includes('Senza barcode')));
  await act(async () => document.querySelector('button[aria-haspopup="dialog"]').click());
  const descending = [...document.querySelectorAll('button')].find(button => button.textContent === 'Z → A');
  assert.equal(descending.getAttribute('aria-pressed'), 'true');
  const template = document.querySelectorAll('select')[1];
  await act(async () => { template.value = '1'; template.dispatchEvent(new Event('change', { bubbles: true })); });
  await click('Chiudi');
  assert.ok(document.querySelector('button[aria-label="Filtri e ordinamento (2 filtri attivi)"]'));
  await click('Alimenti ×');
  assert.ok(document.querySelector('button[aria-label="Filtri e ordinamento (1 filtri attivi)"]'));
  await act(async () => document.querySelector('button[aria-haspopup="dialog"]').click());
  await click('Azzera filtri');
  assert.equal(descending.getAttribute('aria-pressed'), 'true');
  await click('Chiudi');
  assert.ok(document.querySelector('button[aria-label="Filtri e ordinamento"]'));
  await act(async () => root.render(createElement(Harness, { key: 'checklist', checklist: true })));
  await act(async () => document.querySelector('button[aria-haspopup="dialog"]').click());
  await click('Prima bassa');
  assert.equal([...document.querySelectorAll('button')].find(button => button.textContent === 'Prima bassa').getAttribute('aria-pressed'), 'true');
  await click('Chiudi');
});

test('back to top scrolls the page container to zero, including filters, on mobile and desktop', async () => {
  const width = window.innerWidth;
  const windowScroll = window.scrollTo;
  window.scrollTo = () => assert.fail('The document is not the page scroll container');
  try {
    for (const viewport of [390, 800, 1024, 1280]) {
      window.innerWidth = viewport;
      for (const path of ['inventories', 'checklists']) {
        for (const detail of [false, true]) {
          for (const role of detail && viewport < 768 ? ['admin'] : ['admin', 'viewer']) {
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
            assert.ok(scroller.querySelector('input[placeholder*="Filtra"], input[aria-label="Ricerca libera"]'));
            await act(async () => button.click());
            assert.deepEqual(calls, [{ top: 0, behavior: 'smooth' }]);
            assert.equal(scroller.scrollTop, 0);
            if (!detail && viewport < 1280) {
              assert.equal(scroller.querySelectorAll('select').length, 0);
              await act(async () => scroller.querySelector('button[aria-haspopup="dialog"]').click());
              const dialog = document.querySelector('[role="dialog"]');
              assert.ok(dialog);
              assert.deepEqual([...dialog.querySelectorAll('option')].map(option => option.textContent), ['Nome', 'Data modifica', 'Data creazione', 'Numero di oggetti']);
              assert.equal(dialog.textContent.includes('Barcode'), false);
              const select = dialog.querySelector('select');
              await act(async () => { select.value = 'item_count'; select.dispatchEvent(new Event('change', { bubbles: true })); });
              assert.equal(localStorage.getItem(path === 'inventories' ? 'inventory_sortBy' : 'checklist_sortBy'), 'item_count');
              await act(async () => [...dialog.querySelectorAll('button')].find(node => node.textContent === 'Chiudi').click());
            }
            if (detail) {
              if (viewport === 800 && role === 'admin') {
                const add = scroller.querySelector('button[aria-label="Aggiungi item"]');
                assert.ok(add);
                assert.equal(add.textContent, 'Nuovo');
                assert.equal(add.closest('.fixed'), null, 'Tablet actions must remain inside the content column');
                assert.equal(scroller.textContent.includes('Importa / esporta'), false);
                await act(async () => scroller.querySelector('button[aria-label="Modifica item"]').click());
                await act(async () => scroller.querySelector('button[aria-label="Altre azioni"]').click());
                assert.ok(scroller.textContent.includes('Seleziona tutti'));
                assert.ok(scroller.textContent.includes('Condividi su WhatsApp'));
                assert.ok(scroller.textContent.includes('Importa / esporta'));
                assert.equal(scroller.textContent.includes('Aggiungi da inventario'), path === 'checklists');
                await act(async () => scroller.querySelector('button[aria-label="Chiudi altre azioni"]').click());
                await act(async () => scroller.querySelector('button[aria-label="Esci dalla modifica"]').click());
                await act(async () => scroller.querySelector('button[aria-haspopup="dialog"]').click());
                assert.ok(document.querySelector('[role="dialog"]').textContent.includes('Barcode'));
                await act(async () => document.querySelector('button[aria-label="Chiudi filtri"]').click());
              }
              const requests = [];
              const adapter = api.defaults.adapter;
              api.defaults.adapter = config => { requests.push(config.url); return adapter(config); };
              const otherWidth = viewport < 1280 ? 1280 : 800;
              await act(async () => {
                window.innerWidth = otherWidth;
                for (const listener of layoutListeners) listener();
              });
              assert.equal(!!scroller.querySelector('input[aria-label="Ricerca libera"]'), otherWidth < 1280);
              assert.equal(requests.filter(url => /^\/(?:inventory|checklist)\//.test(url)).length, 0, `Resizing must not reload inventory data: ${requests}`);
              await act(async () => {
                window.innerWidth = viewport;
                for (const listener of layoutListeners) listener();
              });
              assert.equal(!!scroller.querySelector('input[aria-label="Ricerca libera"]'), viewport < 1280);
              api.defaults.adapter = adapter;
            }
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
        matching_items: [{ id: 2, name: 'Gioco', quantity: 1, highlighted: { name: '**Gioco**' } }],
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
    assert.equal(card.querySelector('span.bg-blue-100')?.textContent, 'Gioco');
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

test('item search highlights literal matches in names, descriptions and metadata without HTML injection', async () => {
  for (const search of ['rIso', '[.*]', '<img>']) {
    await act(async () => root.render(createElement(SwipeableItemRow, {
      item: {
        id: 2, inventory_id: 1, name: 'Riso [.*] <img>', description: 'RISO [.*] <img>',
        quantity: 1, version_num: 1, data_mod: '2026-11-03T19:09:30',
        metadata_values: [{ id: 1, definition_label: 'Categoria', field_type: 'TEXT', value_text: 'riso [.*] <img>' }],
      },
      search, isMobile: true, isChecklist: false, isInventory: true,
      user: { role: { name: 'viewer' } }, isEditMode: false, selectedItems: [],
      setSelectedItems() {}, setItemBeingEdited() {}, updateItem() {}, deleteItem() {},
      setItems() {}, setIsCloning() {},
    })));
    const highlights = [...document.querySelectorAll('li span.bg-blue-100')];
    assert.equal(highlights.length, 3);
    assert.ok(highlights.every(node => node.textContent.toLowerCase() === search.toLowerCase()));
    assert.equal(document.querySelector('li img'), null);
  }
  await act(async () => root.render(createElement(SwipeableItemRow, {
    item: { id: 2, name: 'Riso', quantity: 1, version_num: 1, data_mod: '2026-11-03T19:09:30' },
    search: '', isMobile: false, isChecklist: false, isInventory: true,
    user: { role: { name: 'viewer' } }, isEditMode: false, selectedItems: [],
    setSelectedItems() {}, setItemBeingEdited() {}, updateItem() {}, deleteItem() {},
    setItems() {}, setIsCloning() {},
  })));
  assert.equal(document.querySelectorAll('li span.bg-blue-100').length, 0);
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
