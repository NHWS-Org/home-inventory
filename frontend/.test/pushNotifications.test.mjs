import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom',
  configFile: false,
  logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());
const push = await server.ssrLoadModule('/src/utils/pushNotifications.ts');
const { api } = await server.ssrLoadModule('/src/api.ts');

const publicKey = Buffer.from(Uint8Array.from(
  [4, ...Array.from({ length: 64 }, (_, index) => index + 1)],
)).toString('base64url');

function browserHarness({ permission = 'default', existing = null } = {}) {
  const storage = new Map();
  const requests = [];
  const events = [];
  let subscription = existing;
  const registration = {
    pushManager: {
      getSubscription: async () => subscription,
      subscribe: async (options) => {
        events.push(['subscribe', options]);
        subscription = {
          expirationTime: null,
          options: { applicationServerKey: options.applicationServerKey },
          toJSON: () => ({
            endpoint: 'https://fcm.googleapis.com/fcm/send/browser-test',
            expirationTime: null,
            keys: { p256dh: publicKey, auth: 'YWFhYWFhYWFhYWFhYWFhYQ' },
          }),
          unsubscribe: async () => { events.push(['unsubscribe']); subscription = null; return true; },
        };
        return subscription;
      },
    },
    showNotification: async (...args) => events.push(['showNotification', ...args]),
  };
  const originalAdapter = api.defaults.adapter;
  api.defaults.adapter = async (config) => {
    const path = config.url;
    requests.push({ method: config.method, path, data: config.data });
    if (path === '/notifications/push/config') {
      return { config, data: { public_key: publicKey, payload_mode: 'detailed', ttl_seconds: 300 }, status: 200, statusText: 'OK', headers: {} };
    }
    if (path === '/notifications/push/subscriptions' && config.method === 'get') {
      return { config, data: [{ id: 41, expires_at: '2099-01-01T00:00:00' }], status: 200, statusText: 'OK', headers: {} };
    }
    if (path === '/notifications/push/subscriptions' && config.method === 'post') {
      return { config, data: { id: 41, expires_at: '2099-01-01T00:00:00', payload_mode: 'detailed' }, status: 201, statusText: 'Created', headers: {} };
    }
    if (path === '/notifications/push/subscriptions/41' && config.method === 'delete') {
      return { config, data: { deleted: 1 }, status: 200, statusText: 'OK', headers: {} };
    }
    throw new Error(`Unexpected API request: ${config.method} ${path}`);
  };
  const originalDescriptors = new Map(
    ['window', 'navigator', 'Notification', 'PushManager', 'localStorage'].map(
      (key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)],
    ),
  );
  const setGlobal = (key, value) => Object.defineProperty(globalThis, key, {
    configurable: true, enumerable: true, writable: true, value,
  });
  setGlobal('localStorage', {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  });
  setGlobal('Notification', {
    permission,
    requestPermission: async () => {
      events.push(['permission']);
      globalThis.Notification.permission = 'granted';
      return 'granted';
    },
  });
  setGlobal('PushManager', class PushManager {});
  setGlobal('navigator', {
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0',
    platform: 'Linux x86_64',
    maxTouchPoints: 0,
    serviceWorker: {
      register: async (...args) => { events.push(['register', ...args]); return registration; },
      getRegistration: async () => registration,
    },
  });
  setGlobal('window', {
    isSecureContext: true,
    location: { hostname: 'localhost', protocol: 'http:' },
    matchMedia: () => ({ matches: false }),
    Notification: globalThis.Notification,
    PushManager: globalThis.PushManager,
  });
  return {
    storage, requests, events, registration,
    setSubscription: (value) => { subscription = value; },
    restore() {
      api.defaults.adapter = originalAdapter;
      for (const [key, descriptor] of originalDescriptors) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    },
  };
}

