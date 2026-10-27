// Drive the original demo page and its port through the same interactions in headless Chrome,
// and compare the rendered DOM and layout after every step.
//
//   ORIGINAL_URL=http://localhost:5174 PORT_URL=http://localhost:5173 node tests/parity/run.mjs [copilot|replan]
//
// ORIGINAL_URL serves demos/original/ (any static server); PORT_URL is the Vite dev server, which
// forwards /api to the backend (uvicorn on port 8000).
// CHROME_PATH overrides the Chrome executable.

import puppeteer from 'puppeteer-core';
import { copilotSteps } from './copilot-steps.mjs';
import { replanSteps } from './replan-steps.mjs';

const ORIGINAL = process.env.ORIGINAL_URL ?? 'http://localhost:5174';
const PORT = process.env.PORT_URL ?? 'http://localhost:5173';
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const pages = {
  copilot: { original: `${ORIGINAL}/pillar-circuit-copilot.html`, port: `${PORT}/copilot.html`, steps: copilotSteps },
  replan: { original: `${ORIGINAL}/pillar-replan-chatgpt.html`, port: `${PORT}/replan.html`, steps: replanSteps },
};

// Make timings, timestamps and random draws identical in both pages.
function freeze() {
  performance.now = () => 0;
  Date.prototype.toISOString = () => '2026-01-01T00:00:00.000Z';
  let seed = 12345;
  Math.random = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  // Clipboard and downloads are not part of the comparison.
  HTMLAnchorElement.prototype.click = function () {};
  // The port reports the server's compile time; zero it like the page's own timers.
  const fetch0 = window.fetch;
  window.fetch = async (...args) => {
    const r = await fetch0(...args);
    if (!String(args[0]).includes('/api/copilot/analyze') || !r.ok) return r;
    const d = await r.json();
    d.compileMs = 0;
    return new Response(JSON.stringify(d), { status: r.status, headers: r.headers });
  };
}

// Page-side helpers available to steps as window.__t.
function helpers() {
  const q = (s) => {
    const el = document.querySelector(s);
    if (!el) throw new Error('missing element ' + s);
    return el;
  };
  // Spinners rotate, so their boxes depend on timing.
  const still = document.createElement('style');
  still.textContent = '*,*::before,*::after{animation:none!important;transition:none!important}';
  document.head.append(still);
  window.__t = {
    click: (s) => q(s).click(),
    set: (s, v) => {
      const el = q(s);
      if (el.type === 'checkbox') el.checked = v;
      else el.value = v;
      el.dispatchEvent(new Event('change', { bubbles: true }));
    },
    value: (s, v) => {
      q(s).value = v;
    },
    key: (s, key) => q(s).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })),
    upload: (s, name, text) => {
      const dt = new DataTransfer();
      dt.items.add(new File([text], name, { type: 'text/csv' }));
      q(s).files = dt.files;
      q(s).dispatchEvent(new Event('change', { bubbles: true }));
    },
  };
}

function snapshot() {
  const norm = (html) =>
    html
      .replace(/<style>[\s\S]*?<\/style>/g, '')
      .replace(/<script[\s\S]*?<\/script>/g, '')
      .replace(/style="([^"]*)"/g, (_, css) => `style="${css.replace(/\s+/g, '')}"`)
      .replace(/>\s+</g, '><')
      .replace(/\s+/g, ' ')
      .replace(/> /g, '>')
      .replace(/ </g, '<')
      .trim();
  const layout = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
    const r = el.getBoundingClientRect(),
      cs = getComputedStyle(el);
    layout.push(
      [
        el.tagName,
        el.id,
        Math.round(r.x),
        Math.round(r.y),
        Math.round(r.width),
        Math.round(r.height),
        cs.color,
        cs.backgroundColor,
        cs.fontSize,
        cs.fontWeight,
        cs.fontFamily,
        cs.display,
      ].join('|'),
    );
  }
  const dialog = document.querySelector('dialog.gpt-dialog');
  return {
    html: norm(document.body.innerHTML),
    layout,
    dialogOpen: !!dialog?.open,
    dialogPrompt: dialog?.querySelector('#gpt-prompt')?.value ?? null,
  };
}

function firstDiff(a, b) {
  let i = 0;
  while (i < a.length && a[i] === b[i]) i++;
  return { at: i, original: a.slice(Math.max(0, i - 120), i + 200), port: b.slice(Math.max(0, i - 120), i + 200) };
}

async function open(browser, url) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000 });
  // Light mode: in dark mode the port deliberately differs, because the shared evaluation panel
  // and ChatGPT dialog follow Replan's dark theme instead of staying light.
  await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'light' }]);
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.evaluateOnNewDocument(freeze);
  await page.goto(url, { waitUntil: 'networkidle0' });
  await page.evaluate(helpers);
  return { page, errors };
}

const which = process.argv[2] ? [process.argv[2]] : Object.keys(pages);
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
let failures = 0;
try {
  for (const name of which) {
    const { original, port, steps } = pages[name];
    const a = await open(browser, original),
      b = await open(browser, port);
    for (const [label, action] of [['initial load', null], ...steps]) {
      for (const { page } of [a, b]) {
        if (action) await page.evaluate(action);
        await new Promise((r) => setTimeout(r, 30));
        await page.waitForNetworkIdle({ idleTime: 80, timeout: 20000 });
      }
      const [sa, sb] = [await a.page.evaluate(snapshot), await b.page.evaluate(snapshot)];
      const problems = [];
      if (sa.html !== sb.html) problems.push(['DOM', firstDiff(sa.html, sb.html)]);
      if (sa.dialogOpen !== sb.dialogOpen || sa.dialogPrompt !== sb.dialogPrompt)
        problems.push([
          'dialog',
          { original: [sa.dialogOpen, sa.dialogPrompt], port: [sb.dialogOpen, sb.dialogPrompt] },
        ]);
      const n = Math.max(sa.layout.length, sb.layout.length);
      for (let i = 0; i < n; i++)
        if (sa.layout[i] !== sb.layout[i]) {
          problems.push(['layout', { element: i, original: sa.layout[i], port: sb.layout[i] }]);
          break;
        }
      if (problems.length) {
        failures++;
        console.log(`✗ ${name}: ${label}`);
        for (const [kind, detail] of problems) console.log(`  ${kind}:`, JSON.stringify(detail, null, 2));
      } else console.log(`✓ ${name}: ${label}`);
    }
    for (const [who, { errors }] of [
      ['original', a],
      ['port', b],
    ])
      if (errors.length) {
        failures++;
        console.log(`✗ ${name}: ${who} page errors:`, errors);
      }
    await a.page.close();
    await b.page.close();
  }
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
