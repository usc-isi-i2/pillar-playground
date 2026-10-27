import './replan.css';
import { api, createSerial } from '../shared/api';
import { createChatGPTBridge, type Json, type Sample } from '../shared/chatgpt-bridge';
import { $, esc } from '../shared/dom';
import { mountEvaluationPanel } from '../shared/evaluation/panel';
import type {
  ComputeResult,
  CustomDemand,
  Diagnosis,
  Evaluation,
  Evidence,
  LaneCheck,
  LlmPlan,
  MissingParam,
  Model,
  Plan,
  PresetId,
  Setup,
  Spec,
  World,
} from './types';

// The engine runs in the backend; the page renders what it returns.
const setup = await api<Setup>('/api/replan/setup');
const PRESETS = setup.presets;
const DEFAULT_EVIDENCE = setup.defaultEvidence;
// Every event handler that reads or changes the plan state runs through this queue, so each one
// sees the previous one's result, as when the page computed synchronously.
const serial = createSerial();

const clone = <T>(o: T): T => JSON.parse(JSON.stringify(o));
const fInt = (v: number) => Math.round(v).toLocaleString('en-US');
const fPct = (p: number) => {
  if (p >= 0.9995) return '100%';
  const r = Math.round(p * 100);
  if (r === 100) return (p * 100).toFixed(1) + '%';
  if (r === 0 && p > 0) return (p * 100).toFixed(1) + '%';
  return r + '%';
};
const fCost = (v: number) => (Math.abs(v) >= 10000 ? (v / 1000).toFixed(0) + 'k' : fInt(v));
const keyLabel = (k: string) => {
  const [s, c] = k.split('|');
  return c === 'units' ? s : s + ' ' + c;
};

type PlanId = 'mmap' | 'mpe' | 'llm';
type AnyPlan = Plan | LlmPlan;

const state: {
  preset: PresetId;
  spec: Spec;
  ev: Evidence;
  /** Normal-week demand from a loaded CSV of M5 aggregates (storm preset only). */
  custom: CustomDemand | null;
  M: Model | null;
  diag: Diagnosis | null;
  /** Parameters the spec still lacks; nothing is solved until the operator supplies them. */
  missing: MissingParam[];
  stats: ComputeResult['stats'];
  plans: Partial<Record<PlanId, AnyPlan>>;
  evals: Partial<Record<PlanId, Evaluation>>;
  bt: Partial<Record<PlanId, { rate: number; avgCost: number }>> | null;
  shadow: { step: number; dc: Record<string, number> } | null;
  llmPlan: LlmPlan | null;
  prev: { what: string; eval: Evaluation; prioKeys: string[] } | null;
  tab: string;
  shipView: PlanId;
  assumed: string[];
  unsupported: string[];
  sample: Sample | null;
  downloads: { save: (o: { filename: string; data: Uint8Array<ArrayBuffer> }) => Promise<void> } | null;
  lastSolveMs: number;
  world: World | null;
  busy: boolean;
} = {
  preset: 'storm',
  spec: null as unknown as Spec,
  ev: null as unknown as Evidence,
  custom: null,
  M: null,
  diag: null,
  missing: [],
  stats: {},
  plans: {},
  evals: {},
  bt: null,
  shadow: null,
  llmPlan: null,
  prev: null,
  tab: 'diagnosis',
  shipView: 'mmap',
  assumed: [],
  unsupported: [],
  sample: null,
  downloads: null,
  lastSolveMs: 0,
  world: null,
  busy: false,
};
const mmapPlan = () => state.plans.mmap as Extract<Plan, { status: 'optimal' }>;

// ---------- deterministic paraphrase of what was compiled (not the LLM’s words)
function paraphrase(spec: Spec) {
  const toy = state.preset === 'toy';
  const L: { t: string; k: string }[] = [];
  const andList = (xs: string[]) =>
    xs.length < 3 ? xs.join(' and ') : xs.slice(0, -1).join(', ') + ' and ' + xs.at(-1);
  for (const r of spec.priority)
    L.push({
      t: `${andList(r.stores)}${toy ? '' : ' ' + r.category} must get at least ${fPct(r.fraction)} of realized demand.`,
      k: 'priority',
    });
  if (spec.exception)
    L.push({ t: `If an emergency is declared, that level drops to ${fPct(spec.exception.fraction)}.`, k: 'exception' });
  if (spec.floor)
    L.push({
      t: `Every store${toy ? '' : ' and category'} gets at least ${fPct(spec.floor.fraction)} of its normal-week forecast.`,
      k: 'floor',
    });
  if (!toy)
    L.push({
      t: spec.crossStateMultiplier
        ? `Cross-state lanes cost ${spec.crossStateMultiplier}× in-state lanes.`
        : 'Cross-state lane costs come from the network data (4× in-state).',
      k: 'crossStateMultiplier',
    });
  if (spec.penalties)
    L.push({
      t: `Shortfall costs ${spec.penalties.priority} per unit on priority items and ${spec.penalties.other} elsewhere.`,
      k: 'penalties',
    });
  if (spec.tau != null)
    L.push({
      t: `The priority rule must hold with probability at least ${fPct(spec.tau)}${spec.joint && spec.priority.reduce((a, r) => a + r.stores.length, 0) > 1 ? ', for all priority stores together' : ', for each priority store'}.`,
      k: 'tau',
    });
  L.push({ t: 'DC capacities and closed lanes are hard limits.', k: 'hard' });
  return L;
}

// ---------- compute everything
async function recompute() {
  const t0 = performance.now();
  const r = await api<ComputeResult>('/api/replan/compute', {
    preset: state.preset,
    spec: state.spec,
    ev: state.ev,
    llmPlan: state.llmPlan,
    custom: state.custom,
  });
  state.missing = r.missing;
  state.stats = r.stats;
  state.diag = r.diag;
  state.M = r.diag.M;
  state.plans = r.plans;
  state.evals = r.evals;
  state.bt = r.bt;
  state.shadow = r.shadow;
  state.lastSolveMs = performance.now() - t0;
  renderAll();
}

// ---------- rendering
function renderAll() {
  renderRules();
  renderPlans();
  renderTabs();
}

function renderRules() {
  const L = paraphrase(state.spec);
  $('#paraphrase').innerHTML = L.map(
    (l) => `<li class="${state.assumed.includes(l.k) ? 'assumed' : ''}">${esc(l.t)}</li>`,
  ).join('');
  $('#unsupported').innerHTML = state.unsupported.length
    ? `<p class="unsupported">Not compiled (the schema can’t express it yet): ${state.unsupported.map(esc).join('; ')}</p>`
    : '';
  const miss = state.missing;
  $('#elicit').innerHTML = miss
    .map(
      (m, i) =>
        `<div class="elicit"><p>${esc(m.q)}</p><div class="opts">${m.opts.map((o, j) => `<button data-el="${i}:${j}">${esc(o[1])}</button>`).join('')}</div></div>`,
    )
    .join('');
  $('#elicit')
    .querySelectorAll<HTMLElement>('button[data-el]')
    .forEach(
      (b) =>
        (b.onclick = () =>
          serial(async () => {
            const [i, j] = b.dataset.el!.split(':').map(Number);
            const m = miss[i];
            (state.spec as unknown as Record<string, unknown>)[m.param] = clone(m.opts[j][0]);
            state.assumed = state.assumed.filter((a) => a !== m.param);
            syncSpecJson();
            await recompute();
          })),
    );
  syncSpecJson(false);
}
function syncSpecJson(force = true) {
  const ta = $<HTMLTextAreaElement>('#specJson');
  if (force || document.activeElement !== ta) ta.value = JSON.stringify(state.spec, null, 2);
}

