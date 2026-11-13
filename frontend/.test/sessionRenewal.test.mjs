import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());
const { renewSessionOnActivity } = await server.ssrLoadModule('/src/utils/sessionRenewal.ts');
const { api } = await server.ssrLoadModule('/src/api.ts');

function token(iat, exp) {
  const payload = Buffer.from(JSON.stringify({ iat, exp })).toString('base64url');
  return `header.${payload}.signature`;
}

function harness(initialToken, subscription = null) {
  const previous = new Map(['window', 'navigator', 'Notification', 'PushManager', 'localStorage']
    .map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const setGlobal = (key, value) => Object.defineProperty(globalThis, key, {
    configurable: true, writable: true, value,
  });
  const storage = new Map([['access_token', initialToken]]);
  const events = [];
  setGlobal('localStorage', {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: key => storage.delete(key),
  });
  setGlobal('Notification', { permission: 'granted' });
  setGlobal('PushManager', class {});
  setGlobal('window', {
    isSecureContext: true, location: { hostname: 'localhost', pathname: '/profile', search: '', hash: '', replace() {} },
    matchMedia: () => ({ matches: false }), Notification: globalThis.Notification, PushManager: globalThis.PushManager,
    dispatchEvent: event => { events.push(event.type); },
  });
  setGlobal('navigator', {
    userAgent: 'Chrome', platform: 'Linux', maxTouchPoints: 0,
    serviceWorker: { getRegistration: async () => ({ pushManager: { getSubscription: async () => subscription } }) },
  });
  const adapter = api.defaults.adapter;
  return {
    storage, events,
    restore() {
      api.defaults.adapter = adapter;
      for (const [key, descriptor] of previous) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else delete globalThis[key];
      }
    },
  };
}

const day = 86400;
const now = () => Math.floor(Date.now() / 1000);

test('ten-day token is not renewed before its five-day threshold', async () => {
  const h = harness(token(now() - 4 * day, now() + 6 * day));
  try {
    api.defaults.adapter = async () => { throw new Error('unexpected request'); };
    assert.equal(await renewSessionOnActivity('alice'), null);
  } finally { h.restore(); }
});

test('client requests renewal strictly below half of the ten-day lifetime', async () => {
  const actualNow = Date.now;
  const fixed = 1_800_000_000;
  const h = harness(token(fixed - 5 * day, fixed + 5 * day));
  let requests = 0;
  try {
    Date.now = () => fixed * 1000;
    api.defaults.adapter = async config => {
      requests++;
      return { config, status: 200, statusText: 'OK', headers: {},
        data: { access_token: token(fixed, fixed + 10 * day), renewed: true, push_extended: null } };
    };
    await renewSessionOnActivity('alice');
    assert.equal(requests, 0);
    Date.now = () => (fixed + 1) * 1000;
    await renewSessionOnActivity('alice');
    assert.equal(requests, 1);
  } finally { Date.now = actualNow; h.restore(); }
});

test('renewal at less than five days preserves native push details and coalesces requests', async () => {
  const h = harness(token(now() - 6 * day, now() + 4 * day), {
    endpoint: 'https://fcm.googleapis.com/fcm/send/test', expirationTime: 12345678900000,
  });
  h.storage.set('web_push_owner', 'alice');
  h.storage.set('web_push_subscription_id:alice', '41');
  let requests = 0;
  const renewed = token(now(), now() + 10 * day);
  try {
    api.defaults.adapter = async config => {
      requests++;
      assert.equal(config.url, '/auth/renew');
      assert.deepEqual(JSON.parse(config.data), {
        push: { id: 41, endpoint: 'https://fcm.googleapis.com/fcm/send/test', expiration_time: 12345678900000 },
      });
      return { config, status: 200, statusText: 'OK', headers: {},
        data: { access_token: renewed, renewed: true, push_extended: true } };
    };
    assert.deepEqual(await Promise.all([renewSessionOnActivity('alice'), renewSessionOnActivity('alice')]), [null, null]);
    assert.equal(requests, 1);
    assert.equal(h.storage.get('access_token'), renewed);
    assert.deepEqual(h.events, ['home-inventory:session-renewed']);
  } finally { h.restore(); }
});

test('missing native push reports warning while still renewing session', async () => {
  const h = harness(token(now() - 6 * day, now() + 4 * day));
  h.storage.set('web_push_owner', 'alice');
  h.storage.set('web_push_subscription_id:alice', '41');
  const renewed = token(now(), now() + 10 * day);
  try {
    api.defaults.adapter = async config => {
      assert.deepEqual(JSON.parse(config.data), { push: null });
      return { config, status: 200, statusText: 'OK', headers: {},
        data: { access_token: renewed, renewed: true, push_extended: null } };
    };
    assert.match(await renewSessionOnActivity('alice'), /notifiche push non sono state aggiornate/);
    assert.equal(h.storage.get('access_token'), renewed);
  } finally { h.restore(); }
});

test('late renewal never restores a token after logout or overwrites a different login', async () => {
  for (const replacement of [null, token(now(), now() + 10 * day)]) {
    const h = harness(token(now() - 6 * day, now() + 4 * day));
    try {
      api.defaults.adapter = async config => {
        if (replacement) h.storage.set('access_token', replacement);
        else h.storage.delete('access_token');
        return { config, status: 200, statusText: 'OK', headers: {},
          data: { access_token: token(now(), now() + 11 * day), renewed: true, push_extended: null } };
      };
      await renewSessionOnActivity('alice');
      assert.equal(h.storage.get('access_token') ?? null, replacement);
    } finally { h.restore(); }
  }
});

test('stale unauthorized response does not clear a newer token', async () => {
  const old = token(now() - 6 * day, now() + 4 * day);
  const newer = token(now(), now() + 10 * day);
  const h = harness(old);
  try {
    api.defaults.adapter = async config => {
      h.storage.set('access_token', newer);
      throw { config, response: { status: 401 } };
    };
    await assert.rejects(renewSessionOnActivity('alice'));
    assert.equal(h.storage.get('access_token'), newer);
  } finally { h.restore(); }
});

test('renewal errors and invalid tokens are propagated', async () => {
  const h = harness(token(now() - 6 * day, now() + 4 * day));
  try {
    api.defaults.adapter = async () => { throw new Error('offline'); };
    await assert.rejects(renewSessionOnActivity('alice'), /offline/);
    h.storage.set('access_token', 'invalid');
    await assert.rejects(renewSessionOnActivity('alice'), /scadenza della sessione/);
  } finally { h.restore(); }
});
