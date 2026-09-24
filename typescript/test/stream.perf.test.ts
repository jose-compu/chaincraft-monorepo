/** Apply and read throughput for app.stream — SPEC/features/app-stream.md. */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MAX_SAFE_INT, type JsonValue } from '../src/canonical.ts';
import { MAX_BATCH, Stream } from '../src/stream.ts';

const BURST = 65536;
const KEEP = 32;

function apply(obj: Stream, message: JsonValue): boolean {
  if (!obj.isValid(message)) return false;
  obj.addMessage(message);
  return true;
}

test('stream apply and read throughput', () => {
  const obj = new Stream();
  assert.equal(apply(obj, { app: 'stream', broker: 'n1', op: 'join', stream: 'orders' }), true);
  assert.equal(apply(obj, { app: 'stream', broker: 'n2', op: 'join', stream: 'orders' }), true);
  for (const partition of [0, 1]) {
    assert.equal(
      apply(obj, {
        app: 'stream',
        op: 'open',
        partition,
        producer: 'alice',
        stream: 'orders',
      }),
      true,
    );
  }
  assert.equal(apply(obj, { app: 'stream', keep: KEEP, op: 'retain', stream: 'orders' }), true);

  let applied = 0;
  const started = performance.now();
  for (const partition of [0, 1]) {
    let seq = 0;
    while (seq < BURST / 2) {
      const records: JsonValue[] = [];
      for (let n = 0; n < MAX_BATCH; n += 1) {
        records.push({ payload: 'x', producer: 'alice', seq });
        seq += 1;
      }
      assert.equal(
        apply(obj, {
          app: 'stream',
          op: 'append',
          partition,
          records,
          stream: 'orders',
        }),
        true,
      );
      applied += MAX_BATCH;
    }
  }
  const elapsed = (performance.now() - started) / 1000;
  const rate = elapsed === 0 ? applied : applied / elapsed;
  console.log(`app.stream apply: ${applied} events in ${elapsed.toFixed(6)}s (${Math.round(rate)}/s)`);
  assert.ok(elapsed < 30, String(elapsed));

  assert.equal(apply(obj, { app: 'stream', broker: 'n2', op: 'fail', stream: 'orders' }), true);
  const head = obj.read('orders', 0, null, KEEP);
  assert.equal(head.length, KEEP);
  assert.equal(head[head.length - 1]?.seq, BURST / 2 - 1);
  assert.equal(apply(obj, { app: 'stream', broker: 'n1', op: 'fail', stream: 'orders' }), true);
  assert.deepEqual(obj.read('orders', 0, null, 4), []);
  assert.ok((obj.state().streams[0]?.partitions[0]?.events.length ?? 0) > 0);

  assert.equal(apply(obj, { app: 'stream', broker: 'n1', op: 'join', stream: 'orders' }), true);
  const readStarted = performance.now();
  const reads = 200;
  for (let i = 0; i < reads; i += 1) {
    assert.equal(obj.read('orders', 1, null, KEEP).length, KEEP);
  }
  const readElapsed = (performance.now() - readStarted) / 1000;
  const readRate = readElapsed === 0 ? reads : reads / readElapsed;
  console.log(
    `app.stream read: ${reads} reads in ${readElapsed.toFixed(6)}s (${Math.round(readRate)}/s)`,
  );

  const sparse = new Stream();
  assert.equal(
    apply(sparse, { app: 'stream', op: 'open', producer: 'alice', stream: 'orders' }),
    true,
  );
  assert.equal(
    apply(sparse, {
      app: 'stream',
      op: 'produce',
      payload: 'z',
      producer: 'alice',
      seq: MAX_SAFE_INT,
      stream: 'orders',
    }),
    true,
  );
  const rejectStarted = performance.now();
  assert.equal(
    sparse.isValid({
      app: 'stream',
      group: 'workers',
      op: 'commit',
      producer: 'alice',
      seq: MAX_SAFE_INT,
      stream: 'orders',
    }),
    false,
  );
  const rejectElapsed = (performance.now() - rejectStarted) / 1000;
  console.log(`app.stream high-seq commit rejection: ${rejectElapsed.toFixed(6)}s`);
  assert.ok(rejectElapsed < 1, String(rejectElapsed));
});
