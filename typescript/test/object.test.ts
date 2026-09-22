import assert from 'node:assert/strict';
import { test } from 'node:test';

import { type JsonValue, BaseSharedObject, ObjectRegistry, StateMemento } from '../src/index.ts';

class Room extends BaseSharedObject {
  readonly lines: string[] = [];

  override receive(message: JsonValue): void {
    const text = (message as { text?: string }).text;
    if (typeof text === 'string') this.lines.push(text);
  }
}

test('a prototype only implements receive', () => {
  const room = new Room();
  assert.equal(room.isValid({ text: 'hi' }), true);
  assert.equal(room.addMessage({ text: 'hi' }), undefined);
  assert.deepEqual(room.lines, ['hi']);
  assert.equal(room.isMerkelized(), false);
  assert.deepEqual(room.getStateDigests(), []);
  assert.deepEqual(room.emitStateMemento(), StateMemento.normalize());

  const registry = new ObjectRegistry();
  const registered = new Room();
  registry.register('room', registered);
  const result = registry.apply({ text: 'hello' });
  assert.equal(result.accepted, true);
  assert.deepEqual(result.mementos.get('room'), StateMemento.normalize());
  assert.deepEqual(registered.lines, ['hello']);
});
