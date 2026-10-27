// Shared adapter: optional server-side Responses API, plus a working ChatGPT copy/paste handoff.
//
// When the backend reports a connection (GET /api/config), prompts go to POST /api/chatgpt.
// Otherwise a dialog shows the prompt for the operator to send to ChatGPT and paste the reply back.

import './chatgpt-bridge.css';

export interface BridgeError extends Error {
  code?: string;
}

export interface RequestOptions {
  onText?: (t: { text: string }) => void;
  /** Accepted for the callers' sake; the bridge does not route by tier. */
  modelTier?: string;
  cache?: boolean;
}

// LLM output is untyped JSON; callers check the fields they use.
export type Json = any;

export interface Sample {
  (prompt: string, options?: RequestOptions): Promise<{ text: string }>;
  json: (prompt: string, options?: RequestOptions) => Promise<Json>;
}

export interface ChatGPTBridge {
  ready: () => Promise<boolean>;
  sample: Sample;
  json: (prompt: string, options?: RequestOptions) => Promise<Json>;
  text: (prompt: string) => Promise<string>;
  isConnected: () => boolean;
  parseJSON: (t: string) => Json;
  download: (name: string, text: BlobPart, type?: string) => void;
  showInfo: () => void;
}

const withCode = (message: string, code: string): BridgeError => Object.assign(new Error(message), { code });

export function createChatGPTBridge(): ChatGPTBridge {
  let connected = false;
  let pending: { resolve: (v: Json) => void; reject: (e: unknown) => void; json: boolean } | null = null;
  const dialog = document.createElement('dialog');
  dialog.className = 'gpt-dialog';
  dialog.innerHTML = `<h2>Continue with ChatGPT</h2>
<p id="gpt-help">Copy the prepared prompt, send it to ChatGPT, then paste its response below. The app will validate and score the result.</p>
<label for="gpt-prompt">Prepared prompt</label><textarea id="gpt-prompt" readonly></textarea>
<div class="gpt-actions"><button id="gpt-copy">Copy prompt</button><a href="https://chatgpt.com/" target="_blank" rel="noopener noreferrer">Open ChatGPT ↗</a><button id="gpt-download">Download prompt</button></div>
<label for="gpt-reply">ChatGPT response</label><textarea id="gpt-reply" placeholder="Paste ChatGPT’s response here"></textarea>
<p id="gpt-error" class="gpt-error" role="alert"></p>
<div class="gpt-actions"><button id="gpt-apply">Use response</button><button id="gpt-cancel">Cancel</button></div>
<small>Automatic replies use a server-side OpenAI API connection when configured. This handoff uses your existing ChatGPT session. No API key is requested or stored in this page.</small>`;
  document.body.appendChild(dialog);
  const q = <T extends HTMLElement = HTMLElement>(id: string) => dialog.querySelector('#' + id) as T;
  const prompt = q<HTMLTextAreaElement>('gpt-prompt'),
    reply = q<HTMLTextAreaElement>('gpt-reply'),
    error = q('gpt-error'),
    copy = q('gpt-copy');

  const download = (name: string, text: BlobPart, type = 'text/plain') => {
    const u = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement('a');
    a.href = u;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 5000);
  };
  function parseJSON(t: string): Json {
    const s = t
      .trim()
      .replace(/^```(?:json)?\s*/i, '')
      .replace(/\s*```$/, '');
    try {
      return JSON.parse(s);
    } catch {
      const i = s.indexOf('{'),
        j = s.lastIndexOf('}');
      if (i >= 0 && j > i) return JSON.parse(s.slice(i, j + 1));
      throw new Error('Paste a complete JSON object from ChatGPT.');
    }
  }
  function cancel() {
    if (pending) {
      pending.reject(withCode('ChatGPT handoff cancelled', 'cancelled'));
      pending = null;
    }
    dialog.close();
  }
  q('gpt-cancel').onclick = cancel;
  dialog.addEventListener('cancel', (e) => {
    e.preventDefault();
    cancel();
  });
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(prompt.value);
      copy.textContent = 'Copied';
    } catch {
      prompt.focus();
      prompt.select();
      error.textContent = 'Select and copy the prompt above.';
    }
  };
  q('gpt-download').onclick = () => download('pillar-chatgpt-prompt.txt', prompt.value);
  q('gpt-apply').onclick = () => {
    if (!pending) return;
    try {
      const value = pending.json ? parseJSON(reply.value) : reply.value.trim();
      if (!value) throw new Error('Paste a response first.');
      const task = pending;
      pending = null;
      dialog.close();
      task.resolve(value);
    } catch (e) {
      error.textContent = (e as Error).message;
    }
  };

  async function ready() {
    try {
      const r = await fetch('/api/config');
      const v = await r.json();
      connected = !!v.connected;
    } catch {
      connected = false;
    }
    return connected;
  }
  async function request(text: string, json = false, options: RequestOptions = {}): Promise<Json> {
    if (connected) {
      const r = await fetch('/api/chatgpt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, json }),
      });
      const d = await r.json();
      if (!r.ok) throw withCode(d.error || 'OpenAI request failed', d.code || 'api_error');
      if (!d.text) throw new Error('OpenAI returned no text.');
      if (options.onText) options.onText({ text: d.text });
      return json ? parseJSON(d.text) : d.text;
    }
    if (pending) throw new Error('Complete or cancel the current ChatGPT handoff first.');
    prompt.value = text + (json ? '\n\nReturn only the requested JSON object, without a code fence.' : '');
    reply.value = '';
    error.textContent = '';
    copy.textContent = 'Copy prompt';
    dialog.showModal();
    return new Promise((resolve, reject) => {
      pending = { resolve, reject, json };
    });
  }
  const sample = (async (text: string, options: RequestOptions = {}) => ({
    text: await request(text, false, options),
  })) as Sample;
  sample.json = (text, options = {}) => request(text, true, options);
  return {
    ready,
    sample,
    json: sample.json,
    text: async (text) => request(text, false),
    isConnected: () => connected,
    parseJSON,
    download,
    showInfo: () => {
      prompt.value = 'Use an LLM action in the application to prepare a task-specific prompt.';
      reply.value = '';
      error.textContent = '';
      dialog.showModal();
    },
  };
}
