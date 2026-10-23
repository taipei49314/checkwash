const { appendFileSync } = require('node:fs');
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
const EMPTY = [];
test.each(EMPTY)('const empty rows', () => { record('CALLBACK'); throw new Error('EMPTY_CALLBACK_EXECUTED'); });

