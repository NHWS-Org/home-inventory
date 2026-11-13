import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readlinkSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const script = new URL('../tls.sh', import.meta.url).pathname;

function command(...args) {
  return execFileSync('openssl', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
}

test('local CA and TLS certificates persist, match names and renew without changing trust', () => {
  const dir = mkdtempSync(join(tmpdir(), 'inventory-tls-'));
  const store = join(dir, 'store'), runtime = join(dir, 'run');
  const run = hosts => spawnSync('bash', [script], { env: { ...process.env, TLS_STORE: store, TLS_RUNTIME: runtime, TLS_HOSTS: hosts, TLS_CERT_FILE: '', TLS_KEY_FILE: '' }, encoding: 'utf8' });
  try {
    let result = run('192.168.1.12,home.example.com');
    assert.equal(result.status, 0, result.stderr);
    const ca = readFileSync(join(store, 'ca/cert.pem'), 'utf8');
    const first = readlinkSync(join(store, 'current'));
    assert.equal(statSync(join(store, 'ca/key.pem')).mode & 0o777, 0o600);
    command('verify', '-CAfile', join(store, 'ca/cert.pem'), join(runtime, 'cert.pem'));
    command('verify', '-verify_hostname', 'home.example.com', '-CAfile', join(store, 'ca/cert.pem'), join(runtime, 'cert.pem'));
    command('verify', '-verify_ip', '192.168.1.12', '-CAfile', join(store, 'ca/cert.pem'), join(runtime, 'cert.pem'));
    assert.throws(() => command('verify', '-verify_hostname', 'wrong.example.com', '-CAfile', join(store, 'ca/cert.pem'), join(runtime, 'cert.pem')));
    assert.match(command('x509', '-in', join(runtime, 'cert.pem'), '-noout', '-checkip', '192.168.1.12'), /does match/);
    assert.match(command('x509', '-in', join(runtime, 'cert.pem'), '-noout', '-checkhost', 'home.example.com'), /does match/);
    result = run('192.168.1.12,home.example.com');
    assert.equal(result.status, 0, result.stderr);
    assert.equal(readlinkSync(join(store, 'current')), first);
    result = run('192.168.1.13,home.example.com');
    assert.equal(result.status, 0, result.stderr);
    assert.notEqual(readlinkSync(join(store, 'current')), first);
    assert.equal(readFileSync(join(store, 'ca/cert.pem'), 'utf8'), ca);
    assert.match(command('x509', '-in', join(runtime, 'cert.pem'), '-noout', '-checkip', '192.168.1.13'), /does match/);

    const current = readlinkSync(join(store, 'current'));
    command('req', '-new', '-key', join(current, 'key.pem'), '-subj', '/CN=Home Inventory', '-out', join(dir, 'short.csr'));
    writeFileSync(join(dir, 'extensions'), 'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1,IP:192.168.1.13,DNS:home.example.com\n');
    command('x509', '-req', '-in', join(dir, 'short.csr'), '-CA', join(store, 'ca/cert.pem'), '-CAkey', join(store, 'ca/key.pem'), '-set_serial', '42', '-days', '1', '-extfile', join(dir, 'extensions'), '-out', join(current, 'cert.pem'));
    result = run('192.168.1.13,home.example.com');
    assert.equal(result.status, 0, result.stderr);
    assert.notEqual(readlinkSync(join(store, 'current')), current);
    assert.equal(readFileSync(join(store, 'ca/cert.pem'), 'utf8'), ca);
    command('verify', '-CAfile', join(store, 'ca/cert.pem'), join(runtime, 'cert.pem'));

    const stable = readlinkSync(join(store, 'current'));
    result = run('home.example.com\nDNS:evil');
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /invalid TLS_HOSTS/);
    assert.equal(readlinkSync(join(store, 'current')), stable);

    command('req', '-new', '-key', join(stable, 'key.pem'), '-subj', '/CN=Home Inventory', '-out', join(dir, 'expired.csr'));
    writeFileSync(join(dir, 'index'), '');
    writeFileSync(join(dir, 'serial'), '43\n');
    writeFileSync(join(dir, 'ca.cnf'), `[ca]\ndefault_ca=local\n[local]\nnew_certs_dir=${dir}\ndatabase=${join(dir, 'index')}\nserial=${join(dir, 'serial')}\nprivate_key=${join(store, 'ca/key.pem')}\ncertificate=${join(store, 'ca/cert.pem')}\ndefault_md=sha256\npolicy=policy\n[policy]\ncommonName=supplied\n`);
    command('ca', '-batch', '-config', join(dir, 'ca.cnf'), '-in', join(dir, 'expired.csr'), '-startdate', '20200101000000Z', '-enddate', '20210101000000Z', '-notext', '-out', join(stable, 'cert.pem'));
    result = run('192.168.1.13,home.example.com');
    assert.equal(result.status, 0, result.stderr);
    assert.notEqual(readlinkSync(join(store, 'current')), stable);
    command('verify', '-CAfile', join(store, 'ca/cert.pem'), join(runtime, 'cert.pem'));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('externally supplied certificates require a readable matching pair', () => {
  const dir = mkdtempSync(join(tmpdir(), 'inventory-custom-tls-'));
  const env = { ...process.env, TLS_STORE: join(dir, 'store'), TLS_RUNTIME: join(dir, 'run'), TLS_CERT_FILE: join(dir, 'cert.pem'), TLS_KEY_FILE: join(dir, 'key.pem') };
  try {
    command('req', '-x509', '-newkey', 'rsa:2048', '-noenc', '-days', '1', '-subj', '/CN=example.com', '-keyout', env.TLS_KEY_FILE, '-out', env.TLS_CERT_FILE);
    let result = spawnSync('bash', [script], { env, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(readlinkSync(join(env.TLS_RUNTIME, 'cert.pem')), env.TLS_CERT_FILE);
    assert.equal(existsSync(join(env.TLS_STORE, 'ca')), false);
    command('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', env.TLS_KEY_FILE);
    result = spawnSync('bash', [script], { env, encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /do not match/);
    result = spawnSync('bash', [script], { env: { ...env, TLS_KEY_FILE: '' }, encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /set both/);
    result = spawnSync('bash', [script], { env: { ...env, TLS_CERT_FILE: 'relative.pem' }, encoding: 'utf8' });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /paths must be absolute/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('default configuration covers localhost and rejects malformed host lists', () => {
  const dir = mkdtempSync(join(tmpdir(), 'inventory-default-tls-'));
  const env = { ...process.env, TLS_STORE: join(dir, 'store'), TLS_RUNTIME: join(dir, 'run'), TLS_CERT_FILE: '', TLS_KEY_FILE: '', TLS_HOSTS: '' };
  try {
    let result = spawnSync('bash', [script], { env, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    command('verify', '-verify_hostname', 'localhost', '-CAfile', join(env.TLS_STORE, 'ca/cert.pem'), join(env.TLS_RUNTIME, 'cert.pem'));
    command('verify', '-verify_ip', '127.0.0.1', '-CAfile', join(env.TLS_STORE, 'ca/cert.pem'), join(env.TLS_RUNTIME, 'cert.pem'));
    for (const hosts of [',example.com', 'example.com,', 'a,,b', '999.999.999.999']) {
      result = spawnSync('bash', [script], { env: { ...env, TLS_HOSTS: hosts }, encoding: 'utf8' });
      assert.notEqual(result.status, 0, hosts);
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
