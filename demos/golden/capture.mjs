// Run the engines inside the original demo HTML files and record their outputs as golden JSON.
//
// The Python engines in demos/backend must reproduce these numbers (uv run pytest). The original
// files are the specification: this script reads their code as-is and never edits it.
//
//   node demos/golden/capture.mjs        (writes demos/golden/*.json)

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const original = name => readFileSync(join(here, '..', 'original', name), 'utf8');
const copilotHtml = original('pillar-circuit-copilot.html');
const engines = {};
const replanHtml = original('pillar-replan-chatgpt.html');

function between(src, start, end) {
  const i = src.indexOf(start);
  const j = src.indexOf(end, i);
  if (i < 0 || j < 0) throw new Error(`markers not found: ${start} … ${end}`);
  return src.slice(i, j);
}

// Source of a top-level `function name(...) { ... }`, found by brace matching.
function functionSource(src, name) {
  const i = src.indexOf(`function ${name}(`);
  if (i < 0) throw new Error(`function ${name} not found`);
  let depth = 0;
  for (let j = src.indexOf('{', i); j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}' && --depth === 0) return src.slice(i, j + 1);
  }
  throw new Error(`unbalanced braces in ${name}`);
}

function run(code, globals = {}) {
  const ctx = vm.createContext({ ...globals });
  vm.runInContext(code, ctx);
  return ctx;
}

// JSON with -0 normalised and functions dropped, so golden files diff cleanly.
const plain = v => JSON.parse(JSON.stringify(v, (_, x) => (Object.is(x, -0) ? 0 : x)));
const write = (name, data) => {
  writeFileSync(join(here, name), JSON.stringify(plain(data), null, 1) + '\n');
  console.log('wrote', name);
};

// ---------------------------------------------------------------- Circuit Copilot
{
  const code = between(copilotHtml, 'function solveLP(', 'globalThis.CircuitDemo=CircuitDemo;');
  const E = run(code + '\nthis.CircuitDemo = CircuitDemo;').CircuitDemo;

  // The engine part of the page's recompute(): the decision plus the most-likely-world plan.
  const analyze = raw => {
    const p = E.validate(raw);
    const c = E.compile(p);
    const result = E.solve(c, p);
    const ps = E.worldWeights(c, p);
    const id = ps.indexOf(Math.max(...ps));
    const pr = E.solve(c, { ...p, evidence: c.worlds[id].name });
    const mpe = pr.best ? E.score(c, pr.best.x, p) : null;
    return { p, circuit: { ...c, evaluate: undefined }, result, mpe };
  };
  const errorOf = raw => {
    try { E.validate(raw); return null; } catch (e) { return e.message; }
  };

  const B = E.base;
  const cases = {
    // The seven tour steps that change parameters (steps 2 and 6 only ask questions).
    tour1_demand: { ...B },
    tour3_tau70: { ...B, tau: 0.7 },
    tour4_storm: { ...B, scenario: 'storm' },
    tour5_storm_backup: { ...B, scenario: 'storm', backupEnabled: true },
    tour7_exception: { ...B, exceptionAuthorized: true },
  };
  for (const scenario of ['demand', 'storm'])
    for (const evidence of ['all', 'Normal', 'Surge', 'Storm'])
      for (const backupEnabled of [false, true])
        cases[`${scenario}_${evidence}_backup${backupEnabled ? 'On' : 'Off'}`] = { ...B, scenario, evidence, backupEnabled };
  for (const capacityB of [0, 30, 80, 200]) cases[`storm_capB${capacityB}`] = { ...B, scenario: 'storm', capacityB };
  for (const stormProbability of [0, 0.1, 0.5, 1]) cases[`storm_q${stormProbability}`] = { ...B, scenario: 'storm', stormProbability };
  for (const tau of [0.3, 0.5, 0.85, 0.99]) cases[`demand_tau${tau}`] = { ...B, tau };
  for (const service of [0.5, 0.8, 1]) cases[`demand_service${service}`] = { ...B, service, exceptionService: Math.min(0.8, service) };
  cases.storm_backup_limit10_cost40 = { ...B, scenario: 'storm', backupEnabled: true, backupLimit: 10, backupCost: 40 };
  cases.storm_exception_backup = { ...B, scenario: 'storm', exceptionAuthorized: true, backupEnabled: true };

  const minimumBackup = {};
  for (const [name, raw] of Object.entries({ demand: { ...B }, storm: { ...B, scenario: 'storm' }, storm_tau90: { ...B, scenario: 'storm', tau: 0.9 } })) {
    const p = E.validate(raw);
    minimumBackup[name] = E.minimumBackup(E.compile(p), p);
  }

  const invalid = {
    notObject: null,
    array: [],
    unknownField: { ...B, color: 'red' },
    badScenario: { ...B, scenario: 'flood' },
    badEvidence: { ...B, evidence: 'Hail' },
    tauTooLow: { ...B, tau: 0 },
    capacityString: { ...B, capacityA: '130' },
    backupNotBool: { ...B, backupEnabled: 1 },
    exceptionAboveService: { ...B, exceptionAuthorized: true, exceptionService: 0.95 },
  };

  const lpCases = {
    simple: [2, [1, 1], [{ a: { 0: 1, 1: 1 }, op: '>=', b: 4 }, { a: { 0: 1 }, op: '<=', b: 3 }]],
    infeasible: [1, [1], [{ a: { 0: 1 }, op: '<=', b: 1 }, { a: { 0: 1 }, op: '>=', b: 2 }]],
    unbounded: [1, [-1], [{ a: { 0: 1 }, op: '>=', b: 1 }]],
    equality_negative_b: [2, [1, 2], [{ a: { 0: 1, 1: 1 }, op: '=', b: 5 }, { a: { 0: -1 }, op: '<=', b: -1 }]],
  };
  const solveLP = run(code + '\nthis.solveLP = solveLP;').solveLP;
  const lp = Object.fromEntries(Object.entries(lpCases).map(([k, [n, c, rows]]) => [k, { input: { n, c, rows }, output: solveLP(n, c, rows) }]));

  engines.copilot = { E, analyze };
  write('copilot.json', {
    base: B,
    cases: Object.fromEntries(Object.entries(cases).map(([k, raw]) => [k, { input: raw, output: analyze(raw) }])),
    minimumBackup,
    independenceContrast: E.independenceContrast(),
    invalid: Object.fromEntries(Object.entries(invalid).map(([k, raw]) => [k, { input: raw, error: errorOf(raw) }])),
    lp,
  });
}

