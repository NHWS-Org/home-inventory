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
const { default: ProfilePage } = await server.ssrLoadModule('/src/pages/ProfilePage.tsx');
const { AuthContext } = await server.ssrLoadModule('/src/auth-context-instance.ts');

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
    'Dati Anagrafici', 'Cambia Password', 'Notifiche push su questo browser',
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
  assert.doesNotMatch(html, /Notifiche push su questo browser/);
});
