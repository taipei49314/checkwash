import { appendFileSync } from 'node:fs';
import { test, expect } from 'vitest';
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test.each([[1]])('one row %s', value => { record('CALLBACK'); expect(value).toBe(1); });

