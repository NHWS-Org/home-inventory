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
const { api, compareBackups } = await server.ssrLoadModule('/src/api.ts');

test('comparison client preserves direction, filters, pagination and cancellation', async () => {
  const originalPost = api.post;
  const signal = new AbortController().signal;
  const result = { total_changes: 0, changes: [], tables: [] };
  const requests = [];
  api.post = async (...args) => {
    requests.push(args);
    return { data: result };
  };
  try {
    assert.equal(await compareBackups('first.hibackup', null, null, 0, signal), result);
    assert.equal(await compareBackups('first.hibackup', 'second.hibackup', 'items', 50, signal), result);
    assert.deepEqual(requests, [
      ['/backup/compare', {
        before_filename: 'first.hibackup', after_filename: null, table: null, offset: 0, limit: 50,
      }, { signal }],
      ['/backup/compare', {
        before_filename: 'first.hibackup', after_filename: 'second.hibackup', table: 'items', offset: 50, limit: 50,
      }, { signal }],
    ]);
  } finally {
    api.post = originalPost;
  }
});

test('comparison client propagates API errors', async () => {
  const originalPost = api.post;
  const failure = new Error('Comparison failed');
  api.post = async () => { throw failure; };
  try {
    await assert.rejects(
      compareBackups('first.hibackup', null, null, 0, new AbortController().signal),
      error => error === failure,
    );
  } finally {
    api.post = originalPost;
  }
});
