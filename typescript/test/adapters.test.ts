import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AdapterBus, AdapterChannel, MAX_UDP_PAYLOAD, UdpLink } from '../src/index.ts';

test('localhost datagram round trip', async () => {
  const a = await UdpLink.bind();
  const b = await UdpLink.bind();
  try {
    const body = new TextEncoder().encode('hello');
    await a.send(b.hostPort, body);
    const got = await b.recv();
    assert.deepEqual(got.body, body);
    assert.ok(got.from.startsWith('127.0.0.1:'));
  } finally {
    await a.close();
    await b.close();
  }
});

test('udp bus rejects an oversize payload', () => {
  const channel = new AdapterChannel(AdapterBus.udp());
  assert.equal(channel.listen('udp://127.0.0.1:1'), true);
  assert.equal(channel.send('udp://127.0.0.1:1', '00'.repeat(MAX_UDP_PAYLOAD)), true);
  assert.equal(channel.send('udp://127.0.0.1:1', '00'.repeat(MAX_UDP_PAYLOAD + 1)), false);
});