// ---------------------------------------------------------------- Replan
{
  const engine = between(replanHtml, 'const EPS = 1e-9;', "if (typeof module !== 'undefined')");
  const helpers = ['missingParams', 'validateSpec'].map(n => functionSource(replanHtml, n)).join('\n');
  const ctx = run(
    `var state = { preset: 'storm' };\n${engine}\n${helpers}\n` +
      'this.api = { buildModel, solvePlan, evaluatePlan, diagnose, backtest, mpeQuery, PRESETS, DEFAULT_EVIDENCE, missingParams, validateSpec };',
  );
  const R = ctx.api;
  const clone = o => JSON.parse(JSON.stringify(o));
  const stripMs = p => (p && typeof p === 'object' ? { ...p, ms: undefined } : p);

  // The engine part of the page's recompute(): diagnose, both plans, scores, backtest, value of capacity.
  const recompute = (preset, spec, ev, llmPlan = null) => {
    const missing = R.missingParams(spec);
    const specForModel = missing.length ? { ...spec, tau: spec.tau ?? 0.9, penalties: spec.penalties ?? { priority: 8, other: 6 } } : spec;
    const diag = R.diagnose(preset, specForModel, ev);
    const M = diag.M;
    const plans = {}, evals = {};
    let bt = null, shadow = null;
    if (!missing.length) {
      plans.mmap = R.solvePlan(M, 'mmap');
      plans.mpe = R.solvePlan(M, 'mpe');
      for (const id of ['mmap', 'mpe']) if (plans[id].status === 'optimal') evals[id] = R.evaluatePlan(M, plans[id].ship);
      if (llmPlan) { plans.llm = llmPlan; evals.llm = R.evaluatePlan(M, llmPlan.ship); }
      const ids = Object.keys(evals);
      const b = R.backtest(M, ids.map(id => plans[id]), 2000, 11);
      bt = {}; ids.forEach((id, i) => (bt[id] = b[i]));
      if (evals.mmap) {
        const step = preset === 'toy' ? 1 : 1000;
        shadow = { step, dc: {} };
        for (const d of M.dcs) {
          const M2 = R.buildModel(preset, specForModel, ev, { capDelta: { [d.id]: step } });
          if (preset === 'toy') M2.dcs.find(x => x.id === d.id).cap += step;
          const p2 = R.solvePlan(M2, 'mmap');
          if (p2.status === 'optimal') shadow.dc[d.id] = R.evaluatePlan(M2, p2.ship).expCost - evals.mmap.expCost;
        }
      }
    }
    for (const id in plans) plans[id] = stripMs(plans[id]);
    return { missing, diag, plans, evals, bt, shadow };
  };

  // The storm preset ships with tau unset, so the page asks for it before solving; most cases answer 90%.
  const stormAsShipped = R.PRESETS.storm.defaultSpec, toy = R.PRESETS.toy.defaultSpec, E0 = R.DEFAULT_EVIDENCE;
  const storm = { ...stormAsShipped, tau: 0.9 };
  const cases = {
    storm_as_shipped: ['storm', stormAsShipped, E0],
    toy_default: ['toy', toy, E0],
    toy_tau70: ['toy', { ...toy, tau: 0.7 }, E0],
    toy_tau90: ['toy', { ...toy, tau: 0.9 }, {}],
    toy_joint: ['toy', { ...toy, joint: true }, E0],
    // Over-committed: floors and priority need more than the 180 units A and B can ship.
    toy_relaxed_floor: ['toy', { ...toy, floor: { fraction: 0.95 } }, E0],
    toy_relaxed_priority: ['toy', { ...toy, tau: 0.99, priority: [{ stores: ['S1', 'S4'], category: 'units', fraction: 1 }] }, E0],
    storm_default: ['storm', storm, E0],
    storm_penalties_missing: ['storm', { ...storm, penalties: null }, E0],
    storm_both_missing: ['storm', { ...storm, tau: null, penalties: null }, E0],
    storm_tau80: ['storm', { ...storm, tau: 0.8 }, E0],
    storm_not_joint: ['storm', { ...storm, joint: false }, E0],
    storm_tau95: ['storm', { ...storm, tau: 0.95 }, E0],
    storm_no_exception: ['storm', { ...storm, exception: null }, E0],
    storm_no_floor: ['storm', { ...storm, floor: null }, E0],
    storm_mult2: ['storm', { ...storm, crossStateMultiplier: 2 }, E0],
    storm_mult8: ['storm', { ...storm, crossStateMultiplier: 8 }, E0],
    storm_wi_priority: ['storm', { ...storm, priority: [...storm.priority, { stores: ['WI_1', 'WI_2', 'WI_3'], category: 'FOODS', fraction: 0.9 }] }, E0],
  };
  const fields = { advisory: ['unknown', 'none', 'warning'], sales: ['flat', 'up', 'sharp'], txCap: [1, 0.4], caLane: ['closed'], emergency: ['declared', 'not_declared'], week: ['snap'] };
  for (const [k, vs] of Object.entries(fields)) for (const v of vs) cases[`storm_ev_${k}_${v}`] = ['storm', storm, { ...E0, [k]: v }];
  cases.storm_worst = ['storm', storm, { advisory: 'warning', sales: 'sharp', txCap: 0.4, caLane: 'closed', emergency: 'declared', week: 'snap' }];
  cases.storm_calm = ['storm', storm, { advisory: 'none', sales: 'flat', txCap: 1, caLane: 'open', emergency: 'not_declared', week: 'normal' }];

  // The full model M is large; keep it for a few cases and only its summary elsewhere.
  const keepModel = new Set(['toy_default', 'storm_default', 'storm_worst']);
  const slim = (k, o) => (keepModel.has(k) ? o : { ...o, diag: { ...o.diag, M: summary(o.diag.M) } });
  const summary = M => ({ dcs: M.dcs, forecast: M.forecast, prio: M.prio, nConfigs: M.configs.length, weights: M.configs.map(k => k.w) });
  const out = {};
  for (const [k, [preset, spec, ev]] of Object.entries(cases)) out[k] = { input: { preset, spec: clone(spec), ev: clone(ev) }, output: slim(k, recompute(preset, clone(spec), ev)) };

  // A hand-written "LLM" plan, scored alongside the solver's plans; one lane is closed.
  const llmPlan = {
    status: 'proposed',
    ship: [
      { dc: 'DC_TX', store: 'TX_1', cat: 'FOODS', qty: 12000 },
      { dc: 'DC_CA', store: 'TX_2', cat: 'FOODS', qty: 9000 },
      { dc: 'DC_WI', store: 'WI_1', cat: 'HOBBIES', qty: 1500 },
    ],
    rationale: 'golden fixture',
  };
  out.storm_llm_plan = { input: { preset: 'storm', spec: clone(storm), ev: clone(E0), llmPlan }, output: slim('', recompute('storm', clone(storm), E0, llmPlan)) };
  const closed = { ...E0, caLane: 'closed' };
  out.storm_llm_plan_lane_closed = { input: { preset: 'storm', spec: clone(storm), ev: closed, llmPlan }, output: slim('', recompute('storm', clone(storm), closed, llmPlan)) };

  // validateSpec reads the active preset from the page state.
  const validate = (preset, raw) => { ctx.state.preset = preset; return R.validateSpec(raw); };
  const specInputs = {
    storm_default: ['storm', stormAsShipped],
    toy_default: ['toy', toy],
    toy_category_fallback: ['toy', { ...toy, priority: [{ stores: ['S1'], category: 'whatever', fraction: 0.8 }] }],
    unknown_category: ['storm', { ...storm, priority: [{ stores: ['TX_1'], category: 'TOYS', fraction: 0.9 }] }],
    unknown_stores: ['storm', { ...storm, priority: [{ stores: ['TX_1', 'NY_1'], category: 'FOODS', fraction: 0.9 }] }],
    bad_fraction: ['storm', { ...storm, priority: [{ stores: ['TX_1'], category: 'FOODS', fraction: 1.5 }] }],
    string_numbers: ['storm', { ...storm, tau: '0.8', floor: { fraction: '0.5' }, penalties: { priority: '9', other: '3' } }],
    tau_low: ['storm', { ...storm, tau: 0.4 }],
    mult_low: ['storm', { ...storm, crossStateMultiplier: 0.5 }],
    no_priority: ['storm', { ...storm, priority: [] }],
    not_object: ['storm', 'nope'],
  };
  const specs = Object.fromEntries(Object.entries(specInputs).map(([k, [preset, raw]]) => [k, { input: { preset, raw }, output: validate(preset, raw) }]));

  // CSV-loaded M5 aggregates replace normal-week demand (the page mutates PRESETS.storm.custom).
  R.PRESETS.storm.custom = { base: { 'TX_1|FOODS': 15000, 'CA_1|HOBBIES': 3000 }, cv: { 'TX_1|FOODS': 0.2 } };
  const customCase = { input: { preset: 'storm', spec: clone(storm), ev: clone(E0), custom: R.PRESETS.storm.custom }, output: recompute('storm', clone(storm), E0) };
  delete R.PRESETS.storm.custom;

  engines.replan = { R, recompute, slim, ctx };
  write('replan.json', { presets: R.PRESETS, defaultEvidence: E0, cases: out, customDemand: customCase, specs });
}

