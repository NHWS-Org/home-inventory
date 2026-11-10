import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createServer } from 'vite';

const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example/' });
const originals = new Map();
for (const [key, value] of Object.entries({
  window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
  localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
})) {
  originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
  Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
}
const { createRoot } = await import('react-dom/client');
const server = await createServer({ appType: 'custom', configFile: false, logLevel: 'error', server: { middlewareMode: true, ws: false } });
const { default: WelcomePage } = await server.ssrLoadModule('/src/pages/WelcomePage.tsx');
const { AuthContext } = await server.ssrLoadModule('/src/auth-context-instance.ts');
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

test('moderator loads recents with configured limit, reports errors and retries', async () => {
  let failure = '';
  const requests = [];
  api.defaults.adapter = async config => {
    requests.push({ url: config.url, params: config.params });
    if (config.url === failure) throw new Error('offline');
    let data;
    if (config.url === '/') data = { title: 'Home', message: 'Benvenuto', stats: {} };
    else if (config.url === '/system/recent-items-limit') data = { limit: 7 };
    else if (config.url === '/recents') data = [{ id: 1, type: 'INVENTORY', name: 'Dispensa', data_mod: '2026-01-01', username_mod: 'editor' }];
    else throw new Error(`Unexpected request: ${config.url}`);
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
  const render = user => root.render(createElement(AuthContext.Provider, {
    value: { user, isLoading: false, setUser: () => {}, logout: async () => {} },
  }, createElement(WelcomePage)));
  const user = { id: 1, username: 'moderator', role: { name: 'moderator' } };
  await act(async () => render(user));
  assert.match(document.body.textContent, /Dispensa/);
  assert.deepEqual(requests.find(request => request.url === '/recents').params, { limit: 7 });
  assert.ok(!requests.some(request => request.url.startsWith('/settings')));

  failure = '/system/recent-items-limit';
  await act(async () => render({ ...user, id: 2 }));
  assert.match(document.querySelector('[role="alert"]').textContent, /Impossibile caricare gli ultimi/);
  assert.doesNotMatch(document.body.textContent, /Dispensa/);
  failure = '/recents';
  await act(async () => [...document.querySelectorAll('button')].find(button => button.textContent === 'Riprova').click());
  assert.match(document.querySelector('[role="alert"]').textContent, /Impossibile caricare gli ultimi/);
  failure = '';
  await act(async () => [...document.querySelectorAll('button')].find(button => button.textContent === 'Riprova').click());
  assert.match(document.body.textContent, /Dispensa/);
  await act(async () => render(null));
  assert.doesNotMatch(document.body.textContent, /Dispensa/);
});
