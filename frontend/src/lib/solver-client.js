// Solver client: mode-switched router between Pyodide (browser) and FastAPI (backend).
//
// VITE_SOLVER_MODE values:
//   "browser" — load Pyodide in a Web Worker, run burmister.py client-side
//   "backend" — POST to ${VITE_API_BASE_URL}/api/solve (legacy / development)
//   "auto"    — try browser; if Pyodide fails to init, fall back to backend
//
// Default in production builds (Pages) is "browser" since GitHub Pages has
// no Python runtime. In dev, leave it unset to use the backend at localhost:8000.

const MODE = import.meta.env.VITE_SOLVER_MODE || "backend";
const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
// Absolute URL to the bundled Python sources. Vite's BASE_URL is "/" in dev
// and "/<repo>/" on Pages, so this resolves correctly in both.
const PY_BASE_URL = new URL((import.meta.env.BASE_URL || "/") + "py/", window.location.origin).href;

let workerPromise = null;
let nextRequestId = 1;
const pendingRequests = new Map();
const statusListeners = new Set();

function emitStatus(msg) {
  statusListeners.forEach((cb) => {
    try { cb(msg); } catch { /* ignore listener errors */ }
  });
}

export function onSolverStatus(callback) {
  statusListeners.add(callback);
  return () => statusListeners.delete(callback);
}

function ensureWorker() {
  if (workerPromise) return workerPromise;
  workerPromise = new Promise((resolve, reject) => {
    let worker;
    try {
      // Vite bundles this on build; in dev it's served by the dev server.
      worker = new Worker(new URL("./pyodide-solver.worker.js", import.meta.url), {
        type: "classic",
      });
    } catch (err) {
      reject(err);
      return;
    }
    worker.onmessage = (event) => {
      const { id, type, result, error, message, stage } = event.data || {};
      if (type === "status") {
        emitStatus({ stage, message });
        return;
      }
      const pending = pendingRequests.get(id);
      if (!pending) return;
      pendingRequests.delete(id);
      if (type === "error") pending.reject(new Error(error || "Worker error"));
      else pending.resolve(result);
    };
    worker.onerror = (err) => reject(err);
    resolve(worker);
  });
  return workerPromise;
}

function workerRequest(type, payload) {
  return ensureWorker().then(
    (worker) =>
      new Promise((resolve, reject) => {
        const id = nextRequestId++;
        pendingRequests.set(id, { resolve, reject });
        worker.postMessage({ id, type, payload, pyBaseUrl: PY_BASE_URL });
      })
  );
}

async function solveViaBrowser(request) {
  return workerRequest("solve", request);
}

async function solveViaBackend(request) {
  const res = await fetch(`${API_BASE}/api/solve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    let detail = `Server ${res.status}`;
    try {
      const err = await res.json();
      detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
    } catch {
      if (res.status === 404) {
        detail = "Backend solver endpoint not found (404). Please verify that your local backend is running.";
      }
    }
    throw new Error(detail);
  }
  try {
    return await res.json();
  } catch (err) {
    throw new Error("Invalid response format received from solver backend.");
  }
}

export async function solveAnalysis(request) {
  if (MODE === "browser") return solveViaBrowser(request);
  if (MODE === "backend") return solveViaBackend(request);
  // auto
  try {
    return await solveViaBrowser(request);
  } catch (err) {
    emitStatus({ stage: "fallback", message: `Browser solver failed (${err.message}); falling back to backend.` });
    return solveViaBackend(request);
  }
}

export function getSolverMode() {
  return MODE;
}

async function optimizeViaBrowser(request) {
  return workerRequest("optimize", request);
}

async function optimizeViaBackend(request) {
  const res = await fetch(`${API_BASE}/api/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    let detail = `Server ${res.status}`;
    try {
      const err = await res.json();
      detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
    } catch {
      if (res.status === 404) {
        detail = "Optimizer endpoint not found (404). Please verify that your local backend is running.";
      }
    }
    throw new Error(detail);
  }
  try {
    return await res.json();
  } catch (err) {
    throw new Error("Invalid response format received from optimizer backend.");
  }
}

export async function runOptimize(request) {
  if (MODE === "browser") return optimizeViaBrowser(request);
  if (MODE === "backend") return optimizeViaBackend(request);
  // auto
  try {
    return await optimizeViaBrowser(request);
  } catch (err) {
    emitStatus({ stage: "fallback", message: `Browser optimizer failed (${err.message}); falling back to backend.` });
    return optimizeViaBackend(request);
  }
}