test('capability states distinguish insecure, unsupported, denied and iOS installation requirements', () => {
  const base = {
    secureContext: true, hostname: 'example.com', userAgent: 'Chrome',
    platform: 'Linux', maxTouchPoints: 0, standalone: false,
    hasNotification: true, hasServiceWorker: true, hasPushManager: true,
  };
  assert.equal(push.detectPushAvailability({ ...base, secureContext: false }), 'insecure');
  assert.equal(push.detectPushAvailability({ ...base, hasPushManager: false }), 'unsupported');
  assert.equal(push.detectPushAvailability({
    ...base, userAgent: 'iPhone; CPU iPhone OS 16_3 like Mac OS X',
  }), 'ios-version-required');
  assert.equal(push.detectPushAvailability({
    ...base, userAgent: 'iPhone; CPU iPhone OS 17_0 like Mac OS X',
  }), 'install-required');
  assert.equal(push.detectPushAvailability({
    ...base, userAgent: 'iPhone; CPU iPhone OS 17_0 like Mac OS X', standalone: true,
  }), 'supported');
  assert.equal(push.detectPushAvailability({
    ...base, userAgent: 'Macintosh', platform: 'MacIntel', maxTouchPoints: 5,
  }), 'install-required');
  assert.equal(push.detectPushAvailability({
    ...base, hostname: 'localhost', secureContext: false,
  }), 'supported');
});

test('VAPID public key decoder accepts only uncompressed P-256 sized base64url', () => {
  const decoded = push.decodeVapidPublicKey(publicKey);
  assert.equal(decoded.length, 65);
  assert.equal(decoded[0], 4);
  for (const invalid of ['', 'https://example.test', '!!!!', 'AQ', 'A'.repeat(87)]) {
    assert.throws(() => push.decodeVapidPublicKey(invalid), /Chiave VAPID non valida/);
  }
});

test('permission prompt is called on the user action before service worker and API work', async () => {
  const harness = browserHarness();
  try {
    await push.enablePushForBrowser('alice');
    assert.equal(harness.events[0][0], 'permission');
    assert.equal(harness.events[1][0], 'register');
    const request = harness.requests.find((row) => row.method === 'post');
    assert.equal(request.path, '/notifications/push/subscriptions');
    const body = JSON.parse(request.data);
    assert.equal(body.consent, true);
    assert.equal(body.endpoint, 'https://fcm.googleapis.com/fcm/send/browser-test');
    assert.equal(body.user_id, undefined);
    assert.equal(body.session_id, undefined);
    assert.equal(harness.storage.get('web_push_owner'), 'alice');
    assert.equal(harness.storage.get('web_push_subscription_id:alice'), '41');
    assert.equal(harness.storage.get(`web_push_public_key:alice`), publicKey);
  } finally {
    harness.restore();
  }
});

test('existing subscription is not re-prompted and an enabled browser can show a local test', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    assert.equal(harness.events.some(([name]) => name === 'permission'), false);
    await push.testPushOnBrowser();
    const notification = harness.events.find(([name]) => name === 'showNotification');
    assert.equal(notification[1], 'Home Inventory · Test');
    assert.equal(notification[2].data.url, '/profile');
  } finally {
    harness.restore();
  }
});

test('browser state is active only when native subscription and authenticated session record match', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    assert.deepEqual(await push.inspectPushBrowser('alice'), {
      state: 'active',
      configuration: { public_key: publicKey, payload_mode: 'detailed', ttl_seconds: 300 },
    });
    assert.equal((await push.inspectPushBrowser('bob')).state, 'expired');
    assert.equal(harness.events.some(([name]) => name === 'unsubscribe'), true);
    assert.equal(harness.storage.has('web_push_owner'), false);
  } finally {
    harness.restore();
  }
});

test('reset browser permission cannot leave the push status active', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    assert.equal((await push.inspectPushBrowser('alice')).state, 'active');
    globalThis.Notification.permission = 'default';
    assert.equal((await push.inspectPushBrowser('alice')).state, 'permission-required');
    assert.equal(harness.storage.get('web_push_subscription_id:alice'), '41');
    globalThis.Notification.permission = 'granted';
    assert.equal((await push.inspectPushBrowser('alice')).state, 'active');
  } finally {
    harness.restore();
  }
});

test('granted browser permission without an existing association is not a stale subscription', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    assert.equal((await push.inspectPushBrowser('alice')).state, 'permission-required');
    harness.storage.set('web_push_owner', 'alice');
    harness.storage.set('web_push_subscription_id:alice', '41');
    assert.equal((await push.inspectPushBrowser('alice')).state, 'expired');
  } finally {
    harness.restore();
  }
});

