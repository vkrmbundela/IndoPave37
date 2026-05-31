import React, { useState, useRef, useEffect, useMemo } from 'react';
import { Box, Play } from 'lucide-react';
import useAdvancedApi from '../../hooks/useAdvancedApi';
import { subgradeModulusFromCBR } from '../../../lib/irc';

const COLORMAP = [
  [49, 54, 149], [69, 117, 180], [116, 173, 209], [171, 217, 233],
  [224, 243, 248], [255, 255, 191], [254, 224, 144], [253, 174, 97],
  [244, 109, 67], [215, 48, 39], [165, 0, 38],
];

function valueToRgb(val, minV, maxV) {
  if (maxV === minV) return [180, 180, 180];
  const t = Math.max(0, Math.min(1, (val - minV) / (maxV - minV)));
  const idx = t * (COLORMAP.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, COLORMAP.length - 1);
  const f = idx - lo;
  return COLORMAP[lo].map((c, i) => Math.round(c * (1 - f) + COLORMAP[hi][i] * f));
}

function HeatmapCanvas({ data, mode, width, height }) {
  const canvasRef = useRef(null);
  const grid = mode === 'eps_z' ? data.eps_z_grid : data.eps_t_grid;
  const rVals = data.r_values;
  const zVals = data.z_values;

  const { minV, maxV } = useMemo(() => {
    const all = grid.flat().map(v => Math.abs(v));
    return { minV: Math.min(...all), maxV: Math.max(...all) };
  }, [grid]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const marginL = 60, marginR = 16, marginT = 20, marginB = 40;
    const plotW = width - marginL - marginR;
    const plotH = height - marginT - marginB;
    const maxR = rVals[rVals.length - 1] || 500;
    const maxZ = zVals[zVals.length - 1] || 500;
    const interfaces = data.layer_interfaces || [];
    const layerNames = data.layer_names || [];

    const xScale = (r) => marginL + (r / maxR) * plotW;
    const yScale = (z) => marginT + (z / maxZ) * plotH;

    // Clear
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    // Draw heatmap cells
    for (let zi = 0; zi < zVals.length - 1; zi++) {
      for (let ri = 0; ri < rVals.length - 1; ri++) {
        const val = Math.abs(grid[zi][ri]);
        const rgb = valueToRgb(val, minV, maxV);
        ctx.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
        const x0 = xScale(rVals[ri]);
        const y0 = yScale(zVals[zi]);
        const x1 = xScale(rVals[ri + 1]);
        const y1 = yScale(zVals[zi + 1]);
        ctx.fillRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1);
      }
    }

    // Draw layer interfaces
    ctx.setLineDash([6, 3]);
    ctx.lineWidth = 1.5;
    interfaces.forEach((depth, i) => {
      const y = yScale(depth);
      ctx.strokeStyle = '#475569';
      ctx.beginPath();
      ctx.moveTo(marginL, y);
      ctx.lineTo(marginL + plotW, y);
      ctx.stroke();
      // Label
      ctx.setLineDash([]);
      ctx.fillStyle = '#1e293b';
      ctx.font = '600 10px Inter, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(layerNames[i] || `L${i + 1}`, marginL - 4, y + 3);
      ctx.setLineDash([6, 3]);
    });
    ctx.setLineDash([]);

    // Axes
    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(marginL, marginT);
    ctx.lineTo(marginL, marginT + plotH);
    ctx.lineTo(marginL + plotW, marginT + plotH);
    ctx.stroke();

    // X-axis ticks & labels
    ctx.fillStyle = '#64748b';
    ctx.font = '10px Inter, sans-serif';
    ctx.textAlign = 'center';
    const xTicks = [0, 100, 200, 300, 400, 500].filter(v => v <= maxR);
    xTicks.forEach(r => {
      const x = xScale(r);
      ctx.beginPath();
      ctx.moveTo(x, marginT + plotH);
      ctx.lineTo(x, marginT + plotH + 4);
      ctx.stroke();
      ctx.fillText(`${r}`, x, marginT + plotH + 15);
    });
    ctx.font = '600 10px Inter, sans-serif';
    ctx.fillText('Radial Distance (mm)', marginL + plotW / 2, marginT + plotH + 32);

    // Y-axis ticks & labels
    ctx.textAlign = 'right';
    ctx.font = '10px Inter, sans-serif';
    const zStep = maxZ > 800 ? 200 : maxZ > 400 ? 100 : 50;
    for (let z = 0; z <= maxZ; z += zStep) {
      const y = yScale(z);
      ctx.beginPath();
      ctx.moveTo(marginL - 4, y);
      ctx.lineTo(marginL, y);
      ctx.stroke();
      ctx.fillStyle = '#64748b';
      ctx.fillText(`${z}`, marginL - 7, y + 3);
    }
    // Y-axis label (rotated)
    ctx.save();
    ctx.translate(12, marginT + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.font = '600 10px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillStyle = '#64748b';
    ctx.fillText('Depth (mm)', 0, 0);
    ctx.restore();

    // Wheel load indicator
    const loadX = xScale(0);
    ctx.fillStyle = '#ea580c';
    ctx.beginPath();
    ctx.moveTo(loadX - 8, marginT - 2);
    ctx.lineTo(loadX + 8, marginT - 2);
    ctx.lineTo(loadX, marginT + 8);
    ctx.closePath();
    ctx.fill();

  }, [data, mode, width, height, grid, rVals, zVals, minV, maxV]);

  return <canvas ref={canvasRef} style={{ width, height }} />;
}

