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
const { safeReturnPath, loginUrl, loginDestination } = await server.ssrLoadModule('/src/utils/loginRedirect.ts');
const { api } = await server.ssrLoadModule('/src/api.ts');

test('login preserves protected paths including QR parameters and fragments', () => {
  for (const path of ['/profile', '/inventories/42?item=7&name=caff%C3%A8#details', '/checklists/12?barcode=123']) {
    const url = loginUrl(path);
    assert.equal(new URL(url, 'https://app.invalid').pathname, '/login');
    assert.equal(loginDestination(new URL(url, 'https://app.invalid').search), path);
  }
});

test('direct login and invalid return paths default to home', () => {
  assert.equal(loginDestination(''), '/');
  for (const path of [
    null, '', 'https://evil.invalid/profile', '//evil.invalid', '/\\evil.invalid',
    'javascript:alert(1)', '/login', '/register?returnTo=/profile', '/x/../login',
    '/profile\n', ' /profile', '/LOGIN', '/login/nested',
  ]) {
    assert.equal(safeReturnPath(path), '/');
  }
  assert.equal(loginUrl('/'), '/login');
});

test('return path encoding is decoded once and cannot create an external redirect', () => {
  assert.equal(loginDestination('?returnTo=%2F%2Fevil.invalid'), '/');
  assert.equal(loginDestination('?returnTo=https%3A%2F%2Fevil.invalid'), '/');
  assert.equal(loginDestination('?returnTo=%252F%252Fevil.invalid'), '/');
  assert.equal(loginDestination('?returnTo=%2Fprofile%3Fnext%3Dhttps%253A%252F%252Fexample.test'), '/profile?next=https%3A%2F%2Fexample.test');
});

test('401 redirects preserve the current page but never redirect a failed login again', async () => {
  const originalWindow = globalThis.window;
  const originalStorage = globalThis.localStorage;
  const originalAdapter = api.defaults.adapter;
  const redirects = [];
  const removed = [];
  globalThis.localStorage = { getItem: () => 'expired', removeItem: key => removed.push(key) };
  globalThis.window = {
    location: {
      pathname: '/profile', search: '?tab=devices', hash: '#sessions',
      replace: url => redirects.push(url),
    },
  };
  api.defaults.adapter = async () => { throw { response: { status: 401 } }; };
  try {
    await assert.rejects(api.get('/auth/me'));
    assert.equal(loginDestination(new URL(redirects[0], 'https://app.invalid').search), '/profile?tab=devices#sessions');
    for (const pathname of ['/login', '/register']) {
      globalThis.window.location.pathname = pathname;
      await assert.rejects(api.get('/auth/me'));
    }
    assert.equal(redirects.length, 1);
    assert.deepEqual(removed, ['access_token', 'access_token', 'access_token']);
  } finally {
    api.defaults.adapter = originalAdapter;
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    if (originalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = originalStorage;
  }
});
