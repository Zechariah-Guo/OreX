// Line-based RPC around the pure helpers exported by src/static/js/tutorial.js.
// Used by tests/test_tutorial_js_properties.py so Hypothesis can exercise the real
// browser code instead of a Python re-implementation.
//
// Protocol: one JSON object per stdin line: {"fn": "<name>", "args": [...]}
// Reply:    one JSON object per stdout line: {"result": ...} or {"error": "..."}
const readline = require('readline');
const logic = require('../src/static/js/tutorial.js');

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
    let reply;
    try {
        const { fn, args } = JSON.parse(line);
        if (typeof logic[fn] !== 'function') throw new Error('unknown function ' + fn);
        reply = { result: logic[fn](...args) };
    } catch (e) {
        reply = { error: String((e && e.message) || e) };
    }
    process.stdout.write(JSON.stringify(reply) + '\n');
});
