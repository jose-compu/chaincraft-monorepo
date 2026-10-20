/** Live PeerJS id from the public broker. Not a golden vector. */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { parseAddress } from '../src/channel.ts';
import { fetchPeerId, peerOptions } from '../src/peer.ts';

test('live PeerJS id', async () => {
  const ident = await fetchPeerId();
  const parsed = parseAddress(`webrtc:${ident}`);
  assert.equal(parsed.ok, true);
  assert.equal(parsed.canonical, `webrtc:${ident}`);
  assert.deepEqual(peerOptions(), {
    host: 'dechess-org-peerjs.vercel.app',
    port: 443,
    path: '/',
    secure: true,
    key: 'peerjs',
  });
});
