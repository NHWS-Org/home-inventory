import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());
const notifications = await server.ssrLoadModule('/src/notificationsApi.ts');
const { api } = await server.ssrLoadModule('/src/api.ts');

test('compact actions show signed deltas, checks, historical text and legacy labels', () => {
  assert.equal(notifications.notificationAction({inventory_type:'INVENTORY', event:{event_type:'item_quantity_changed', previous_quantity:2,quantity:3}}), 'Quantità: +1');
  assert.equal(notifications.notificationAction({inventory_type:'INVENTORY', event:{event_type:'item_quantity_changed', previous_quantity:5,quantity:2}}), 'Quantità: -3');
  assert.equal(notifications.notificationAction({inventory_type:'CHECKLIST', event:{event_type:'item_quantity_changed', previous_quantity:1,quantity:0}}), 'Spunta: da completare');
  assert.equal(notifications.notificationAction({event:{event_type:'item_updated',changed_fields:['description','name'],details:{description:'xxx',name:'yyy'}}}), 'Descrizione: xxx · Titolo: yyy');
  assert.equal(notifications.notificationAction({event:{event_type:'item_updated',changed_fields:['barcodes']}}), 'Barcode: modificato');
  assert.equal(notifications.notificationDate({action_at:'2026-11-07T01:00:00+01:00'}).toISOString(), '2026-11-07T00:00:00.000Z');
  assert.equal(notifications.notificationDate({created_at:'2026-11-07T00:00:00'}).toISOString(), '2026-11-07T00:00:00.000Z');
});

test('notification deep links use the authorized inventory type', () => {
  assert.equal(notifications.notificationLink({ inventory_type: 'CHECKLIST', event: { inventory_id: 7 } }), '/checklists/7');
  assert.equal(notifications.notificationLink({ inventory_type: 'INVENTORY', event: { inventory_id: 8 } }), '/inventories/8');
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
    assert.deepEqual(requests.slice(2).map(r => [r.method, r.url]), [
      ['put', '/notifications/12/read'], ['put', '/notifications/read-all'],
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