function renderEvidence() {
  const box = $('#evidence');
  const csv = $<HTMLInputElement>('#csv');
  if (state.preset === 'toy') {
    box.innerHTML = `<p class="note">The toy’s evidence is fixed, as on slide 3: DC B is down to 50 units and S4 demand is 60, 70 or 80 with probabilities 15%, 55% and 30%.</p>`;
    $('#dataNote').textContent = 'The toy uses the hand-set demand table from the tag-up slides.';
    csv.disabled = true;
    return;
  }
  csv.disabled = false;
  $('#dataNote').textContent = state.custom
    ? 'Using your loaded M5 aggregates for normal-week demand.'
    : 'Normal-week demand is synthetic, sized like M5’s 10 stores and 3 categories. Load a CSV of M5 aggregates (store_id, cat_id, weekly_mean, optional cv) to replace it.';
  const ev = state.ev as unknown as Record<string, unknown>;
  const sel = (id: string, label: string, opts: [string | number, string][]) =>
    `<label for="ev-${id}">${label}</label><select id="ev-${id}" data-ev="${id}">${opts.map(([v, t]) => `<option value="${v}" ${String(ev[id]) === String(v) ? 'selected' : ''}>${t}</option>`).join('')}</select>`;
  box.innerHTML = `<div class="ev-grid">
    ${sel('advisory', 'Storm advisory', [
      ['unknown', 'Not reported'],
      ['none', 'None'],
      ['watch', 'Watch'],
      ['warning', 'Warning'],
    ])}
    ${sel('sales', 'TX sales signal', [
      ['unknown', 'Not reported'],
      ['flat', 'Flat'],
      ['up', 'Up'],
      ['sharp', 'Sharply up'],
    ])}
    ${sel('txCap', 'TX DC capacity', [
      [1, '100% of normal'],
      [0.7, '70% of normal'],
      [0.4, '40% of normal'],
    ])}
    ${sel('caLane', 'CA→TX lane', [
      ['open', 'Open'],
      ['closed', 'Closed'],
    ])}
    ${sel('emergency', 'Emergency', [
      ['unknown', 'Not reported'],
      ['declared', 'Declared'],
      ['not_declared', 'Not declared'],
    ])}
    ${sel('week', 'Week type', [
      ['normal', 'Normal'],
      ['snap', 'SNAP-heavy'],
    ])}
  </div><p class="note" style="margin-top:10px">Each change updates beliefs about the storm and re-solves the plans.</p>`;
  box.querySelectorAll('select').forEach(
    (s) =>
      (s.onchange = () =>
        serial(async () => {
          const id = s.dataset.ev!;
          snapshotPrev(`${s.previousElementSibling!.textContent}: ${s.options[s.selectedIndex].text}`);
          ev[id] = id === 'txCap' ? +s.value : s.value;
          await recompute();
        })),
  );
}

function snapshotPrev(what: string) {
  if (state.evals.mmap) state.prev = { what, eval: state.evals.mmap, prioKeys: Object.keys(state.M!.prio) };
}

function planMeta(id: PlanId) {
  const tau = state.spec.tau;
  return {
    mmap: {
      name: 'PILLAR plan',
      sub: `Constrained MMAP: averages over demand, rule held at ${tau != null ? fPct(tau) : 'τ'}`,
    },
    mpe: { name: 'Most-likely-world plan', sub: 'Plans for the single most likely scenario (MPE)' },
    llm: { name: 'LLM-only plan', sub: 'Written directly by the LLM, then scored here' },
  }[id];
}

function renderPlans() {
  const box = $('#planRows');
  const miss = state.missing;
  const prioKeys = state.M ? Object.keys(state.M.prio) : [];
  $('#planCaption').textContent = prioKeys.length
    ? `The priority rule covers ${prioKeys.map(keyLabel).join(', ')}${state.spec.joint && prioKeys.length > 1 ? ', all together' : ''}. Bars show its probability under the composed model; costs are expected costs including shortfall penalties.`
    : '';
  document.querySelector<HTMLElement>('.axis')!.style.visibility = miss.length ? 'hidden' : 'visible';
  if (miss.length) {
    box.innerHTML = `<p class="note" style="padding:14px 0;border-top:1px solid var(--rule)">Answer the question under Compiled rules to solve. The agent won’t guess ${miss.map((m) => (m.param === 'tau' ? 'the confidence level' : 'shortfall costs')).join(' or ')}.</p>`;
    $('#delta').innerHTML = '';
    return;
  }
  const tau = state.spec.tau!;
  const rows = (['mmap', 'mpe', 'llm'] as const)
    .filter((id) => state.evals[id])
    .map((id) => {
      const e = state.evals[id]!,
        p = state.plans[id]!,
        m = planMeta(id);
      const pAll = e.pAll;
      const w = Math.max(0, Math.min(1, pAll)) * 100;
      const inside = w > 30;
      const flags: string[] = [];
      if (id !== 'llm' && p.status && p.status !== 'optimal') flags.push('Solver: ' + p.status);
      for (const i of e.issues) flags.push(i);
      if (e.floorShort.length)
        flags.push(
          `Misses the ${fPct(state.spec.floor!.fraction)} floor at ${e.floorShort.length} store-categor${e.floorShort.length === 1 ? 'y' : 'ies'}`,
        );
      const relaxed = 'relaxed' in p ? p.relaxed : undefined;
      if (relaxed && relaxed.length)
        flags.push(
          `Policy can’t be met as written: relaxed ${relaxed
            .map((r) => `${r.rule === 'floor' ? 'floor' : 'priority rule'} at ${keyLabel(r.key)} by ${fInt(r.units)}`)
            .slice(0, 3)
            .join('; ')}${relaxed.length > 3 ? '…' : ''}`,
        );
      return `<div class="plan ${id}">
      <div><div class="name">${m.name}</div><div class="sub">${m.sub}</div>${flags.map((f) => `<div class="flag">${esc(f)}</div>`).join('')}</div>
      <div class="rail" role="img" aria-label="${m.name}: ${fPct(pAll)} probability the rule is met; target ${fPct(tau)}">
        <div class="fill" style="width:${w}%"></div>
        <div class="tau" style="left:calc(${tau * 100}% - 1px)"><span>target ${fPct(tau)}</span></div>
        <div class="val" style="${inside ? `right:${100 - w}%;color:var(--surface)` : `left:${w}%`}">${fPct(pAll)}</div>
      </div>
      <div class="nums"><b>${fCost(e.expCost)}</b>expected cost<br>transport ${fCost(e.transport)}</div>
    </div>`;
    });
  box.innerHTML = rows.join('') || '<p class="note">No plan could be solved.</p>';
  // change since the last evidence or rule update
  const pv = state.prev,
    cur = state.evals.mmap;
  if (pv && cur) {
    const dq = pv.prioKeys.reduce((a, k) => a + ((cur.q[k] || 0) - (pv.eval.q[k] || 0)), 0);
    $('#delta').innerHTML =
      `<p class="delta"><b>After “${esc(pv.what)}”:</b> PILLAR plan sends ${fInt(Math.abs(dq))} ${dq >= 0 ? 'more' : 'fewer'} units to the priority items; probability ${fPct(pv.eval.pAll)} → ${fPct(cur.pAll)}; expected cost ${fCost(pv.eval.expCost)} → ${fCost(cur.expCost)}. Re-conditioned and re-solved in ${Math.round(state.lastSolveMs)} ms.</p>`;
  } else $('#delta').innerHTML = '';
}

const TABS = [
  ['diagnosis', 'Diagnosis'],
  ['ship', 'Shipments'],
  ['cert', 'Certificate'],
  ['backtest', 'Backtest'],
  ['model', 'Model'],
];
function renderTabs() {
  $('#tabs').innerHTML = TABS.map(
    ([id, t]) => `<button role="tab" aria-selected="${state.tab === id}" data-tab="${id}">${t}</button>`,
  ).join('');
  $('#tabs')
    .querySelectorAll('button')
    .forEach(
      (b) =>
        (b.onclick = () => {
          state.tab = b.dataset.tab!;
          renderTabs();
        }),
    );
  const f = { diagnosis: tabDiagnosis, ship: tabShip, cert: tabCert, backtest: tabBacktest, model: tabModel }[
    state.tab as 'diagnosis'
  ];
  $('#tabBody').innerHTML = f();
  bindTab();
}
function bars(rows: [string, number][]) {
  const mx = Math.max(...rows.map((r) => r[1]));
  return `<div class="bars">${rows.map(([l, v]) => `<span>${esc(l)}</span><div class="bar ${v === mx ? 'best' : ''}"><i style="width:${v * 100}%"></i></div><span class="n">${fPct(v)}</span>`).join('')}</div>`;
}

