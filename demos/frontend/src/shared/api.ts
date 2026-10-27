// Client for the Python backend (demos/backend). In development Vite forwards /api to it.

export interface ApiError extends Error {
  code?: string;
  status?: number;
}

/** GET (no body) or POST `body` as JSON. A non-2xx reply throws its `error` message. */
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(
    path,
    body === undefined
      ? undefined
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
  );
  const d = await r.json();
  if (!r.ok)
    throw Object.assign(new Error(d.error || `Request failed (${r.status})`), { code: d.code, status: r.status });
  return d as T;
}

/**
 * Run tasks one at a time, in call order. The original pages recomputed synchronously, so each
 * action saw the previous one's result; queueing keeps that true now that results come from the
 * server. When nothing is running, a task starts at once, so its synchronous part (opening a
 * dialog, say) happens within the click, as it did before.
 */
export function createSerial() {
  let running = 0;
  let tail: Promise<unknown> = Promise.resolve();
  return <T>(task: () => Promise<T> | T): Promise<T> => {
    const start = (): Promise<T> => {
      running++;
      let result: Promise<T>;
      try {
        result = Promise.resolve(task());
      } catch (e) {
        result = Promise.reject(e);
      }
      return result.finally(() => running--);
    };
    const run = running === 0 ? start() : tail.then(start, start);
    tail = run.catch(() => undefined);
    return run;
  };
}
