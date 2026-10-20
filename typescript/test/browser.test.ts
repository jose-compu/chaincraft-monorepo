/** The browser entry must not pull node:net or the TCP mesh. */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { peerOptions } from '../src/browser.ts';

const src = join(dirname(fileURLToPath(import.meta.url)), '../src');

function localImports(file: string): string[] {
  const text = readFileSync(file, 'utf8');
  const found: string[] = [];
  for (const match of text.matchAll(/from '\.\/([^']+)'/g)) {
    const name = (match[1] ?? '').replace(/\.ts$/, '');
    found.push(join(src, `${name}.ts`));
  }
  return found;
}

test('browser entry stays off node builtins', () => {
  const seen = new Set<string>();
  const queue = [join(src, 'browser.ts')];
  while (queue.length > 0) {
    const file = queue.pop();
    if (file === undefined || seen.has(file)) continue;
    seen.add(file);
    const text = readFileSync(file, 'utf8');
    const imports = text
      .split('\n')
      .filter((line) => line.includes(' from ') || line.includes('import('))
      .join('\n');
    assert.doesNotMatch(imports, /node:/, file);
    assert.doesNotMatch(imports, /mesh\.ts/, file);
    assert.doesNotMatch(imports, /adapters\.ts/, file);
    queue.push(...localImports(file));
  }
  assert.ok(seen.size > 1);
  assert.equal(peerOptions().host, 'dechess-org-peerjs.vercel.app');
});