function tabDiagnosis() {
  const d = state.diag!;
  if (state.preset === 'toy') {
    return `<h3>What is most likely going on</h3><p>The most likely demand at S4 is <b>70</b> (MPE), with 30% of the mass at 80. A plan conditioned on 70 ignores that 30%.</p>
      <h3>S4 demand given the evidence</h3>${bars([
        ['60', 0.15],
        ['70', 0.55],
        ['80', 0.3],
      ])}`;
  }
  const P = PRESETS.storm,
    post = d.posterior!,
    mpe = d.mpe;
  const att = d.attribution.length
    ? `<h3>What moved the beliefs</h3><div class="scroll"><table><thead><tr><th>Evidence</th><th class="n">p(landfall) without → with</th><th class="n">p(high surge) without → with</th></tr></thead><tbody>${d.attribution.map((a) => `<tr><td>${esc(a.label)}: ${esc(a.value.replace('_', ' '))}</td><td class="n">${fPct(a.landfallWithout)} → ${fPct(a.landfallWith)}</td><td class="n">${fPct(a.highWithout)} → ${fPct(a.highWith)}</td></tr>`).join('')}</tbody></table></div><p class="note" style="margin-top:6px">Each row removes one piece of evidence and recomputes the posterior exactly. TX DC capacity and lane status are also evidence about the storm.</p>`
    : '';
  const txF = Object.keys(state.M!.prio).slice(0, 3);
  return `<h3>Most likely explanation (MPE)</h3>
    <p>${esc(cap(mpe.label.z))} with ${esc(mpe.label.u)} demand surge, ${mpe.label.e ? 'emergency declared' : 'no emergency declared'}. In that world ${txF.map((k) => `${keyLabel(k)} demand is ${fInt(mpe.demand[k])}`).join(', ')}.</p>
    <p class="note" style="margin-top:4px">This scenario has probability ${fPct(mpe.w)}; the plan has to live with the other ${fPct(1 - mpe.w)} too.</p>
    <h3>Storm outcome</h3>${bars(P.Z.map((z, i) => [cap(z), post.z[i]]))}
    <h3>Texas demand surge</h3>${bars(P.U.map((u, i) => [cap(u), post.u[i]]))}
    <h3>Emergency declared</h3>${bars([
      ['Yes', post.e],
      ['No', 1 - post.e],
    ])}
    ${att}`;
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function tabShip() {
  if (!Object.keys(state.evals).length)
    return '<p class="note">Solve first: answer the question under Compiled rules.</p>';
  if (!state.evals[state.shipView]) state.shipView = 'mmap';
  const id = state.shipView,
    p = state.plans[id]!,
    e = state.evals[id]!,
    M = state.M!;
  const seg = `<div class="seg" role="group" aria-label="Plan to show">${(['mmap', 'mpe', 'llm'] as const)
    .filter((x) => state.evals[x])
    .map((x) => `<button data-ship="${x}" aria-pressed="${x === id}">${planMeta(x).name}</button>`)
    .join('')}</div>`;
  const from: Record<string, Record<string, number>> = {};
  for (const s of p.ship!) {
    const k = s.store + '|' + s.cat;
    from[k] = from[k] || {};
    from[k][s.dc] = (from[k][s.dc] || 0) + s.qty;
  }
  const head = `<tr><th>Store</th>${M.cats.map((c) => `<th class="n">${c === 'units' ? 'Units shipped' : c}</th>`).join('')}</tr>`;
  const body = M.stores
    .map(
      (s) =>
        `<tr><td>${s}</td>${M.cats
          .map((c) => {
            const k = s + '|' + c;
            const src = from[k] || {};
            const pr = M.prio[k] != null;
            return `<td class="n">${pr ? '<b>' : ''}${fInt(e.q[k])}${pr ? '</b>' : ''}<small>${Object.entries(src)
              .map(([dc, v]) => `${dc.replace('DC_', '')} ${fInt(v)}`)
              .join(' · ')}</small><small>mean demand ${fInt(state.stats[k].mean)}</small></td>`;
          })
          .join('')}</tr>`,
    )
    .join('');
  const util = M.dcs
    .map((d) => {
      const u = e.used[d.id] / d.cap;
      return `<span>${d.id}</span><div class="bar ${u > 0.999 ? 'best' : ''}"><i style="width:${Math.min(1, u) * 100}%"></i></div><span>${fInt(e.used[d.id])} of ${fInt(d.cap)}</span>`;
    })
    .join('');
  return `${seg}<h3>Units shipped by store${M.cats.length > 1 ? ' and category' : ''}</h3><p class="note" style="margin-bottom:8px">Bold cells are under the priority rule. Small lines show which DC ships them and the expected demand.</p><div class="scroll"><table><thead>${head}</thead><tbody>${body}</tbody></table></div>
    <h3>DC utilization</h3><div class="util">${util}</div>`;
}

function certificate(): [string, string, string][] | null {
  const M = state.M!,
    e = state.evals.mmap;
  if (!e) return null;
  const p = mmapPlan();
  const rows: [string, string, string][] = [];
  rows.push(['Plan', `${p.ship.length} lane shipments; ${fInt(p.ship.reduce((a, s) => a + s.qty, 0))} units`, '—']);
  rows.push([
    'Hard constraints and floors',
    e.issues.length || e.floorShort.length
      ? [...e.issues, ...e.floorShort.map((x) => 'Floor missed at ' + x.key)].join('; ')
      : 'Capacity, lanes, and floors respected',
    e.feasible ? 'Checked' : 'Failed',
  ]);
  rows.push([
    'Probability the priority rule is met',
    `${fPct(e.pAll)}${e.rules.length > 1 ? ` all together; per store ${e.rules.map((r) => `${keyLabel(r.key)} ${fPct(r.p)}`).join(', ')}` : ''}`,
    'Exact under the model',
  ]);
  rows.push([
    'Chance constraint used',
    `${e.rules.length > 1 && state.spec.joint ? `Conservative allocation: each store at ${fPct(p.tauEach)} (union bound gives ${fPct(state.spec.tau!)} jointly)` : `At ${fPct(p.tauEach)}`}; minimum units ${Object.entries(
      p.threshold,
    )
      .map(([k, v]) => `${keyLabel(k)} ${fInt(v)}`)
      .join(', ')}`,
    'Exact',
  ]);
  rows.push([
    'Expected cost',
    `${fCost(e.expCost)} (transport ${fCost(e.transport)}, shortfall penalties ${fCost(e.shortPen)})`,
    'Exact under the model',
  ]);
  rows.push(['Expected shortfall', `${fInt(e.expShortTotal)} units across all stores`, 'Exact under the model']);
  rows.push([
    'Optimality scope',
    p.relaxed.length
      ? 'Optimum of a penalized relaxation; requested rules are not all satisfied.'
      : M.spec.joint && e.rules.length > 1
        ? 'Numerical optimum of the conservative union-bound LP; no global joint-chance gap certificate.'
        : 'Numerical LP optimum for the supported finite-model formulation.',
    'Numerical',
  ]);
  rows.push(['Binding constraints', e.binding.length ? e.binding.join('; ') : 'None', 'Exact']);
  if (state.shadow)
    rows.push([
      `Value of +${fInt(state.shadow.step)} capacity`,
      Object.entries(state.shadow.dc)
        .map(([d, v]) => `${d}: ${v <= -0.5 ? 'saves ' + fCost(-v) : 'no saving'}`)
        .join('; '),
      'Exact (re-solved)',
    ]);
  if (state.preset === 'storm') {
    const ex = state.diag!.posterior!.e;
    rows.push([
      'Exception status',
      state.spec.exception ? `Emergency rule fires with probability ${fPct(ex)}` : 'No exception rule compiled',
      'Exact',
    ]);
  }
  rows.push([
    'Model caveat',
    state.preset === 'toy'
      ? 'Hand-set demand table from the slides'
      : state.custom
        ? 'Normal-week demand from loaded M5 aggregates; storm effects are synthetic overlay parameters'
        : 'Demand is synthetic M5-shaped; storm effects are synthetic overlay parameters',
    'Stated',
  ]);
  rows.push([
    'Solver status',
    `Two-phase simplex, ${p.nVars} variables × ${p.nRows} constraints, ${p.iterations} pivots`,
    'Exact',
  ]);
  return rows;
}
function tabCert() {
  const rows = certificate();
  if (!rows) return '<p class="note">Solve first: answer the question under Compiled rules.</p>';
  return `<h3>Answer certificate for the PILLAR plan</h3><div class="scroll"><table><thead><tr><th>Field</th><th>Value</th><th>Status</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td><span class="pill ${r[2].startsWith('Exact') ? 'ok' : ''}">${esc(r[2])}</span></td></tr>`).join('')}</tbody></table></div>
  <p class="note" style="margin-top:8px">“Exact under the model” means exact for the composed model as stated; it is only as good as the model’s calibration.</p>
  <div class="row" id="dlRow"><button id="dlCert">Download certificate (JSON)</button><span id="dlMsg" class="note"></span></div>`;
}

function tabBacktest() {
  if (!state.bt) return '<p class="note">Solve first: answer the question under Compiled rules.</p>';
  const bt = state.bt;
  const ids = Object.keys(bt) as PlanId[];
  const rows = ids
    .map(
      (id) =>
        `<tr><td>${planMeta(id).name}</td><td class="n">${fPct(state.evals[id]!.pAll)}</td><td class="n">${fPct(bt[id]!.rate)}</td><td class="n">${fCost(bt[id]!.avgCost)}</td></tr>`,
    )
    .join('');
  let draw = '';
  if (state.world) {
    const w = state.world,
      M = state.M!,
      pk = Object.keys(M.prio);
    draw = `<h3>One realized week</h3><p>Storm: ${esc(w.k.label.z)}, surge ${esc(w.k.label.u)}${w.k.label.e ? ', emergency declared' : ''}.</p><div class="scroll"><table><thead><tr><th>Priority item</th><th class="n">Realized demand</th>${ids.map((id) => `<th class="n">${planMeta(id).name}</th>`).join('')}</tr></thead><tbody>${pk
      .map(
        (k) =>
          `<tr><td>${keyLabel(k)}</td><td class="n">${fInt(w.d[k])}</td>${ids
            .map((id) => {
              const q = state.evals[id]!.q[k];
              const ok = q >= w.k.frac[k] * w.d[k] - 1e-9;
              return `<td class="n">${fInt(q)} <span class="pill ${ok ? 'ok' : 'bad'}">${ok ? 'met' : 'missed'}</span></td>`;
            })
            .join('')}</tr>`,
      )
      .join('')}</tbody></table></div>`;
  }
  return `<h3>2,000 weeks drawn from the model</h3><div class="scroll"><table><thead><tr><th>Plan</th><th class="n">Predicted p(rule met)</th><th class="n">Realized share met</th><th class="n">Average realized cost</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note" style="margin-top:8px">Draws come from the same model the plans were solved on, so this checks self-consistency, not real-world calibration. Scoring against held-out M5 weeks needs the real data loaded.</p>
    <div class="row"><button id="drawWeek">Draw one week</button></div>${draw}`;
}

function tabModel() {
  const M = state.M!;
  const p = state.plans.mmap as Extract<Plan, { status: 'optimal' }> | undefined;
  const nLeaves = M.configs.reduce((a, k) => a + M.sc.reduce((b, key) => b + k.atoms[key].length, 0), 0);
  let html = `<h3>What is computed, and how</h3><div class="scroll"><table><tbody>
    <tr><td>Inference</td><td>Exact sum-product evaluation over ${M.configs.length} latent configuration${M.configs.length === 1 ? '' : 's'} with posterior weight, each a product over ${M.sc.length} store-category demand distributions (${fInt(nLeaves)} leaves in total). Posteriors, MPE and rule probabilities are exact for this model.</td></tr>
    <tr><td>Solver</td><td>${p ? `Linear program, two-phase simplex in the page: ${p.nVars} variables, ${p.nRows} constraints. Chance constraints reduce exactly to minimum-service thresholds; expected shortfall enters as a piecewise-linear term built from the demand distribution.` : 'Not solved yet.'}</td></tr>
    <tr><td>Last update</td><td>${Math.round(state.lastSolveMs)} ms to rebuild the model, condition on evidence, solve both plans, score them, and value capacity.</td></tr>
    <tr><td>Where PILLAR differs</td><td>Here the scenario model is small enough to enumerate. In PILLAR the same queries run on a compiled circuit, with the demand model distilled from a trained forecaster.</td></tr>
    <tr><td>Check against slide 20</td><td id="slideCheck"></td></tr>
  </tbody></table></div>`;
  if (state.preset === 'storm') {
    const P = PRESETS.storm;
    html += `<h3>Disruption model (illustrative parameters)</h3><div class="scroll"><table><thead><tr><th>Variable</th><th class="n">Miss</th><th class="n">Graze</th><th class="n">Landfall</th></tr></thead><tbody>
      <tr><td>Prior</td>${P.pZ.map((v) => `<td class="n">${fPct(v)}</td>`).join('')}</tr>
      ${Object.entries(P.pAdv)
        .map(([k, v]) => `<tr><td>Advisory = ${k}</td>${v.map((x) => `<td class="n">${fPct(x)}</td>`).join('')}</tr>`)
        .join('')}
      ${Object.entries(P.pCap)
        .map(
          ([k, v]) => `<tr><td>TX DC at ${fPct(+k)}</td>${v.map((x) => `<td class="n">${fPct(x)}</td>`).join('')}</tr>`,
        )
        .join('')}
      <tr><td>CA→TX lane closed</td>${P.pLaneClosed.map((x) => `<td class="n">${fPct(x)}</td>`).join('')}</tr>
      <tr><td>Emergency declared</td>${P.pEmerg.map((x) => `<td class="n">${fPct(x)}</td>`).join('')}</tr>
      <tr><td>Surge low / medium / high</td>${P.pU.map((r) => `<td class="n">${r.map(fPct).join(' / ')}</td>`).join('')}</tr>
    </tbody></table></div>
    <p class="note" style="margin-top:8px">Surge raises TX FOODS demand by ${P.surge.map(fPct).join(', ')} (HOUSEHOLD by 80% of that; HOBBIES falls by half of it). The sales signal depends on surge. Store-level noise uses a 5-point distribution with coefficient of variation ${Object.entries(
      P.cv,
    )
      .map(([c, v]) => `${c} ${fPct(v)}`)
      .join(', ')}.</p>`;
  }
  return html;
}
function slideCheck() {
  const out: string[] = [];
  for (const { tau, transport, s4 } of setup.slideCheck)
    out.push(`τ = ${fPct(tau)}: transport ${fInt(transport)}, S4 gets ${fInt(s4)}`);
  const ok = out[0].includes('transport 421') && out[1].includes('transport 429');
  return `${out.join('; ')}. Slide 20 reports 421 and 429. <span class="pill ${ok ? 'ok' : 'bad'}">${ok ? 'matches' : 'mismatch'}</span>`;
}
function bindTab() {
  document.querySelectorAll<HTMLElement>('[data-ship]').forEach(
    (b) =>
      (b.onclick = () => {
        state.shipView = b.dataset.ship as PlanId;
        renderTabs();
      }),
  );
  const dw = document.querySelector<HTMLElement>('#drawWeek');
  if (dw)
    dw.onclick = () =>
      serial(async () => {
        // The page draws the uniforms, as the original drew from Math.random: one for the
        // scenario and one per demand key.
        const uniforms = Array.from({ length: 1 + state.M!.sc.length }, () => Math.random());
        const { preset, spec, ev, custom } = state;
        state.world = await api<World>('/api/replan/sample-world', { preset, spec, ev, custom, uniforms });
        renderTabs();
      });
  const sc = document.querySelector('#slideCheck');
  if (sc) sc.innerHTML = slideCheck();
  const dl = document.querySelector<HTMLButtonElement>('#dlCert');
  if (dl) {
    if (!state.downloads) dl.hidden = true;
    dl.onclick = downloadCert;
  }
}
async function downloadCert() {
  const data = {
    scenario: PRESETS[state.preset].title,
    evidence: state.ev,
    spec: state.spec,
    certificate: certificate()!.map((r) => ({ field: r[0], value: r[1], status: r[2] })),
    shipments: mmapPlan().ship,
  };
  try {
    await state.downloads!.save({
      filename: 'pillar-certificate.json',
      data: new TextEncoder().encode(JSON.stringify(data, null, 2)),
    });
    $('#dlMsg').textContent = 'Saved.';
  } catch (e) {
    $('#dlMsg').textContent =
      (e as { code?: string }).code === 'declined' ? 'Download cancelled.' : 'Downloads aren’t available here.';
  }
}

// ---------- suggestions
function renderSuggest() {
  const s =
    state.preset === 'toy'
      ? ['What is going on?', 'What do I do now?', 'What if the confidence is 70%?', 'Why this plan?']
      : [
          'What is going on?',
          'What do I do now?',
          'TX FOODS sales are up this morning.',
          'The governor declared an emergency.',
          'Can we still meet the Texas rule if the CA lane closes?',
          'Why this plan?',
          'Treat WI FOODS as priority too.',
        ];
  $('#suggest').innerHTML = s.map((t) => `<button>${esc(t)}</button>`).join('');
  $('#suggest')
    .querySelectorAll('button')
    .forEach(
      (b) =>
        (b.onclick = () => {
          $<HTMLInputElement>('#q').value = b.textContent!;
          ask();
        }),
    );
}

// ---------- routing: LLM when available, keywords otherwise
interface Route {
  intent: string;
  evidence?: Record<string, unknown>;
  whatif?: { tau?: number; priorityFraction?: number };
  rule_text?: string;
}
function keywordRoute(q: string): Route {
  const t = q.toLowerCase();
  const r: Route & { evidence: Record<string, unknown> } = { intent: 'other', evidence: {} };
  const pct = (t.match(/(\d{2,3})\s*%/) || [])[1];
  const isIf = /\bif\b|what if|still/.test(t);
  if (/lane/.test(t) && /clos/.test(t)) {
    if (isIf) return { intent: 'verify_lane' };
    r.evidence.caLane = 'closed';
  }
  if (/lane/.test(t) && /re-?open/.test(t)) r.evidence.caLane = 'open';
  if (/emergency/.test(t)) r.evidence.emergency = /\bnot\b|\bno\b|n’t|n't/.test(t) ? 'not_declared' : 'declared';
  if (/sales/.test(t)) {
    if (/sharp|spik|surg|way up|doubl/.test(t)) r.evidence.sales = 'sharp';
    else if (/\bup\b|uptick|higher|rising|jump/.test(t)) r.evidence.sales = 'up';
    else if (/flat|normal/.test(t)) r.evidence.sales = 'flat';
  }
  if (/warning/.test(t)) r.evidence.advisory = 'warning';
  else if (/\bwatch\b/.test(t)) r.evidence.advisory = 'watch';
  else if (/advisory/.test(t) && /lift|cancel|none|no /.test(t)) r.evidence.advisory = 'none';
  if (/capacity/.test(t) && pct) {
    const v = +pct / 100;
    r.evidence.txCap = [1, 0.7, 0.4].reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
  }
  if (Object.keys(r.evidence).length) {
    r.intent = 'evidence';
    return r;
  }
  if (/priority/.test(t) && /\b(ca|tx|wi|california|texas|wisconsin)\b/.test(t))
    return { intent: 'rule_change', rule_text: q };
  if (/confiden|\btau\b|τ|sure/.test(t) && pct) return { intent: 'whatif', whatif: { tau: +pct / 100 } };
  if (/(floor|serve|priority|level)/.test(t) && pct)
    return { intent: 'whatif', whatif: { priorityFraction: +pct / 100 } };
  if (/why/.test(t)) return { intent: 'explain' };
  if (/going on|happen|diagnos|most likely|situation/.test(t)) return { intent: 'diagnose' };
  if (/what (do|should)|plan|recommend|now\?|ship|decide/.test(t)) return { intent: 'decide' };
  return r;
}
async function llmRoute(q: string): Promise<Route> {
  const prompt = `Classify an operator's message to a supply-chain replanning agent. Reply with only JSON:
{"intent": one of "diagnose" (asks what is going on), "decide" (asks what to do or for a plan), "verify_lane" (asks whether the policy still holds IF the CA-to-TX lane closes), "explain" (asks why), "evidence" (reports a new observation), "rule_change" (adds or changes a standing rule or priority), "whatif" (asks about a hypothetical confidence level or priority percentage), "other",
 "evidence": {optional keys: "advisory": "none"|"watch"|"warning", "sales": "flat"|"up"|"sharp", "txCap": 1|0.7|0.4, "caLane": "open"|"closed", "emergency": "declared"|"not_declared"},
 "whatif": {optional keys: "tau": number 0-1, "priorityFraction": number 0-1},
 "rule_text": the rule change in the operator's words, if intent is rule_change}
Scenario: ${state.preset === 'toy' ? 'toy network with DCs A, B and stores S1-S4' : 'three DCs (CA, TX, WI), ten stores, a storm threatening Texas'}.
Message: """${q}"""`;
  const r = await state.sample!.json(prompt, { modelTier: 'quick' });
  if (!r || typeof r.intent !== 'string') throw { code: 'invalid_json' };
  return r;
}

// ---------- asking
async function ask() {
  const q = $<HTMLInputElement>('#q').value.trim();
  if (!q || state.busy) return;
  state.busy = true;
  $<HTMLButtonElement>('#askBtn').disabled = true;
  showAnswer(q, '<span class="spin"></span>Working…', '');
  await serial(() => answerQuestion(q));
  state.busy = false;
  $<HTMLButtonElement>('#askBtn').disabled = false;
}
async function answerQuestion(q: string) {
  let route: Route | null = null;
  let via = 'keywords';
  try {
    if (state.sample) {
      route = await llmRoute(q);
      via = 'LLM';
    }
  } catch {
    route = null;
  }
  if (!route) route = keywordRoute(q);
  try {
    await act(q, route, via);
  } catch (e) {
    const err = e as { message?: string; code?: string };
    showAnswer(q, esc('Something failed while answering: ' + (err.message || err.code || e)), '');
  }
}

type Extra = { update?: string; verify?: LaneCheck };

async function act(q: string, route: Route, via: string) {
  const intent = route.intent;
  const extra: Extra = {};
  if (intent === 'evidence' && state.preset === 'storm') {
    const ev = route.evidence || {};
    const allowed: Record<string, (string | number)[]> = {
      advisory: ['none', 'watch', 'warning'],
      sales: ['flat', 'up', 'sharp'],
      txCap: [1, 0.7, 0.4],
      caLane: ['open', 'closed'],
      emergency: ['declared', 'not_declared'],
    };
    const applied: string[] = [];
    for (const k in ev)
      if (allowed[k] && allowed[k].map(String).includes(String(ev[k]))) {
        applied.push(`${k} = ${ev[k]}`);
      }
    if (applied.length) {
      snapshotPrev(q.length > 60 ? q.slice(0, 57) + '…' : q);
      const cur = state.ev as unknown as Record<string, unknown>;
      for (const k in ev)
        if (allowed[k] && allowed[k].map(String).includes(String(ev[k])))
          cur[k] = k === 'txCap' ? +(ev[k] as number) : ev[k];
      renderEvidence();
      await recompute();
    }
    extra.update = applied.length ? applied.join(', ') : 'nothing recognized';
  } else if (intent === 'rule_change') {
    await changeRule(route.rule_text || q);
    extra.update = 'rule change compiled';
  } else if (intent === 'whatif') {
    const w = route.whatif || {};
    snapshotPrev(q.length > 60 ? q.slice(0, 57) + '…' : q);
    if (w.tau! > 0.5 && w.tau! <= 1) state.spec.tau = +w.tau!;
    if (w.priorityFraction! > 0 && w.priorityFraction! <= 1)
      state.spec.priority.forEach((r) => (r.fraction = +w.priorityFraction!));
    syncSpecJson();
    await recompute();
    extra.update = 'rule parameters changed';
  } else if (intent === 'verify_lane' && state.preset === 'storm') {
    extra.verify = await verifyLane();
  }
  if (intent === 'diagnose') state.tab = 'diagnosis';
  else if (intent === 'explain') state.tab = 'cert';
  renderTabs();
  const facts = buildFacts(intent, extra);
  const template = templateAnswer(intent, facts);
  if (state.sample && !state.missing.length) {
    try {
      const out = await state.sample(
        `You are the voice of a supply-chain replanning agent. Answer the operator in 2 to 4 short sentences of plain English, leading with the answer. Use only numbers that appear in FACTS, written exactly as they appear there; do not compute or round new numbers. Do not mention JSON or FACTS.
Operator: """${q}"""
FACTS: ${JSON.stringify(facts)}`,
        { modelTier: 'quick', onText: ({ text }) => showAnswer(q, esc(text), '') },
      );
      const chk = checkNumbers(out.text, facts);
      showAnswer(
        q,
        chk.html,
        `Routed by ${via} as “${intent}”. Worded by the LLM; ${chk.bad ? `<b style="color:var(--crit)">${chk.bad} number${chk.bad > 1 ? 's' : ''} not found in the computed facts (highlighted)</b>` : `all ${chk.total} numbers match computed values`}.`,
      );
      return;
    } catch {
      /* fall back to the template */
    }
  }
  showAnswer(q, esc(template), `Routed by ${via} as “${intent}”. Template answer from computed values.`);
}

function verifyLane() {
  const { preset, spec, ev, custom } = state;
  return api<LaneCheck>('/api/replan/verify-lane', { preset, spec, ev, custom, plan: state.plans.mmap ?? null });
}

// Facts are what the LLM may quote: every number is preformatted here.
type Facts = Record<string, Json>;
function buildFacts(intent: string, extra: Extra): Facts {
  const M = state.M!,
    d = state.diag!,
    f: Facts = { scenario: PRESETS[state.preset].title };
  const miss = state.missing;
  if (miss.length) {
    f.waiting_for = miss.map((m) => m.q);
    return f;
  }
  f.target_probability = fPct(state.spec.tau!);
  f.priority_items = Object.keys(M.prio).map(keyLabel);
  if (state.preset === 'storm') {
    const P = PRESETS.storm;
    f.most_likely_explanation = `${d.mpe.label.z}, ${d.mpe.label.u} surge, ${d.mpe.label.e ? 'emergency declared' : 'no emergency'}`;
    f.probability_of_that_explanation = fPct(d.mpe.w);
    f.storm_outcome_probabilities = Object.fromEntries(P.Z.map((z, i) => [z, fPct(d.posterior!.z[i])]));
    f.surge_probabilities = Object.fromEntries(P.U.map((u, i) => [u, fPct(d.posterior!.u[i])]));
    f.probability_emergency = fPct(d.posterior!.e);
    if (d.attribution.length)
      f.evidence_effects = d.attribution.map(
        (a) => `${a.label} (${a.value}) moved p(landfall) from ${fPct(a.landfallWithout)} to ${fPct(a.landfallWith)}`,
      );
  } else {
    f.most_likely_explanation = 'S4 demand of 70';
    f.probability_of_that_explanation = '55%';
    f.demand_tail = '30% chance S4 demand is 80';
  }
  const planFacts = (id: PlanId) => {
    const e = state.evals[id];
    if (!e) return undefined;
    return {
      probability_rule_met: fPct(e.pAll),
      expected_cost: fCost(e.expCost),
      transport_cost: fCost(e.transport),
      units_to_priority_items: fInt(Object.keys(M.prio).reduce((a, k) => a + e.q[k], 0)),
      feasible: e.feasible
        ? 'yes'
        : 'no: ' + [...e.issues, ...e.floorShort.map((x) => 'floor missed at ' + keyLabel(x.key))].join('; '),
    };
  };
  f.pillar_plan = planFacts('mmap');
  f.most_likely_world_plan = planFacts('mpe');
  if (state.evals.llm) f.llm_only_plan = planFacts('llm');
  if (state.evals.mmap) {
    const p = mmapPlan();
    f.pillar_binding_constraints = state.evals.mmap.binding.slice(0, 5);
    f.pillar_minimum_units_per_priority_item = Object.fromEntries(
      Object.entries(p.threshold).map(([k, v]) => [keyLabel(k), fInt(v)]),
    );
    if (p.relaxed.length)
      f.rules_relaxed_because_infeasible = p.relaxed.map(
        (r) => `${r.rule} at ${keyLabel(r.key)} by ${fInt(r.units)} units`,
      );
    if (state.shadow)
      f.value_of_extra_capacity = Object.fromEntries(
        Object.entries(state.shadow.dc).map(([dc, v]) => [
          `${dc} +${fInt(state.shadow!.step)} units`,
          v <= -0.5 ? 'saves ' + fCost(-v) : 'no saving',
        ]),
      );
  }
  if (state.prev && state.evals.mmap && (intent === 'evidence' || intent === 'whatif' || intent === 'rule_change')) {
    const pv = state.prev,
      cur = state.evals.mmap;
    const dq = pv.prioKeys.reduce((a, k) => a + ((cur.q[k] || 0) - (pv.eval.q[k] || 0)), 0);
    f.change_since_last_plan = {
      trigger: pv.what,
      units_to_priority_items_change: (dq >= 0 ? '+' : '−') + fInt(Math.abs(dq)),
      probability_before: fPct(pv.eval.pAll),
      probability_after: fPct(cur.pAll),
      expected_cost_before: fCost(pv.eval.expCost),
      expected_cost_after: fCost(cur.expCost),
      solve_time: Math.round(state.lastSolveMs) + ' ms',
    };
  }
  if (extra.update) f.applied_update = extra.update;
  if (extra.verify) {
    const v = extra.verify;
    f.if_ca_lane_closes = {
      units_lost_from_current_plan: fInt(v.lostUnits),
      current_plan_probability_rule_met: fPct(v.keptP),
      replanned_probability_rule_met: v.replanP != null ? fPct(v.replanP) : 'no feasible plan',
      replanned_expected_cost: v.replanCost != null ? fCost(v.replanCost) : 'n/a',
      note: 'conditioning on the closure also raises the belief in landfall',
    };
  }
  return f;
}

function templateAnswer(intent: string, f: Facts) {
  if (f.waiting_for) return `Before I can plan, I need one more parameter: ${f.waiting_for.join(' ')}`;
  const pp = f.pillar_plan,
    mp = f.most_likely_world_plan;
  const decide = pp
    ? `Use the PILLAR plan: it meets the priority rule with probability ${pp.probability_rule_met} (target ${f.target_probability}) at expected cost ${pp.expected_cost}. Planning for the most likely world (${f.most_likely_explanation}) meets it with probability ${mp ? mp.probability_rule_met : 'n/a'} at expected cost ${mp ? mp.expected_cost : 'n/a'}.`
    : 'No plan could be solved.';
  if (intent === 'diagnose')
    return (
      `Most likely: ${f.most_likely_explanation} (probability ${f.probability_of_that_explanation}).` +
      (f.storm_outcome_probabilities
        ? ` Storm outcome: miss ${f.storm_outcome_probabilities.miss}, graze ${f.storm_outcome_probabilities.graze}, landfall ${f.storm_outcome_probabilities.landfall}. Emergency declared: ${f.probability_emergency}.`
        : ` But there is a ${f.demand_tail}.`)
    );
  if (intent === 'explain')
    return `${decide} The plan is shaped by: ${(f.pillar_binding_constraints || []).join('; ') || 'no binding capacity'}. Each priority item gets at least ${Object.entries(
      f.pillar_minimum_units_per_priority_item || {},
    )
      .map(([k, v]) => `${v} units at ${k}`)
      .join(', ')}, the smallest amounts that meet the rule.`;
  if (intent === 'verify_lane' && f.if_ca_lane_closes) {
    const v = f.if_ca_lane_closes;
    return `If the CA→TX lane closes, the current plan loses ${v.units_lost_from_current_plan} units and meets the Texas rule with probability ${v.current_plan_probability_rule_met}. Replanning with the lane closed gets ${v.replanned_probability_rule_met} at expected cost ${v.replanned_expected_cost}.`;
  }
  if (f.change_since_last_plan) {
    const c = f.change_since_last_plan;
    return `Updated (${f.applied_update}). ${decide} Compared with before: ${c.units_to_priority_items_change} units to the priority items, probability ${c.probability_before} → ${c.probability_after}, expected cost ${c.expected_cost_before} → ${c.expected_cost_after}.`;
  }
  return decide;
}

// numbers in the LLM's text must appear in the computed facts
function checkNumbers(text: string, facts: Facts) {
  const allowed = new Set<string>();
  const norm = (s: string) =>
    s
      .replace(/[,\s]/g, '')
      .replace(/[%k]$/i, '')
      .replace(/^[+−-]/, '');
  (function walk(o: unknown) {
    if (o == null) return;
    if (typeof o === 'object') {
      for (const k in o) {
        walk(k);
        walk((o as Record<string, unknown>)[k]);
      }
      return;
    }
    String(o).replace(/\d[\d,]*(\.\d+)?/g, (m) => {
      allowed.add(norm(m));
      return m;
    });
  })(facts);
  let bad = 0,
    total = 0;
  const html = esc(text).replace(/\d[\d,]*(\.\d+)?\s?(%|k\b)?/g, (m) => {
    const n = norm(m.trim());
    total++;
    if (allowed.has(n) || (/^\d+$/.test(n) && +n <= 10) || /^(19|20)\d\d$/.test(n)) return m;
    bad++;
    return `<mark title="Not in the computed facts">${m}</mark>`;
  });
  return { html, bad, total };
}

function showAnswer(q: string, html: string, meta: string) {
  const a = $('#answer');
  a.classList.remove('empty');
  a.innerHTML = `<div class="q">${esc(q)}</div><div class="a">${html}</div>${meta ? `<div class="meta">${meta}</div>` : ''}`;
}

// ---------- LLM: compile rules
const SPEC_SCHEMA = `{"spec": {"priority": [{"stores": [store ids], "category": category id, "fraction": number between 0 and 1}], "floor": {"fraction": number} or null, "exception": {"when": "emergency_declared", "fraction": number} or null, "crossStateMultiplier": number or null, "penalties": {"priority": number, "other": number} or null, "tau": number between 0.5 and 1 or null, "joint": boolean}, "unsupported": [short quotes of operator statements this schema cannot express], "assumed": [names of spec fields whose values you inferred rather than read directly]}`;
function vocab() {
  const P = PRESETS[state.preset];
  return `stores: ${P.stores.map((s) => s.id).join(', ')}\ncategories: ${P.cats.join(', ')}${state.preset === 'storm' ? '\nStore ids start with their state (CA, TX, WI).' : ''}`;
}
function specRules() {
  return `Rules:
- Never invent a number. If the text gives no confidence level for the priority rule, "tau" is null. If it gives no shortfall costs, "penalties" is null.
- "joint" is true only if the text says the rule must hold for all listed stores together.
- Capacities, lane availability and demand come from network data, not from this spec; ignore them.
- Reply with only the JSON object.`;
}
async function translate() {
  const btn = $<HTMLButtonElement>('#translateBtn'),
    st = $('#translateStatus');

  btn.disabled = true;
  st.innerHTML = '<span class="spin"></span>Compiling with the LLM…';
  const text = $<HTMLTextAreaElement>('#knowledge').value;
  try {
    const r = await chatgpt.json(
      `Convert an operator's supply-chain knowledge into a JSON spec that a solver compiles.\n\nVocabulary (use exactly these ids):\n${vocab()}\n\nReply in this shape:\n${SPEC_SCHEMA}\n\n${specRules()}\n\nOperator text:\n"""${text}"""`,
      { modelTier: 'default' },
    );
    await applyCompiled(r, 'Compiled');
  } catch (e) {
    const code = (e as { code?: string }).code;
    st.textContent =
      code === 'not_granted'
        ? 'ChatGPT handoff was cancelled. You can still edit the spec directly.'
        : 'Compilation failed (' + (code || 'error') + '). Try again, or edit the spec directly.';
  }
  btn.disabled = false;
}
async function changeRule(instruction: string) {
  if (state.sample) {
    try {
      const r = await state.sample.json(
        `Apply an operator's change to a supply-chain policy spec. Return the full updated spec.\n\nVocabulary:\n${vocab()}\n\nCurrent spec:\n${JSON.stringify(state.spec)}\n\nReply in this shape:\n${SPEC_SCHEMA}\n\n${specRules()}\n- Keep every current value the change does not touch.\n\nChange requested:\n"""${instruction}"""`,
        { modelTier: 'default' },
      );
      snapshotPrev(instruction.length > 60 ? instruction.slice(0, 57) + '…' : instruction);
      await applyCompiled(r, 'Rule change compiled');
      return;
    } catch {
      /* fall through */
    }
  }
  // keyword fallback: add a priority rule for a state’s stores
  const t = instruction.toLowerCase();
  const st =
    (t.match(/\b(ca|tx|wi)\b/) || [])[1] ||
    ({ california: 'ca', texas: 'tx', wisconsin: 'wi' } as Record<string, string>)[
      (t.match(/california|texas|wisconsin/) || [])[0]!
    ];
  if (st && state.preset === 'storm') {
    const cat = (t.match(/foods|household|hobbies/) || ['foods'])[0].toUpperCase();
    const pct = (t.match(/(\d{2,3})\s*%/) || [])[1];
    snapshotPrev(instruction);
    state.spec.priority.push({
      stores: PRESETS.storm.stores.filter((s) => s.state === st.toUpperCase()).map((s) => s.id),
      category: cat,
      fraction: pct ? +pct / 100 : state.spec.priority[0]?.fraction || 0.9,
    });
    syncSpecJson();
    await recompute();
  }
}
function validateSpec(raw: unknown) {
  return api<{ spec: Spec | null; errs: string[] }>('/api/replan/validate-spec', { preset: state.preset, raw });
}
async function applyCompiled(r: Json, label: string) {
  const raw = r && r.spec ? r.spec : r;
  const { spec, errs } = await validateSpec(raw);
  const st = $('#translateStatus');
  if (!spec || !spec.priority.length) {
    st.textContent = 'The LLM’s output didn’t compile: ' + errs.join(' ');
    return;
  }
  state.spec = spec;
  state.unsupported = Array.isArray(r.unsupported) ? r.unsupported.map(String).slice(0, 6) : [];
  state.assumed = Array.isArray(r.assumed) ? r.assumed.map(String) : [];
  st.textContent = `${label}. Check the paraphrase below; it is generated from what was compiled, not written by the LLM.${errs.length ? ' Warnings: ' + errs.join(' ') : ''}`;
  syncSpecJson();
  await recompute();
}

