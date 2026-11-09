import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());
const { default: NotificationBell } = await server.ssrLoadModule('/src/components/NotificationBell.tsx');

function renderBell(variant, count, error = false, path = '/') {
  return renderToStaticMarkup(createElement(
    MemoryRouter, { initialEntries: [path] },
    createElement(NotificationBell, { variant, count, error, navItemClass: active => active ? 'mobile-active' : 'mobile-inactive' }),
  ));
}

for (const variant of ['desktop', 'mobile']) {
  test(`${variant} notification navigation distinguishes zero, unread, loading and error`, () => {
    const zero = renderBell(variant, 0);
    assert.match(zero, /aria-label="Notifiche: 0 da leggere"/);
    assert.doesNotMatch(zero, /rounded-full|notification-bell-ringing/);
    const unread = renderBell(variant, 3);
    assert.match(unread, /aria-label="Notifiche: 3 da leggere"/);
    assert.match(unread, /notification-bell-ringing/);
    assert.match(unread, /rounded-full[^"]*"[^>]*>3<\/span>/);
    assert.match(renderBell(variant, 150), /aria-label="Notifiche: 150 da leggere"/);
    assert.match(renderBell(variant, 150), />99\+<\/span>/);
    const loading = renderBell(variant, null);
    assert.match(loading, /Notifiche: caricamento/);
    assert.doesNotMatch(loading, /rounded-full|notification-bell-ringing/);
    const error = renderBell(variant, null, true);
    assert.match(error, /Notifiche: conteggio non disponibile/);
    assert.match(error, />!<\/span>/);
    assert.doesNotMatch(error, /notification-bell-ringing/);
    const active = renderBell(variant, 0, false, '/notifications');
    assert.match(active, /aria-current="page"/);
    assert.match(active, variant === 'mobile' ? /mobile-active/ : /bg-gradient-to-r/);
  });
}
