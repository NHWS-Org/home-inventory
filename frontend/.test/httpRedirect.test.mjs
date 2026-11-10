import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');

test('HTTP redirects permanently to HTTPS preserving hostname, path and query', () => {
  const template = read('../nginx.conf.template');
  assert.match(template, /server\s*\{\s*listen 80;\s*server_name _;\s*return 308 https:\/\/\$host:\$\{FRONTEND_HTTPS_PORT\}\$request_uri;\s*\}/);
  assert.match(template, /listen 443 ssl;/);
  assert.match(read('../Dockerfile'), /EXPOSE 80 443/);
  const entrypoint = read('../entrypoint.sh');
  assert.match(entrypoint, /envsubst '\$\{BACKEND_BASE_URL\} \$\{FRONTEND_HTTPS_PORT\}'/);
});

test('both Compose files publish HTTP and route redirects to the published HTTPS port', () => {
  for (const path of ['../../docker-compose.yml', '../../docker-compose-dev.yml']) {
    const compose = read(path);
    assert.match(compose, /FRONTEND_HTTPS_PORT: \$\{FRONTEND_PORT:-443\}/);
    assert.match(compose, /"\$\{FRONTEND_HTTP_PORT:-80\}:80"/);
    assert.match(compose, /"\$\{FRONTEND_PORT:-443\}:443"/);
  }
});

test('HTTPS redirect port defaults to 443, supports overrides and rejects invalid ports', () => {
  const entrypoint = read('../entrypoint.sh');
  const start = entrypoint.indexOf('export FRONTEND_HTTPS_PORT=');
  const end = entrypoint.indexOf('\nenvsubst ', start);
  assert.ok(start >= 0 && end > start);
  const validation = entrypoint.slice(start, end);
  for (const [port, expected] of [['', '443'], ['443', '443'], ['3000', '3000'], ['65535', '65535']]) {
    const result = spawnSync('sh', ['-c', `${validation}\nprintf '%s' "$FRONTEND_HTTPS_PORT"`], {
      env: { ...process.env, FRONTEND_HTTPS_PORT: port },
      encoding: 'utf8',
    });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, expected);
  }
  for (const port of ['0', '65536', '-1', '443/path', '443;bad', 'abc']) {
    const result = spawnSync('sh', ['-c', validation], {
      env: { ...process.env, FRONTEND_HTTPS_PORT: port },
      encoding: 'utf8',
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Invalid FRONTEND_HTTPS_PORT/);
  }
});
