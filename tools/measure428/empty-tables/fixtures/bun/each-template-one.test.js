import { appendFileSync } from 'node:fs';
import { test, expect } from 'bun:test';
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test.each`
value
${1}
`('template $value', ({ value }) => { record('CALLBACK'); expect(value).toBe(1); });

