/** Three meshes: hub `allowPeer` rejects only the sender's gossip. */

import assert from 'node:assert/strict';
import test from 'node:test';

import { Mesh } from '../src/mesh.ts';

test('three node allowPeer blocks sender only', async () => {
  const senderAddr: string[] = [];
  const gotB: Array<[string, unknown]> = [];
  const b = new Mesh(undefined, () => undefined);
  b.allowPeer = (addr) => !senderAddr.length || addr !== senderAddr[0];
  b.onApp = (typeName, data) => {
    gotB.push([typeName, data]);
  };

  const a = new Mesh();
  const c = new Mesh();
  const addrB = await b.start('127.0.0.1', 0);
  await a.start('127.0.0.1', 0);
  await c.start('127.0.0.1', 0);
  await a.connect(addrB);
  const deadlinePeer = Date.now() + 2000;
  while (Date.now() < deadlinePeer && b.peers.length === 0) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.ok(b.peers.length > 0);
  senderAddr.push(b.peers[0]!.addr);
  await c.connect(addrB);

  const blocked = await a.broadcast('app.blocked', { n: 0 });
  const waitBlocked = Date.now() + 2000;
  while (Date.now() < waitBlocked) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.deepEqual(gotB, []);
  assert.ok(!b.ids().includes(blocked));
  assert.ok(!c.ids().includes(blocked));

  gotB.length = 0;
  const allowed = await c.broadcast('app.ok', { n: 1 });
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline && !b.ids().includes(allowed)) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.deepEqual(gotB, [['app.ok', { n: 1 }]]);
  assert.ok(b.ids().includes(allowed));
  assert.ok(c.ids().includes(allowed));

  a.close();
  b.close();
  c.close();
});