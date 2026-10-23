const { appendFileSync } = require('node:fs');
const record = event => appendFileSync(process.env.CW428_EVENTS, event + '\n');
record('MODULE_LOADED');
test('plain fail', () => { record('CALLBACK'); expect(1).toBe(2); });

