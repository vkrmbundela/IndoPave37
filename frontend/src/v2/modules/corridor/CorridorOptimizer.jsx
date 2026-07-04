import React, { useState, useRef, useEffect } from 'react';
import { Route, Upload, Play, Download, FileText } from 'lucide-react';
import { getSolverMode } from '../../../lib/solver-client';

// This module talks to the FastAPI backend directly (multipart CSV upload +
// job polling) — it has no Pyodide equivalent. AdvancedPanel disables the tab
// in browser mode; the guard below keeps the component honest if it is ever
// rendered there anyway.
const BACKEND_AVAILABLE = getSolverMode() === 'backend';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

// Polling safety budgets. Corridor jobs are minutes-scale, never hours; if
// status hasn't reported "complete" within MAX_POLLS the backend has either
// crashed or is wedged, and we should surface an error rather than hold the
// user's UI hostage forever.
const POLL_INTERVAL_MS = 1500;
const MAX_POLLS = 1200;                   // 30 min hard ceiling
const MAX_CONSECUTIVE_ERRORS = 5;         // ~7.5 s of network failures → abort

const SAMPLE_CSV = `Chainage,Subgrade_CBR,CVPD,VDF,LDF
0+000,8,800,2.5,0.75
0+500,6,800,2.5,0.75
1+000,10,1000,3.0,0.75
1+500,5,600,2.0,0.75
2+000,7,900,2.5,0.75`;

