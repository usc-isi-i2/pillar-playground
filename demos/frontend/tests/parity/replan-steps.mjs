// Interactions for the Replan parity run. Each action runs inside the page.

const tabs = ['diagnosis', 'ship', 'cert', 'backtest', 'model'];
const tabSteps = (prefix) => tabs.map((t) => [`${prefix} tab ${t}`, new Function(`__t.click('[data-tab="${t}"]')`)]);
const askStep = (text) => [
  `ask: ${text}`,
  new Function(`__t.value('#q', ${JSON.stringify(text)}); __t.click('#askBtn')`),
];
const evidenceStep = (id, v) => [`evidence ${id} = ${v}`, new Function(`__t.set('#ev-${id}', ${JSON.stringify(v)})`)];

const m5csv = [
  'store_id,cat_id,weekly_mean,cv',
  'TX_1,FOODS,15000,0.2',
  'CA_1,HOBBIES,3000,',
  'NY_1,FOODS,100,0.1',
].join('\n');

export const replanSteps = [
  ...tabSteps('unsolved'),
  ['answer tau 90%', () => __t.click('#elicit button[data-el="0:1"]')],
  ...tabSteps('solved'),
  ['ship view: most-likely plan', () => (__t.click('[data-tab="ship"]'), __t.click('[data-ship="mpe"]'))],
  ['backtest: draw a week', () => (__t.click('[data-tab="backtest"]'), __t.click('#drawWeek'))],
  ['certificate download', () => (__t.click('[data-tab="cert"]'), __t.click('#dlCert'))],
  evidenceStep('advisory', 'warning'),
  evidenceStep('sales', 'sharp'),
  evidenceStep('txCap', '0.4'),
  evidenceStep('caLane', 'closed'),
  evidenceStep('emergency', 'declared'),
  evidenceStep('week', 'snap'),
  evidenceStep('emergency', 'not_declared'),
  evidenceStep('caLane', 'open'),
  ...tabSteps('after evidence'),
  ...[0, 1, 2, 3, 4, 5, 6].map((i) => [
    `suggestion ${i}`,
    new Function(`document.querySelectorAll('#suggest button')[${i}].click()`),
  ]),
  askStep('The storm advisory was lifted, none now'),
  askStep('TX DC capacity is at 100%'),
  askStep('What if we need 95% confidence?'),
  askStep('Serve 85% at priority stores'),
  askStep('Would the plan still hold if the lane closes?'),
  askStep('The CA lane is closed'),
  askStep('The lane re-opened'),
  askStep('Emergency is not declared'),
  askStep('Make CA HOUSEHOLD priority at 70%'),
  askStep('hello'),
  ['ask with Enter key', () => (__t.value('#q', 'Why this plan?'), __t.key('#q', 'Enter'))],
  ['spec: bad JSON', () => (__t.value('#specJson', '{'), __t.click('#applySpec'))],
  ['spec: no priority', () => (__t.value('#specJson', '{"priority":[]}'), __t.click('#applySpec'))],
  [
    'spec: valid with warnings',
    () => (
      __t.value(
        '#specJson',
        JSON.stringify({
          priority: [{ stores: ['TX_1', 'NY_9'], category: 'FOODS', fraction: 0.85 }],
          floor: { fraction: 0.5 },
          crossStateMultiplier: 0.5,
          penalties: { priority: 9, other: 4 },
          tau: 0.4,
          joint: false,
        }),
      ),
      __t.click('#applySpec')
    ),
  ],
  ['answer tau 95%', () => __t.click('#elicit button[data-el="0:2"]')],
  ['translate opens handoff', () => __t.click('#translateBtn')],
  [
    'paste compiled spec',
    () => (
      __t.value(
        '#gpt-reply',
        JSON.stringify({
          spec: {
            priority: [{ stores: ['TX_1', 'TX_2'], category: 'FOODS', fraction: 0.9 }],
            floor: { fraction: 0.6 },
            exception: null,
            crossStateMultiplier: 3,
            penalties: null,
            tau: null,
            joint: true,
          },
          unsupported: ['night shifts'],
          assumed: ['floor'],
        }),
      ),
      __t.click('#gpt-apply')
    ),
  ],
  ['answer penalties 20/10', () => __t.click('#elicit button[data-el="1:1"]')],
  ['answer tau 80%', () => __t.click('#elicit button[data-el="0:0"]')],
  ['translate then cancel', () => (__t.click('#translateBtn'), __t.click('#gpt-cancel'))],
  ['LLM plan opens handoff', () => __t.click('#llmPlanBtn')],
  [
    'paste LLM plan',
    () => (
      __t.value(
        '#gpt-reply',
        '```json\n' +
          JSON.stringify({
            ship: [
              { dc: 'DC_TX', store: 'TX_1', cat: 'FOODS', qty: 12000 },
              { dc: 'DC_CA', store: 'TX_2', cat: 'FOODS', qty: 9000 },
              { dc: 'DC_WI', store: 'WI_1', cat: 'HOBBIES', qty: 0 },
            ],
            rationale: 'Cover Texas first.',
          }) +
          '\n```',
      ),
      __t.click('#gpt-apply')
    ),
  ],
  ...tabSteps('with LLM plan'),
  ['ship view: LLM plan', () => (__t.click('[data-tab="ship"]'), __t.click('[data-ship="llm"]'))],
  [
    'LLM plan again, invalid reply',
    () => (__t.click('#llmPlanBtn'), __t.value('#gpt-reply', '{"ship":[{"dc":"X"}]}'), __t.click('#gpt-apply')),
  ],
  ['chatgpt setup info', () => __t.click('#chatgptSetup')],
  ['close info', () => __t.click('#gpt-cancel')],
  ['reset knowledge', () => (__t.value('#knowledge', 'x'), __t.click('#resetKnow'))],
  ['load M5 CSV', new Function(`__t.upload('#csv', 'm5.csv', ${JSON.stringify(m5csv)})`)],
  ['load bad CSV', () => __t.upload('#csv', 'bad.csv', 'a,b\n1,2')],
  ...tabSteps('custom demand'),
  ['preset toy', () => __t.set('#preset', 'toy')],
  ...tabSteps('toy'),
  ['toy suggestion: confidence 70%', () => document.querySelectorAll('#suggest button')[2].click()],
  askStep('What do I do now?'),
  askStep('What is going on?'),
  askStep('The CA lane is closed'),
  ['preset storm again', () => __t.set('#preset', 'storm')],
  [
    'evaluation: upload CSV',
    () => {
      const rows = ['date,store_id,demand'];
      for (let t = 1; t <= 30; t++)
        for (const s of ['a', 'b', 'c'])
          rows.push(`2024-02-${String(t).padStart(2, '0')},${s},${((t * 7) % 23) + 30 + (s.charCodeAt(0) % 5)}`);
      __t.upload('#ev-file', 'obs.csv', rows.join('\n'));
    },
  ],
  ['evaluation: bad upload', () => __t.upload('#ev-file', 'bad.csv', 'date,store_id,demand\n1,a,1')],
];
