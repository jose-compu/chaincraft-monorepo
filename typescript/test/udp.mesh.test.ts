/** Two meshes exchange one envelope on the optional UDP listener. */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { JsonValue } from '../src/canonical.ts';
import { Mesh } from '../src/mesh.ts';

test('udp listener delivers gossip', async () => {
  const received: JsonValue[] = [];
  const left = new Mesh();
  const right = new Mesh();
  right.onApp = (_type, data) => {
    received.push(data);
  };
  await left.start('127.0.0.1', 0);
  await right.start('127.0.0.1', 0);
  try {
    const port = await right.bindUdp();
    await left.bindUdp();
    await left.connect(`udp://${port}`);
    left.broadcast('app.hello', { message: 'hi' });
    const deadline = Date.now() + 3000;
    while (received.length === 0 && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.deepEqual(received, [{ message: 'hi' }]);
  } finally {
    await left.close();
    await right.close();
  }
});