test('failed server cleanup retains association for an explicit retry', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    const successAdapter = api.defaults.adapter;
    api.defaults.adapter = async (config) => {
      if (config.method === 'delete') throw new Error('server unavailable');
      return successAdapter(config);
    };
    await assert.rejects(push.disablePushForBrowser('alice'), /server unavailable/);
    assert.equal(harness.storage.get('web_push_owner'), 'alice');
    assert.equal(harness.storage.get('web_push_subscription_id:alice'), '41');
    assert.equal((await push.inspectPushBrowser('alice')).state, 'expired');
    api.defaults.adapter = successAdapter;
    await push.disablePushForBrowser('alice');
    assert.equal(harness.storage.has('web_push_owner'), false);
    assert.equal(harness.storage.has('web_push_subscription_id:alice'), false);
  } finally {
    harness.restore();
  }
});

test('failed native unsubscribe retains association until cleanup succeeds', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    const subscription = await harness.registration.pushManager.getSubscription();
    const unsubscribe = subscription.unsubscribe;
    subscription.unsubscribe = async () => false;
    await assert.rejects(push.disablePushForBrowser('alice'), /non ha confermato/);
    assert.equal(harness.storage.get('web_push_subscription_id:alice'), '41');
    subscription.unsubscribe = unsubscribe;
    await push.disablePushForBrowser('alice');
    assert.equal(harness.storage.has('web_push_owner'), false);
    assert.equal(await harness.registration.pushManager.getSubscription(), null);
  } finally {
    harness.restore();
  }
});

test('disable removes server record, unsubscribes this browser and clears local association', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    await push.disablePushForBrowser('alice');
    assert.ok(harness.requests.some((row) => row.method === 'delete' && row.path.endsWith('/41')));
    assert.equal(harness.events.filter(([name]) => name === 'unsubscribe').length, 1);
    assert.equal(harness.storage.has('web_push_owner'), false);
    assert.equal(await harness.registration.pushManager.getSubscription(), null);
  } finally {
    harness.restore();
  }
});

test('expired VAPID key unsubscribes the stale browser subscription and requires renewal', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    const { decodeVapidPublicKey } = push;
    const old = await harness.registration.pushManager.getSubscription();
    old.options.applicationServerKey = decodeVapidPublicKey(
      Buffer.from(Uint8Array.from([4, ...Array(64).fill(99)])).toString('base64url'),
    ).buffer;
    harness.setSubscription(old);
    assert.equal((await push.inspectPushBrowser('alice')).state, 'expired');
    assert.equal(harness.events.some(([name]) => name === 'unsubscribe'), true);
    assert.equal(harness.storage.get('web_push_subscription_id:alice'), '41');
    await push.enablePushForBrowser('alice');
    assert.ok(harness.requests.some((row) => row.method === 'delete' && row.path.endsWith('/41')));
    assert.equal((await push.inspectPushBrowser('alice')).state, 'active');
  } finally {
    harness.restore();
  }
});

test('expired native subscription retains its server id until renewal can remove it', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    const old = await harness.registration.pushManager.getSubscription();
    old.expirationTime = Date.now() - 1;
    harness.setSubscription(old);
    assert.equal((await push.inspectPushBrowser('alice')).state, 'expired');
    assert.equal(harness.storage.get('web_push_subscription_id:alice'), '41');
    await push.enablePushForBrowser('alice');
    assert.ok(harness.requests.some((row) => row.method === 'delete' && row.path.endsWith('/41')));
    assert.equal((await push.inspectPushBrowser('alice')).state, 'active');
  } finally {
    harness.restore();
  }
});

test('denied permission does not prompt again and profile cleanup remains possible', async () => {
  const harness = browserHarness({ permission: 'granted' });
  try {
    await push.enablePushForBrowser('alice');
    globalThis.Notification.permission = 'denied';
    assert.equal((await push.inspectPushBrowser('alice')).state, 'denied');
    await push.disablePushForBrowser('alice');
    assert.equal(harness.events.filter(([name]) => name === 'unsubscribe').length, 1);
    assert.equal(harness.storage.has('web_push_owner'), false);
  } finally {
    harness.restore();
  }
});
