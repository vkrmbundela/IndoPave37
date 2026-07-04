import React, { useState } from 'react';
import { Grid3x3, Play, AlertCircle } from 'lucide-react';
import useAdvancedApi from '../../hooks/useAdvancedApi';
import { subgradeModulusFromCBR, bottomBituminousModulus, cumulativeMSA, classifyPointRoles } from '../../../lib/irc';

function CdfCell({ value }) {
  if (value == null) return <td className="px-2 py-1 text-center text-[10px] text-gray-300">--</td>;
  const v = parseFloat(value);
  const bg = v > 1.0 ? 'bg-red-100 text-red-800' : v > 0.8 ? 'bg-orange-100 text-orange-800' : 'bg-emerald-50 text-emerald-700';
  return <td className={`px-2 py-1 text-center text-[11px] font-mono font-medium ${bg}`}>{v.toFixed(3)}</td>;
}

export default function SensitivityHeatmap({ sharedState }) {
  const { loading, error, post } = useAdvancedApi();
  const [result, setResult] = useState(null);
  const [rolesOk, setRolesOk] = useState(true);

  const canRun = sharedState.results?.length > 0;

  const handleRun = async () => {
    const layers = [];
    for (let i = 0; i < sharedState.numLayers - 1; i++) {
      const l = sharedState.layers[i];
      layers.push({ modulus: l.E, poisson: l.nu, thickness: l.is_fixed ? (l.fixed_h || 0) : (l.min_h || 0), name: l.name || l.type || `Layer ${i + 1}` });
    }
    // IRC:37-2018 subgrade modulus (Eq. 6.1/6.2, capped 100 MPa) and ν = 0.35,
    // not the old flat CBR*10 / ν = 0.40.
    layers.push({ modulus: subgradeModulusFromCBR(sharedState.subgradeCbr), poisson: 0.35, thickness: 0, name: "Subgrade" });

    const points = [];
    for (let i = 0; i < sharedState.numPoints; i++) {
      const p = sharedState.points[i];
      points.push({ z: p.z, r: p.r });
    }

    // Tell the backend WHICH rows are the fatigue / rutting probes by depth,
    // instead of letting it assume rows 0-1 / 2-3 (wrong for 6-point CTB
    // layouts). When classification fails (stale points) we fall back to the
    // legacy assumption and show a warning banner.
    const roles = classifyPointRoles(sharedState.layers, sharedState.numLayers, points);
    setRolesOk(roles.ok);

    // Real cumulative MSA from the traffic inputs (not raw CVPD), and the
    // BOTTOM bituminous layer modulus for fatigue (IRC §3.6.2).
    const msa = cumulativeMSA({
      cvpd: sharedState.cvpd, growthRate: sharedState.growthRate,
      designLife: sharedState.designLife, ldf: sharedState.ldf, vdf: sharedState.vdf,
    });
    const mixE = bottomBituminousModulus(sharedState.layers, sharedState.numLayers);

    const resp = await post('/sensitivity', {
      layers,
      load: {
        load: sharedState.load,
        pressure: sharedState.pressure,
        is_dual: sharedState.wheelType === 'Dual',
        // Pull spacing & reliability from sharedState so the sensitivity
        // analysis is consistent with the cockpit configuration. Falls
        // back to IRC defaults only if the cockpit hasn't initialized them.
        spacing: sharedState.wheelSpacing ?? 310,
      },
      eval_points: points,
      cumulative_msa: msa,
      mix_modulus: mixE,
      reliability: sharedState.reliabilityPercent ?? 80,
      air_voids: sharedState.airVoids ?? 3.0,
      bitumen_volume: sharedState.bitumenVolume ?? 11.5,
      point_roles: roles.ok ? { bit_bottom: roles.bit_bottom, sub_top: roles.sub_top } : undefined,
    });

    if (resp?.status === 'ok') setResult(resp.layers);
  };

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Grid3x3 size={16} className="text-orange-600" />
          <h2 className="text-sm font-bold text-gray-900">Sensitivity Heatmap</h2>
          <span className="text-[10px] text-gray-400">Thickness perturbation vs CDF response</span>
        </div>
        <button
          onClick={handleRun}
          disabled={loading || !canRun}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 text-white text-[11px] font-medium rounded hover:bg-orange-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? <span className="animate-spin rounded-full h-3 w-3 border border-white border-t-transparent" /> : <Play size={11} />}
          {loading ? 'Computing...' : 'Run Sensitivity'}
        </button>
      </div>

      {!canRun && (
        <div className="flex items-center gap-2 p-3 bg-orange-50 border border-orange-200 rounded text-[11px] text-orange-800">
          <AlertCircle size={13} /> Run Evaluate on the main panel first to generate baseline results.
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-[11px] text-red-700">{error}</div>
      )}

      {!rolesOk && result && (
        <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded text-[11px] text-amber-800">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          <span>
            The analysis points don't line up with the current layer interfaces, so the legacy
            row-order assumption was used. Update the point depths to the bituminous bottom and
            top of subgrade for reliable sensitivities.
          </span>
        </div>
      )}

      {result && result.map((layer, li) => (
        <div key={li} className="border border-gray-200 rounded overflow-hidden">
          <div className="bg-gray-50 px-3 py-1.5 text-[11px] font-semibold text-gray-700 border-b border-gray-200">
            Layer {layer.layer_index + 1} — Base: {layer.base_thickness} mm
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="px-2 py-1 text-left font-medium text-gray-500">Delta</th>
                <th className="px-2 py-1 text-center font-medium text-gray-500">Thickness</th>
                <th className="px-2 py-1 text-center font-medium text-gray-500">CDF Fatigue</th>
                <th className="px-2 py-1 text-center font-medium text-gray-500">CDF Rutting</th>
                <th className="px-2 py-1 text-center font-medium text-gray-500">eps_t (micro)</th>
                <th className="px-2 py-1 text-center font-medium text-gray-500">eps_v (micro)</th>
              </tr>
            </thead>
            <tbody>
              {layer.deltas.map((d, di) => (
                <tr key={di} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-2 py-1 font-mono text-gray-600">{d.delta_mm > 0 ? '+' : ''}{d.delta_mm} mm</td>
                  <td className="px-2 py-1 text-center font-mono text-gray-700">{d.thickness_mm}</td>
                  <CdfCell value={d.CDF_f} />
                  <CdfCell value={d.CDF_r} />
                  <td className="px-2 py-1 text-center font-mono text-gray-600">
                    {d.eps_t != null ? (d.eps_t * 1e6).toFixed(1) : '--'}
                  </td>
                  <td className="px-2 py-1 text-center font-mono text-gray-600">
                    {d.eps_v != null ? (d.eps_v * 1e6).toFixed(1) : '--'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