export default function CorridorOptimizer() {
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);
  const pollRef = useRef(null);

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f && f.name.endsWith('.csv')) setFile(f);
  };

  const useSample = () => {
    const blob = new Blob([SAMPLE_CSV], { type: 'text/csv' });
    setFile(new File([blob], 'sample_corridor.csv', { type: 'text/csv' }));
  };

  const startOptimization = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setStatus(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`${API_BASE}/api/v2/corridor`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      try {
        const data = await res.json();
        startPolling(data.job_id);
      } catch (err) {
        throw new Error("Invalid response format received from corridor optimizer backend.");
      }
    } catch (e) {
      setError(e.message);
      setLoading(false);
    }
  };

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = (id) => {
    stopPolling();
    let pollsRemaining = MAX_POLLS;
    let consecutiveErrors = 0;

    pollRef.current = setInterval(async () => {
      pollsRemaining -= 1;
      if (pollsRemaining <= 0) {
        stopPolling();
        setLoading(false);
        setError(
          `Corridor optimization timed out after ${(MAX_POLLS * POLL_INTERVAL_MS) / 60000} min — ` +
          'the backend stopped reporting progress. Refresh and try again.'
        );
        return;
      }

      try {
        const res = await fetch(`${API_BASE}/api/v2/corridor/${id}/status`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        let data;
        try {
          data = await res.json();
        } catch (err) {
          throw new Error("Invalid response format received from corridor status backend.");
        }
        consecutiveErrors = 0;       // reset on any successful response
        setStatus(data);

        if (data.status === 'complete') {
          stopPolling();
          setLoading(false);
        } else if (data.status === 'error' || (typeof data.status === 'string' && data.status.startsWith('error'))) {
          stopPolling();
          setLoading(false);
          setError(data.detail || data.status || 'Corridor optimization failed on the backend');
        }
      } catch (err) {
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          stopPolling();
          setLoading(false);
          setError(
            `Lost connection to the backend after ${MAX_CONSECUTIVE_ERRORS} consecutive failed status checks ` +
            `(${err.message || 'network error'}).`
          );
        }
        // else: transient blip — keep polling but accumulate the error count
      }
    }, POLL_INTERVAL_MS);
  };

  // Always tear the interval down on unmount so we don't keep firing
  // requests after the panel closes.
  useEffect(() => {
    return () => stopPolling();
  }, []);

  const downloadResults = () => {
    if (!status?.sections) return;
    const header = 'Chainage,CBR,MSA,Status,Total_Thickness,Cost_per_km,CO2_per_km,CDF_f,CDF_r\n';
    const rows = status.sections.map(s =>
      `${s.chainage},${s.cbr},${s.msa},${s.status},${s.total_thickness},${s.cost_per_km},${s.co2_per_km},${s.cdf_f},${s.cdf_r}`
    ).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'corridor_results.csv'; a.click();
    URL.revokeObjectURL(url);
  };

  // Guard against an uninitialized or empty job (status.total = 0). Without
  // the check this becomes Infinity / NaN and the progress bar renders garbage.
  const progress = (status && status.total > 0)
    ? Math.min(100, Math.round((status.completed / status.total) * 100))
    : 0;

  if (!BACKEND_AVAILABLE) {
    return (
      <div className="p-6 text-center text-xs text-gray-500">
        <Route size={40} className="mx-auto mb-3 text-gray-200" />
        <p className="font-bold text-gray-600 mb-1">Corridor optimization needs the local backend</p>
        <p>
          CSV upload and job polling run on the FastAPI server, which the static in-browser deploy
          does not include. Start it locally with
          <code className="mx-1 px-1 bg-gray-100 rounded">python -m mep_opt.web.main</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Route size={16} className="text-orange-600" />
        <h2 className="text-sm font-bold text-gray-900">Corridor Optimization</h2>
        <span className="text-[10px] text-gray-400">Batch section-by-section optimization from CSV</span>
      </div>

      {/* Upload */}
      {!status?.status && (
        <div
          className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-orange-400 transition-colors"
          onDragOver={e => e.preventDefault()}
          onDrop={handleDrop}
        >
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={handleFile} />
          <Upload size={24} className="mx-auto mb-2 text-gray-400" />
          <p className="text-[11px] text-gray-600 mb-2">
            {file ? <><FileText size={12} className="inline" /> {file.name}</> : 'Drop CSV here or click to browse'}
          </p>
          <div className="flex items-center justify-center gap-2">
            <button onClick={() => fileRef.current?.click()} className="px-3 py-1.5 text-[11px] bg-gray-100 hover:bg-gray-200 rounded border border-gray-200 font-medium">
              Browse
            </button>
            <button onClick={useSample} className="px-3 py-1.5 text-[11px] text-orange-700 bg-orange-50 hover:bg-orange-100 rounded border border-orange-200 font-medium">
              Use Sample CSV
            </button>
          </div>
          {file && (
            <button
              onClick={startOptimization}
              disabled={loading}
              className="mt-3 flex items-center gap-1.5 mx-auto px-4 py-2 bg-orange-600 text-white text-[11px] font-medium rounded hover:bg-orange-700 disabled:opacity-40 transition-colors"
            >
              {loading ? <span className="animate-spin rounded-full h-3 w-3 border border-white border-t-transparent" /> : <Play size={11} />}
              {loading ? 'Optimizing...' : 'Start Optimization'}
            </button>
          )}
        </div>
      )}

      {/* Progress */}
      {loading && status && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px] text-gray-600">
            <span>Optimizing {status.completed}/{status.total} sections...</span>
            <span className="font-mono">{progress}%</span>
          </div>
          <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
            <div className="h-full bg-orange-500 transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-[11px] text-red-700">{error}</div>
      )}

      {/* Corridor Strategy */}
      {status?.corridor_strategy && (
        <div className="border border-emerald-200 bg-emerald-50 rounded p-3">
          <h3 className="text-[11px] font-bold text-emerald-800 mb-2">Unified Corridor Strategy</h3>
          <div className="flex items-center gap-4 text-[11px]">
            <span className="text-emerald-700">
              Thicknesses: {status.corridor_strategy.unified_thicknesses.map(t => `${t}mm`).join(' / ')}
            </span>
            <span className="font-mono text-emerald-800 font-bold">
              Total: {status.corridor_strategy.total_thickness} mm
            </span>
            <span className="text-emerald-600">
              ({status.corridor_strategy.sections_optimized}/{status.corridor_strategy.sections_total} sections)
            </span>
          </div>
        </div>
      )}

      {/* Results Table */}
      {status?.sections?.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-gray-700">Per-Section Results</span>
            <button onClick={downloadResults} className="flex items-center gap-1 px-2 py-1 text-[10px] text-gray-600 hover:bg-gray-100 rounded border border-gray-200">
              <Download size={10} /> Export CSV
            </button>
          </div>
          <div className="border border-gray-200 rounded overflow-auto max-h-64">
            <table className="w-full text-[11px]">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  {['Chainage', 'CBR', 'MSA', 'Status', 'Thicknesses', 'Total', 'Cost/km', 'CDF_f', 'CDF_r'].map(h => (
                    <th key={h} className="px-2 py-1.5 text-left font-medium text-gray-500 border-b border-gray-200">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {status.sections.map((s, i) => (
                  <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-2 py-1 font-mono">{s.chainage}</td>
                    <td className="px-2 py-1">{s.cbr}%</td>
                    <td className="px-2 py-1 font-mono">{s.msa}</td>
                    <td className={`px-2 py-1 font-medium ${s.status === 'ok' ? 'text-emerald-600' : 'text-red-500'}`}>{s.status}</td>
                    <td className="px-2 py-1 font-mono text-gray-600">{s.thicknesses.join(' / ')}</td>
                    <td className="px-2 py-1 font-mono font-medium">{s.total_thickness}</td>
                    <td className="px-2 py-1 font-mono">{s.cost_per_km?.toLocaleString()}</td>
                    <td className="px-2 py-1 font-mono">{s.cdf_f?.toFixed(3)}</td>
                    <td className="px-2 py-1 font-mono">{s.cdf_r?.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
