import React, { useState } from 'react';
import { Dice5, Play, AlertCircle } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer, Cell } from 'recharts';
import useAdvancedApi from '../../hooks/useAdvancedApi';

export default function MonteCarloPanel({ sharedState }) {
  const { loading, error, post } = useAdvancedApi();
  const [result, setResult] = useState(null);
  const [nSims, setNSims] = useState(200);
  const [sigmas, setSigmas] = useState(() =>
    Array.from({ length: sharedState.numLayers }, () => 5)
  );

  const canRun = sharedState.results?.length > 0;

  const updateSigma = (idx, val) => {
    const next = [...sigmas];
    next[idx] = parseFloat(val) || 0;
    setSigmas(next);
  };

  const handleRun = async () => {
    const layers = [];
    for (let i = 0; i < sharedState.numLayers; i++) {
      const l = sharedState.layers[i];
      layers.push({ modulus: l.E, poisson: l.nu, thickness: l.is_fixed ? (l.fixed_h || 0) : (l.min_h || 0) });
    }
    layers.push({ modulus: sharedState.subgradeCbr * 10, poisson: 0.4, thickness: 0 });

    const points = [];
    for (let i = 0; i < sharedState.numPoints; i++) {
      const p = sharedState.points[i];
      points.push({ z: p.z, r: p.r });
    }

    const msa = parseFloat(sharedState.cvpd) || 300;
    const mixE = sharedState.layers[0]?.E || 1250;

    const resp = await post('/montecarlo', {
      layers,
      load: {
        load: sharedState.load,
        pressure: sharedState.pressure,
        is_dual: sharedState.wheelType === 'Dual',
        spacing: 310,
      },
      eval_points: points,
      cumulative_msa: msa,
      mix_modulus: mixE,
      sigmas: [...sigmas, 0],
      n_simulations: nSims,
      reliability: 80,
    });

    if (resp?.status === 'ok') setResult(resp);
  };

  const chartData = result?.histogram?.map(bin => ({
    name: bin.bin_start.toFixed(2),
    count: bin.count,
    midpoint: (bin.bin_start + bin.bin_end) / 2,
  })) || [];

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Dice5 size={16} className="text-orange-600" />
          <h2 className="text-sm font-bold text-gray-900">Monte Carlo Risk Analysis</h2>
          <span className="text-[10px] text-gray-400">Construction tolerance simulation</span>
        </div>
        <button
          onClick={handleRun}
          disabled={loading || !canRun}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 text-white text-[11px] font-medium rounded hover:bg-orange-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <span className="animate-spin rounded-full h-3 w-3 border border-white border-t-transparent" /> : <Play size={11} />}
          {loading ? `Running ${nSims} sims...` : 'Run Simulation'}
        </button>
      </div>

      {!canRun && (
        <div className="flex items-center gap-2 p-3 bg-orange-50 border border-orange-200 rounded text-[11px] text-orange-800">
          <AlertCircle size={13} /> Run Evaluate first to establish baseline design.
        </div>
      )}

      {/* Config */}
      <div className="grid grid-cols-2 gap-4">
        <div className="border border-gray-200 rounded p-3">
          <h3 className="text-[11px] font-semibold text-gray-700 mb-2">Thickness Uncertainty (sigma, mm)</h3>
          {Array.from({ length: sharedState.numLayers }, (_, i) => (
            <div key={i} className="flex items-center gap-2 mb-1">
              <span className="text-[10px] text-gray-500 w-14">Layer {i + 1}</span>
              <input
                type="number"
                value={sigmas[i] ?? 5}
                onChange={e => updateSigma(i, e.target.value)}
                className="w-16 text-[11px] px-2 py-0.5 border border-gray-200 rounded text-center font-mono"
                min={0}
                max={50}
                step={1}
              />
              <span className="text-[10px] text-gray-400">mm</span>
            </div>
          ))}
        </div>
        <div className="border border-gray-200 rounded p-3">
          <h3 className="text-[11px] font-semibold text-gray-700 mb-2">Simulation Count</h3>
          <select
            value={nSims}
            onChange={e => setNSims(parseInt(e.target.value))}
            className="text-[11px] px-2 py-1 border border-gray-200 rounded bg-white w-full"
          >
            <option value={50}>50 (Fast)</option>
            <option value={100}>100</option>
            <option value={200}>200 (Recommended)</option>
            <option value={500}>500 (Detailed)</option>
            <option value={1000}>1000 (Thorough)</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-[11px] text-red-700">{error}</div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Probability Banner */}
          <div className={`rounded p-4 text-center ${
            result.probability_adequate >= 90 ? 'bg-emerald-50 border border-emerald-200' :
            result.probability_adequate >= 70 ? 'bg-orange-50 border border-orange-200' :
            'bg-red-50 border border-red-200'
          }`}>
            <div className={`text-2xl font-bold ${
              result.probability_adequate >= 90 ? 'text-emerald-700' :
              result.probability_adequate >= 70 ? 'text-orange-700' : 'text-red-700'
            }`}>
              {result.probability_adequate}%
            </div>
            <div className="text-[11px] text-gray-600 mt-1">
              Probability of Adequate Design ({result.n_adequate}/{result.n_simulations} simulations passed)
            </div>
          </div>

          {/* Histogram */}
          {chartData.length > 0 && (
            <div className="border border-gray-200 rounded p-3">
              <h3 className="text-[11px] font-semibold text-gray-700 mb-2">Max CDF Distribution</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={chartData}>
                  <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                  <YAxis tick={{ fontSize: 9 }} />
                  <Tooltip
                    contentStyle={{ fontSize: '11px', padding: '4px 8px' }}
                    formatter={(val) => [`${val} sims`, 'Count']}
                  />
                  <ReferenceLine x="1.00" stroke="#dc2626" strokeDasharray="4 4" label={{ value: 'CDF=1.0', fontSize: 9, fill: '#dc2626' }} />
                  <Bar dataKey="count">
                    {chartData.map((entry, i) => (
                      <Cell key={i} fill={entry.midpoint > 1 ? '#fca5a5' : '#86efac'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* CDF Stats */}
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Fatigue CDF', stats: result.cdf_f_stats },
              { label: 'Rutting CDF', stats: result.cdf_r_stats },
            ].map(({ label, stats }) => (
              <div key={label} className="border border-gray-200 rounded p-3">
                <h4 className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mb-2">{label}</h4>
                <div className="grid grid-cols-2 gap-1 text-[11px]">
                  <span className="text-gray-500">Mean:</span>
                  <span className="font-mono font-medium">{stats?.mean?.toFixed(4) ?? '--'}</span>
                  <span className="text-gray-500">Std Dev:</span>
                  <span className="font-mono">{stats?.std?.toFixed(4) ?? '--'}</span>
                  <span className="text-gray-500">P5:</span>
                  <span className="font-mono">{stats?.p5?.toFixed(4) ?? '--'}</span>
                  <span className="text-gray-500">P95:</span>
                  <span className="font-mono">{stats?.p95?.toFixed(4) ?? '--'}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
