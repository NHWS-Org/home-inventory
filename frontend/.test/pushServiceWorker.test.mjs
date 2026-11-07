import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../public/push-sw.js', import.meta.url), 'utf8');

function createWorker() {
  const listeners = new Map();
  const calls = [];
  const windows = [];
  const self = {
    location: { origin: 'https://inventory.example' },
    registration: {
      showNotification: async (...args) => calls.push(['showNotification', ...args]),
    },
    clients: {
      claim: async () => calls.push(['claim']),
      matchAll: async () => windows,
      openWindow: async (url) => calls.push(['openWindow', url]),
    },
    skipWaiting: async () => calls.push(['skipWaiting']),
    addEventListener: (name, callback) => listeners.set(name, callback),
  };
  vm.runInNewContext(source, { self, URL, JSON, Promise, RegExp });
  return { listeners, calls, windows };
}

test('minimal worker activates and never installs a fetch/cache handler', async () => {
  const { listeners, calls } = createWorker();
  assert.deepEqual([...listeners.keys()].sort(), ['activate', 'install', 'notificationclick', 'push']);
  let wait;
  listeners.get('install')({ waitUntil: (promise) => { wait = promise; } });
  await wait;
  assert.deepEqual(calls, [['skipWaiting']]);
  listeners.get('activate')({ waitUntil: (promise) => { wait = promise; } });
  await wait;
  assert.deepEqual(calls.at(-1), ['claim']);
});

test('push displays detailed payload without touching authenticated API or cache', async () => {
  const { listeners, calls } = createWorker();
  let wait;
  listeners.get('push')({
    data: { json: () => ({
      title: 'Inventario: Dispensa', body: 'Riso · Quantità: +1 (2 → 3)',
      tag: 'event-123', url: '/inventories/12',
    }) },
    waitUntil: (promise) => { wait = promise; },
  });
  await wait;
  const [name, title, options] = calls[0];
  assert.equal(name, 'showNotification');
  assert.equal(title, 'Inventario: Dispensa');
  assert.equal(options.body, 'Riso · Quantità: +1 (2 → 3)');
  assert.equal(options.data.url, 'https://inventory.example/inventories/12');
  assert.equal(options.tag, 'event-123');
});

test('malformed payload uses generic safe defaults', async () => {
  const { listeners, calls } = createWorker();
  let wait;
  listeners.get('push')({
    data: { json: () => { throw new Error('invalid'); } },
    waitUntil: (promise) => { wait = promise; },
  });
  await wait;
  assert.equal(calls[0][1], 'Home Inventory');
  assert.equal(calls[0][2].body, 'Hai una nuova notifica');
  assert.equal(calls[0][2].data.url, 'https://inventory.example/');
});

test('detailed Unicode titles and long bodies are not replaced with generic defaults', async () => {
  const { listeners, calls } = createWorker();
  const title = '😀'.repeat(80);
  const body = '😀'.repeat(500);
  let wait;
  listeners.get('push')({
    data: { json: () => ({ title, body, tag: 'event-456', url: '/checklists/2' }) },
    waitUntil: promise => { wait = promise; },
  });
  await wait;
  assert.equal(calls[0][1], title);
  assert.equal(calls[0][2].body, body);
  assert.equal(calls[0][2].data.url, 'https://inventory.example/checklists/2');
});

test('notification click focuses an existing same-origin window and navigates to the resource', async () => {
  const { listeners, calls, windows } = createWorker();
  const clientCalls = [];
  const sameOriginClient = {
    url: 'https://inventory.example/profile',
    navigate: async (url) => {
      clientCalls.push(['navigate', url]);
      return sameOriginClient;
    },
    focus: async () => clientCalls.push(['focus']),
  };
  windows.push(sameOriginClient);
  let wait;
  listeners.get('notificationclick')({
    notification: { data: { url: 'https://inventory.example/inventories/12?item=2' }, close() {} },
    waitUntil: (promise) => { wait = promise; },
  });
  await wait;
  assert.deepEqual(clientCalls, [
    ['navigate', 'https://inventory.example/inventories/12?item=2'], ['focus'],
  ]);
  assert.deepEqual(calls, []);
});

test('notification click opens a window when existing client cannot navigate', async () => {
  const { listeners, calls, windows } = createWorker();
  windows.push({
    url: 'https://inventory.example/profile',
    navigate: async () => null,
    focus: async () => {},
  });
  let wait;
  listeners.get('notificationclick')({
    notification: { data: { url: '/inventories/12' }, close() {} },
    waitUntil: (promise) => { wait = promise; },
  });
  await wait;
  assert.deepEqual(calls, [['openWindow', 'https://inventory.example/inventories/12']]);
});

test('notification click opens safe same-origin link when no app window exists', async () => {
  const { listeners, calls } = createWorker();
  let wait;
  listeners.get('notificationclick')({
    notification: { data: { url: '/notifications' }, close() {} },
    waitUntil: (promise) => { wait = promise; },
  });
  await wait;
  assert.deepEqual(calls, [['openWindow', 'https://inventory.example/notifications']]);
});

test('external, protocol-relative and malformed notification destinations fall back to app home', async () => {
  for (const url of [
    'https://attacker.example/', '//attacker.example/', 'javascript:alert(1)',
    '/\\attacker.example/', '/path\nheader',
  ]) {
    const { listeners, calls } = createWorker();
    let wait;
    listeners.get('notificationclick')({
      notification: { data: { url }, close() {} },
      waitUntil: (promise) => { wait = promise; },
    });
    await wait;
    assert.deepEqual(calls, [['openWindow', 'https://inventory.example/']], url);
  }
});
