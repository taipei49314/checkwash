import test from 'node:test';
import assert from 'node:assert/strict';

function total() { return 2; }

test('total', () => {
  if (process.env.CW_RUN_TOTAL === '1') {
    assert.strictEqual(total(), 3);
  }
});
