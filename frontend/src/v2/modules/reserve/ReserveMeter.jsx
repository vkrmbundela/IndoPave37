import React, { useEffect, useState } from 'react';
import { Gauge, AlertCircle, ShieldCheck, TrendingUp } from 'lucide-react';
import useAdvancedApi from '../../hooks/useAdvancedApi';

function GaugeBar({ label, value, max, color, unit = 'MSA' }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="mb-3">
      <div className="flex justify-between text-[11px] mb-1">
        <span className="text-gray-500 font-medium">{label}</span>
        <span className="font-mono font-bold text-gray-700">{value.toFixed(1)} {unit}</span>
      </div>
      <div className="h-3 bg-gray-100 rounded-full overflow-hidden border border-gray-200">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function StatusBadge({ reserve }) {
  if (reserve > 20) return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-green-50 border border-green-200 text-green-700 text-xs font-bold">
      <ShieldCheck size={13} /> Excellent Reserve (+{reserve.toFixed(0)}%)
    </div>
  );
  if (reserve > 5) return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-orange-50 border border-orange-200 text-orange-700 text-xs font-bold">
      <TrendingUp size={13} /> Moderate Reserve (+{reserve.toFixed(0)}%)
    </div>
  );
  return (
    <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-red-50 border border-red-200 text-red-700 text-xs font-bold">
      <AlertCircle size={13} /> Low Reserve (+{reserve.toFixed(0)}%)
    </div>
  );
}

