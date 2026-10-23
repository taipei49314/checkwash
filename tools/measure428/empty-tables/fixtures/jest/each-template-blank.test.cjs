const { appendFileSync } = require('node:fs');
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test.each``('blank template', () => { record('CALLBACK'); throw new Error('BLANK_TEMPLATE_CALLBACK_EXECUTED'); });

