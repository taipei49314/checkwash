import { appendFileSync } from 'node:fs';
import { test, expect } from 'vitest';
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test.for([])('for empty', () => { record('CALLBACK'); throw new Error('EMPTY_CALLBACK_EXECUTED'); });

