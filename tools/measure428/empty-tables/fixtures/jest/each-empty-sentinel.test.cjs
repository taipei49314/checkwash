const { appendFileSync } = require('node:fs');
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test.each([])('empty rows', () => { record('CALLBACK'); throw new Error('EMPTY_CALLBACK_EXECUTED'); });
test('sentinel', () => { record('SENTINEL'); expect(1).toBe(1); });

