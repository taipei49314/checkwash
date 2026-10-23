import { appendFileSync } from 'node:fs';
import { test, expect } from 'vitest';
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test.each`
value
`('header only', () => { record('CALLBACK'); throw new Error('HEADER_ONLY_CALLBACK_EXECUTED'); });

