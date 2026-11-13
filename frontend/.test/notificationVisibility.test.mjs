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
    createElement('button', { type: 'button', id: 'other-control' }, 'Altro controllo'),
  );
}

test('preference changes show and hide both navigation entries after successful saves', async () => {
  let rows = ['item_quantity_changed', 'item_updated', 'inventory_updated', 'filter_trigger_matched'].map(event_type => ({
    event_type, in_app_enabled: false, push_enabled: false,
  }));
  let fail = false;
  let pauseSave = false;
  let finishSave;
  api.defaults.adapter = async config => {
    if (fail) throw new Error('offline');
    let data;
    if (config.method === 'put') {
      if (pauseSave) await new Promise(resolve => { finishSave = resolve; });
      const eventType = config.url.split('/').pop();
      rows = rows.map(row => row.event_type === eventType ? { ...row, ...JSON.parse(config.data) } : row);
      data = {};
    } else if (config.url === '/notifications/preferences') data = rows;
    else if (config.url === '/triggers') data = [{
      id: 9, name: 'Controllo scorte', filter_id: 3, filter_name: 'Scorte',
      enabled: true, time: '08:00', timezone: 'Europe/Rome', weekdays: [1, 2, 3, 4, 5],
      inventory_ids: null, notify_mode: 'always', can_manage: false,
      scope_preview: { scope_type: 'all_inventories', summary: 'Tutti gli inventari', inventories: [] },
      last_run_at: null, next_run_at: null, last_result_count: null, last_container_count: null, last_error: null,
    }];
    else if (config.url === '/triggers/subscriptions') data = [];
    else data = { count: 2 };
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
  const bells = () => document.querySelectorAll('a[href="/notifications"]');
  const inputs = () => document.querySelectorAll('fieldset:first-of-type input[type="radio"]');
  const choose = async mode => {
    await act(async () => {
      const input = [...inputs()].find(input => input.value === mode);
      input.focus();
      input.click();
    });
  };
  await act(async () => root.render(createElement(Screen, { userId: 1 })));
  assert.equal(inputs().length, 3);
  assert.deepEqual([...inputs()].map(input => input.parentElement.textContent), ['Disattivate', 'Solo Inbox', 'Inbox + Push']);
  assert.equal(document.querySelectorAll('select').length, 0);
  assert.equal(document.querySelectorAll('input[type="radio"]:checked').length, 4);
  assert.match(document.body.textContent, /Avvisi da trigger/);
  assert.equal(document.querySelectorAll('input[type="checkbox"]').length, 0);
  assert.equal(bells().length, 0);
  const subscription = () => document.querySelector('[role="switch"][aria-label$="Controllo scorte"]');
  assert.ok(subscription());
  await act(async () => subscription().click());
  assert.equal(subscription().getAttribute('aria-checked'), 'true');
  pauseSave = true;
  await choose('inbox');
  assert.equal(inputs()[1].closest('fieldset').disabled, true);
  await act(async () => {
    inputs()[1].blur();
    finishSave();
  });
  pauseSave = false;
  assert.equal(document.activeElement?.getAttribute('value'), 'inbox');
  assert.deepEqual(rows[0], { event_type: 'item_quantity_changed', in_app_enabled: true, push_enabled: false });
  assert.equal(bells().length, 2);
  assert.match(bells()[0].getAttribute('aria-label'), /2 da leggere/);
  pauseSave = true;
  await choose('off');
  await act(async () => {
    document.getElementById('other-control').focus();
    finishSave();
  });
  pauseSave = false;
  assert.equal(document.activeElement.id, 'other-control');
  assert.equal(bells().length, 0);
  await choose('inbox_push');
  assert.deepEqual(rows[0], { event_type: 'item_quantity_changed', in_app_enabled: true, push_enabled: true });
  assert.equal(bells().length, 2);
  fail = true;
  await act(async () => subscription().click());
  assert.equal(subscription().getAttribute('aria-checked'), 'true');
  assert.match(document.body.textContent, /Iscrizione non salvata/);
  await choose('off');
  assert.equal([...inputs()].find(input => input.checked).value, 'inbox_push');
  assert.equal(bells().length, 2);
  assert.match(document.body.textContent, /Salvataggio non riuscito/);
  fail = false;
  await choose('off');
  assert.deepEqual(rows[0], { event_type: 'item_quantity_changed', in_app_enabled: false, push_enabled: false });
  assert.equal(bells().length, 0);
  fail = true;
  await act(async () => window.dispatchEvent(new Event('focus')));
  assert.equal(bells().length, 2);
  assert.match(bells()[0].getAttribute('aria-label'), /non disponibile/);
});