// ---------- LLM-only baseline
async function llmPlan() {
  const btn = $<HTMLButtonElement>('#llmPlanBtn');

  if (state.missing.length) {
    showAnswer('Ask ChatGPT to plan directly', 'Answer the question under Compiled rules first.', '');
    return;
  }
  const M = state.M!;
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span>LLM is planning…';
  const laneLines =
    state.preset === 'toy'
      ? M.lanes.map((L) => `${L.dc}→${L.store}: ${L.cost}`).join(', ')
      : (() => {
          const g: Record<string, number> = {};
          for (const L of M.lanes) {
            const k = `${L.dc}→${M.storeState[L.store]} stores`;
            g[k] = L.cost;
          }
          return (
            Object.entries(g)
              .map(([k, v]) => `${k}: ${v}`)
              .join(', ') + (state.ev.caLane === 'closed' ? ' (DC_CA→TX is CLOSED)' : '')
          );
        })();
  const fc = M.sc
    .map(
      (k) =>
        `${keyLabel(k)}: mean ${fInt(state.stats[k].mean)} (10th–90th percentile ${fInt(state.stats[k].p10)}–${fInt(state.stats[k].p90)}); normal-week forecast ${fInt(M.forecast[k])}`,
    )
    .join('\n');
  const evText =
    state.preset === 'toy'
      ? 'DC B capacity dropped to 50. S4 demand is 60, 70 or 80 with probabilities 0.15, 0.55, 0.30.'
      : `Advisory: ${state.ev.advisory}; TX sales signal: ${state.ev.sales}; TX DC at ${state.ev.txCap * 100}% capacity; CA→TX lane ${state.ev.caLane}; emergency: ${state.ev.emergency}.`;
  const prompt = `Plan this week's shipments for a supply network under disruption. Decide how many units each DC ships to each store${M.cats.length > 1 ? ' and category' : ''}.

Operator knowledge:
${$<HTMLTextAreaElement>('#knowledge').value}

Compiled policy:
${paraphrase(state.spec)
  .map((l) => '- ' + l.t)
  .join('\n')}

Current evidence: ${evText}

DC capacities (units, hard limits): ${M.dcs.map((d) => `${d.id} ${d.cap}`).join(', ')}
Lane cost per unit: ${laneLines}
Demand this week given the evidence:
${fc}

Reply with only JSON: {"ship": [{"dc": "${M.dcs[0].id}", "store": "${M.stores[0]}", "cat": "${M.cats[0]}", "qty": 100}], "rationale": "one sentence"}. List every shipment with qty above zero.`;
  try {
    const r = await chatgpt.json(prompt, { modelTier: 'default', cache: false });
    if (!Array.isArray(r.ship)) throw { code: 'missing_shipments' };
    for (const s of r.ship)
      if (
        !M.dcs.some((d) => d.id === s.dc) ||
        !M.stores.includes(s.store) ||
        !M.cats.includes(s.cat) ||
        !Number.isFinite(s.qty) ||
        s.qty < 0
      )
        throw { code: 'invalid_shipment' };
    const ship = r.ship
      .map((s: Json) => ({ dc: s.dc, store: s.store, cat: s.cat, qty: s.qty }))
      .filter((s: { qty: number }) => s.qty > 0);
    if (!ship.length) throw { code: 'empty' };
    state.llmPlan = { status: 'proposed', ship, rationale: String(r.rationale || '') };
    await recompute();
    const e = state.evals.llm!;
    showAnswer(
      'Ask ChatGPT to plan directly',
      esc(
        `The LLM proposed ${ship.length} shipments. Scored under the same model: probability the rule is met ${fPct(e.pAll)}, expected cost ${fCost(e.expCost)}${e.feasible ? '' : '; it breaks hard constraints or floors'}. Its stated rationale: “${state.llmPlan.rationale}”`,
      ),
      'The plan is the LLM’s; every number here is computed by the engine.',
    );
  } catch (e) {
    showAnswer(
      'Ask ChatGPT to plan directly',
      esc('The LLM’s plan couldn’t be read (' + ((e as { code?: string }).code || 'error') + '). Try again.'),
      '',
    );
  }
  btn.disabled = false;
  btn.textContent = state.llmPlan ? 'Ask ChatGPT to plan again' : 'Ask ChatGPT to plan directly';
}

