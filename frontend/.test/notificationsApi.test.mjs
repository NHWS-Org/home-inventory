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

test('notification deep links use the authorized inventory type, including checklist shares', () => {
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

test('preferences and rule CRUD never send user/session identities or request browser consent', async () => {
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
      event_type: 'inventory_shared', in_app_enabled: true, push_enabled: false, include_own_actions: false,
    });
    assert.deepEqual(JSON.parse(requests[0].data), {
      in_app_enabled: true, push_enabled: false, include_own_actions: false,
    });
    const rule = { event_type: 'item_quantity_changed', threshold: 3, recipients: [{ kind: 'owner' }], enabled: true };
    await notifications.saveNotificationRule(7, rule);
    await notifications.saveNotificationRule(7, rule, 11);
    await notifications.getRuleRecipients(7);
    await notifications.deleteNotificationRule(7, 11);
    assert.deepEqual(requests.slice(1).map(r => [r.method, r.url]), [
      ['post', '/notifications/rules/7'], ['put', '/notifications/rules/7/11'],
      ['get', '/notifications/rules/7/recipients'], ['delete', '/notifications/rules/7/11'],
    ]);
    assert.deepEqual(JSON.parse(requests[1].data), rule);
    api.defaults.adapter = async () => { throw new Error('access revoked'); };
    await assert.rejects(notifications.getInbox(), /access revoked/);
    await assert.rejects(notifications.markAllNotificationsRead(), /access revoked/);
    await assert.rejects(notifications.saveNotificationRule(7, rule), /access revoked/);
  } finally {
    api.defaults.adapter = oldAdapter;
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage);
    else delete globalThis.localStorage;
  }
});
