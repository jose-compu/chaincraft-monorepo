/** Three meshes: the hub records the first gossip peer and blocks the rest. */

import assert from 'node:assert/strict';
import test from 'node:test';

import { Mesh } from '../src/mesh.ts';

test('three node allowPeer blocks late gossip', async () => {
  const first: string[] = [];
  const gotB: Array<[string, unknown]> = [];
  const b = new Mesh(undefined, () => undefined);
  b.allowPeer = (addr) => {
    if (first.length === 0) {
      first.push(addr);
      return true;
    }
    return addr === first[0];
  };
  b.onApp = (typeName, data) => {
    gotB.push([typeName, data]);
  };

  const a = new Mesh();
  const c = new Mesh();
  const addrB = await b.start('127.0.0.1', 0);
  await a.start('127.0.0.1', 0);
  await c.start('127.0.0.1', 0);
  await a.connect(addrB);
  await c.connect(addrB);

  const warm = await a.broadcast('app.warm', { n: 0 });
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline && !b.ids().includes(warm)) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(first.length > 0, 'expected first gossip peer on b');

  gotB.length = 0;
  const digest = await c.broadcast('app.blocked', { n: 1 });
  const waitUntil = Date.now() + 2000;
  while (Date.now() < waitUntil) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.deepEqual(gotB, []);
  assert.ok(!b.ids().includes(digest));
  assert.ok(c.ids().includes(digest));

  a.close();
  b.close();
  c.close();
});