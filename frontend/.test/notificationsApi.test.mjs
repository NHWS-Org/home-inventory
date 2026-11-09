import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());
const notifications = await server.ssrLoadModule('/src/notificationsApi.ts');
const { api, createItem } = await server.ssrLoadModule('/src/api.ts');
const { NotificationOpenLink } = await server.ssrLoadModule('/src/pages/NotificationsPage.tsx');

test('compact actions show signed deltas, checks, historical text and legacy labels', () => {
  assert.equal(notifications.notificationAction({inventory_type:'INVENTORY', event:{event_type:'item_quantity_changed', previous_quantity:2,quantity:3}}), 'Quantità: +1');
  assert.equal(notifications.notificationAction({inventory_type:'INVENTORY', event:{event_type:'item_quantity_changed', previous_quantity:5,quantity:2}}), 'Quantità: -3');
  assert.equal(notifications.notificationAction({inventory_type:'CHECKLIST', event:{event_type:'item_quantity_changed', previous_quantity:1,quantity:0}}), 'Spunta: da completare');
  assert.equal(notifications.notificationAction({event:{event_type:'item_updated',changed_fields:['description','name'],details:{description:'xxx',name:'yyy'}}}), 'Descrizione: xxx · Titolo: yyy');
  assert.equal(notifications.notificationAction({event:{event_type:'item_updated',changed_fields:['barcodes']}}), 'Barcode: modificato');
  assert.equal(notifications.notificationDate({action_at:'2026-11-07T01:00:00+01:00'}).toISOString(), '2026-11-07T00:00:00.000Z');
  assert.equal(notifications.notificationDate({created_at:'2026-11-07T00:00:00'}).toISOString(), '2026-11-07T00:00:00.000Z');
});

test('creation notifications show the initial name and quantity or checklist status', () => {
  for (const [type, quantity, expected] of [
    ['INVENTORY', 0, 'Nuovo elemento · Quantità: 0'],
    ['INVENTORY', 6, 'Nuovo elemento · Quantità: 6'],
    ['CHECKLIST', 0, 'Nuovo elemento · Spunta: da completare'],
    ['CHECKLIST', 1, 'Nuovo elemento · Spunta: completato'],
  ]) {
    const row = {inventory_type: type, item_name: 'Renamed', event: {
      event_type: 'item_updated', operation: 'created', quantity, changed_fields: ['name'],
      details: {name: 'Original'},
    }};
    assert.equal(notifications.notificationAction(row), expected);
    assert.equal(notifications.notificationItemName(row), 'Original');
  }
  assert.equal(notifications.notificationItemName({item_name: 'Current', event: {event_type: 'item_updated'}}), 'Current');
});

test('deleted notifications show the snapshot and open only their container', () => {
  for (const [type, path] of [['INVENTORY', 'inventories'], ['CHECKLIST', 'checklists']]) {
    const row = { id: 21, read_at: null, inventory_type: type, item_name: null, event: {
      event_type: 'item_updated', inventory_id: 7, operation: 'deleted',
      changed_fields: ['name'], details: { name: 'Deleted' },
    }};
    assert.equal(notifications.notificationAction(row), 'Elemento eliminato');
    assert.equal(notifications.notificationItemName(row), 'Deleted');
    assert.equal(notifications.notificationLink(row), `/${path}/7?notification_id=21`);
    row.read_at = '2026-01-01';
    assert.equal(notifications.notificationLink(row), `/${path}/7`);
  }
});

test('item creation submits initial metadata in the same request', async () => {
  const oldAdapter = api.defaults.adapter;
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } });
  const requests = [];
  api.defaults.adapter = async config => {
    requests.push(config);
    return { config, data: { id: 1 }, status: 201, statusText: 'Created', headers: {} };
  };
  try {
    const payload = {name: 'Item', quantity: 0, inventory_id: 1, metadata_values: [{definition_id: 2, value_text: 'Value'}]};
    await createItem(payload);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/item/');
    assert.deepEqual(JSON.parse(requests[0].data), payload);
  } finally {
    api.defaults.adapter = oldAdapter;
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage);
    else delete globalThis.localStorage;
  }
});

test('notification deep links use the authorized inventory type', () => {
  assert.equal(notifications.notificationLink({ id: 12, read_at: null, inventory_type: 'CHECKLIST', event: { inventory_id: 7 } }), '/checklists/7?notification_id=12');
  assert.equal(notifications.notificationLink({ id: 13, read_at: null, inventory_type: 'INVENTORY', event: { inventory_id: 8 } }), '/inventories/8?notification_id=13');
  assert.equal(notifications.notificationLink({ id: 13, read_at: '2026-01-01', inventory_type: 'INVENTORY', event: { inventory_id: 8 } }), '/inventories/8');
});

