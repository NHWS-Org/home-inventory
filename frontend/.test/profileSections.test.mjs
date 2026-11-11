import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { act, createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom',
  configFile: false,
  logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());
const { default: ProfilePage, PushStatusBadge, DeviceCountBadge } = await server.ssrLoadModule('/src/pages/ProfilePage.tsx');
const { AuthContext } = await server.ssrLoadModule('/src/auth-context-instance.ts');
const { default: PushNotificationsPanel } = await server.ssrLoadModule('/src/components/PushNotificationsPanel.tsx');

function renderProfile(role) {
  return renderToStaticMarkup(createElement(
    MemoryRouter,
    null,
    createElement(
      AuthContext.Provider,
      { value: { user: { username: 'test', role: { name: role } }, isLoading: false } },
      createElement(ProfilePage),
    ),
  ));
}

test('profile sections start collapsed and retain their content for editors', () => {
  const html = renderProfile('admin');
  assert.equal((html.match(/<details class=/g) ?? []).length, 5);
  assert.doesNotMatch(html, /<details[^>]*\sopen(?:[=>\s])/);
  for (const heading of [
    'Dati Anagrafici', 'Cambia Password', 'Attivazione notifiche push',
    'Preferenze notifiche', 'Dispositivi connessi',
  ]) {
    assert.match(html, new RegExp(`<summary[^>]*><h2[^>]*>${heading}</h2>`));
  }
  assert.match(html, /aria-labelledby="profile-push-heading"/);
  assert.match(html, /aria-labelledby="notification-preferences-heading"/);
  assert.match(html, /id="profile-devices-heading"/);
  assert.match(html, /Salva Password/);
  assert.match(html, /Pulisci sessioni scadute \/ disconnesse/);
});

test('viewer profile keeps its notification explanation without push controls', () => {
  const html = renderProfile('viewer');
  assert.equal((html.match(/<details class=/g) ?? []).length, 4);
  assert.match(html, /Gli utenti con sola lettura non le ricevono/);
  assert.doesNotMatch(html, /Attivazione notifiche push/);
});

test('push badge distinguishes active, inactive, checking and error without relying on color', () => {
  for (const [state, label, color] of [
    ['active', 'Notifiche push attive su questo browser', 'text-green-700'],
    ['permission-required', 'Notifiche push non attive su questo browser', 'text-gray-500'],
    ['denied', 'Notifiche push non attive su questo browser', 'text-gray-500'],
    ['expired', 'Notifiche push non attive su questo browser', 'text-gray-500'],
    ['checking', 'Verifica notifiche push in corso', 'text-gray-500'],
    ['error', 'Stato notifiche push non disponibile', 'text-amber-700'],
  ]) {
    const html = renderToStaticMarkup(createElement(PushStatusBadge, { state }));
    assert.match(html, new RegExp(label));
    assert.match(html, new RegExp(color));
    assert.match(html, /class="sr-only"/);
  }
});

test('push activation remains retryable after an error', () => {
  const html = renderToStaticMarkup(createElement(
    AuthContext.Provider,
    { value: { user: { username: 'test' } } },
    createElement(PushNotificationsPanel, { state: 'error', setState: () => {} }),
  ));
  assert.match(html, /Non è stato possibile verificare le notifiche/);
  assert.match(html, /Attiva su questo browser/);
});

test('device badge communicates active session count and unavailable states', () => {
  for (const [status, count, label] of [
    ['ready', 0, '0 sessioni attive'],
    ['ready', 1, '1 sessione attiva'],
    ['ready', 3, '3 sessioni attive'],
    ['loading', 0, 'Verifica dispositivi in corso'],
    ['error', 0, 'Numero dispositivi non disponibile'],
  ]) {
    const sessions = Array.from({ length: count }, () => ({ is_expired: false, revoked_at: null }));
    const html = renderToStaticMarkup(createElement(DeviceCountBadge, { status, sessions }));
    assert.match(html, new RegExp(label));
    assert.match(html, /class="sr-only"/);
  }
});

test('active device count excludes expired and revoked sessions', () => {
  const html = renderToStaticMarkup(createElement(DeviceCountBadge, { status: 'ready', sessions: [
    { is_expired: false, revoked_at: null },
    { is_expired: false, revoked_at: null },
    { is_expired: true, revoked_at: null },
    { is_expired: false, revoked_at: '2026-01-01T00:00:00Z' },
  ] }));
  assert.match(html, /2 sessioni attive/);
});

