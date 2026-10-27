# PILLAR demos

Two supply-planning demos, ported from single-file HTML pages into a Python backend and a
TypeScript (Vite) front end. Both help a supply manager answer: "Things have changed. What should
I ship now?"

- **PILLAR Replan** (`replan.html`): the planning demo. It compiles the manager's rules into a
  shipment plan, and compares planning for the most likely demand with planning over the range
  of demands.
- **Circuit Copilot** (`copilot.html`): the "will this plan hold up?" demo. It checks which
  situations make a plan fail when a storm raises demand and delays deliveries together, and
  whether extra local supply fixes it.

The linear programs both demos solve are written out in
[`docs/lp-formulations.md`](docs/lp-formulations.md).

Both pages end with the same forecast comparison section: a three-store stocking problem that
compares a point forecast with an empirical distribution on held-out dates.

ChatGPT only interprets instructions and words answers; every number comes from the engines. The
engines are the original pages' JavaScript, ported to Python, and they reproduce its results exactly.

## Layout

```
demos/
  original/   the two HTML files as received. They are the specification; do not edit them.
  golden/     capture.mjs runs the engines inside original/ under Node and writes golden JSON
  backend/    Python package pillar_demos (FastAPI)
    src/pillar_demos/
      copilot.py, replan.py, evaluation.py   the engines
      lp.py        the original two-phase simplex
      js.py        JavaScript number semantics the engines depend on
      api.py       HTTP endpoints; also serves frontend/dist when it exists
      chatgpt.py   server-side OpenAI Responses API connection
    tests/        golden, random-case and API tests
  frontend/   Vite project: the pages and their UI code
    copilot.html, replan.html, index.html
    src/copilot/, src/replan/   main.ts (UI), types.ts (API shapes), CSS
    src/shared/   api.ts (client and action queue), chatgpt-bridge.ts, evaluation/ (panel), dom.ts
    tests/parity/ drives each original page and its port side by side in Chrome
```

The pages send each change to the backend and render the result. One endpoint returns everything a
page update needs: `/api/copilot/analyze` for Copilot and `/api/replan/compute` for Replan. Page
actions go through a queue (`createSerial` in `src/shared/api.ts`), so each action sees the
previous one's result, as when the originals computed synchronously.

## Running

```sh
# backend, http://localhost:8000
cd demos/backend
uv sync
uv run uvicorn pillar_demos.api:app --port 8000

# front end in development, http://localhost:5173 (forwards /api to port 8000)
cd demos/frontend
npm install
npm run dev
```

For a single process, run `npm run build` in `frontend/`, then start uvicorn. It serves the built
pages at http://localhost:8000 (set `PILLAR_DEMOS_DIST` to serve another directory).

### ChatGPT

Set `OPENAI_API_KEY` and `OPENAI_MODEL` (and optionally `OPENAI_BASE_URL`) before starting
uvicorn. The pages then show "ChatGPT API connected" and send prompts through
`/api/chatgpt`; the key stays on the server. Without them, the pages use the copy-and-paste
hand-off: they show the prompt, and you paste ChatGPT's reply back.

## Checks

```sh
cd demos/backend
uv run pytest            # engines against golden/*.json, exactly; API and ChatGPT proxy
uv run ruff check . && uv run ruff format --check .

cd demos/frontend
npm run typecheck
npm run format:check
npm run build
npm run parity           # needs the backend, `npm run dev` and `npm run serve:original` running
```

`npm run parity` opens each original page and its port in headless Chrome (uses the installed
Google Chrome; set `CHROME_PATH` to override) and runs the same clicks, inputs, uploads and
ChatGPT hand-offs in both, 154 steps in all. After every step it compares the DOM, every element's
box and key styles, and the dialog state. Pass `copilot` or `replan` to run one page. To check the
single-process build, set `PORT_URL=http://localhost:8000`.

`golden/` holds hand-picked cases plus seeded random ones (`random.json`). Regenerate it only if
`original/` changes: `node demos/golden/capture.mjs`.

## Keeping the behaviour identical

- `lp.py` is the original simplex, rule for rule. Its pivot choices decide which plan appears when
  several are optimal, so do not swap in another solver.
- Use the helpers in `js.py` where JavaScript and Python differ: `js_round` (halves round up),
  `js_sum` (Python 3.12's `sum` compensates float error; JS does not), the 32-bit `mulberry32`,
  `js_str` and `js_number`.
- CSS minification is off in `vite.config.ts`. The minifier reordered declarations and changed
  Replan's number rendering.
- One deliberate change: in Replan's dark mode, the forecast comparison panel and the ChatGPT
  dialog now follow the dark theme (the originals kept them light). Their colours are variables
  in `panel.css` and `chatgpt-bridge.css`, remapped in `replan.css`. Light mode, and Copilot,
  which has no dark theme, are unchanged, and `npm run parity` runs in light mode.
- Kept from the originals although they do nothing: the "Download app" links point to
  `/download`, which nothing serves.
- Known differences, all on malformed input: a CSV in the forecast comparison orders dates by
  plain string comparison (the original used `localeCompare`; ISO and zero-padded dates order the
  same either way); pasting the literal `null` as rules counts as "not submitted"; and a Replan
  spec whose `stores` is not a list is treated as an empty list. In those two cases the original
  showed a browser TypeError.
