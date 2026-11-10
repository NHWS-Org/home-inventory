import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example/profile' });
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
const { useUnreadNotifications } = await server.ssrLoadModule('/src/components/useUnreadNotifications.ts');
const { default: NotificationPreferences } = await server.ssrLoadModule('/src/components/NotificationPreferences.tsx');
const { default: NotificationBell } = await server.ssrLoadModule('/src/components/NotificationBell.tsx');
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

function Screen({ userId }) {
  const status = useUnreadNotifications(userId);
  return createElement(MemoryRouter, null,
    status.enabled && createElement(NotificationBell, { ...status, variant: 'desktop', navItemClass: () => '' }),
    status.enabled && createElement(NotificationBell, { ...status, variant: 'mobile', navItemClass: () => '' }),
    createElement(NotificationPreferences),
  );
}

test('preference changes show and hide both navigation entries after successful saves', async () => {
  let rows = ['item_quantity_changed', 'item_updated', 'inventory_updated'].map(event_type => ({
    event_type, in_app_enabled: false, push_enabled: false, include_own_actions: false,
  }));
  let fail = false;
  api.defaults.adapter = async config => {
    if (fail) throw new Error('offline');
    let data;
    if (config.method === 'put') {
      const eventType = config.url.split('/').pop();
      rows = rows.map(row => row.event_type === eventType ? { ...row, ...JSON.parse(config.data) } : row);
      data = {};
    } else data = config.url === '/notifications/preferences' ? rows : { count: 2 };
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
  const bells = () => document.querySelectorAll('a[href="/notifications"]');
  const inputs = () => document.querySelectorAll('input[type="checkbox"]');
  await act(async () => root.render(createElement(Screen, { userId: 1 })));
  assert.equal(bells().length, 0);
  await act(async () => inputs()[0].click());
  assert.equal(bells().length, 2);
  assert.match(bells()[0].getAttribute('aria-label'), /2 da leggere/);
  await act(async () => inputs()[0].click());
  assert.equal(bells().length, 0);
  await act(async () => inputs()[1].click());
  assert.equal(bells().length, 2);
  fail = true;
  await act(async () => inputs()[1].click());
  assert.equal(bells().length, 2);
  assert.match(document.body.textContent, /Salvataggio non riuscito/);
  fail = false;
  await act(async () => inputs()[1].click());
  assert.equal(bells().length, 0);
  fail = true;
  await act(async () => window.dispatchEvent(new Event('focus')));
  assert.equal(bells().length, 2);
  assert.match(bells()[0].getAttribute('aria-label'), /non disponibile/);
});
