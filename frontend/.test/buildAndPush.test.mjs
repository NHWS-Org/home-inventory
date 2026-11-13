import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const script = new URL('../../build_and_push.sh', import.meta.url).pathname;

test('build script reads VERSION without backend env and produces release/dev tags', () => {
  const dir = mkdtempSync(join(tmpdir(), 'inventory-build-'));
  try {
    mkdirSync(join(dir, 'backend'));
    mkdirSync(join(dir, 'frontend'));
    writeFileSync(join(dir, 'backend/VERSION'), '1.6.0\n');
    writeFileSync(join(dir, 'frontend/package.json'), '{"version":"1.6.0"}');
    for (const channel of ['dev', 'release']) {
      const result = spawnSync('bash', [script, channel], { cwd: dir, input: 'n\nn\n', encoding: 'utf8' });
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /Ultima versione di Backend: 1\.6\.0/);
      const suffix = channel === 'dev' ? '-dev' : '';
      assert.ok(result.stdout.includes(`home-inventory-backend:1.6.0${suffix}`));
      assert.ok(result.stdout.includes(`home-inventory-frontend:1.6.0${suffix}`));
      assert.match(result.stdout, /Costruzione dell'immagine per Backend saltato/);
      assert.match(result.stdout, /Costruzione dell'immagine per Frontend saltato/);
    }
    writeFileSync(join(dir, 'backend/VERSION'), 'invalid\n');
    const invalid = spawnSync('bash', [script, 'dev'], { cwd: dir, input: 'n\nn\n', encoding: 'utf8' });
    assert.notEqual(invalid.status, 0);
    assert.match(invalid.stderr, /versione del Backend non valida/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