// ---------- CSV of M5 aggregates
function loadCsv(file: File) {
  const rd = new FileReader();
  rd.onload = () =>
    serial(async () => {
      const lines = String(rd.result)
        .split(/\r?\n/)
        .filter((l) => l.trim());
      const head = lines
        .shift()!
        .split(',')
        .map((h) => h.trim().toLowerCase());
      const iS = head.indexOf('store_id'),
        iC = head.indexOf('cat_id'),
        iM = head.indexOf('weekly_mean'),
        iV = head.indexOf('cv');
      if (iS < 0 || iC < 0 || iM < 0) {
        $('#csvMsg').textContent = 'Needs columns store_id, cat_id, weekly_mean (and optionally cv).';
        return;
      }
      const custom: CustomDemand = { base: {}, cv: {} };
      let n = 0;
      for (const l of lines) {
        const c = l.split(',');
        const k = c[iS].trim() + '|' + c[iC].trim();
        const m = +c[iM];
        if (
          PRESETS.storm.stores.some((s) => s.id === c[iS].trim()) &&
          PRESETS.storm.cats.includes(c[iC].trim()) &&
          m > 0
        ) {
          custom.base[k] = m;
          if (iV >= 0 && +c[iV] > 0) custom.cv[k] = +c[iV];
          n++;
        }
      }
      if (!n) {
        $('#csvMsg').textContent = 'No rows matched the 10 M5 stores and 3 categories.';
        return;
      }
      state.custom = custom;
      $('#csvMsg').textContent = `Loaded ${n} of 30 store-category rows.`;
      renderEvidence();
      await recompute();
    });
  rd.readAsText(file);
}