// ---------------------------------------------------------------- Forecast comparison (shared)
{
  const a = between(copilotHtml, '/* Shared, browser-local forecasting', '</script>');
  const b = between(replanHtml, '/* Shared, browser-local forecasting', '</script>');
  if (a !== b) throw new Error('the two copies of the evaluation module differ');
  const API = run(a).PillarEvaluation;

  const datasets = Object.fromEntries(['correlated', 'independent', 'shift'].map(k => [k, API.synthetic(k)]));
  const ref = { priority_floor: 0.9, base_floor: 0.6, emergency: false };
  const ruleSets = { reference: ref, lower: { priority_floor: 0.8, base_floor: 0.5, emergency: false }, emergency: { ...ref, emergency: true } };
  const runs = {};
  for (const [dk, data] of Object.entries(datasets))
    for (const [rk, rules] of Object.entries(ruleSets))
      for (const capacity of [150, 240])
        for (const dependence of ['joint', 'independent'])
          runs[`${dk}_${rk}_${capacity}_${dependence}`] = { input: { dataset: dk, rules, capacity, dependence }, output: API.run(data, rules, capacity, dependence) };

  const err = f => { try { return { ok: f() }; } catch (e) { return { error: e.message }; } };
  const csv = rows => 'date,store_id,demand\n' + rows.join('\n');
  const good = [];
  for (let t = 1; t <= 24; t++) for (const s of ['s1', 's2', 's3']) good.push(`2024-01-${String(t).padStart(2, '0')},${s},${10 * t + s.charCodeAt(1)}`);
  const parse = {
    good: csv(good),
    missingColumn: 'date,store,demand\n1,a,2',
    twoStores: csv(good.filter(l => !l.includes(',s3,'))),
    negative: csv([...good.slice(0, -1), '2024-01-24,s3,-1']),
    duplicate: csv([...good, good[0]]),
    tooFew: csv(good.slice(0, 30)),
  };
  const rules = {
    ok: ref,
    extraKey: { ...ref, x: 1 },
    zero: { ...ref, base_floor: 0 },
    stringEmergency: { ...ref, emergency: 'no' },
  };
  engines.evaluation = API;
  write('evaluation.json', {
    datasets,
    runs,
    parse: Object.fromEntries(Object.entries(parse).map(([k, raw]) => [k, { input: raw, ...err(() => API.parse(raw)) }])),
    rules: Object.fromEntries(Object.entries(rules).map(([k, o]) => [k, { input: o, ...err(() => API.rules(o)) }])),
  });
}