function ColorBar({ minV, maxV, mode }) {
  const unit = mode === 'eps_z' ? 'Vertical' : 'Tensile';
  const steps = 6;
  const labels = [];
  for (let i = 0; i <= steps; i++) {
    const v = minV + (maxV - minV) * (i / steps);
    labels.push((v * 1e6).toFixed(1));
  }
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[9px] font-semibold text-gray-500 uppercase">{unit} Strain (micro)</span>
      <div className="flex items-center gap-1">
        <span className="text-[9px] font-mono text-gray-500">{labels[0]}</span>
        <div className="w-32 h-3 rounded-sm" style={{
          background: `linear-gradient(to right, ${COLORMAP.map((c, i) =>
            `rgb(${c.join(',')}) ${(i / (COLORMAP.length - 1) * 100).toFixed(0)}%`
          ).join(', ')})`
        }} />
        <span className="text-[9px] font-mono text-gray-500">{labels[labels.length - 1]}</span>
      </div>
    </div>
  );
}

export default function StrainBulbViewer({ sharedState }) {
  const { loading, error, post } = useAdvancedApi();
  const [data, setData] = useState(null);
  const [mode, setMode] = useState('eps_z');
  const containerRef = useRef(null);
  const [dims, setDims] = useState({ w: 600, h: 400 });

  const canRun = sharedState.numLayers > 0;

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDims({ w: Math.floor(width), h: Math.floor(height) });
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const handleRun = async () => {
    const layers = [];
    for (let i = 0; i < sharedState.numLayers - 1; i++) {
      const l = sharedState.layers[i];
      layers.push({ modulus: l.E, poisson: l.nu, thickness: l.is_fixed ? (l.fixed_h || 0) : (l.min_h || 0), name: l.name || l.type || `Layer ${i + 1}` });
    }
    layers.push({ modulus: subgradeModulusFromCBR(sharedState.subgradeCbr), poisson: 0.35, thickness: 0, name: "Subgrade" });

    const resp = await post('/strain-field', {
      layers,
      load: {
        load: sharedState.load,
        pressure: sharedState.pressure,
        is_dual: sharedState.wheelType === 'Dual',
        // Pull spacing from sharedState so the bulb visualization matches
        // the dual-tire geometry the user actually configured.
        spacing: sharedState.wheelSpacing ?? 310,
      },
      r_steps: 14,
      z_steps: 30,
      r_max: 500,
    });

    if (resp?.status === 'ok') setData(resp);
  };

  const stats = useMemo(() => {
    if (!data) return null;
    const grid = mode === 'eps_z' ? data.eps_z_grid : data.eps_t_grid;
    const absVals = grid.flat().map(v => Math.abs(v));
    const maxVal = Math.max(...absVals);
    const minVal = Math.min(...absVals);
    // Find location of max
    let maxZi = 0, maxRi = 0;
    for (let zi = 0; zi < grid.length; zi++) {
      for (let ri = 0; ri < grid[zi].length; ri++) {
        if (Math.abs(grid[zi][ri]) === maxVal) { maxZi = zi; maxRi = ri; }
      }
    }
    return {
      maxVal, minVal,
      maxZ: data.z_values[maxZi],
      maxR: data.r_values[maxRi],
      totalPoints: grid.flat().length,
    };
  }, [data, mode]);

  return (
    <div className="p-4 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Box size={16} className="text-orange-600" />
          <h2 className="text-sm font-bold text-gray-900">Strain Bulb Cross-Section</h2>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <>
              <select
                value={mode}
                onChange={e => setMode(e.target.value)}
                className="text-[11px] px-2 py-1 border border-gray-200 rounded bg-white"
              >
                <option value="eps_z">Vertical Strain (eps_z)</option>
                <option value="eps_t">Tensile Strain (eps_t)</option>
              </select>
              <ColorBar minV={stats?.minVal || 0} maxV={stats?.maxVal || 1} mode={mode} />
            </>
          )}
          <button
            onClick={handleRun}
            disabled={loading || !canRun}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 text-white text-[11px] font-medium rounded hover:bg-orange-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? <span className="animate-spin rounded-full h-3 w-3 border border-white border-t-transparent" /> : <Play size={11} />}
            {loading ? 'Computing...' : 'Generate Field'}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-[11px] text-red-700 mb-3">{error}</div>
      )}

      {/* Content */}
      <div className="flex-1 min-h-0 flex gap-3">
        {/* Heatmap */}
        <div ref={containerRef} className="flex-1 min-h-0 rounded border border-gray-200 bg-white overflow-hidden relative">
          {!data && !loading && (
            <div className="absolute inset-0 flex items-center justify-center text-gray-400">
              <div className="text-center">
                <Box size={40} className="mx-auto mb-2 opacity-30" />
                <p className="text-[11px]">Click "Generate Field" to compute the subsurface strain distribution</p>
              </div>
            </div>
          )}
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <div className="animate-spin rounded-full h-8 w-8 border-2 border-orange-200 border-t-orange-600 mx-auto mb-2" />
                <p className="text-[11px] text-gray-500">Computing strain field (420 points)...</p>
              </div>
            </div>
          )}
          {data && !loading && dims.w > 0 && (
            <HeatmapCanvas data={data} mode={mode} width={dims.w} height={dims.h} />
          )}
        </div>

        {/* Stats Panel */}
        {data && !loading && stats && (
          <div className="w-52 flex-none flex flex-col gap-2">
            <div className="border border-gray-200 rounded p-2.5 bg-white">
              <h4 className="text-[10px] font-bold text-gray-400 uppercase mb-2">Peak Values</h4>
              <div className="space-y-1.5">
                <div>
                  <span className="text-[10px] text-gray-500">Max Strain</span>
                  <div className="text-sm font-bold font-mono text-red-700">{(stats.maxVal * 1e6).toFixed(2)} <span className="text-[10px] font-normal text-gray-400">micro</span></div>
                </div>
                <div>
                  <span className="text-[10px] text-gray-500">At Depth</span>
                  <div className="text-[12px] font-bold font-mono text-gray-800">{stats.maxZ.toFixed(1)} mm</div>
                </div>
                <div>
                  <span className="text-[10px] text-gray-500">At Offset</span>
                  <div className="text-[12px] font-bold font-mono text-gray-800">{stats.maxR.toFixed(1)} mm</div>
                </div>
              </div>
            </div>
            <div className="border border-gray-200 rounded p-2.5 bg-white">
              <h4 className="text-[10px] font-bold text-gray-400 uppercase mb-2">Layer Interfaces</h4>
              <div className="space-y-1">
                {data.layer_names?.map((name, i) => (
                  <div key={i} className="flex justify-between items-center">
                    <span className="text-[10px] text-gray-600 font-medium">{name}</span>
                    <span className="text-[10px] font-mono text-gray-800">{data.layer_interfaces[i]} mm</span>
                  </div>
                ))}
                <div className="flex justify-between items-center border-t border-gray-100 pt-1">
                  <span className="text-[10px] text-gray-500">Subgrade</span>
                  <span className="text-[10px] font-mono text-gray-400">extends below</span>
                </div>
              </div>
            </div>
            <div className="border border-gray-200 rounded p-2.5 bg-white">
              <h4 className="text-[10px] font-bold text-gray-400 uppercase mb-2">Grid Info</h4>
              <div className="text-[10px] text-gray-600 space-y-0.5">
                <div>{data.r_values.length} x {data.z_values.length} = {stats.totalPoints} pts</div>
                <div>R: 0 - {data.r_values[data.r_values.length - 1]} mm</div>
                <div>Z: {data.z_values[0].toFixed(0)} - {data.z_values[data.z_values.length - 1].toFixed(0)} mm</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
