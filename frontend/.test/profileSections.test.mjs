import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createElement } from 'react';
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