// ---------------------------------------------------------------- Seeded random cases
// Hand-picked cases can miss paths; these sample the input space with a fixed seed.
{
  let seed = 20261026;
  const rnd = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const pick = (xs) => xs[Math.floor(rnd() * xs.length)];
  const between = (lo, hi, step) => lo + Math.round((rnd() * (hi - lo)) / step) * step;
  const clone = (o) => JSON.parse(JSON.stringify(o));

  // Circuit Copilot: valid parameter objects across the whole range.
  const { E, analyze } = engines.copilot;
  const copilot = [];
  while (copilot.length < 60) {
    const service = between(0.5, 1, 0.01);
    const raw = {
      scenario: pick(['demand', 'storm']),
      capacityA: between(60, 200, 1),
      capacityB: between(0, 130, 1),
      service,
      tau: between(0.5, 1, 0.01),
      floor: between(0, 0.9, 0.05),
      penaltyPriority: between(0, 60, 1),
      penaltyOther: between(0, 40, 1),
      backupEnabled: rnd() < 0.5,
      backupLimit: between(0, 100, 1),
      backupCost: between(0, 60, 1),
      exceptionAuthorized: rnd() < 0.3,
      exceptionService: Math.min(service, between(0.5, 1, 0.01)),
      stormProbability: between(0, 1, 0.01),
      evidence: pick(['all', 'all', 'Normal', 'Surge', 'Storm']),
    };
    let output;
    try {
      output = analyze(raw);
    } catch (e) {
      output = { error: e.message };
    }
    const p = E.validate(raw);
    const backup = rnd() < 0.25 ? E.minimumBackup(E.compile(p), p) : undefined;
    copilot.push({ input: raw, output, minimumBackup: backup });
  }

  // Replan: random evidence, specs, LLM plans and loaded demand.
  const { R, recompute, slim } = engines.replan;
  const S = R.PRESETS.storm;
  const replan = [];
  while (replan.length < 40) {
    const preset = rnd() < 0.2 ? 'toy' : 'storm';
    const P = R.PRESETS[preset];
    const spec = clone(P.defaultSpec);
    spec.tau = pick([0.8, 0.85, 0.9, 0.95, 0.99]);
    spec.joint = rnd() < 0.6;
    spec.penalties = { priority: between(1, 30, 1), other: between(1, 20, 1) };
    spec.floor = rnd() < 0.2 ? null : { fraction: between(0, 0.9, 0.05) };
    if (preset === 'storm') {
      spec.exception = rnd() < 0.3 ? null : { when: 'emergency_declared', fraction: between(0.5, 0.9, 0.05) };
      spec.crossStateMultiplier = rnd() < 0.2 ? null : between(1, 8, 0.5);
      spec.priority = [];
      for (let i = 0, n = 1 + Math.floor(rnd() * 3); i < n; i++) {
        const st = pick(S.states);
        spec.priority.push({
          stores: S.stores.filter((s) => s.state === st && rnd() < 0.8).map((s) => s.id),
          category: pick(S.cats),
          fraction: between(0.6, 1, 0.05),
        });
      }
      spec.priority = spec.priority.filter((r) => r.stores.length);
      if (!spec.priority.length) spec.priority = clone(P.defaultSpec.priority);
    } else spec.priority[0].fraction = between(0.6, 1, 0.05);
    const ev =
      preset === 'toy'
        ? clone(R.DEFAULT_EVIDENCE)
        : {
            advisory: pick(['unknown', 'none', 'watch', 'warning']),
            sales: pick(['unknown', 'flat', 'up', 'sharp']),
            txCap: pick([1, 0.7, 0.4]),
            caLane: pick(['open', 'closed']),
            emergency: pick(['unknown', 'declared', 'not_declared']),
            week: pick(['normal', 'snap']),
          };
    let llmPlan = null;
    if (rnd() < 0.4) {
      const dcs = preset === 'toy' ? ['A', 'B'] : ['DC_CA', 'DC_TX', 'DC_WI'];
      const ship = [];
      for (let i = 0, n = 1 + Math.floor(rnd() * 12); i < n; i++)
        ship.push({
          dc: pick(dcs),
          store: pick(P.stores).id,
          cat: pick(P.cats),
          qty: preset === 'toy' ? between(0, 80, 0.5) : between(0, 20000, 25),
        });
      llmPlan = { status: 'proposed', ship, rationale: 'random' };
    }
    let custom = null;
    if (preset === 'storm' && rnd() < 0.25) {
      custom = { base: {}, cv: {} };
      for (const s of S.stores)
        for (const c of S.cats)
          if (rnd() < 0.3) {
            custom.base[s.id + '|' + c] = between(500, 20000, 1);
            if (rnd() < 0.5) custom.cv[s.id + '|' + c] = between(0.02, 0.4, 0.01);
          }
    }
    R.PRESETS.storm.custom = custom || undefined;
    const output = slim('', recompute(preset, clone(spec), ev, llmPlan));
    delete R.PRESETS.storm.custom;
    replan.push({ input: { preset, spec, ev, llmPlan, custom }, output });
  }

  // Forecast comparison: random uploaded observations, rules and capacities.
  const API = engines.evaluation;
  const evaluation = [];
  while (evaluation.length < 20) {
    const days = 20 + Math.floor(rnd() * 141);
    const stores = ['north', 'east', 'west'];
    const base = stores.map(() => between(20, 120, 1));
    const lines = ['date,store_id,demand'];
    for (let t = 0; t < days; t++) {
      const shock = rnd() < 0.2 ? 1.6 : 1;
      const date = new Date(Date.UTC(2024, 0, 1 + t)).toISOString().slice(0, 10);
      stores.forEach((s, j) => lines.push(`${date},${s},${Math.round(base[j] * shock * (0.8 + 0.4 * rnd()))}`));
    }
    const csv = lines.join('\n');
    const rules = { priority_floor: between(0.5, 1, 0.05), base_floor: between(0.3, 0.8, 0.05), emergency: rnd() < 0.2 };
    const capacity = between(Math.round(base.reduce((a, b) => a + b) * 0.8), Math.round(base.reduce((a, b) => a + b) * 2), 1);
    const dependence = pick(['joint', 'independent']);
    evaluation.push({ input: { csv, rules, capacity, dependence }, output: API.run(API.parse(csv), rules, capacity, dependence) });
  }

  write('random.json', { copilot, replan, evaluation });
}
