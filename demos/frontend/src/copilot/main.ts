import './copilot.css';
import { api, createSerial } from '../shared/api';
import { createChatGPTBridge } from '../shared/chatgpt-bridge';
import { $, esc } from '../shared/dom';
import { mountEvaluationPanel } from '../shared/evaluation/panel';
import type { Analysis, Circuit, MinimumBackup, Params, Score, Setup, SolveResult } from './types';

// The engine runs in the backend; the page renders what it returns.
const setup = await api<Setup>('/api/copilot/setup');
const BASE = setup.base;
const serial = createSerial();

const fmt = (n: number) => (Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'),
  pct = (n: number) => fmt(n * 100) + '%';
const bridge = createChatGPTBridge();

interface LogEntry {
  revision: number;
  event: string;
  at: string;
  status: SolveResult['status'];
}

const ui: {
  p: Params;
  c: Circuit | null;
  result: SolveResult | null;
  mpe: Score | null;
  /** From the last analysis: the service level in force, world posteriors, and gate values. */
  alpha: number;
  worldWeights: number[];
  circuitValues: number[] | null;
  tab: string;
  compiles: number;
  revision: number;
  ms: number;
  compileMs: number;
  tour: number;
  log: LogEntry[];
  lastAnswer: string;
} = {
  p: { ...BASE },
  c: null,
  result: null,
  mpe: null,
  alpha: 0,
  worldWeights: [],
  circuitValues: null,
  tab: 'worlds',
  compiles: 0,
  revision: 0,
  ms: 0,
  compileMs: 0,
  tour: -1,
  log: [],
  lastAnswer: 'recommend',
};
const knowledgeDefault =
  'A can dispatch 130 units and B can dispatch 50. Forecast requests for S1-S4 are 50, 40, 45, and 55 units. Every site must receive at least 60% of its original forecast. S1 and S4 are priority sites: serve at least 90% of realized demand, with at least 95% probability that both targets hold. Minimize transport cost plus expected shortfall; shortage costs 20 per unit at priority sites and 10 elsewhere. A local backup option, if enabled, can reach S4 in time at cost 12 per unit, up to 30 units. An explicitly authorized exception lowers the service level to 80%.';
const knowledge = $<HTMLTextAreaElement>('#knowledge');
knowledge.value = knowledgeDefault;

type AnswerKind = 'checked' | 'infeasible' | 'chatgpt';
function answer(text: string, kind: AnswerKind = 'checked', meta = '') {
  const el = $('#answer');
  el.classList.toggle('bad', kind === 'infeasible');
  el.querySelector('.answer-label')!.textContent =
    kind === 'chatgpt'
      ? 'ChatGPT wording · consult the checked results below'
      : kind === 'infeasible'
        ? 'Infeasibility under the stated model'
        : 'Checked model result';
  $('#answerText').textContent = text;
  $('#answerMeta').textContent =
    meta || 'Computed locally from the active rules and model. Revision ' + ui.revision + '.';
}

function syncControls() {
  const p = ui.p;
  for (const k of ['scenario', 'evidence', 'backupLimit', 'backupCost'] as const)
    $<HTMLInputElement>('#' + k).value = String(p[k]);
  for (const k of ['capacityB', 'service', 'tau', 'stormProbability'] as const) {
    const val = k === 'capacityB' ? p[k] : p[k] * 100;
    $<HTMLInputElement>('#' + k).value = String(val);
    $('#' + k + 'Val').textContent = k === 'capacityB' ? fmt(val) + ' units' : pct(p[k]);
  }
  for (const k of ['backupEnabled', 'exceptionAuthorized'] as const) $<HTMLInputElement>('#' + k).checked = p[k];
  $<HTMLTextAreaElement>('#specJson').value = JSON.stringify(p, null, 2);
}

/** Validate and solve `p` on the server; a parameter error throws its message. */
async function analyze(p: unknown, note: string) {
  const t = performance.now();
  const r = await api<Analysis>('/api/copilot/analyze', { params: p });
  ui.p = r.p;
  // The circuit's structure depends only on the scenario; count a compilation when it changes.
  if (!ui.c || ui.c.signature !== r.circuit.signature) {
    ui.compileMs = r.compileMs;
    ui.compiles++;
  }
  ui.c = r.circuit;
  ui.result = r.result;
  ui.mpe = r.mpe;
  ui.alpha = r.alpha;
  ui.worldWeights = r.worldWeights;
  ui.circuitValues = r.circuitValues;
  ui.ms = performance.now() - t;
  ui.revision++;
  ui.log.unshift({ revision: ui.revision, event: note, at: new Date().toISOString(), status: ui.result.status });
  ui.log = ui.log.slice(0, 30);
  $('#specError').textContent = '';
  syncControls();
  render();
  recommend();
}

function recompute(note = 'Model updated') {
  return serial(async () => {
    try {
      await analyze(ui.p, note);
    } catch (e) {
      $('#specError').textContent = (e as Error).message;
      answer(
        (e as Error).message,
        'infeasible',
        'The previous valid result has not been promoted to a result for this input.',
      );
    }
  });
}

function recommend() {
  const r = ui.result,
    p = ui.p;
  if (!r) return;
  ui.lastAnswer = 'recommend';
  if (r.best) {
    const b = r.best;
    answer(
      'Send A: ' +
        b.x.slice(0, 4).map(fmt).join(' / ') +
        '. Send B: ' +
        b.x.slice(4, 8).map(fmt).join(' / ') +
        '.' +
        (b.x[8] > 1e-6 ? ' Add ' + fmt(b.x[8]) + ' timely local units at S4.' : '') +
        ' This meets the joint priority rule with modeled probability ' +
        pct(b.probability) +
        ', at expected total cost ' +
        fmt(b.total) +
        '.',
      'checked',
      'Units are listed in S1–S4 order. Numerical optimum within this finite continuous-allocation formulation.',
    );
  } else {
    const storm = ui.p.scenario === 'storm' && ui.p.evidence !== 'Normal' && ui.p.evidence !== 'Surge',
      gap = Math.max(0, ui.alpha * 80 - p.capacityB - (p.backupEnabled ? p.backupLimit : 0));
    answer(
      'No plan meets the requested ' +
        pct(p.tau) +
        ' joint assurance with the active resources and hard floors. ' +
        (r.hardFeasible
          ? 'The maximum attainable modeled compliance is ' + pct(r.maxProbability) + '.'
          : 'Even the hard forecast floors cannot all be met.') +
        (storm && gap > 0
          ? ' In the storm state, the S4 target is ' +
            fmt(ui.alpha * 80) +
            ' timely units; the B-plus-local limit leaves at least ' +
            fmt(gap) +
            ' units missing.'
          : ''),
      'infeasible',
      'All eight subsets of the three supported demand states were checked with the numerical LP solver.',
    );
  }
}

function render() {
  const p = ui.p,
    r = ui.result!,
    b = r.best;
  $('#probability').textContent = b ? pct(b.probability) : '≤ ' + pct(r.maxProbability);
  $('#probability').className = 'value ' + (b ? 'good' : 'bad-text');
  $('#totalCost').textContent = b ? fmt(b.total) : '—';
  $('#costSub').textContent = b
    ? 'Transport ' + fmt(b.transport) + ' · backup ' + fmt(b.backupCost) + ' · shortfall ' + fmt(b.shortage)
    : 'No assurance-feasible recommendation';
  $('#assurance').textContent = b ? 'Verified feasible' : 'Infeasible';
  $('#assurance').className = 'value ' + (b ? 'good' : 'bad-text');
  $('#assuranceSub').textContent = 'Model-relative · target ' + pct(p.tau) + ' · service ' + pct(ui.alpha);
  const plans: [string, Score | null, boolean][] = [
    ['Circuit decision', b, false],
    ['Most-likely-world plan', ui.mpe, true],
  ];
  $('#planComparison').innerHTML = plans
    .map(([name, v, amber]) =>
      v
        ? '<div class="compare-row"><span>' +
          name +
          '</span><div class="track"><div class="fill ' +
          (amber ? 'amber' : '') +
          '" style="width:' +
          Math.min(100, v.probability * 100) +
          '%"></div><div class="target" style="left:calc(' +
          p.tau * 100 +
          '% - 1px)"></div></div><span class="prob">' +
          pct(v.probability) +
          '</span><span class="cost num">' +
          fmt(v.total) +
          ' cost</span></div>'
        : '<div class="compare-row"><span>' +
          name +
          '</span><span class="bad-text">No feasible plan at this target</span><span>—</span><span></span></div>',
    )
    .join('');
  document
    .querySelectorAll<HTMLElement>('[data-preset]')
    .forEach((el) =>
      el.setAttribute(
        'aria-pressed',
        String(
          (el.dataset.preset === 'repair' && p.backupEnabled) || (el.dataset.preset === p.scenario && !p.backupEnabled),
        ),
      ),
    );
  renderNetwork(b || ui.mpe);
  renderTab();
}

function renderNetwork(v: Score | null) {
  const x = v?.x || Array(9).fill(0);
  let lines = '';
  for (let d = 0; d < 2; d++)
    for (let j = 0; j < 4; j++) {
      const active = x[d * 4 + j] > 1e-5;
      lines +=
        '<line x1="155" y1="' +
        (d ? 128 : 40) +
        '" x2="470" y2="' +
        (22 + j * 42) +
        '" stroke="' +
        (active ? '#70b9bc' : '#dfe8ec') +
        '" stroke-width="' +
        (active ? 2 : 1) +
        '" ' +
        (j === 3 && d === 0 && ui.p.scenario === 'storm' ? 'stroke-dasharray="6 5"' : '') +
        '/>';
    }
  const sites = [0, 1, 2, 3]
    .map(
      (j) =>
        '<rect x="470" y="' +
        (7 + j * 42) +
        '" width="200" height="31" rx="6" fill="' +
        (j === 0 || j === 3 ? '#e7f4f2' : '#f2f6f8') +
        '"/><text x="482" y="' +
        (27 + j * 42) +
        '" font-size="12" fill="#173348">S' +
        (j + 1) +
        (j === 0 || j === 3 ? ' · priority' : '') +
        ' — ' +
        fmt(x[j] + x[j + 4] + (j === 3 ? x[8] : 0)) +
        ' dispatched</text>',
    )
    .join('');
  $('#network').innerHTML =
    '<svg viewBox="0 0 730 180" role="img" aria-label="Two depots supply four destinations, with a storm-sensitive lane to S4"><g>' +
    lines +
    '</g><rect x="10" y="20" width="145" height="43" rx="7" fill="#173b4c"/><text x="23" y="46" fill="white" font-size="13">A · limit ' +
    fmt(ui.p.capacityA) +
    '</text><rect x="10" y="106" width="145" height="43" rx="7" fill="#173b4c"/><text x="23" y="132" fill="white" font-size="13">B · limit ' +
    fmt(ui.p.capacityB) +
    '</text>' +
    sites +
    '</svg>';
  $('#networkCaption').textContent =
    (ui.result!.best
      ? 'Recommended dispatch. '
      : 'Most-likely-world alternative shown for inspection; it does not achieve the requested assurance. ') +
    (ui.p.scenario === 'storm'
      ? 'Dashed A→S4 lane misses the cutoff in the storm state. '
      : 'All lanes arrive before the cutoff. ') +
    (x[8] > 0 ? 'Local supplier adds ' + fmt(x[8]) + ' timely units at S4.' : '');
}

const tabs = [
  ['worlds', 'Uncertain worlds'],
  ['shipments', 'Shipments'],
  ['explanation', 'Why this action'],
  ['circuit', 'Compiled circuit'],
  ['model', 'Rules & model'],
  ['certificate', 'Result record'],
  ['dependence', 'Independence test'],
];

function table(head: string[], rows: (string | number)[][]) {
  return (
    '<div class="scroll"><table><thead><tr>' +
    head.map((v) => '<th>' + v + '</th>').join('') +
    '</tr></thead><tbody>' +
    rows.map((r) => '<tr>' + r.map((v) => '<td>' + v + '</td>').join('') + '</tr>').join('') +
    '</tbody></table></div>'
  );
}

function renderTab() {
  $('#tabs').innerHTML = tabs
    .map(
      ([id, t]) =>
        '<button role="tab" data-tab="' + id + '" aria-selected="' + (ui.tab === id) + '">' + t + '</button>',
    )
    .join('');
  document.querySelectorAll<HTMLElement>('[data-tab]').forEach(
    (b) =>
      (b.onclick = () => {
        ui.tab = b.dataset.tab!;
        renderTab();
      }),
  );
  const p = ui.p,
    c = ui.c!,
    r = ui.result!,
    b = r.best || ui.mpe;
  let html = '';
  if (ui.tab === 'worlds') {
    const ps = ui.worldWeights;
    html =
      '<h2>Joint demand and arrival states</h2>' +
      table(
        ['State', 'Posterior probability', 'S4 demand', 'A→S4 arrival', 'S4 timely units', 'Priority rule'],
        c.worlds.map((w, i) => {
          const s = b?.states[i];
          return [
            esc(w.name),
            pct(ps[i]),
            fmt(w.demand),
            w.timely ? 'Before cutoff' : 'After cutoff',
            s ? fmt(s.delivered[3]) : '—',
            s
              ? '<span class="pill ' +
                (s.policy ? '' : 'fail') +
                '">' +
                (ps[i] === 0 ? 'Not active' : s.policy ? 'Met' : 'Missed') +
                '</span>'
              : '—',
          ];
        }),
      ) +
      '<p class="note">' +
      (r.best ? 'Recommendation' : 'Most-likely-world alternative') +
      ' is evaluated here. The service target is ' +
      pct(ui.alpha) +
      ' of realized demand. Probabilities are synthetic and normalized after conditioning.</p>';
  }
  if (ui.tab === 'shipments') {
    html =
      '<h2>' +
      (r.best ? 'Recommended shipments' : 'Alternative for inspection') +
      '</h2>' +
      (b
        ? table(
            ['Destination', 'From A', 'From B', 'Local backup', 'Expected timely delivery'],
            [0, 1, 2, 3].map((j) => [
              'S' + (j + 1),
              fmt(b.x[j]),
              fmt(b.x[j + 4]),
              j === 3 ? fmt(b.x[8]) : '0',
              fmt(b.states.reduce((s, w) => s + w.p * w.delivered[j], 0)),
            ]),
          )
        : '<p>No feasible shipment plan.</p>') +
      '<p class="note">Dispatch is chosen before the regime is known. Delayed A→S4 shipments still incur transport cost. Quantities are divisible; an integer-routing solver is not claimed.</p>';
  }
  if (ui.tab === 'explanation') {
    html =
      '<h2>Rules and counterexamples behind the action</h2><div class="binding"><b>R1 / R2 — Dispatch capacity.</b> A ≤ ' +
      fmt(p.capacityA) +
      ', B ≤ ' +
      fmt(p.capacityB) +
      '.</div><div class="binding"><b>R3 — Forecast floors.</b> Every active world must provide each site at least ' +
      pct(p.floor) +
      ' of its original forecast.</div><div class="binding"><b>R4 — Joint priority service.</b> S1 and S4 each receive ' +
      pct(ui.alpha) +
      ' of realized demand, together with probability ≥ ' +
      pct(p.tau) +
      '.</div><div class="binding"><b>R5 — Exception guard.</b> ' +
      (p.exceptionAuthorized
        ? 'Explicit authorization is active; the exception level applies.'
        : 'No authorization is active. Storm evidence cannot authorize it.') +
      '</div><h3>Why the 70-unit plan can fail</h3><p>At demand 80 and a 90% service rule, S4 needs 72 timely units. Sending 70 misses that threshold. Under the reference demand probabilities, that state carries 30% probability.</p><p class="note">This counterexample refers to the 90% reference policy; current controls may specify a different service level.</p>';
  }
  if (ui.tab === 'circuit') {
    const values = ui.circuitValues;
    html =
      '<h2>An executable, inspectable arithmetic circuit</h2><div class="pipeline"><div><b>Author</b>Typed facts and policy parameters</div><div><b>Compile</b>Joint-world and policy gates</div><div><b>Condition</b>Evidence and weight updates</div><div><b>Decide & check</b>Search actions; evaluate event probability</div></div><div class="mini-metrics"><span><b>' +
      c.nodes.length +
      '</b> DAG nodes</span><span><b>' +
      ui.compiles +
      '</b> structural compilations</span><span><b>' +
      fmt(ui.compileMs) +
      ' ms</b> last compile</span><span><b>' +
      fmt(ui.ms) +
      ' ms</b> current search + scoring</span></div><p>The event numerator sums each world’s weight × evidence indicator × policy indicator. Divide by the evidence mass to obtain the conditional probability. Each policy gate checks the selected plan in its world.</p>' +
      table(
        ['Gate', 'Operation', 'Meaning', 'Value'],
        c.nodes.map((n) => [n.id, esc(n.op), esc(n.label), values ? fmt(values[n.id]) : '—']),
      ) +
      '<p class="note">This small reference compiler builds finite-model arithmetic gates. It is not a general-purpose probabilistic logic compiler or a distilled neural model. A learned uncertainty module can later replace the explicit regime weights. Changing supported parameters reuses the DAG; changing the dependency structure recompiles it.</p>';
  }
  if (ui.tab === 'model') {
    html =
      '<h2>Compiled interpretation</h2>' +
      table(
        ['Kind', 'Meaning'],
        [
          ['Facts', 'Two depots; four sites; one product; one cutoff. Base requests: 50, 40, 45, 55.'],
          ['Decision', 'Eight depot shipments plus one local S4 shipment, all nonnegative.'],
          ['Uncertainty', 'Three joint regimes; late arrival is linked to the storm only in the correlated model.'],
          [
            'Policy',
            'Forecast floors are hard in every active world. Priority compliance is a joint chance constraint.',
          ],
          ['Objective', 'Transport + local supply + expected shortage penalties.'],
          ['Exception', 'Only the explicit authorization flag changes the service obligation.'],
        ],
      ) +
      table(
        ['Cost / unit', 'S1', 'S2', 'S3', 'S4'],
        [
          ['A', '1', '2', '5', '6'],
          ['B', '6', '5', '2', '1'],
        ],
      ) +
      '<details open><summary>Active typed parameters</summary><pre>' +
      esc(JSON.stringify(p, null, 2)) +
      '</pre></details><p class="note">Scope: synthetic allocation scenario inspired by the kickoff example and inventory routing. No official ROADEF or M5 benchmark performance is claimed.</p>';
  }
  if (ui.tab === 'certificate') {
    html =
      '<h2>Checkable result record</h2>' +
      table(
        ['Field', 'Result'],
        [
          ['Revision', ui.revision],
          ['Status', r.best ? 'Verified feasible under this model' : 'Infeasible at the requested probability'],
          ['Required probability', pct(p.tau)],
          ['Achieved / attainable', r.best ? pct(r.best.probability) : 'At most ' + pct(r.maxProbability)],
          [
            'Hard feasibility',
            r.best
              ? r.best.issues.length
                ? 'Failed'
                : 'Passed numerical checks'
              : r.hardFeasible
                ? 'Hard constraints feasible; requested assurance infeasible'
                : 'Hard floors infeasible',
          ],
          [
            'Optimality scope',
            'All eight scenario subsets searched; numerical LP optima for continuous quantities. No solver dual certificate is supplied.',
          ],
          ['Assumption boundary', 'Synthetic probabilities; confirmed backup timing; model-relative checks.'],
          ['Compilation', ui.compiles + ' structural compilations; ' + c.nodes.length + ' nodes'],
          ['Last search + scoring', fmt(ui.ms) + ' ms'],
        ],
      ) +
      '<details><summary>Scenario history</summary><pre>' +
      esc(JSON.stringify(ui.log, null, 2)) +
      '</pre></details><p class="note">Export result saves parameters, circuit nodes, shipments, per-world checks, and this revision’s numerical results.</p>';
  }
  if (ui.tab === 'dependence') {
    const d = setup.independence;
    html =
      '<h2>The same marginals can hide joint risk</h2><p>Fixed comparison case: 9 units from A, 50 from B, and 13 timely local units reach S4. It receives 72 if A is timely and 63 if A is late. Demand is 60/70/80 with probabilities 15%/55%/30%; the late probability is 30%.</p>' +
      table(
        ['Model', 'Failure calculation', 'Compliance', 'At a 90% target'],
        [
          [
            'Shared storm cause',
            'High demand and late delivery coincide: 0.30',
            pct(d.joint),
            '<span class="pill fail">Reject</span>',
          ],
          [
            'Assumed independence',
            '0.30 × 0.30 = 0.09',
            pct(d.independent),
            '<span class="pill">Accepts incorrectly</span>',
          ],
        ],
      ) +
      '<p>The joint model rejects the candidate because its 80-demand world is precisely the late-delivery world. Matching individual forecast marginals does not preserve the decision risk.</p><p class="note">This is a fixed verification example with a hypothetical 13-unit local option, separate from the current recommendation and controls. The independence estimate is deliberately misspecified.</p>';
  }
  $('#tabBody').innerHTML = html;
}

/** A parameter change. `update` maps the current parameters to the new ones; errors throw. */
function setParams(update: unknown, note: string) {
  return serial(() => analyze(typeof update === 'function' ? update(ui.p) : update, note));
}

function preset(name: string) {
  ui.tour = -1;
  $('#tourTitle').textContent = 'Evaluator walkthrough';
  $('#tourText').textContent =
    'Seven live steps: decision, explanation, policy change, disruption, repair, dependence, exception.';
  $('#tourNext').textContent = 'Start tour';
  $<HTMLButtonElement>('#tourPrev').disabled = true;
  setParams(
    { ...BASE, scenario: name === 'demand' ? 'demand' : 'storm', backupEnabled: name === 'repair' },
    'Loaded ' + name + ' preset',
  );
}

/** Keyword routing for the "Ask agent" box; every answer comes from the engine. */
function localAsk(q: string) {
  return serial(() => routeQuestion(q));
}
async function routeQuestion(q: string) {
  const t = q.toLowerCase();
  if (/independen|correlat|dependen/.test(t)) {
    ui.tab = 'dependence';
    renderTab();
    const d = setup.independence;
    answer(
      'In the fixed dependence test, the shared-storm model gives ' +
        pct(d.joint) +
        ' compliance. Assuming independence gives ' +
        pct(d.independent) +
        ', so a 90% threshold would accept the candidate incorrectly. See the exact comparison below.',
    );
    return;
  }
  if (/backup|extra supply|additional.*unit/.test(t)) {
    const b = await api<MinimumBackup>('/api/copilot/minimum-backup', { params: ui.p });
    answer(
      b
        ? 'The minimum available timely local capacity that makes the current assurance requirement feasible is ' +
            fmt(b.units) +
            ' units. This assumes the local supply arrives before the cutoff; it does not activate a policy exception.'
        : 'No local backup limit up to 100 units makes all current constraints feasible.',
      'checked',
      'Computed by numerical bisection on backup capacity, checking the full finite-model decision problem at each limit.',
    );
    return;
  }
  const percentage = t.match(/(\d+(?:\.\d+)?)\s*%/);
  if (percentage && /confidence|assurance|probability|\btau\b/.test(t)) {
    await analyze({ ...ui.p, tau: Number(percentage[1]) / 100 }, q);
    return;
  }
  if (/70|why|explain/.test(t)) {
    ui.tab = 'explanation';
    renderTab();
    answer(
      'Under the reference 90% service rule, S4 demand of 80 requires 72 timely units. The 70-unit plan fails in that world, which has 30% probability in the reference model. The current rule and its exception status are listed below.',
    );
    return;
  }
  if (/what|plan|recommend|now|ship|decid/.test(t)) {
    recommend();
    return;
  }
  answer(
    'Local questions cover recommendations, why the 70-unit plan fails, minimum backup, dependence, and confidence changes. Use Ask ChatGPT for other questions about the current checked result.',
  );
}

function facts() {
  return {
    params: ui.p,
    status: ui.result!.status,
    maximum_attainable_probability: ui.result!.maxProbability,
    recommendation: ui.result!.best,
    most_likely_plan: ui.mpe,
    model_scope: 'synthetic finite-domain continuous allocation; no learned forecaster',
    revision: ui.revision,
  };
}

const question = $<HTMLInputElement>('#question');
$('#ask').onclick = () => {
  const q = question.value.trim();
  if (q) localAsk(q);
};
question.onkeydown = (e) => {
  if (e.key === 'Enter') $('#ask').click();
};
document.querySelectorAll<HTMLElement>('[data-query]').forEach(
  (b) =>
    (b.onclick = () => {
      question.value = b.dataset.query!;
      localAsk(b.dataset.query!);
    }),
);
document.querySelectorAll<HTMLElement>('[data-preset]').forEach((b) => (b.onclick = () => preset(b.dataset.preset!)));
for (const id of [
  'scenario',
  'evidence',
  'capacityB',
  'stormProbability',
  'backupEnabled',
  'backupLimit',
  'backupCost',
  'service',
  'tau',
  'exceptionAuthorized',
])
  $('#' + id).onchange = async () => {
    try {
      const el = $<HTMLInputElement>('#' + id),
        v =
          el.type === 'checkbox'
            ? el.checked
            : ['scenario', 'evidence'].includes(id)
              ? el.value
              : Number(el.value) / (id === 'service' || id === 'tau' || id === 'stormProbability' ? 100 : 1);
      await setParams((p: Params) => ({ ...p, [id]: v }), 'Changed ' + id);
    } catch (e) {
      $('#specError').textContent = (e as Error).message;
      syncControls();
    }
  };
$('#applySpec').onclick = async () => {
  try {
    await setParams(JSON.parse($<HTMLTextAreaElement>('#specJson').value), 'Applied typed model');
  } catch (e) {
    $('#specError').textContent = (e as Error).message;
  }
};
$('#resetKnowledge').onclick = () => (knowledge.value = knowledgeDefault);
$('#compileKnowledge').onclick = async () => {
  const b = $<HTMLButtonElement>('#compileKnowledge');
  b.disabled = true;
  $('#compileStatus').textContent = 'Complete the ChatGPT task, then review the compiled interpretation.';
  try {
    const prompt =
      'Convert operator knowledge into the supported PILLAR parameter object. Keep current values for fields the user does not change, but list any missing assumptions or unsupported requests. Do not invent fields or authorize an exception unless the operator explicitly authorizes it. Percentages are decimal fractions. Capacities and quantities are numeric; flags are booleans. scenario is demand or storm; evidence is all, Normal, Surge, or Storm. Return JSON {"params":FULL_PARAMETER_OBJECT,"unsupported":[],"clarifications":[]}. Current supported parameter object: ' +
      JSON.stringify(ui.p) +
      '\nOperator knowledge:\n' +
      knowledge.value;
    const r = await bridge.json(prompt);
    if (r.clarifications?.length) throw new Error('Clarify: ' + r.clarifications.join('; '));
    await setParams(r.params, 'ChatGPT compiled operator knowledge');
    $('#compileStatus').textContent =
      'Compiled. Review Rules & model.' + (r.unsupported?.length ? ' Not compiled: ' + r.unsupported.join('; ') : '');
    ui.tab = 'model';
    renderTab();
  } catch (e) {
    $('#compileStatus').textContent = (e as Error).message;
  } finally {
    b.disabled = false;
  }
};
$('#chatgptAnswer').onclick = async () => {
  const b = $<HTMLButtonElement>('#chatgptAnswer');
  b.disabled = true;
  try {
    const q = question.value.trim() || 'What should I do now?';
    const text = await bridge.text(
      'Explain the following checked logistics result to the operator in 2-4 sentences. Use only values in the result, preserve its model-relative status, and never invent feasibility or optimality. Operator: ' +
        q +
        '\nChecked result: ' +
        JSON.stringify(await serial(facts)),
    );
    answer(
      text,
      'chatgpt',
      'ChatGPT wording is supplementary. The probability, cost, and assurance panels remain computed by the local engine.',
    );
  } catch (e) {
    answer((e as Error).message);
  } finally {
    b.disabled = false;
  }
};
$('#exportCase').onclick = () =>
  serial(() =>
    bridge.download(
      'pillar-circuit-result.json',
      JSON.stringify({ version: 1, ...facts(), circuit: ui.c, history: ui.log }, null, 2),
      'application/json',
    ),
  );

const steps: [string, string, () => Promise<unknown>][] = [
  [
    'Choose under uncertainty',
    'Demand-only model: inspect the 72-unit S4 recommendation.',
    () => setParams({ ...BASE }, 'Tour: demand-only decision'),
  ],
  [
    'Explain a rejected alternative',
    'The 70-unit plan fails when demand reaches 80.',
    () => localAsk('Why not send 70 units to S4?'),
  ],
  [
    'Change the assurance requirement',
    'At 70% assurance, the 70-unit plan is acceptable.',
    () => setParams({ ...BASE, tau: 0.7 }, 'Tour: change assurance to 70%'),
  ],
  [
    'Introduce correlated delay',
    'At 95% assurance, the storm scenario has no feasible plan.',
    () => setParams({ ...BASE, scenario: 'storm' }, 'Tour: correlated storm'),
  ],
  [
    'Repair with backup supply',
    'The supplier restores feasibility; the optimum uses 22 units.',
    () => setParams({ ...BASE, scenario: 'storm', backupEnabled: true }, 'Tour: timely backup supply'),
  ],
  [
    'Expose a modeling error',
    'Compare 70% true-model compliance with 91% under independence.',
    () => localAsk('Compare joint and independent uncertainty'),
  ],
  [
    'Activate an authorized exception',
    'Reset demand-only; explicit authorization lowers service to 80%.',
    () => setParams({ ...BASE, exceptionAuthorized: true }, 'Tour: authorized exception'),
  ],
];
function runTour(i: number) {
  ui.tour = i;
  const s = steps[i];
  s[2]();
  $('#tourTitle').textContent = i + 1 + ' / 7 · ' + s[0];
  $('#tourText').textContent = s[1];
  $('#tourNext').textContent = i === 6 ? 'Restart tour' : 'Next step';
  $<HTMLButtonElement>('#tourPrev').disabled = i === 0;
}
$('#tourNext').onclick = () => runTour(ui.tour < 0 || ui.tour === 6 ? 0 : ui.tour + 1);
$('#tourPrev').onclick = () => {
  if (ui.tour > 0) runTour(ui.tour - 1);
};

recompute('Initial demand-only case');
bridge
  .ready()
  .then(
    (v) =>
      ($('#connectionState').textContent = v
        ? 'ChatGPT API connected.'
        : 'ChatGPT handoff: copy the prompt, send it in ChatGPT, paste the reply.'),
  );
mountEvaluationPanel();
