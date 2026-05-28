import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);

function startServer() {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (req.headers['x-test-auth'] === 'letmein') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(`
          <html>
            <head><title>Authed capture</title></head>
            <body><button id="open-admin">Open admin</button></body>
          </html>
        `);
        return;
      }

      res.writeHead(403, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(`
        <html>
          <head><title>Forbidden</title></head>
          <body>missing header</body>
        </html>
      `);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
    server.on('error', reject);
  });
}

async function stopServer(server) {
  await new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

test('capture-snapshot applies custom HTTP headers', async () => {
  const server = await startServer();
  const address = server.address();
  const tmpRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'nexui-capture-header-'));
  const snapshotDir = path.join(tmpRoot, 'snapshot');

  try {
    const { stdout } = await execFileAsync(
      'node',
      [
        'tools/capture-snapshot.mjs',
        '--url',
        `http://127.0.0.1:${address.port}/`,
        '--snapshot-dir',
        snapshotDir,
        '--http-header',
        'X-Test-Auth=letmein'
      ],
      { cwd: path.resolve('.') }
    );

    const summary = JSON.parse(stdout);
    assert.equal(summary.title, 'Authed capture');
    assert.ok(summary.candidate_count >= 1);

    const candidates = JSON.parse(await fs.readFile(path.join(snapshotDir, 'candidates.json'), 'utf8'));
    assert.ok(candidates.some((candidate) => candidate.name === 'Open admin'));
  } finally {
    await stopServer(server);
    await fs.rm(tmpRoot, { recursive: true, force: true });
  }
});

