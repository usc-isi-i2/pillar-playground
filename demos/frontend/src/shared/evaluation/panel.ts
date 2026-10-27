// The "Forecasting, translation, and decisions" section appended below both demos.

import { api, createSerial } from '../api';
import type { Comparison, Dataset, DatasetKind, Dependence } from './types';
import markup from './panel.html?raw';
import './panel.css';

export async function mountEvaluationPanel() {
  const section = document.createElement('section');
  section.id = 'evaluation';
  section.innerHTML = markup;
  document.body.append(section);
  const nav = document.createElement('a');
  nav.href = '#evaluation';
  nav.textContent = 'Open component evaluation';
  nav.style.cssText =
    'position:fixed;bottom:18px;right:18px;background:#007f82;color:white;padding:12px 18px;border-radius:6px;z-index:90;font:15px system-ui;box-shadow:0 3px 15px #0003';
  document.body.append(nav);

  const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById('ev-' + id) as T;
  const input = (id: string) => el<HTMLInputElement>(id);
  let data: Dataset = await api<Dataset>('/api/evaluation/synthetic', { kind: 'correlated' });
  let last: unknown = null;
  const serial = createSerial();

  async function render() {
    try {
      const capacity = +input('capacity').value;
      const dependence = input('dependence').value as Dependence;
      // The pasted translation is parsed here so a JSON error reads as the browser reports it.
      // It is reported after a capacity error, as before.
      const raw = input('json').value.trim();
      let parsed: unknown = null,
        parseError: unknown = null;
      if (raw)
        try {
          parsed = JSON.parse(raw.replace(/^```(?:json)?\s*|\s*```$/g, ''));
        } catch (e) {
          parseError = e;
        }
      const c = await api<Comparison>('/api/evaluation/compare', {
        data,
        rules: parseError ? null : parsed,
        capacity: Number.isFinite(capacity) ? capacity : null,
        dependence,
      });
      if (parseError) throw parseError;
      el('results').innerHTML = '';
      for (const row of c.rows) {
        const tr = document.createElement('tr');
        const res = row.result,
          b = res?.best;
        const vals = [
          row.name,
          row.demand,
          res ? (b ? b.x.join(' / ') : 'Infeasible') : 'Awaiting translation',
          b ? (100 * b.prob).toFixed(1) + '%' : '—',
          b && res.best ? (100 * res.violation).toFixed(1) + '%' : '—',
          b && res.best ? res.realCost.toFixed(2) : '—',
        ];
        for (const v of vals) {
          const td = document.createElement('td');
          td.textContent = v;
          tr.append(td);
        }
        el('results').append(tr);
      }
      el('metrics').textContent =
        `Training: ${c.trainDates.length} dates. Test: ${c.testDates.length} dates. Stores: ${data.stores.join(', ')}. ` +
        `Point forecast MAE: ${c.mae.toFixed(2)} units. ` +
        `Translation: ${c.rules ? (c.matchesReference ? 'matches reference' : 'DIFFERS from reference') : 'not submitted'}.`;
      const result = c.rows[1].result!;
      el('diagnosis').textContent = c.failureDates
        ? `Distribution-plan failure dates: ${c.failureDates.join(', ') || 'none'}.\nRepair: increase capacity or add supply if the plan is infeasible. Rerun to verify.`
        : `No feasible plan under the selected capacity. Highest candidate model compliance: ${(100 * result.maxP).toFixed(1)}%. Increase capacity and rerun.`;
      el('provenance').textContent =
        data.source +
        (data.source.startsWith('Synthetic')
          ? '. Not a vanilla M5 result.'
          : '. This is a simple mean/empirical baseline, not an official M5 benchmark score.');
      el('status').textContent = 'Comparison complete. Forecasting uses training observations only.';
      last = {
        dataset: data.source,
        stores: data.stores,
        trainDates: c.trainDates,
        testDates: c.testDates,
        referenceRules: c.referenceRules,
        llmRules: c.rules,
        dependence,
        capacity,
        rows: c.rows,
        mae: c.mae,
      };
    } catch (e) {
      el('status').textContent = (e as Error).message;
      last = null;
    }
  }

  function download(name: string, content: string, type: string) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([content], { type }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 500);
  }

  el('dataset').onchange = () =>
    serial(async () => {
      data = await api<Dataset>('/api/evaluation/synthetic', { kind: input('dataset').value as DatasetKind });
      input('file').value = '';
      await render();
    });
  el('file').onchange = () =>
    serial(async () => {
      try {
        data = await api<Dataset>('/api/evaluation/parse', { csv: await input('file').files![0].text() });
        await render();
      } catch (e) {
        el('status').textContent = (e as Error).message;
      }
    });
  el('run').onclick = () => serial(render);
  el('dependence').onchange = () => serial(render);
  el('template').onclick = () =>
    serial(() =>
      download(
        'synthetic_observations_template.csv',
        'date,store_id,demand\n' +
          data.rows.map((r) => r.x.map((d, j) => [r.date, data.stores[j], d].join(',')).join('\n')).join('\n'),
        'text/csv',
      ),
    );
  el('copy').onclick = async () => {
    const prompt =
      'Translate the operator instructions below into JSON only, exactly these fields: priority_floor (fraction), base_floor (fraction), emergency (boolean). Do not propose an allocation. This schema fixes joint reliability at 0.95. If the instructions cannot be expressed, say UNSUPPORTED.\n' +
      input('instructions').value;
    try {
      await navigator.clipboard.writeText(prompt);
      el('status').textContent = 'Prompt copied. Open ChatGPT, then paste its JSON response here.';
    } catch {
      input('json').value = prompt;
      el('status').textContent =
        'Clipboard unavailable. Prompt placed in the text box for manual copying; replace it with ChatGPT JSON.';
    }
  };
  el('export').onclick = () =>
    serial(() => {
      if (!last) {
        el('status').textContent = 'Run a valid comparison first.';
        return;
      }
      download('pillar_component_evaluation.json', JSON.stringify(last, null, 2), 'application/json');
    });
  await serial(render);
  if (location.hash === '#evaluation') section.scrollIntoView();
}
