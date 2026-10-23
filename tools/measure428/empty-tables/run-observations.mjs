// DRAFT: approved hosted Linux only. Runner failures are observations.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

if (process.platform !== 'linux' || process.env.GITHUB_ACTIONS !== 'true') {
  throw new Error('approved venue is hosted Linux; no local execution');
}
if (process.version !== 'v26.12.1') throw new Error('Node version differs');
const digest = path => createHash('sha256').update(readFileSync(path)).digest('hex');
const expectedLock = process.env.CW428_LOCK_SHA256;
if (!/^[a-f0-9]{64}$/.test(expectedLock || '') || digest('package-lock.json') !== expectedLock) {
  throw new Error('exact reviewed lock hash required');
}
const plan = JSON.parse(readFileSync('cases.json', 'utf8'));
for (const name of ['jest', 'vitest', 'vite']) {
  const installed = JSON.parse(readFileSync('node_modules/' + name + '/package.json', 'utf8'));
  if (installed.version !== plan.runner_versions[name]) throw new Error(name + ' version differs');
}
const out = resolve(process.env.CW428_OUTPUT || 'observation-results');
if (existsSync(out)) throw new Error('new output required; no overwrite/resume');
mkdirSync(out);
const facts = {
  status: 'RUNNING', node: process.version, platform: process.platform, arch: process.arch,
  lock_sha256: expectedLock, cases_sha256: digest('cases.json'), source_sha256: digest('run-observations.mjs'),
  source_commit: process.env.GITHUB_SHA, run_id: process.env.GITHUB_RUN_ID,
  runner_os: process.env.RUNNER_OS, started: new Date().toISOString(), results: [],
};
writeFileSync(out + '/receipt.json', JSON.stringify(facts, null, 2));
const started = Date.now();

for (const c of plan.cases) {
  const remaining = 1800_000 - (Date.now() - started);
  if (remaining <= 0) {
    facts.status = 'INCOMPLETE_TOTAL_DEADLINE';
    break;
  }
  const dir = out + '/' + c.runner + '-' + c.id;
  mkdirSync(dir);
  const events = dir + '/events.txt';
  writeFileSync(events, '');
  let exe = process.execPath, args;
  if (c.runner === 'jest') {
    args = ['node_modules/jest/bin/jest.js', '--config', 'jest.config.cjs', '--runInBand',
      '--runTestsByPath', c.path, '--json', '--outputFile', dir + '/runner.json'];
  } else if (c.runner === 'vitest') {
    args = ['node_modules/vitest/vitest.mjs', 'run', c.path, '--config', 'vitest.config.mjs',
      '--reporter=json', '--outputFile=' + dir + '/runner.json'];
  } else {
    exe = 'bun';
    args = ['test', './' + c.path, '--timeout', '5000', '--reporter', 'junit',
      '--reporter-outfile', dir + '/runner.xml'];
  }
  const stdout = createWriteStream(dir + '/stdout.log');
  const stderr = createWriteStream(dir + '/stderr.log');
  const begin = Date.now();
  const result = await new Promise(resolveResult => {
    let timeout = false, spawnError = null;
    const child = spawn(exe, args, {
      cwd: process.cwd(), detached: true,
      env: { ...process.env, CW428_EVENTS: events, CI: 'true', NO_COLOR: '1',
        NODE_OPTIONS: '', BUN_OPTIONS: '' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child.stdout.pipe(stdout);
    child.stderr.pipe(stderr);
    const timer = setTimeout(() => {
      timeout = true;
      try { process.kill(-child.pid, 'SIGKILL'); } catch {}
    }, Math.min(c.timeout_seconds * 1000, remaining));
    child.on('error', error => { spawnError = String(error); });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      stdout.end(); stderr.end();
      resolveResult({ code, signal, timeout, spawn_error: spawnError });
    });
  });
  const lines = readFileSync(events, 'utf8').split('\n').filter(Boolean);
  const row = { ...c, argv: [exe, ...args], ...result, duration_ms: Date.now() - begin,
    fixture_sha256: digest(c.path), events: lines,
    callbacks: lines.filter(x => x === 'CALLBACK').length,
    sentinels: lines.filter(x => x === 'SENTINEL').length,
    modules_loaded: lines.filter(x => x === 'MODULE_LOADED').length };
  facts.results.push(row);
  writeFileSync(dir + '/observation.json', JSON.stringify(row, null, 2));
  writeFileSync(out + '/receipt.json', JSON.stringify(facts, null, 2));
}
if (facts.status === 'RUNNING') {
  facts.status = facts.results.some(r => r.timeout || r.spawn_error)
    ? 'COMPLETE_WITH_UNANALYSED_INVOCATIONS' : 'OBSERVATIONS_CAPTURED_REVIEW_REQUIRED';
}
facts.finished = new Date().toISOString();
writeFileSync(out + '/receipt.json', JSON.stringify(facts, null, 2));
if (facts.status !== 'OBSERVATIONS_CAPTURED_REVIEW_REQUIRED') process.exitCode = 2;