export default function ReserveMeter({ sharedState }) {
  const api = useAdvancedApi();
  const { post } = api;
  const [result, setResult] = useState(null);

  const hasResults = sharedState.results && sharedState.results.length > 0;

  useEffect(() => {
    if (!hasResults) return;

    // Extract critical strains from results
    const allEpsZ = sharedState.results.map(r => Math.abs(r.eps_z || r.strain_z || 0));
    const allEpsT = sharedState.results.map(r => Math.abs(r.eps_t || r.strain_t || 0));
    const maxEpsV = Math.max(...allEpsZ);
    const maxEpsT = Math.max(...allEpsT);

    if (maxEpsV < 1e-15 && maxEpsT < 1e-15) return;

    // Get bituminous layer modulus (first layer)
    const bitLayer = sharedState.layers?.[0];
    const mixModulus = bitLayer?.E || 1250;

    // Compute design MSA from CVPD (simplified: use defaults for growth, VDF, LDF)
    const cvpd = sharedState.cvpd || 800;
    const growthRate = 0.05;
    const designLife = 20;
    const ldf = 0.75;
    const vdf = 2.5;
    const N = 365 * cvpd * ldf * vdf * ((Math.pow(1 + growthRate, designLife) - 1) / growthRate);
    const designMsa = N / 1e6;

    post('/reserve', {
      eps_t: maxEpsT,
      eps_v: maxEpsV,
      mix_modulus: mixModulus,
      design_msa: designMsa,
      reliability: 80,
    }).then(res => {
      if (res && res.status === 'ok') setResult(res);
    });
  }, [hasResults, sharedState.results, sharedState.layers, sharedState.cvpd, post]);

  if (!hasResults) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center max-w-sm">
          <Gauge size={48} className="mx-auto mb-3 text-gray-200" />
          <p className="text-sm font-medium text-gray-500">No Results Available</p>
          <p className="text-xs text-gray-400 mt-1">
            Run <span className="font-bold text-orange-600">Evaluate</span> on your pavement structure first.
            The Reserve Meter will calculate the exact traffic capacity of your design.
          </p>
        </div>
      </div>
    );
  }

  if (api.loading || !result) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-orange-200 border-t-orange-600 mx-auto mb-3" />
          <p className="text-xs text-gray-400">Computing structural reserve...</p>
        </div>
      </div>
    );
  }

  if (api.error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded p-3 text-xs text-red-700">
          <AlertCircle size={12} className="inline mr-1" /> {api.error}
        </div>
      </div>
    );
  }

  const maxCapacity = Math.max(result.intercept_msa, result.design_msa) * 1.15;

  return (
    <div className="p-6 max-w-2xl mx-auto">
      {/* Title */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-base font-bold text-gray-900 flex items-center gap-2">
            <Gauge size={18} className="text-orange-600" /> Structural Reserve Meter
          </h2>
          <p className="text-[11px] text-gray-400 mt-0.5">
            Value engineering — quantify the safety buffer in your design
          </p>
        </div>
        <StatusBadge reserve={result.reserve_percent} />
      </div>

      {/* Main Gauge */}
      <div className="bg-gray-50 rounded-lg border border-gray-200 p-5 mb-5">
        <div className="flex justify-between text-xs text-gray-500 mb-2 font-medium">
          <span>Design Traffic</span>
          <span>Structural Capacity</span>
        </div>

        {/* Combined gauge */}
        <div className="relative h-8 bg-gray-100 rounded-full overflow-hidden border border-gray-200 mb-2">
          {/* Design fill */}
          <div
            className="absolute inset-y-0 left-0 bg-orange-400 rounded-l-full transition-all duration-700"
            style={{ width: `${(result.design_msa / maxCapacity) * 100}%` }}
          />
          {/* Reserve fill */}
          <div
            className="absolute inset-y-0 bg-green-400/60 rounded-r-full transition-all duration-700"
            style={{
              left: `${(result.design_msa / maxCapacity) * 100}%`,
              width: `${((result.intercept_msa - result.design_msa) / maxCapacity) * 100}%`
            }}
          />
          {/* Center label */}
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-[11px] font-bold text-gray-800 bg-white/70 px-2 rounded">
              {result.design_msa.toFixed(1)} MSA → {result.intercept_msa.toFixed(1)} MSA
            </span>
          </div>
        </div>

        <div className="flex justify-between text-[10px] text-gray-400">
          <span>0 MSA</span>
          <span className={`font-bold ${result.governing_mode === 'fatigue' ? 'text-orange-600' : 'text-blue-600'}`}>
            Governed by {result.governing_mode}
          </span>
          <span>{maxCapacity.toFixed(0)} MSA</span>
        </div>
      </div>

      {/* Individual Capacities */}
      <div className="grid grid-cols-2 gap-4 mb-5">
        <div className="bg-white rounded border border-gray-200 p-4">
          <p className="text-[10px] uppercase tracking-wider text-orange-500 font-bold mb-2">Fatigue Capacity</p>
          <GaugeBar label="Nf" value={result.Nf_msa} max={maxCapacity} color="bg-orange-400" />
          <p className="text-[10px] text-gray-400">
            Allowable repetitions before fatigue cracking
          </p>
        </div>
        <div className="bg-white rounded border border-gray-200 p-4">
          <p className="text-[10px] uppercase tracking-wider text-blue-500 font-bold mb-2">Rutting Capacity</p>
          <GaugeBar label="NR" value={result.NR_msa} max={maxCapacity} color="bg-blue-400" />
          <p className="text-[10px] text-gray-400">
            Allowable repetitions before subgrade rutting
          </p>
        </div>
      </div>

      {/* Summary Card */}
      <div className="bg-orange-50/50 rounded-lg border border-orange-100 p-4">
        <h3 className="text-xs font-bold text-orange-900 mb-2">Engineering Summary</h3>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div>
            <p className="text-[10px] text-gray-500">Design Traffic</p>
            <p className="text-sm font-bold font-mono text-gray-800">{result.design_msa.toFixed(1)}</p>
            <p className="text-[9px] text-gray-400">MSA</p>
          </div>
          <div>
            <p className="text-[10px] text-gray-500">Structural Capacity</p>
            <p className="text-sm font-bold font-mono text-orange-700">{result.intercept_msa.toFixed(1)}</p>
            <p className="text-[9px] text-gray-400">MSA</p>
          </div>
          <div>
            <p className="text-[10px] text-gray-500">Reserve Buffer</p>
            <p className={`text-sm font-bold font-mono ${
              result.reserve_percent > 20 ? 'text-green-600' :
              result.reserve_percent > 5 ? 'text-orange-600' : 'text-red-600'
            }`}>+{result.reserve_percent.toFixed(0)}%</p>
            <p className="text-[9px] text-gray-400">surplus</p>
          </div>
        </div>
      </div>
    </div>
  );
}
