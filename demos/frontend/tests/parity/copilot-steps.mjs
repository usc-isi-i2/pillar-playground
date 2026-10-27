// Interactions for the Circuit Copilot parity run. Each action runs inside the page.

const tabs = ['worlds', 'shipments', 'explanation', 'circuit', 'model', 'certificate', 'dependence'];

export const copilotSteps = [
  ...[1, 2, 3, 4, 5, 6, 7].map((i) => [`tour step ${i}`, () => __t.click('#tourNext')]),
  ['tour back', () => __t.click('#tourPrev')],
  ...tabs.map((t) => [`tab ${t}`, new Function(`__t.click('[data-tab="${t}"]')`)]),
  ['preset storm', () => __t.click('[data-preset="storm"]')],
  ...tabs.map((t) => [`storm tab ${t}`, new Function(`__t.click('[data-tab="${t}"]')`)]),
  ['preset repair', () => __t.click('[data-preset="repair"]')],
  ['preset demand', () => __t.click('[data-preset="demand"]')],
  ['chip: why not 70', () => __t.click('[data-query="Why not send 70 units to S4?"]')],
  ['chip: minimum backup', () => __t.click('[data-query="How much backup supply do we need?"]')],
  ['chip: independence', () => __t.click('[data-query="Compare joint and independent uncertainty"]')],
  ['chip: recommend', () => __t.click('[data-query="What should I do now?"]')],
  ['ask: confidence 80%', () => (__t.value('#question', 'Set assurance to 80%'), __t.click('#ask'))],
  ['ask: enter key, unknown question', () => (__t.value('#question', 'hello there'), __t.key('#question', 'Enter'))],
  ['scenario storm', () => __t.set('#scenario', 'storm')],
  ['ask: backup in storm', () => (__t.value('#question', 'how much backup?'), __t.click('#ask'))],
  ['evidence Storm', () => __t.set('#evidence', 'Storm')],
  ['evidence Normal', () => __t.set('#evidence', 'Normal')],
  ['evidence all', () => __t.set('#evidence', 'all')],
  ['capacity B 80', () => __t.set('#capacityB', '80')],
  ['storm probability 60%', () => __t.set('#stormProbability', '60')],
  ['backup on', () => __t.set('#backupEnabled', true)],
  ['backup limit 10', () => __t.set('#backupLimit', '10')],
  ['backup cost 40', () => __t.set('#backupCost', '40')],
  ['service 80%', () => __t.set('#service', '80')],
  ['tau 70%', () => __t.set('#tau', '70')],
  ['exception on', () => __t.set('#exceptionAuthorized', true)],
  ['tab certificate after edits', () => __t.click('[data-tab="certificate"]')],
  ['invalid typed model', () => (__t.value('#specJson', '{"tau": 2}'), __t.click('#applySpec'))],
  ['unknown field typed model', () => (__t.value('#specJson', '{"colour": 1}'), __t.click('#applySpec'))],
  ['bad JSON typed model', () => (__t.value('#specJson', '{'), __t.click('#applySpec'))],
  [
    'valid typed model',
    () => (__t.value('#specJson', '{"scenario":"storm","backupEnabled":true,"tau":0.9}'), __t.click('#applySpec')),
  ],
  ['service below exception', () => __t.set('#service', '70')],
  ['reset knowledge', () => (__t.value('#knowledge', 'x'), __t.click('#resetKnowledge'))],
  ['compile with ChatGPT opens handoff', () => __t.click('#compileKnowledge')],
  ['cancel handoff', () => __t.click('#gpt-cancel')],
  ['ask ChatGPT opens handoff', () => __t.click('#chatgptAnswer')],
  ['paste ChatGPT answer', () => (__t.value('#gpt-reply', 'Ship as recommended.'), __t.click('#gpt-apply'))],
  ['compile again', () => __t.click('#compileKnowledge')],
  [
    'paste compiled params',
    () => (
      __t.value(
        '#gpt-reply',
        '```json\n{"params":{"scenario":"storm","capacityB":60,"tau":0.8,"backupEnabled":true},"unsupported":["night shifts"],"clarifications":[]}\n```',
      ),
      __t.click('#gpt-apply')
    ),
  ],
  ['evaluation: independent dataset', () => __t.set('#ev-dataset', 'independent')],
  ['evaluation: shift dataset', () => __t.set('#ev-dataset', 'shift')],
  ['evaluation: independent marginals', () => __t.set('#ev-dependence', 'independent')],
  ['evaluation: capacity 150', () => (__t.value('#ev-capacity', '150'), __t.click('#ev-run'))],
  ['evaluation: bad capacity', () => (__t.value('#ev-capacity', '-3'), __t.click('#ev-run'))],
  [
    'evaluation: ChatGPT rules differ',
    () => (
      __t.value('#ev-capacity', '240'),
      __t.value('#ev-json', '{"priority_floor":0.8,"base_floor":0.6,"emergency":true}'),
      __t.click('#ev-run')
    ),
  ],
  [
    'evaluation: rules match',
    () => (__t.value('#ev-json', '{"base_floor":0.6,"priority_floor":0.9,"emergency":false}'), __t.click('#ev-run')),
  ],
  ['evaluation: bad rules', () => (__t.value('#ev-json', '{"priority_floor":2}'), __t.click('#ev-run'))],
  ['evaluation: export without result', () => __t.click('#ev-export')],
];