test('notification arrow links carry the correct unread id, including for new tabs', () => {
  for (const [type, name, path] of [['INVENTORY', 'Dispensa', 'inventories'], ['CHECKLIST', 'Spesa', 'checklists']]) {
    const render = read_at => renderToStaticMarkup(createElement(MemoryRouter, null,
      createElement(NotificationOpenLink, { row: { id: 21, read_at, inventory_type: type, inventory_name: name, event: { inventory_id: 7 } } }),
    ));
    assert.match(render(null), new RegExp(`href="/${path}/7\\?notification_id=21"`));
    assert.match(render('2026-01-01'), new RegExp(`href="/${path}/7"`));
    assert.match(render(null), new RegExp(`aria-label="Apri (lista|inventario) ${name}"`));
  }
});

test('opening a notification marks only its own row or push event and reports failures', async () => {
  const oldAdapter = api.defaults.adapter;
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const oldWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const requests = [], events = [];
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { dispatchEvent: event => events.push(event.type) } });
  api.defaults.adapter = async config => {
    requests.push(config);
    return { config, data: {}, status: 200, statusText: 'OK', headers: {} };
  };
  try {
    assert.equal(await notifications.markOpenedNotificationRead('?notification_id=12'), true);
    assert.equal(await notifications.markOpenedNotificationRead('?notification_event=event-key'), true);
    assert.equal(await notifications.markOpenedNotificationRead('?other=1'), false);
    assert.deepEqual(requests.map(r => [r.method, r.url]), [
      ['put', '/notifications/12/read'], ['put', '/notifications/events/event-key/read'],
    ]);
    assert.deepEqual(events, [notifications.NOTIFICATIONS_CHANGED, notifications.NOTIFICATIONS_CHANGED]);
    for (const search of ['?notification_id=0', '?notification_id=abc', '?notification_id=99999999999999999999', '?notification_event=', '?notification_id=12&notification_event=abc']) {
      await assert.rejects(notifications.markOpenedNotificationRead(search));
    }
    api.defaults.adapter = async () => { throw new Error('access revoked'); };
    await assert.rejects(notifications.markOpenedNotificationRead('?notification_id=12'), /access revoked/);
    assert.equal(events.length, 2);
  } finally {
    api.defaults.adapter = oldAdapter;
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage);
    else delete globalThis.localStorage;
    if (oldWindow) Object.defineProperty(globalThis, 'window', oldWindow);
    else delete globalThis.window;
  }
});

test('inbox client preserves pagination and sends scoped read requests', async () => {
  const oldAdapter = api.defaults.adapter;
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } });
  const requests = [];
  api.defaults.adapter = async config => {
    requests.push(config);
    return { config, data: config.url.endsWith('unread-count') ? { count: 6 } : [], status: 200, statusText: 'OK', headers: {} };
  };
  try {
    await notifications.getInbox(50);
    assert.deepEqual(requests[0].params, { limit: 50, offset: 50 });
    assert.equal(await notifications.getUnreadCount(), 6);
    await notifications.markNotificationRead(12);
    await notifications.markAllNotificationsRead();
    await notifications.markNotificationEventRead('event-key');
    assert.deepEqual(requests.slice(2).map(r => [r.method, r.url]), [
      ['put', '/notifications/12/read'], ['put', '/notifications/read-all'],
      ['put', '/notifications/events/event-key/read'],
    ]);
  } finally {
    api.defaults.adapter = oldAdapter;
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage);
    else delete globalThis.localStorage;
  }
});

test('personal change preferences never send user/session identities or request browser consent', async () => {
  const oldAdapter = api.defaults.adapter;
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } });
  const requests = [];
  api.defaults.adapter = async config => {
    requests.push(config);
    return { config, data: {}, status: 200, statusText: 'OK', headers: {} };
  };
  try {
    await notifications.saveNotificationPreference({
      event_type: 'item_quantity_changed', in_app_enabled: true, push_enabled: false, include_own_actions: false,
    });
    assert.deepEqual(JSON.parse(requests[0].data), {
      in_app_enabled: true, push_enabled: false, include_own_actions: false,
    });
    assert.equal(requests[0].url, '/notifications/preferences/item_quantity_changed');
    assert.deepEqual(Object.keys(notifications.notificationLabels).sort(), [
      'inventory_updated', 'item_quantity_changed', 'item_updated',
    ]);
    await notifications.saveNotificationPreference({
      event_type: 'item_updated', in_app_enabled: false, push_enabled: true, include_own_actions: false,
    });
    await notifications.saveNotificationPreference({
      event_type: 'inventory_updated', in_app_enabled: false, push_enabled: false, include_own_actions: true,
    });
    assert.deepEqual(requests.map(r => r.url), [
      '/notifications/preferences/item_quantity_changed', '/notifications/preferences/item_updated',
      '/notifications/preferences/inventory_updated',
    ]);
    api.defaults.adapter = async () => { throw new Error('access revoked'); };
    await assert.rejects(notifications.getInbox(), /access revoked/);
    await assert.rejects(notifications.markAllNotificationsRead(), /access revoked/);
    await assert.rejects(notifications.saveNotificationPreference({
      event_type: 'item_updated', in_app_enabled: true, push_enabled: false, include_own_actions: false,
    }), /access revoked/);
  } finally {
    api.defaults.adapter = oldAdapter;
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage);
    else delete globalThis.localStorage;
  }
});
