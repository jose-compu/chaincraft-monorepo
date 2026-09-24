import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AdapterBus, AdapterChannel } from '../src/index.ts';

test('pipe mesh throughput', () => {
  const peersN = 4;
  const burst = 65536;
  const payload = 'ab'.repeat(64);
  const bus = AdapterBus.pipe();
  const names = Array.from({ length: peersN }, (_, index) => `pipe:n${index}`);
  const peers = names.map(() => new AdapterChannel(bus));
  for (const [index, name] of names.entries()) {
    const peer = peers[index];
    assert.ok(peer !== undefined);
    assert.equal(peer.listen(name), true);
  }
  const started = performance.now();
  for (let index = 0; index < burst; index += 1) {
    const src = index % peersN;
    const dst = (src + 1) % peersN;
    const peer = peers[src];
    const dest = names[dst];
    assert.ok(peer !== undefined && dest !== undefined);
    assert.equal(peer.send(dest, payload), true);
  }
  const elapsed = (performance.now() - started) / 1000;
  for (const peer of peers) {
    const got = peer.recv();
    assert.equal(got.length, burst / peersN);
    assert.equal(got[0]?.data, payload);
    assert.equal(got[0]?.from.startsWith('pipe:n'), true);
  }
  const rate = burst / elapsed;
  console.log(
    `channel.pipe apply: ${burst} events in ${elapsed.toFixed(6)}s (${rate.toFixed(0)}/s)`,
  );
  assert.ok(elapsed < 30, `${elapsed}`);
});
