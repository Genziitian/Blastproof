// Run with node tests/test_results_ui.js. No browser or third-party packages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({matchMedia: () => ({matches: false})});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/static/core.js'), 'utf8'), context);
function sample(modelCalls = [6, 3, 1.7]) {
  return {eval: {name: 'latest-test', source: {at: '2026-10-18T10:00:00Z', file: 'summary.json'},
    meta: {model: 'test-model', max_steps: 12, arms: ['A', 'B', 'C']},
    summary: Object.fromEntries(['A', 'B', 'C'].map((arm, i) => [arm, {all: {
      n: 30, accuracy: 1, mean_llm_requests: modelCalls[i], mean_steps: 5,
      duplicate_notifications: 0, memory_helped: i * 5}}]))}};
}
const render = (data) => { context.testData = data; return vm.runInContext('evaluationHtml(testData)', context); };
assert.match(render(sample()), /72%/);
assert.match(render(sample([6, 3, 3])), /50%/);
const rules = sample([0, 0, 0]);
rules.eval.meta.model = 'rule-based'; rules.eval.meta.max_steps = 8;
rules.eval.summary.C.all.accuracy = 14 / 30;
const html = render(rules);
assert.match(html, /47%/);
assert.match(html, /No model calls in this run/);
assert.match(html, /8-step budget/);
assert.doesNotMatch(html, /NaN|Infinity|71%/);
assert.match(html, /Not run yet/);
delete rules.eval.summary.B;
assert.match(render(rules), /2 memory arms/);
const failed = {isolation: {ok: false, leaks: {a: {other_company_markers_found: ['canary']}}},
  fencing: {ok: false, stale_writes_rejected: 0, stale_writes_attempted: 5}};
assert.match(render(failed), /Failed · 1 leaked markers/);
assert.match(render(failed), /0\/5 · failed/);
console.log('Results renderer: dynamic model savings, deterministic runs, two arms and missing/failed evidence passed.');
