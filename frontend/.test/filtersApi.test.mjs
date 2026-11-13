import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const server = await createServer({
  appType: 'custom', configFile: false, logLevel: 'error',
  server: { middlewareMode: true, ws: false },
});
after(() => server.close());

const filters = await server.ssrLoadModule('/src/filtersApi.ts');
const { api } = await server.ssrLoadModule('/src/api.ts');

function useAdapter(handler) {
  const previous = api.defaults.adapter;
  const oldStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } });
  api.defaults.adapter = handler;
  return () => {
    api.defaults.adapter = previous;
    if (oldStorage) Object.defineProperty(globalThis, 'localStorage', oldStorage);
    else delete globalThis.localStorage;
  };
}

function response(config, data = {}) {
  return { config, data, status: 200, statusText: 'OK', headers: {} };
}

test('filter APIs keep mixed fields, signed relative dates, and range endpoints in one request', async () => {
  const requests = [];
  const restore = useAdapter(async config => {
    requests.push(config);
    return response(config, config.url.endsWith('/fields') ? [] : []);
  });
  try {
    await filters.getFilterFields();
    await filters.getFilters(42);
    const input = {
      name: 'Scadenze',
      is_shared: true,
      container_type: 'INVENTORY',
      match_mode: 'all',
      conditions: [
        { source: 'item', field: 'quantity', operator: 'gte', value: 1 },
        { source: 'metadata', field: 'expires_on', definition_id: 8, operator: 'between',
          range_from: { relative_days: -2 }, range_to: { relative_days: 4 } },
      ],
    };
    await filters.previewFilter({ ...input, inventory_id: 42, timezone: 'Europe/Rome' });
    await filters.evaluateFilter(13, { inventory_id: 42, timezone: 'Europe/Rome' });
    assert.deepEqual(requests.map(request => [request.method, request.url]), [
      ['get', '/filters/fields'], ['get', '/filters'], ['post', '/filters/preview'], ['post', '/filters/13/evaluate'],
    ]);
    assert.deepEqual(requests[1].params, { inventory_id: 42 });
    assert.deepEqual(JSON.parse(requests[2].data).conditions, input.conditions);
    assert.deepEqual(JSON.parse(requests[2].data).conditions[1].range_from, { relative_days: -2 });
    assert.deepEqual(JSON.parse(requests[2].data).conditions[1].range_to, { relative_days: 4 });
    assert.deepEqual(JSON.parse(requests[3].data), { inventory_id: 42, timezone: 'Europe/Rome' });
  } finally { restore(); }
});

test('filter validation rejects blank names and empty conditions', () => {
  const valid = { name: 'Filtro', conditions: [{ field: 'name' }] };
  assert.throws(() => filters.validateFilterInput({ ...valid, name: '  ' }), /nome del filtro/);
  assert.throws(() => filters.validateFilterInput({ ...valid, conditions: [] }), /almeno una condizione/);
  assert.doesNotThrow(() => filters.validateFilterInput(valid));
});

test('trigger schedules use ISO weekdays and subscription failures propagate', async () => {
  const requests = [];
  const restore = useAdapter(async config => {
    requests.push(config);
    return response(config, config.url === '/triggers/subscriptions' ? [{ trigger_id: 7, enabled: false }] : {});
  });
  try {
    assert.equal(filters.formatWeekdays([1, 2, 3, 4, 5]), 'Lun – Ven');
    assert.equal(filters.formatWeekdays([1, 2, 3, 4, 5, 6, 7]), 'Ogni giorno');
    assert.equal(filters.formatWeekdays([]), 'Nessun giorno');
    const input = {
      name: 'Promemoria',
      filter_id: 13,
      enabled: true,
      time: '08:30',
      timezone: 'Europe/Rome',
      weekdays: [1, 3, 5],
      inventory_ids: null,
      notify_mode: 'changed',
    };
    await filters.createTrigger(input);
    await filters.previewTrigger(7);
    assert.deepEqual(await filters.getTriggerSubscriptions(), [{ trigger_id: 7, enabled: false }]);
    await filters.saveTriggerSubscription(7, true);
    assert.deepEqual(requests.map(request => [request.method, request.url]), [
      ['post', '/triggers'], ['post', '/triggers/7/preview'], ['get', '/triggers/subscriptions'],
      ['put', '/triggers/7/subscription'],
    ]);
    assert.deepEqual(JSON.parse(requests[0].data), input);
    assert.equal(requests[1].data, undefined);
    assert.deepEqual(JSON.parse(requests[3].data), { enabled: true });

    api.defaults.adapter = async () => { throw new Error('Access revoked'); };
    await assert.rejects(filters.getTriggerSubscriptions(), /Access revoked/);
    await assert.rejects(filters.saveTriggerSubscription(7, false), /Access revoked/);
  } finally { restore(); }
});
