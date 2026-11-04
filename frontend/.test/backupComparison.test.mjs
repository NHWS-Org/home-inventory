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
const { api, compareBackups, convertLegacyBackup, deleteLegacyBackup } = await server.ssrLoadModule('/src/api.ts');

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

test('legacy conversion and source deletion are separate requests', async () => {
  const originalPost = api.post;
  const originalRequest = api.request;
  const calls = [];
  api.post = async (...args) => {
    calls.push(args);
    return { data: { filename: 'old backup.hibackup' } };
  };
  api.request = async config => { calls.push(config); };
  try {
    assert.deepEqual(await convertLegacyBackup('old backup.sql'), { filename: 'old backup.hibackup' });
    assert.equal(calls.length, 1);
    await deleteLegacyBackup('old backup.sql');
    assert.deepEqual(calls, [
      ['/backup/convert-legacy/old%20backup.sql'],
      { url: '/backup/legacy/old%20backup.sql', method: 'DELETE', data: true },
    ]);
  } finally {
    api.post = originalPost;
    api.request = originalRequest;
  }
});