test('desktop tabs support keyboard navigation and preserve mobile accordions without remounting forms', async () => {
  const { JSDOM } = await import('jsdom');
  const dom = new JSDOM('<div id="root"></div>', { url: 'https://inventory.example/profile' });
  const originals = new Map();
  for (const [key, value] of Object.entries({
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    localStorage: dom.window.localStorage, IS_REACT_ACT_ENVIRONMENT: true,
  })) {
    originals.set(key, Object.getOwnPropertyDescriptor(globalThis, key));
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  }
  const listeners = new Set();
  const media = {
    matches: false,
    addEventListener: (_event, listener) => listeners.add(listener),
    removeEventListener: (_event, listener) => listeners.delete(listener),
  };
  dom.window.matchMedia = () => media;
  const { createRoot } = await import('react-dom/client');
  const { api } = await server.ssrLoadModule('/src/api.ts');
  const adapter = api.defaults.adapter;
  const requests = [];
  api.defaults.adapter = async config => {
    requests.push(config.url);
    const data = config.url === '/auth/me' ? { email_masked: 't***@example.com' } : [];
    return { config, data, status: 200, statusText: 'OK', headers: {} };
  };
  const root = createRoot(document.getElementById('root'));
  const render = role => root.render(createElement(MemoryRouter, null,
    createElement(AuthContext.Provider, {
      value: { user: { username: 'test', role: { name: role } }, isLoading: false },
    }, createElement(ProfilePage)),
  ));
  const resize = async desktop => {
    await act(async () => {
      media.matches = desktop;
      listeners.forEach(listener => listener());
    });
  };
  try {
    await act(async () => render('moderator'));
    assert.equal(document.querySelector('[role="tablist"]'), null);
    const personal = document.querySelector('#profile-panel-personal details');
    const password = document.querySelector('input[type="password"]');
    await act(async () => {
      personal.querySelector('summary').click();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    assert.equal(personal.open, true);

    await resize(true);
    assert.equal(document.querySelectorAll('[role="tab"]').length, 5);
    assert.equal(document.querySelectorAll('[role="tabpanel"]:not([hidden])').length, 1);
    assert.equal(document.querySelector('#profile-tab-personal').getAttribute('aria-selected'), 'true');
    assert.ok([...document.querySelectorAll('summary')].every(summary => summary.hidden));
    await act(async () => document.querySelector('#profile-tab-password').click());
    assert.equal(document.querySelector('#profile-panel-password').hidden, false);
    assert.equal(document.querySelector('input[type="password"]'), password);
    await act(async () => document.querySelector('#profile-tab-password').dispatchEvent(
      new dom.window.KeyboardEvent('keydown', { key: 'End', bubbles: true }),
    ));
    assert.equal(document.activeElement.id, 'profile-tab-devices');
    assert.equal(document.querySelector('#profile-panel-devices').hidden, false);
    assert.equal(document.querySelectorAll('[role="tab"][tabindex="0"]').length, 1);
    for (const [key, expected] of [['Home', 'personal'], ['ArrowLeft', 'devices'], ['ArrowRight', 'personal']]) {
      await act(async () => document.activeElement.dispatchEvent(
        new dom.window.KeyboardEvent('keydown', { key, bubbles: true }),
      ));
      assert.equal(document.activeElement.id, `profile-tab-${expected}`);
    }

    await resize(false);
    assert.equal(document.querySelector('[role="tablist"]'), null);
    assert.equal(personal.open, true);
    assert.equal(document.querySelector('#profile-panel-devices details').open, false);
    assert.equal(document.querySelector('input[type="password"]'), password);
    assert.equal(requests.filter(url => url === '/notifications/preferences').length, 1);

    await resize(true);
    await act(async () => render('viewer'));
    assert.equal(document.querySelectorAll('[role="tab"]').length, 4);
    assert.equal(document.querySelector('#profile-tab-push'), null);
    await act(async () => document.querySelector('#profile-tab-notifications').click());
    assert.match(document.querySelector('#profile-panel-notifications').textContent, /Gli utenti con sola lettura non le ricevono/);
  } finally {
    await act(async () => root.unmount());
    api.defaults.adapter = adapter;
    dom.window.close();
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
});
