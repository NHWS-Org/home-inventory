import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example/' });
dom.window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const originals = new Map();
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  Event: dom.window.Event, localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
})) {
  originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
const { MemoryRouter } = await import('react-router-dom');
const server = await createServer({ appType: 'custom', configFile: false, logLevel: 'error', server: { middlewareMode: true, ws: false } });
const { default: SidebarLayout } = await server.ssrLoadModule('/src/pages/SidebarLayout.tsx');
const { AuthContext } = await server.ssrLoadModule('/src/auth-context-instance.ts');
const { api } = await server.ssrLoadModule('/src/api.ts');
const adapter = api.defaults.adapter;
api.defaults.adapter = async config => ({ config, data: config.url === '/version' ? { version: '1.5.0' } : {}, status: 200, statusText: 'OK', headers: {} });
const root = createRoot(document.getElementById('root'));
after(async () => {
  await act(async () => root.unmount());
  api.defaults.adapter = adapter;
  await server.close();
  dom.window.close();
  for (const [key, descriptor] of originals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});

const render = (user, path = '/') => act(async () => root.render(createElement(AuthContext.Provider, {
  value: { user, isLoading: false, setUser: () => {}, logout: async () => {} },
}, createElement(MemoryRouter, { key: `${user?.id ?? 'guest'}:${path}`, initialEntries: [path] }, createElement(SidebarLayout, null, createElement('p', null, 'Contenuto'))))));
const bottomNav = () => document.querySelector('nav[aria-label="Navigazione principale"]');
const navLabels = () => [...bottomNav().querySelectorAll('a, button')].map(item => item.textContent.trim());
const sheetText = () => document.querySelector('[role="dialog"]')?.textContent ?? '';
const openAccount = () => act(async () => bottomNav().querySelector('button[aria-haspopup="dialog"]').click());

test('guest mobile bar only offers Home and Accedi, with About and theme in the footer', async () => {
  await render(null);
  assert.deepEqual(navLabels(), ['Home', 'Accedi']);
  assert.equal(bottomNav().querySelector('a[href="/login"]').textContent.trim(), 'Accedi');
  const footer = document.querySelector('footer[aria-label="Informazioni e tema"]');
  assert.ok(footer.querySelector('a[href="/about"]'));
  assert.match(footer.textContent, /Tema: Sistema/);
  assert.equal(document.querySelector('[aria-label="Apri account e preferenze"]'), null);
});

test('viewer account sheet hides organization tools', async () => {
  await render({ id: 2, username: 'viewer', role: { name: 'viewer' } });
  assert.deepEqual(navLabels().filter(label => !label.endsWith('Notifiche')), ['Home', 'Inventari', 'Liste', 'VAccount']);
  assert.equal(document.querySelector('footer[aria-label="Informazioni e tema"]'), null);
  await openAccount();
  assert.match(sheetText(), /Gestione profilo/);
  assert.match(sheetText(), /About/);
  assert.doesNotMatch(sheetText(), /Gestione filtri|Gestione trigger|Impostazioni/);
});

test('admin account sheet groups organization and system entries', async () => {
  await render({ id: 1, username: 'admin', role: { name: 'admin' } }, '/triggers');
  assert.ok(bottomNav().querySelector('button[aria-haspopup="dialog"]').className.includes('bg-blue-100'));
  await openAccount();
  const dialog = document.querySelector('[role="dialog"]');
  for (const path of ['/profile', '/filters', '/triggers', '/settings', '/about']) assert.ok(dialog.querySelector(`a[href="${path}"]`), path);
  assert.match(sheetText(), /Organizzazione.*Sistema.*Tema.*Esci/s);
});