// ---------- boot
async function loadPreset(id: PresetId) {
  state.preset = id;
  const P = PRESETS[id];
  state.spec = clone(P.defaultSpec);
  state.ev = { ...DEFAULT_EVIDENCE };
  state.llmPlan = null;
  state.prev = null;
  state.world = null;
  state.assumed = [];
  state.unsupported = [];
  $<HTMLTextAreaElement>('#knowledge').value = P.knowledge;
  $('#translateStatus').textContent = '';
  $('#llmPlanBtn').textContent = 'Ask ChatGPT to plan directly';
  $('#answer').className = 'answer empty';
  $('#answer').innerHTML =
    `<div class="a">${id === 'storm' ? 'Start by answering the question under Compiled rules, then ask “What is going on?”' : 'This is the slide-3 toy. Ask “What do I do now?” and compare with slide 7.'}</div>`;
  renderEvidence();
  renderSuggest();
  await recompute();
}
$('#preset').onchange = (e) => serial(() => loadPreset((e.target as HTMLSelectElement).value as PresetId));
$('#translateBtn').onclick = () => serial(translate);
$('#resetKnow').onclick = () => {
  $<HTMLTextAreaElement>('#knowledge').value = PRESETS[state.preset].knowledge;
};
$('#applySpec').onclick = () =>
  serial(async () => {
    try {
      const { spec, errs } = await validateSpec(JSON.parse($<HTMLTextAreaElement>('#specJson').value));
      if (!spec || !spec.priority.length) {
        $('#specErr').textContent = errs.join(' ');
        return;
      }
      snapshotPrev('spec edited');
      state.spec = spec;
      state.assumed = [];
      $('#specErr').textContent = errs.join(' ');
      await recompute();
    } catch (e) {
      $('#specErr').textContent = 'That isn’t valid JSON: ' + (e as Error).message;
    }
  });
$('#askBtn').onclick = ask;
$('#q').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') ask();
});
$('#llmPlanBtn').onclick = () => serial(llmPlan);
$('#csv').onchange = (e) => {
  const f = (e.target as HTMLInputElement).files![0];
  if (f) loadCsv(f);
};
serial(() => loadPreset('storm'));

const chatgpt = createChatGPTBridge();
state.downloads = {
  save: async ({ filename, data }) => chatgpt.download(filename, data, 'application/json'),
};
$('#chatgptSetup').onclick = () => chatgpt.showInfo();
(async () => {
  const connected = await chatgpt.ready();
  state.sample = connected ? chatgpt.sample : null;
  const status = $('#llmStatus');
  status.textContent = connected ? 'ChatGPT API connected' : 'ChatGPT handoff ready';
  status.classList.add('on');
  // Queued behind the first computation, which may still be in flight.
  await serial(renderTabs);
})();
mountEvaluationPanel();
